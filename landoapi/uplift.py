# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import json
import logging
import re
import time
from typing import (
    Any,
    Optional,
)

import requests
from flask import current_app
from packaging.version import (
    InvalidVersion,
    Version,
)

from landoapi import bmo
from landoapi.cache import DEFAULT_CACHE_KEY_TIMEOUT_SECONDS, cache
from landoapi.phabricator import PhabricatorClient
from landoapi.phabricator_patch import patch_to_changes
from landoapi.repos import (
    Repo,
    get_repos_for_env,
)
from landoapi.stacks import (
    RevisionData,
    RevisionStack,
    build_stack_graph,
    request_extended_revision_data,
)

logger = logging.getLogger(__name__)

# Maximum number of revisions allowable in a stack to be auto-uplifted.
MAX_UPLIFT_STACK_SIZE = 5

UPLIFT_BUG_UPDATE_RETRIES = 3


def add_original_revision_line_if_needed(summary: str, uri: str) -> str:
    """Return the summary with `Original Revision` added."""
    if any(line.startswith("Original Revision:") for line in summary.splitlines()):
        return summary

    return f"{summary}\n\nOriginal Revision: {uri}"


def parse_milestone_version(milestone_contents: str) -> Version:
    """Parse the milestone version from the contents of `config/milestone.txt`."""
    try:
        # Get the last line of the file.
        milestone = milestone_contents.strip().splitlines()[-1]

        return Version(milestone)
    except InvalidVersion as e:
        raise ValueError(
            f"`config/milestone.txt` is not in the expected format:\n{milestone_contents}"
        ) from e


def get_uplift_request_form(revision: dict) -> Optional[str]:
    """Return the content of the uplift request form or `None` if missing."""
    bug = PhabricatorClient.expect(revision, "fields").get("uplift.request")
    return bug


@cache.cached(
    key_prefix="uplift-repositories", timeout=DEFAULT_CACHE_KEY_TIMEOUT_SECONDS
)
def get_uplift_repositories(phab: PhabricatorClient) -> list:
    repos = phab.call_conduit(
        "diffusion.repository.search",
        constraints={"projects": ["uplift"]},
    )

    repos = phab.expect(repos, "data")

    return repos


def get_revisions_without_bugs(phab: PhabricatorClient, revisions: dict) -> set[str]:
    """Return revisions in the stack without an associated bug number."""
    missing_bugs = set()
    for revision in revisions:
        bug_id = phab.expect(revision, "fields", "bugzilla.bug-id")

        if not bug_id:
            rev_id = phab.expect(revision, "id")
            missing_bugs.add(rev_id)

    return missing_bugs


def get_uplift_conduit_state(
    phab: PhabricatorClient, revision_id: int, target_repository_name: str
) -> tuple[RevisionData, RevisionStack, dict]:
    """Queries Conduit for repository and stack information about the requested uplift.

    Gathers information about:
        - the requested uplift repository.
        - the stack of revisions to be uplifted.

    Also enforces the stack has appropriate properties for uplift, such as a max
    stack size.
    """
    # Load target repo from Phabricator
    target_repo = phab.call_conduit(
        "diffusion.repository.search",
        # Attach `metrics` to get the most recent commit in the repo.
        attachments={"metrics": True},
        constraints={"shortNames": [target_repository_name]},
    )
    target_repo = phab.single(target_repo, "data")

    if not target_repo:
        raise ValueError(f"Could not find uplift target repo {target_repository_name}")

    # Load base revision details from Phabricator
    revision = phab.call_conduit(
        "differential.revision.search", constraints={"ids": [revision_id]}
    )
    revision = phab.single(revision, "data", none_when_empty=True)
    if not revision:
        raise ValueError(f"No revision found with id {revision_id}")

    nodes, edges = build_stack_graph(revision)

    stack_data = request_extended_revision_data(phab, list(nodes))

    if len(stack_data.revisions) > MAX_UPLIFT_STACK_SIZE:
        raise ValueError(
            f"Cannot create uplift for stack > {MAX_UPLIFT_STACK_SIZE} revisions."
        )

    missing_bugs = get_revisions_without_bugs(phab, stack_data.revisions.values())
    if missing_bugs:
        missing = ", ".join(f"D{rev_id}" for rev_id in missing_bugs)
        raise ValueError(
            f"Every uplifted patch must have an associated bug ID: {missing} do not."
        )

    stack = RevisionStack(set(stack_data.revisions.keys()), edges)

    return stack_data, stack, target_repo


