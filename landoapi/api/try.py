# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import base64
import io
import logging
from typing import Iterable, Optional

from connexion import ProblemException
from flask import (
    current_app,
    g,
)

from landoapi import auth
from landoapi.hgexports import (
    GitPatchHelper,
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


# Borrowed from Mercurial core.
def person(author: bytes) -> bytes:
    """Returns the name before an email address,
    interpreting it as per RFC 5322

    >>> person(b'foo@bar')
    'foo'
    >>> person(b'Foo Bar <foo@bar>')
    'Foo Bar'
    >>> person(b'"Foo Bar" <foo@bar>')
    'Foo Bar'
    >>> person(b'"Foo \"buz\" Bar" <foo@bar>')
    'Foo "buz" Bar'
    >>> # The following are invalid, but do exist in real-life
    ...
    >>> person(b'Foo "buz" Bar <foo@bar>')
    'Foo "buz" Bar'
    >>> person(b'"Foo Bar <foo@bar>')
    'Foo Bar'
    """
    if b"@" not in author:
        return author
    f = author.find(b"<")
    if f != -1:
        return author[:f].strip(b' "').replace(b'\\"', b'"')
    f = author.find(b"@")
    return author[:f].replace(b".", b" ")


# Borrowed from Mercurial core.
def email(author: bytes) -> Optional[bytes]:
    """Get email of author."""
    r = author.find(b">")
    if r == -1:
        r = None
    return author[author.find(b"<") + 1 : r]


# TODO rename this.
def parse_values_from_user_header(user_header: bytes) -> tuple[bytes, bytes]:
    """Parse user's name and email address from the `User` Mercurial patch header."""
    return person(user_header), email(user_header)


def get_timestamp_from_date(date_header: bytes) -> int:
    """Convert a Git patch date header into a timestamp."""
    # TODO implement this properly
    return 0


def parse_hgexport_patches_to_revisions(patches: Iterable[bytes]) -> list[Revision]:
    """Turn an iterable of `bytes` patches from `hg export` into `Revision` objects."""
    # TODO test this and fix typing problems.
    revisions = []
    for patch in patches:
        helper = HgPatchHelper(io.BytesIO(patch))

        user = helper.header("User")
        if not user:
            raise ValueError("Patch does not have a `User` header.")

        author, email = parse_values_from_user_header(user)

        date = helper.header("Date")
        # TODO parse proper timestamp from Date.
        if not date:
            raise ValueError("Patch does not have a `Date` header.")

        # TODO make this a proper function with better handling.
        timestamp = date.split(b" ")[0]

        commit_message = helper.commit_description()
        if not commit_message:
            raise ValueError("Patch does not have a commit description.")

        revisions.append(
            Revision.new_from_patch(
                patch_bytes=helper.get_diff(),
                patch_data={
                    "author_name": author,
                    "author_email": email,
                    "commit_message": helper.commit_description(),
                    "timestamp": timestamp,
                },
            )
        )
    return revisions


def parse_git_format_patches_to_revisions(patches: Iterable[bytes]) -> list[Revision]:
    """Turn an iterable of `bytes` patches from `git format-patch` into `Revision` objects."""
    revisions = []

    for patch in patches:
        helper = GitPatchHelper(io.BytesIO(patch))

        from_header = helper.header("From")
        if not from_header:
            raise ValueError("Patch does not have a `From:` header.")

        author, email = parse_values_from_user_header(from_header)

        date = helper.header("Date")
        if not date:
            raise ValueError("Patch does not have a `Date:` header.")

        timestamp = get_timestamp_from_date(date)

        revisions.append(
            Revision.new_from_patch(
                patch_bytes=helper.get_diff(),
                patch_data={
                    "author_name": author,
                    "author_email": email,
                    "commit_message": helper.commit_description(),
                    # TODO this doesn't work apparently?
                    "timestamp": timestamp,
                },
            )
        )
    return revisions


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

    raise ValueError(f"Unknown value for `patch_format`: {patch_format}.")


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
