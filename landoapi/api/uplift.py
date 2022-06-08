# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import logging

from connexion import problem
from flask import current_app, g

from landoapi import auth
from landoapi.phabricator import PhabricatorClient
from landoapi.projects import get_relman_group_phid
from landoapi.repos import get_repos_for_env
from landoapi.transplants import convert_path_id_to_phid
from landoapi.uplift import (
    create_uplift_revision,
    get_uplift_conduit_state,
    get_uplift_repositories,
)
from landoapi.validation import parse_landing_path
from landoapi.decorators import require_phabricator_api_key

logger = logging.getLogger(__name__)


@auth.require_auth0(scopes=("lando", "profile", "email"), userinfo=True)
def get():
    """"""
    phab: PhabricatorClient = g.phabricator
    repos = [
        phab.expect(repo, "fields", "name") for repo in get_uplift_repositories(phab)
    ]

    return {"repos": repos}, 201


@require_phabricator_api_key(optional=False)
@auth.require_auth0(scopes=("lando", "profile", "email"), userinfo=True)
def create(data):
    """Create new uplift requests for requested repository & revision"""
    repo_name = data["repository"]
    landing_path = parse_landing_path(data["landing_path"])
    tip_revision_id = landing_path[-1][0]
    phab: PhabricatorClient = g.phabricator

    # Validate repository.
    all_repos = get_repos_for_env(current_app.config.get("ENVIRONMENT"))
    repository = all_repos.get(repo_name)
    if repository is None:
        return problem(
            400,
            f"Repository {repo_name} is not a repository known to Lando.",
            "Please select an uplift repository to create the uplift request.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
        )

    if not repository.approval_required:
        return problem(
            400,
            f"Repository {repo_name} is not an uplift repository.",
            "Please select an uplift repository to create the uplift request.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
        )

    try:
        logger.info(
            "Checking approval state",
            extra={
                "revision": tip_revision_id,
                "target_repository": repo_name,
            },
        )
        revision_data, target_repository = get_uplift_conduit_state(
            phab,
            revision_id=tip_revision_id,
            target_repository_name=repo_name,
        )
        logger.info("Approval state is valid")
    except ValueError as err:
        logger.exception(
            "Hit an error retreiving uplift state from conduit.",
            extra={"error": str(err)},
        )
        return problem(
            404,
            "Revision not found",
            err.args[0],
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404",
        )

    # Get the `#release-managers` group PHID for requesting review.
    relman_phid = get_relman_group_phid(phab)
    if not relman_phid:
        return problem(
            500,
            "#release-managers group not found.",
            (
                "The RelMan review group could not be found. This is a server-side "
                "issue, please file a bug."
            ),
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404",
        )

    landing_path = convert_path_id_to_phid(landing_path, revision_data)
    commit_stack = []
    for rev_id, _diff_id in landing_path:
        # Get the relevant revision.
        revision = revision_data.revisions[rev_id]

        # Get the relevant diff.
        diff_phid = phab.expect(revision, "fields", "diffPHID")
        diff = revision_data.diffs[diff_phid]

        # Get the parent commit PHID from the stack if available.
        parent_phid = commit_stack[-1]["revision_phid"] if commit_stack else None

        try:
            # Create the revision.
            rev = create_uplift_revision(
                phab, revision, diff, parent_phid, relman_phid, target_repository
            )
            commit_stack.append(rev)
        except Exception as e:
            logger.error(
                "Failed to create an uplift request",
                extra={
                    "revision": tip_revision_id,
                    "repository": repository,
                    "error": str(e),
                },
            )

            if commit_stack:
                # Log information about any half-completed stack uplifts.
                logger.error(
                    "Uplift request completed partially, some resources are invalid.",
                    extra={
                        "commit_stack": commit_stack,
                        "repository": repository,
                    },
                )
            raise

    output = {rev["revision_phid"]: rev for rev in commit_stack}
    output["tip_differential"] = commit_stack[-1]

    return output, 201