def get_local_uplift_repo(phab: PhabricatorClient, target_repository: dict) -> Repo:
    """Return the local Repo object corresponding to `target_repository`.

    Raise if the repo is not an uplift repo.
    """
    # Check the target repository needs an approval.
    repos = get_repos_for_env(current_app.config.get("ENVIRONMENT"))
    repo_shortname = phab.expect(target_repository, "fields", "shortName")
    local_repo = repos.get(repo_shortname)

    if not local_repo:
        # Assert the repo is known.
        raise ValueError(f"Unknown repository {repo_shortname}")

    if not local_repo.approval_required:
        # Assert the repo is an uplift train.
        raise ValueError(f"No approval required for {repo_shortname}")

    return local_repo


DEPENDS_ON_RE = re.compile(r"^Depends on D\d+$")


def strip_depends_on_from_commit_message(commit_message: str) -> str:
    """Strip any found `Depends on` lines from the passed commit message.

    `moz-phab` still adds the `Depends on` lines to commit messages, which were
    previously the only method of specifying revision dependencies. Nowadays we
    have specific Conduit API calls which handle this functionality, and having
    the legacy `Depends on` values causes issues with uplift requests.
    """
    return "\n".join(
        line for line in commit_message.splitlines() if not DEPENDS_ON_RE.match(line)
    )


def create_uplift_revision(
    phab: PhabricatorClient,
    local_repo: Repo,
    source_revision: dict,
    source_diff: dict,
    parent_phid: Optional[str],
    base_revision: str,
    target_repository: dict,
) -> dict[str, str]:
    """Create a new revision on a repository, cloning a diff from another repo.

    Returns a `dict` to be returned as JSON from the uplift API.
    """
    # Get raw diff.
    raw_diff = phab.call_conduit("differential.getrawdiff", diffID=source_diff["id"])
    if not raw_diff:
        raise Exception("Missing raw source diff, cannot uplift revision.")

    # The first commit in the attachment list is the current HEAD of stack
    # we can use the HEAD to mark the changes being created.
    commits = phab.expect(source_diff, "attachments", "commits", "commits")

    if not commits or "identifier" not in commits[0]:
        raise ValueError("Source diff does not have commit information attached.")

    head = commits[0]["identifier"]

    # Upload it on target repo.
    new_diff = phab.call_conduit(
        "differential.creatediff",
        changes=patch_to_changes(raw_diff, head),
        sourceMachine=local_repo.url,
        sourceControlSystem=phab.expect(target_repository, "fields", "vcs"),
        sourceControlPath="/",
        sourceControlBaseRevision=base_revision,
        creationMethod="lando-uplift",
        lintStatus="none",
        unitStatus="none",
        repositoryPHID=phab.expect(target_repository, "phid"),
        sourcePath=None,
        branch=phab.expect(target_repository, "fields", "defaultBranch"),
    )
    new_diff_id = phab.expect(new_diff, "diffid")
    new_diff_phid = phab.expect(new_diff, "phid")
    logger.info("Created new diff", extra={"id": new_diff_id, "phid": new_diff_phid})

    # Attach commit information to setup the author (needed for landing).
    phab.call_conduit(
        "differential.setdiffproperty",
        diff_id=new_diff_id,
        name="local:commits",
        data=json.dumps(
            {
                commit["identifier"]: {
                    "author": phab.expect(commit, "author", "name"),
                    "authorEmail": phab.expect(commit, "author", "email"),
                    "time": 0,
                    "summary": phab.expect(commit, "message").splitlines()[0],
                    "message": strip_depends_on_from_commit_message(
                        phab.expect(commit, "message")
                    ),
                    "commit": phab.expect(commit, "identifier"),
                    "rev": phab.expect(commit, "identifier"),
                    "parents": [base_revision],
                }
                for commit in commits
            }
        ),
    )

    summary = str(phab.expect(source_revision, "fields", "summary"))

    # Add a link to the original revision if one isn't already present.
    # One may already be present if this revision is being uplift to a
    # second train.
    uri = str(phab.expect(source_revision, "fields", "uri"))
    summary = add_original_revision_line_if_needed(summary, uri)
    summary = strip_depends_on_from_commit_message(summary)

    transactions = [
        {"type": "update", "value": new_diff_phid},
        # Copy title & summary from source revision.
        {"type": "title", "value": phab.expect(source_revision, "fields", "title")},
        {"type": "summary", "value": summary},
        # Copy Bugzilla id.
        {
            "type": "bugzilla.bug-id",
            "value": phab.expect(source_revision, "fields", "bugzilla.bug-id"),
        },
    ]

    # Finally create the revision to link all the pieces.
    new_rev = phab.call_conduit(
        "differential.revision.edit",
        transactions=transactions,
    )
    new_rev_id = phab.expect(new_rev, "object", "id")
    new_rev_phid = phab.expect(new_rev, "object", "phid")
    logger.info(
        "Created new Phabricator revision",
        extra={"id": new_rev_id, "phid": new_rev_phid},
    )

    repository = str(phab.expect(target_repository, "fields", "shortName"))

    if parent_phid:
        # If `parent_phid` is defined, set the parent revision. We do this in a separate
        # transaction to avoid a bug where revisions with similar diff properties are
        # automatically associated with one another.
        phab.call_conduit(
            "differential.revision.edit",
            objectIdentifier=new_rev_phid,
            transactions=[{"type": "parents.set", "value": [parent_phid]}],
        )

    return {
        "mode": "uplift",
        "repository": repository,
        "url": f"{phab.url_base}/D{new_rev_id}",
        "revision_id": new_rev_id,
        "revision_phid": new_rev_phid,
        "diff_id": new_diff_id,
        "diff_phid": new_diff_phid,
    }


