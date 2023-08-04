# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import base64
import binascii
import io
import logging

from connexion import ProblemException
from flask import (
    current_app,
    g,
)

from landoapi import auth
from landoapi.hgexports import (
    GitPatchHelper,
    HgPatchHelper,
    PatchHelper,
)
from landoapi.models.landing_job import (
    LandingJobStatus,
    add_job_with_revisions,
)
from landoapi.models.revisions import Revision
from landoapi.repos import (
    SCM_LEVEL_1,
    get_repos_for_env,
)

logger = logging.getLogger(__name__)


def build_revision_from_patch_helper(helper: PatchHelper) -> Revision:
    author, email = helper.parse_author_information()

    timestamp = helper.get_timestamp()

    commit_message = helper.get_commit_description()
    if not commit_message:
        raise ValueError("Patch does not have a commit description.")

    return Revision.new_from_patch(
        raw_diff=helper.get_diff(),
        patch_data={
            "author_name": author,
            "author_email": email,
            "commit_message": commit_message,
            "timestamp": timestamp,
        },
    )


def convert_json_patch_to_bytes(patch: str) -> bytes:
    """Convert from the base64 encoded patch to `bytes`."""
    try:
        return base64.b64decode(patch.encode("ascii"))
    except binascii.Error:
        raise ProblemException(
            400,
            "Patch decoding error.",
            "A patch could not be decoded from base64.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
        )


def parse_revisions_from_request(
    patches: list[str], patch_format: str
) -> list[Revision]:
    """Convert a set of base64 encoded patches to `Revision` objects."""
    patches_bytes = (
        io.BytesIO(convert_json_patch_to_bytes(patch)) for patch in patches
    )

    if patch_format == "hgexport":
        return [
            build_revision_from_patch_helper(HgPatchHelper(patch))
            for patch in patches_bytes
        ]

    if patch_format == "git-format-patch":
        return [
            build_revision_from_patch_helper(GitPatchHelper(patch))
            for patch in patches_bytes
        ]

    raise ValueError(f"Unknown value for `patch_format`: {patch_format}.")


@auth.require_auth0(scopes=("openid", "lando", "profile", "email"), userinfo=True)
@auth.enforce_request_scm_level(SCM_LEVEL_1)
def post_patches(data: dict):
    base_commit = data["base_commit"]
    patches = data["patches"]
    patch_format = data["patch_format"]

    environment_repos = get_repos_for_env(current_app.config.get("ENVIRONMENT"))
    try_repo = environment_repos.get("try")
    if not try_repo:
        raise ProblemException(
            500,
            "Could not find a `try` repo to submit to.",
            "Could not find a `try` repo to submit to.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500",
        )

    # Add a landing job for this try push.
    ldap_username = g.auth0_user.email
    revisions = parse_revisions_from_request(patches, patch_format)
    job = add_job_with_revisions(
        revisions,
        repository_name=try_repo.short_name,
        repository_url=try_repo.url,
        requester_email=ldap_username,
        status=LandingJobStatus.SUBMITTED,
        target_commit_hash=base_commit,
    )
    logger.info(
        f"Created try landing job {job.id} with {len(revisions)} "
        f"changesets against {base_commit} for {ldap_username}."
    )

    return {"id": job.id}, 201
