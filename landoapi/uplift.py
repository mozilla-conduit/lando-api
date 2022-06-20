# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import logging
import json
import time

from typing import (
    Any,
    Optional,
    Tuple,
)

import requests

from flask import current_app

from landoapi import bmo
from landoapi.commit_message import parse_bugs
from landoapi.phabricator import PhabricatorClient
from landoapi.phabricator_patch import patch_to_changes
from landoapi.projects import RELMAN_PROJECT_SLUG
from landoapi.repos import get_repos_for_env
from landoapi.stacks import (
    RevisionData,
    request_extended_revision_data,
)


logger = logging.getLogger(__name__)


UPLIFT_BUG_UPDATE_RETRIES = 3


def get_uplift_request_form(revision) -> Optional[str]:
    """Return the content of the uplift request form or `None` if missing."""
    bug = PhabricatorClient.expect(revision, "fields").get("uplift.request")
    return bug


def get_release_managers(phab: PhabricatorClient) -> dict:
    """Load the release-managers group details from Phabricator"""
    groups = phab.call_conduit(
        "project.search",
        attachments={"members": True},
        constraints={"slugs": [RELMAN_PROJECT_SLUG]},
    )
    return phab.single(groups, "data")


def check_approval_state(
    phab: PhabricatorClient, revision_id: int, target_repository_name: str
) -> Tuple[bool, dict, dict]:
    """Helper to load the Phabricator revision and check its approval requirement state

    * if the revision's target repository is the same as its current
      repository, it's an approval
    * otherwise it's an uplift request
    """

    # Load target repo from Phabricator
    target_repo = phab.call_conduit(
        "diffusion.repository.search",
        constraints={"shortNames": [target_repository_name]},
    )
    target_repo = phab.single(target_repo, "data")
    target_repo_phid = phab.expect(target_repo, "phid")

    # Load base revision details from Phabricator
    revision = phab.call_conduit(
        "differential.revision.search", constraints={"ids": [revision_id]}
    )
    revision = phab.single(revision, "data")
    revision_repo_phid = phab.expect(revision, "fields", "repositoryPHID")

    # Lookup if this is an uplift or an approval request
    is_approval = target_repo_phid == revision_repo_phid
    return is_approval, revision, target_repo


def create_uplift_revision(
    phab: PhabricatorClient,
    source_revision: dict,
    target_repository: dict,
    form_content: str,
):
    """Create a new revision on a repository, cloning a diff from another repo"""
    # Check the target repository needs an approval
    repos = get_repos_for_env(current_app.config.get("ENVIRONMENT"))
    local_repo = repos.get(target_repository["fields"]["shortName"])
    assert local_repo is not None, f"Unknown repository {target_repository}"
    assert (
        local_repo.approval_required is True
    ), f"No approval required for {target_repository}"

    # Load release managers group for review
    release_managers = get_release_managers(phab)

    # Find the source diff on phabricator
    stack = request_extended_revision_data(phab, [source_revision["phid"]])
    diff = stack.diffs[source_revision["fields"]["diffPHID"]]

    # Get raw diff
    raw_diff = phab.call_conduit("differential.getrawdiff", diffID=diff["id"])
    if not raw_diff:
        raise Exception("Missing raw source diff, cannot uplift revision.")

    # Base revision hash is available on the diff fields
    refs = {ref["type"]: ref for ref in phab.expect(diff, "fields", "refs")}
    base_revision = refs["base"]["identifier"] if "base" in refs else None

    # The first commit in the attachment list is the current HEAD of stack
    # we can use the HEAD to mark the changes being created
    commits = phab.expect(diff, "attachments", "commits", "commits")
    head = commits[0] if commits else None

    # Upload it on target repo
    new_diff = phab.call_conduit(
        "differential.creatediff",
        changes=patch_to_changes(raw_diff, head["identifier"] if head else None),
        sourceMachine=local_repo.url,
        sourceControlSystem="hg",
        sourceControlPath="/",
        sourceControlBaseRevision=base_revision,
        creationMethod="lando-uplift",
        lintStatus="none",
        unitStatus="none",
        repositoryPHID=target_repository["phid"],
        sourcePath=None,  # TODO ? Local path
        branch="HEAD",
    )
    new_diff_id = phab.expect(new_diff, "diffid")
    new_diff_phid = phab.expect(new_diff, "phid")
    logger.info("Created new diff", extra={"id": new_diff_id, "phid": new_diff_phid})

    # Attach commit information to setup the author (needed for landing)
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
                    "message": phab.expect(commit, "message"),
                    "commit": phab.expect(commit, "identifier"),
                    "tree": None,
                    "parents": phab.expect(commit, "parents"),
                }
                for commit in commits
            }
        ),
    )

    # Append an uplift mention to the summary
    summary = phab.expect(source_revision, "fields", "summary")
    summary += f"\nNOTE: Uplifted from D{source_revision['id']}"

    # Finally create the revision to link all the pieces
    new_rev = phab.call_conduit(
        "differential.revision.edit",
        transactions=[
            {"type": "update", "value": new_diff_phid},
            # Copy title & summary from source revision
            {"type": "title", "value": phab.expect(source_revision, "fields", "title")},
            {"type": "summary", "value": summary},
            # Set release managers as reviewers
            {"type": "reviewers.add", "value": [release_managers["phid"]]},
            # Post the form as a comment on the revision
            {"type": "comment", "value": form_content},
            # Copy Bugzilla id
            {
                "type": "bugzilla.bug-id",
                "value": phab.expect(source_revision, "fields", "bugzilla.bug-id"),
            },
        ],
    )
    new_rev_id = phab.expect(new_rev, "object", "id")
    new_rev_phid = phab.expect(new_rev, "object", "phid")
    logger.info(
        "Created new Phabricator revision",
        extra={"id": new_rev_id, "phid": new_rev_phid},
    )

    return {
        "mode": "uplift",
        "repository": phab.expect(target_repository, "fields", "shortName"),
        "url": f"{phab.url_base}/D{new_rev_id}",
        "revision_id": new_rev_id,
        "revision_phid": new_rev_phid,
        "diff_id": new_diff_id,
        "diff_phid": new_diff_phid,
    }


