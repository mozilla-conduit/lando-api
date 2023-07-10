# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import base64
import io
import logging

from typing import Iterable

from connexion import ProblemException
from flask import (
    current_app,
    g,
)

from landoapi import auth
from landoapi.hgexports import (
    HgPatchHelper,
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


def parse_hgexport_patches_to_revisions(patches: Iterable[bytes]) -> list[Revision]:
    """Turn an iterable of `bytes` patches from `hg export` into `Revision` objects."""
    return [
        Revision.new_from_patch(
            patch_bytes=base64.b64decode(patch["diff"]).decode("ascii"),
            patch_data={
                "author_name": patch["author"],
                "author_email": patch["author_email"],
                "commit_message": patch["commit_message"],
                "timestamp": patch["timestamp"],
            },
        )
        # TODO should we just do a loop here?
        for patch in map(HgPatchHelper, map(io.BytesIO, patches))
    ]


def parse_git_format_patches_to_revisions(patches: Iterable[bytes]) -> list[Revision]:
    """Turn an iterable of `bytes` patches from `git format-patch` into `Revision` objects."""
    return [
        Revision.new_from_patch(
            # TODO write this function.
            patch_bytes=strip_git_diff_file_summary(diff),
            patch_data={
                # TODO write these two functions to parse fields from author.
                "author_name": get_author_name(commit.author),
                "author_email": get_author_email(commit.author),
                "commit_message": commit.message,
                # TODO this doesn't work apparently?
                "timestamp": commit.commit_time,
            },
        )
        # TODO should we just do a loop here?
        for commit, diff, git_vers in map(
            patch.git_am_split_patch, map(io.BytesIO, patches)
        )
    ]


def convert_json_patch_to_bytes(patch: str) -> bytes:
    """Convert from the base64 encoded patch to `bytes`."""
    return base64.b64decode(patch.encode("ascii"))


def parse_revisions_from_request(
    patches: list[str], patch_format: str
) -> list[Revision]:
    """Convert a set of base64 encoded patches to `Revision` objects."""
    patches_bytes = (convert_json_patch_to_bytes(patch) for patch in patches)

    if patch_format == "hgexport":
        return parse_hgexport_patches_to_revisions(patches_bytes)

    if patch_format == "git-format-patch":
        return parse_git_format_patches_to_revisions(patches_bytes)

    raise ValueError()


@auth.require_auth0(scopes=("openid", "lando", "profile", "email"), userinfo=True)
@auth.enforce_request_scm_level(SCM_LEVEL_1)
def post(data: dict):
    base_commit = data["base_commit"]
    patches = data["patches"]
    patch_format = data["patch_format"]

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
    revisions = parse_revisions_from_request(patches, patch_format)
    # TODO Parse patch data
    revisions = [
        Revision.new_from_patch(
            patch_bytes=base64.b64decode(patch["diff"]).decode("ascii"),
            patch_data={
                "author_name": patch["author"],
                "author_email": patch["author_email"],
                "commit_message": patch["commit_message"],
                "timestamp": patch["timestamp"],
            },
        )
        for patch in patches
    ]
    job = add_job_with_revisions(
        revisions,
        repository_name=try_repo.short_name,
        repository_url=try_repo.url,
        requester_email=ldap_username,
        status=LandingJobStatus.SUBMITTED,
        target_commit_hash=base_commit,
    )
    logger.info(
        f"Created try landing job with {len(revisions)} "
        f"changesets against {base_commit} for {ldap_username}."
    )

    return {"id": job.id}, 201
