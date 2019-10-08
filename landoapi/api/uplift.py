# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import logging

from connexion import problem
from flask import current_app, g

from landoapi import auth
from landoapi.repos import get_repos_for_env
from landoapi.uplift import create_uplift_revision
from landoapi.decorators import require_phabricator_api_key

logger = logging.getLogger(__name__)


@require_phabricator_api_key(optional=True)
@auth.require_auth0(scopes=("lando", "profile", "email"), userinfo=True)
def create(data):
    """Create new uplift requests for requested repositories & revision"""

    # Validate repositories
    all_repos = get_repos_for_env(current_app.config.get("ENVIRONMENT"))
    repositories = [
        repo_key
        for repo_key, repo in all_repos.items()
        if repo_key in data["repositories"] and repo.approval_required is True
    ]
    if not repositories:
        return problem(
            400,
            "No valid uplift repositories",
            "Please select an uplift repository to create that uplift request.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
        )

    out = {}
    for repo in repositories:
        # TODO: check this is not a duplicate

        try:
            out[repo] = create_uplift_revision(
                g.phabricator, data["revision_id"], repo, data
            )
        except Exception as e:
            logger.error(
                "Failed to create an uplift request on revision {} and repository {} : {}".format(  # noqa
                    data["revision_id"], repo, str(e)
                )
            )

            raise

    return out, 201
