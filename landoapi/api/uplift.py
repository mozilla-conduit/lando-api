# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import logging

from connexion import problem
from flask import current_app

from landoapi import auth
from landoapi.decorators import require_phabricator_api_key
from landoapi.phabricator import PhabricatorClient
from landoapi.repos import get_repos_for_env
from landoapi.uplift import (
    create_uplift_revision,
    get_latest_non_commit_diff,
    get_local_uplift_repo,
    get_uplift_conduit_state,
    get_uplift_repositories,
)
from landoapi.validation import revision_id_to_int

logger = logging.getLogger(__name__)


@require_phabricator_api_key(optional=True)
def get(phab: PhabricatorClient):
    """Return the list of valid uplift repositories."""
    repos = [
        phab.expect(repo, "fields", "shortName")
        for repo in get_uplift_repositories(phab)
    ]

    return {"repos": repos}, 201


@require_phabricator_api_key(optional=False)
@auth.require_auth0(scopes=("lando", "profile", "email"), userinfo=True)
def create(phab: PhabricatorClient, data: dict):
    """Create new uplift requests for requested repository & revision"""
    repo_name = data["repository"]
    revision_id = revision_id_to_int(data["revision_id"])

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
                "revision": revision_id,
                "target_repository": repo_name,
            },
        )
        (
            revision_data,
            revision_stack,
            target_repository,
            rev_ids_to_all_diffs,
        ) = get_uplift_conduit_state(
            phab,
            revision_id=revision_id,
            target_repository_name=repo_name,
        )
        local_repo = get_local_uplift_repo(phab, target_repository)
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

    revision_phid = next(
        rev["phid"]
        for rev in revision_data.revisions.values()
        if rev["id"] == revision_id
    )

    # Get the most recent commit for `sourceControlBaseRevision`.
    base_revision = phab.expect(
        target_repository, "attachments", "metrics", "recentCommit", "identifier"
    )

    commit_stack = []
    for phid in revision_stack.iter_stack_from_root(dest=revision_phid):
        # Get the revision.
        revision = revision_data.revisions[phid]

        # Get the relevant diff.
        diff = get_latest_non_commit_diff(rev_ids_to_all_diffs[revision["id"]])

        # Get the parent commit PHID from the stack if available.
        parent_phid = commit_stack[-1]["revision_phid"] if commit_stack else None

        try:
            # Create the revision.
            rev = create_uplift_revision(
                phab,
                local_repo,
                revision,
                diff,
                parent_phid,
                base_revision,
                target_repository,
            )
            commit_stack.append(rev)
        except Exception as e:
            logger.error(
                "Failed to create an uplift request",
                extra={
                    "revision": revision_id,
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
