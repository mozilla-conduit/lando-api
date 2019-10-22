# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import logging

from connexion import problem
from flask import current_app, g

from landoapi import auth
from landoapi.repos import get_repos_for_env
from landoapi.uplift import (
    create_approval_request,
    create_uplift_revision,
    check_approval_state,
)
from landoapi.decorators import require_phabricator_api_key

logger = logging.getLogger(__name__)


@require_phabricator_api_key(optional=False)
@auth.require_auth0(scopes=("lando", "profile", "email"), userinfo=True)
def create(data):
    """Create new uplift requests for requested repository & revision"""

    # Validate repository
    all_repos = get_repos_for_env(current_app.config.get("ENVIRONMENT"))
    repository = next(
        iter(
            [
                repo_key
                for repo_key, repo in all_repos.items()
                if repo_key == data["repository"] and repo.approval_required is True
            ]
        ),
        None,
    )
    if repository is None:
        return problem(
            400,
            "No valid uplift repository",
            "Please select an uplift repository to create that uplift request.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
        )

    state = check_approval_state(
        g.phabricator,
        revision_id=data["revision_id"],
        target_repository_name=data["repository"],
    )

    try:
        if state["is_approval"]:
            output = create_approval_request(
                g.phabricator, state["revision"], data["form_content"]
            )
        else:
            output = create_uplift_revision(
                g.phabricator,
                state["revision"],
                state["target_repository"],
                data["form_content"],
            )
    except Exception as e:
        logger.error(
            "Failed to create an uplift request on revision {} and repository {} : {}".format(  # noqa
                data["revision_id"], repository, str(e)
            )
        )

        raise

    return output, 201