def create_approval_request(phab: PhabricatorClient, revision: dict, form_content: str):
    """Update an existing revision with reviewers & form comment"""
    release_managers = get_release_managers(phab)

    rev = phab.call_conduit(
        "differential.revision.edit",
        objectIdentifier=revision["phid"],
        transactions=[
            # Set release managers as reviewers
            {"type": "reviewers.add", "value": [release_managers["phid"]]},
            # Post the form as a comment on the revision
            {"type": "comment", "value": form_content},
        ],
    )
    rev_id = phab.expect(rev, "object", "id")
    rev_phid = phab.expect(rev, "object", "phid")
    assert rev_id == revision["id"], "Revision id mismatch"

    logger.info("Updated Phabricator revision", extra={"id": rev_id, "phid": rev_phid})

    return {
        "mode": "approval",
        "url": f"{phab.url_base}/D{rev_id}",
        "revision_id": rev_id,
        "revision_phid": rev_phid,
    }


def stack_uplift_form_submitted(stack_data: RevisionData) -> bool:
    """Return `True` if the stack has a valid uplift request form submitted."""
    # NOTE: this just checks that any of the revisions in the stack have the uplift form
    # submitted.
    return any(
        get_uplift_request_form(revision) for revision in stack_data.revisions.values()
    )


def create_uplift_bug_update_payload(
    bug: dict, repo_name: str, milestone: int
) -> dict[str, Any]:
    """Create a payload for updating a bug using the BMO REST API.

    Examines the data returned from the BMO REST API bug access endpoint to
    determine if any post-uplift updates should be made to the bug.

    - Sets the `status_firefoxXX` flags to `fixed`.
    - Removes `[checkin-needed-*]` from the bug whiteboard.

    Returns the bug update payload to be passed to the BMO REST API.
    """
    payload: dict[str, Any] = {
        "ids": [bug["id"]],
    }

    milestone_tracking_flag = f"cf_status_firefox{milestone}"
    if "leave-open" not in bug["keywords"] and milestone_tracking_flag in bug:
        # Set the status of a bug to fixed if the fix was uplifted to a branch
        # and the "leave-open" keyword is not set.
        payload[milestone_tracking_flag] = "fixed"

    checkin_needed_flag = f"[checkin-needed-{repo_name}]"
    if checkin_needed_flag in bug["whiteboard"]:
        # Remove "[checkin-needed-beta]" etc. texts from the whiteboard.
        payload["whiteboard"] = bug["whiteboard"].replace(checkin_needed_flag, "")

    return payload



def update_bugs_for_uplift(
    changeset_titles: list[str],
    repo_name: str,
    milestone: int,
):
    """Update Bugzilla bugs for uplift."""
    bugs = [str(bug) for title in changeset_titles for bug in parse_bugs(title)]
    params = {
        "ids": ",".join(bugs),
    }

    bugs = bmo.get_bug(params)["bugs"]

    for bug in bugs:
        payload = create_uplift_bug_update_payload(bug, repo_name, milestone)

        for i in range(1, UPLIFT_BUG_UPDATE_RETRIES + 1):
            # Update bug and account for potential errors.
            try:
                bmo.update_bug(payload)

                continue
            except requests.RequestException as e:
                if i == UPLIFT_BUG_UPDATE_RETRIES:
                    raise e

                logger.exception(
                    f"Error while updating bugs after uplift on attempt {i}, retrying..."
                )
                logger.exception(str(e))

                time.sleep(1.0 * i)
