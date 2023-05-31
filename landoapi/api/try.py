# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import base64
import logging

from connexion import ProblemException
from flask import (
    current_app,
    g,
)

from landoapi import auth
from landoapi.models.landing_job import (
    LandingJobStatus,
    add_job_with_revisions,
)
from landoapi.models.revisions import Revision
from landoapi.repos import get_repos_for_env

logger = logging.getLogger(__name__)


@auth.require_auth0(scopes=("lando", "profile", "email"), userinfo=True)
@auth.enforce_scm_level_1
def post(data: dict):
    base_commit = data["base_commit"]
    patches = data["patches"]

    if not base_commit or len(base_commit) != 40:
        raise ProblemException(
            400,
            "Base commit must be a 40-character commit hash.",
            "Base commit must be a 40-character commit hash.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
        )

    if not patches:
        raise ProblemException(
            400,
            "Patches must contain at least 1 patch.",
            "Patches must contain at least 1 patch.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
        )

    try_repo = get_repos_for_env(current_app.config.get("ENVIRONMENT")).get("try")
    if not try_repo:
        raise ProblemException(
            500,
            "Could not find a `try` repo to submit to.",
            "Could not find a `try` repo to submit to.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500",
        )

    # Add a landing job for this try push.
    ldap_username = g.auth0_user.email
    revisions = [
        # TODO do something more useful with `patch_data`, maybe gather data from
        # rs-parsepatch??
        Revision(patch_bytes=base64.b64decode(patch.encode("ascii")), patch_data={})
        for patch in patches
    ]
    add_job_with_revisions(
        revisions,
        repository_name=try_repo.short_name,
        repository_url=try_repo.url,
        requester_email=ldap_username,
        status=LandingJobStatus.SUBMITTED,
        target_cset=base_commit,
    )
    logger.info(
        f"Created try landing job with {len(revisions)} "
        f"changesets against {base_commit} for {ldap_username}."
    )

    return None, 201
