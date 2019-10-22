# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import logging
import json

from landoapi.phabricator import PhabricatorClient
from landoapi.repos import get_repos_for_env
from landoapi.stacks import request_extended_revision_data

from flask import current_app


logger = logging.getLogger(__name__)


def get_release_managers(phab: PhabricatorClient) -> dict:
    """Load the release-managers group details from Phabricator"""
    groups = phab.call_conduit(
        "project.search", constraints={"slugs": ["release-managers"]}
    )
    group = phab.single(groups, "data")
    logger.info(f"Will request review from {group['fields']['name']} - {group['phid']}")
    return group


def check_approval_state(
    phab: PhabricatorClient, revision_id: int, target_repository_name: str
) -> dict:
    """
    Helper to load the Phabricator revision and its presence
    in the source and target repository
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

    # Load base revision details from Phabricator
    revision = phab.call_conduit(
        "differential.revision.search", constraints={"ids": [revision_id]}
    )
    revision = phab.single(revision, "data")

    # Lookup if this is an uplift or an approval request
    is_approval = revision["fields"]["repositoryPHID"] == target_repo["phid"]
    logger.info(
        "Revision {} needs an {} request towards repository {}".format(
            revision_id, is_approval and "approval" or "uplift", target_repository_name
        )
    )

    return {
        "target_repository": target_repo,
        "revision": revision,
        "is_approval": is_approval,
    }


def create_uplift_revision(
    phab: PhabricatorClient,
    source_revision: dict,
    target_repository: dict,
    form_content: str,
):
    """
    Create a new revision on a repository, cloning a diff from another repo
    """
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
    assert raw_diff, "Missing raw source diff"

    # Upload it on target repo
    new_diff = phab.call_conduit(
        "differential.createrawdiff",
        diff=raw_diff,
        repositoryPHID=target_repository["phid"],
    )
    new_diff_id = phab.expect(new_diff, "id")
    new_diff_phid = phab.expect(new_diff, "phid")
    logger.info(f"Created new diff {new_diff_id} - {new_diff_phid}")

    # Attach commit information to setup the author (needed for landing)
    commits = diff["attachments"]["commits"]["commits"]
    phab.call_conduit(
        "differential.setdiffproperty",
        diff_id=new_diff_id,
        name="local:commits",
        data=json.dumps(
            {
                commit["identifier"]: {
                    "author": commit["author"]["name"],
                    "authorEmail": commit["author"]["email"],
                    "time": 0,
                    "message": commit["message"],
                    "commit": commit["identifier"],
                    "tree": None,
                    "parents": commit["parents"],
                }
                for commit in commits
            }
        ),
    )

    # Finally create the revision to link all the pieces
    new_rev = phab.call_conduit(
        "differential.revision.edit",
        transactions=[
            {"type": "update", "value": new_diff_phid},
            {
                "type": "title",
                "value": f"Uplift request D{source_revision['id']}: {source_revision['fields']['title']}",  # noqa
            },
            # Set release managers as reviewers
            {"type": "reviewers.add", "value": [release_managers["phid"]]},
            # Post the form as a comment on the revision
            {"type": "comment", "value": form_content},
        ],
    )
    logger.info(
        f"Created new Phabricator revision {new_rev['object']['id']} - {new_rev['object']['phid']}"  # noqa
    )

    return {
        "mode": "uplift",
        "repository": target_repository["fields"]["shortName"],
        "url": f"{phab.url_base}/D{new_rev['object']['id']}",
        "revision_id": new_rev["object"]["id"],
        "revision_phid": new_rev["object"]["id"],
        "diff_id": new_diff_id,
        "diff_phid": new_diff_phid,
    }


def create_approval_request(phab: PhabricatorClient, revision: dict, form_content: str):
    """
    Update an existing revision with reviewers & form comment
    """
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
    assert rev["object"]["id"] == revision["id"], "Revision id mismatch"

    logger.info(
        f"Updated Phabricator revision {rev['object']['id']} - {rev['object']['phid']}"
    )

    return {
        "mode": "approval",
        "url": f"{phab.url_base}/D{rev['object']['id']}",
        "revision_id": rev["object"]["id"],
        "revision_phid": rev["object"]["id"],
    }
