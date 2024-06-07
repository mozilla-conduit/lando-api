# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import base64
import binascii
import enum
import io
import logging

import rs_parsepatch
from connexion import ProblemException
from flask import (
    current_app,
    g,
)

from landoapi import auth
from landoapi.hgexports import (
    DiffAssessor,
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
    Repo,
    get_repos_for_env,
)

logger = logging.getLogger(__name__)


@enum.unique
class PatchFormat(enum.Enum):
    """Enumeration of the acceptable types of patches."""

    GitFormatPatch = "git-format-patch"
    HgExport = "hgexport"


PATCH_HELPER_MAPPING = {
    PatchFormat.GitFormatPatch: GitPatchHelper,
    PatchFormat.HgExport: HgPatchHelper,
}


def build_revision_from_patch_helper(helper: PatchHelper, repo: Repo) -> Revision:
    author, email = helper.parse_author_information()

    timestamp = helper.get_timestamp()

    commit_message = helper.get_commit_description()
    if not commit_message:
        raise ValueError("Patch does not have a commit description.")

    raw_diff = helper.get_diff()

    # Check diff for errors.
    parsed_diff = rs_parsepatch.get_diffs(raw_diff)
    errors = DiffAssessor(
        author=author, commit_message=commit_message, parsed_diff=parsed_diff, repo=repo
    ).run_diff_checks()
    if errors:
        raise ValueError(f"Patch failed checks: {' '.join(errors)}")

    return Revision.new_from_patch(
        raw_diff=raw_diff,
        patch_data={
            "author_name": author,
            "author_email": email,
            "commit_message": commit_message,
            "timestamp": timestamp,
        },
    )


def decode_json_patch_to_text(patch: str) -> str:
    """Decode from the base64 encoded patch to `str`."""
    try:
        return base64.b64decode(patch.encode("ascii")).decode("utf-8")
    except binascii.Error:
        raise ProblemException(
            400,
            "Patch decoding error.",
            "A patch could not be decoded from base64.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
        )


def parse_revisions_from_request(
    patches: list[str], patch_format: PatchFormat, repo: Repo
) -> list[Revision]:
    """Convert a set of base64 encoded patches to `Revision` objects."""
    patches_io = (io.StringIO(decode_json_patch_to_text(patch)) for patch in patches)

    patch_helpers = (PATCH_HELPER_MAPPING[patch_format](patch) for patch in patches_io)

    try:
        return [
            build_revision_from_patch_helper(patch_helper, repo)
            for patch_helper in patch_helpers
        ]
    except ValueError as exc:
        raise ProblemException(
            400,
            "Improper patch format.",
            f"Patch does not match expected format `{patch_format.value}`: {str(exc)}",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
        )


@auth.require_auth0(scopes=("openid", "lando", "profile", "email"), userinfo=True)
# Re-enable this check once our Auth0 instance returns group membership for access
# tokens granted via the Device Authorization flow.
# @auth.enforce_request_scm_level(SCM_LEVEL_1)
def post_patches(data: dict):
    base_commit = data["base_commit"]
    patches = data["patches"]
    patch_format = PatchFormat(data["patch_format"])

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
    revisions = parse_revisions_from_request(patches, patch_format, try_repo)
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