def stack_uplift_form_submitted(stack_data: RevisionData) -> bool:
    """Return `True` if the stack has a valid uplift request form submitted."""
    # NOTE: this just checks that any of the revisions in the stack have the uplift form
    # submitted.
    return any(
        get_uplift_request_form(revision) for revision in stack_data.revisions.values()
    )


def create_uplift_bug_update_payload(
    bug: dict, repo_name: str, milestone: int, milestone_tracking_flag_template: str
) -> dict[str, Any]:
    """Create a payload for updating a bug using the BMO REST API.

    Examines the data returned from the BMO REST API bug access endpoint to
    determine if any post-uplift updates should be made to the bug.

    - Sets the `status_firefoxXX` flags to `fixed`.
    - Removes `[checkin-needed-*]` from the bug whiteboard.

    Returns the bug update payload to be passed to the BMO REST API.
    """
    payload: dict[str, Any] = {
        "ids": [int(bug["id"])],
    }

    milestone_tracking_flag = milestone_tracking_flag_template.format(
        milestone=milestone
    )
    if (
        milestone_tracking_flag
        and "keywords" in bug
        and "leave-open" not in bug["keywords"]
        and milestone_tracking_flag in bug
    ):
        # Set the status of a bug to fixed if the fix was uplifted to a branch
        # and the "leave-open" keyword is not set.
        payload[milestone_tracking_flag] = "fixed"

    checkin_needed_flag = f"[checkin-needed-{repo_name}]"
    if "whiteboard" in bug and checkin_needed_flag in bug["whiteboard"]:
        # Remove "[checkin-needed-beta]" etc. texts from the whiteboard.
        payload["whiteboard"] = bug["whiteboard"].replace(checkin_needed_flag, "")

    return payload


def update_bugs_for_uplift(
    repo_name: str,
    milestone_file_contents: str,
    milestone_tracking_flag_template: str,
    bug_ids: list[str],
):
    """Update Bugzilla bugs for uplift."""
    if not bug_ids:
        raise ValueError("No bugs found in uplift landing.")

    params = {
        "id": ",".join(bug_ids),
    }

    # Get information about the parsed bugs.
    bugs = bmo.get_bug(params).json()["bugs"]

    # Get the major release number from `config/milestone.txt`.
    milestone = parse_milestone_version(milestone_file_contents)

    # Create bug update payloads.
    payloads = [
        create_uplift_bug_update_payload(
            bug, repo_name, milestone.major, milestone_tracking_flag_template
        )
        for bug in bugs
    ]

    for payload in payloads:
        for i in range(1, UPLIFT_BUG_UPDATE_RETRIES + 1):
            # Update bug and account for potential errors.
            try:
                bmo.update_bug(payload)

                break
            except requests.RequestException as e:
                if i == UPLIFT_BUG_UPDATE_RETRIES:
                    raise e

                logger.exception(
                    f"Error while updating bugs after uplift on attempt {i}, retrying...\n"
                    f"{str(e)}"
                )

                time.sleep(1.0 * i)
