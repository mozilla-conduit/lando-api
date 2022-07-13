# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import json
import logging
import re

from typing import (
    Optional,
    Tuple,
)

from flask import current_app

from landoapi.phabricator import PhabricatorClient, PhabricatorAPIException
from landoapi.phabricator_patch import patch_to_changes
from landoapi.projects import RELMAN_PROJECT_SLUG
from landoapi.repos import get_repos_for_env
from landoapi.stacks import (
    RevisionData,
    build_stack_graph,
    request_extended_revision_data,
)


logger = logging.getLogger(__name__)

# Maximum number of revisions allowable in a stack to be auto-uplifted.
MAX_UPLIFT_STACK_SIZE = 5

ARC_DIFF_REV_RE = re.compile(
    r"^\s*Differential Revision:\s*(?P<phab_url>https?://.+)/D(?P<rev>\d+)\s*$",
    flags=re.MULTILINE,
)
ORIGINAL_DIFF_REV_RE = re.compile(
    r"^\s*Original Revision:\s*(?P<phab_url>https?://.+)/D(?P<rev>\d+)\s*$",
    flags=re.MULTILINE,
)


def move_drev_to_original(body: str) -> str:
    """Handle moving the `Differential Revision` line.

    Moves the `Differential Revision` line to `Original Revision`, if a link
    to the original revision does not already exist. If the `Original Revision`
    line does exist, scrub the `Differential Revision` line.

    Args:
        body: `str` text of the commit message.

    Returns:
        New commit message body text as `str`.
    """
    differential_revision = ARC_DIFF_REV_RE.search(body)
    original_revision = ORIGINAL_DIFF_REV_RE.search(body)

    # If both match, we already have an `Original Revision` line.
    if differential_revision and original_revision:
        return body

    def repl(match):
        phab_url = match.group("phab_url")
        rev = match.group("rev")
        return f"\nOriginal Revision: {phab_url}/D{rev}"

    # Update the commit message.
    return ARC_DIFF_REV_RE.sub(repl, body)


def get_uplift_request_form(revision) -> Optional[str]:
    """Return the content of the uplift request form or `None` if missing."""
    bug = PhabricatorClient.expect(revision, "fields").get("uplift.request")
    return bug


def get_uplift_repositories(phab: PhabricatorClient) -> list:
    repos = phab.call_conduit(
        "diffusion.repository.search",
        constraints={"projects": ["uplift"]},
    )

    repos = phab.expect(repos, "data")

    return repos


def get_release_managers(phab: PhabricatorClient) -> dict:
    """Load the release-managers group details from Phabricator"""
    groups = phab.call_conduit(
        "project.search",
        attachments={"members": True},
        constraints={"slugs": [RELMAN_PROJECT_SLUG]},
    )
    return phab.single(groups, "data")


def get_uplift_conduit_state(
    phab: PhabricatorClient, revision_id: int, target_repository_name: str
) -> Tuple[RevisionData, dict]:
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
        constraints={"shortNames": [target_repository_name]},
    )
    target_repo = phab.single(target_repo, "data")

    # Load base revision details from Phabricator
    revision = phab.call_conduit(
        "differential.revision.search", constraints={"ids": [revision_id]}
    )
    revision = phab.single(revision, "data", none_when_empty=True)
    if not revision:
        raise ValueError(f"No revision found with id {revision_id}")

    try:
        nodes, _ = build_stack_graph(phab, phab.expect(revision, "phid"))
    except PhabricatorAPIException as e:
        # If a revision within the stack causes an API exception, treat the whole stack
        # as not found.
        logger.exception(
            f"Phabricator returned an error searching for {revision_id}: {str(e)}"
        )
        raise ValueError(f"Missing revision info for stack ending in {revision_id}")

    stack_data = request_extended_revision_data(phab, [phid for phid in nodes])

    if len(stack_data.revisions) > MAX_UPLIFT_STACK_SIZE:
        raise ValueError(
            f"Cannot create uplift for stack > {MAX_UPLIFT_STACK_SIZE} revisions."
        )

    return stack_data, target_repo


def create_uplift_revision(
    phab: PhabricatorClient,
    source_revision: dict,
    source_diff: dict,
    parent_phid: Optional[str],
    relman_phid: str,
    target_repository: dict,
) -> dict[str, str]:
    """Create a new revision on a repository, cloning a diff from another repo.

    Returns a `dict` to be returned as JSON from the uplift API.
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

    # Get raw diff.
    raw_diff = phab.call_conduit("differential.getrawdiff", diffID=source_diff["id"])
    if not raw_diff:
        raise Exception("Missing raw source diff, cannot uplift revision.")

    # Base revision hash is available on the diff fields.
    refs = {ref["type"]: ref for ref in phab.expect(source_diff, "fields", "refs")}
    base_revision = refs["base"]["identifier"] if "base" in refs else None

    # The first commit in the attachment list is the current HEAD of stack
    # we can use the HEAD to mark the changes being created.
    commits = phab.expect(source_diff, "attachments", "commits", "commits")
    head = commits[0] if commits else None

    # Upload it on target repo.
    new_diff = phab.call_conduit(
        "differential.creatediff",
        changes=patch_to_changes(raw_diff, head["identifier"] if head else None),
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
                    "message": phab.expect(commit, "message"),
                    "commit": phab.expect(commit, "identifier"),
                    "rev": phab.expect(commit, "identifier"),
                    "parents": phab.expect(commit, "parents"),
                }
                for commit in commits
            }
        ),
    )

    # Update `Differential Revision` to `Original Revision`.
    summary = str(phab.expect(source_revision, "fields", "summary"))
    summary = move_drev_to_original(summary)

    transactions = [
        {"type": "update", "value": new_diff_phid},
        # Copy title & summary from source revision.
        {"type": "title", "value": phab.expect(source_revision, "fields", "title")},
        {"type": "summary", "value": summary},
        # Set release managers as reviewers.
        {
            "type": "reviewers.add",
            "value": [f"blocking({relman_phid})"],
        },
        # Copy Bugzilla id.
        {
            "type": "bugzilla.bug-id",
            "value": phab.expect(source_revision, "fields", "bugzilla.bug-id"),
        },
    ]

    # If `parent_phid` is defined, add a transaction to set the parent.
    if parent_phid:
        transactions.append({"type": "parents.set", "value": [parent_phid]})

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

    return {
        "mode": "uplift",
        "repository": repository,
        "url": f"{phab.url_base}/D{new_rev_id}",
        "revision_id": new_rev_id,
        "revision_phid": new_rev_phid,
        "diff_id": new_diff_id,
        "diff_phid": new_diff_phid,
    }


def stack_uplift_form_submitted(stack_data) -> bool:
    """Return `True` if the stack has a valid uplift request form submitted."""
    # NOTE: this just checks that any of the revisions in the stack have the uplift form
    # submitted.
    return any(
        get_uplift_request_form(revision) for revision in stack_data.revisions.values()
    )
