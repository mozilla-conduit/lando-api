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


def create_uplift_revision(
    phab: PhabricatorClient,
    source_revision_id: int,
    target_repository: str,
    form_content: str,
):
    """
    Create a new revision on a repository, cloning a diff from another repo
    """
    # Check the target repository needs an approval
    repos = get_repos_for_env(current_app.config.get("ENVIRONMENT"))
    local_repo = repos.get(target_repository)
    assert local_repo is not None, f"Unknown repository {target_repository}"
    assert (
        local_repo.approval_required is True
    ), f"No approval required for {target_repository}"

    # Load repo phid from Phabricator
    phab_repo = phab.call_conduit(
        "diffusion.repository.search", constraints={"shortNames": [target_repository]}
    )
    phab_repo = phab.single(phab_repo, "data")
    logger.info(
        f"Will create an uplift request on {phab_repo['fields']['name']} - {phab_repo['phid']}"  # noqa
    )

    # Load the release-managers group details from Phabricator
    release_managers = phab.call_conduit(
        "project.search", constraints={"slugs": ["release-managers"]}
    )
    release_managers = phab.single(release_managers, "data")
    logger.info(
        f"Will request review from {release_managers['fields']['name']} - {release_managers['phid']}"  # noqa
    )

    # Find the source diff on phabricator
    source_revision = phab.call_conduit(
        "differential.revision.search", constraints={"ids": [source_revision_id]}
    )
    source_revision = phab.single(source_revision, "data")
    stack = request_extended_revision_data(phab, [source_revision["phid"]])
    diff = stack.diffs[source_revision["fields"]["diffPHID"]]

    # Get raw diff
    raw_diff = phab.call_conduit("differential.getrawdiff", diffID=diff["id"])
    assert raw_diff, "Missing raw source diff"

    # Upload it on target repo
    new_diff = phab.call_conduit(
        "differential.createrawdiff", diff=raw_diff, repositoryPHID=phab_repo["phid"]
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
        "repository": target_repository,
        "url": f"{phab.url_base}/D{new_rev['object']['id']}",
        "revision_id": new_rev["object"]["id"],
        "revision_phid": new_rev["object"]["id"],
        "diff_id": new_diff_id,
        "diff_phid": new_diff_phid,
    }
