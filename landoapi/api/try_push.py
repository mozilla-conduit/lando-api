# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import base64
import io
import logging
import math

from connexion import ProblemException
from dateutil.parser import parse as dateparse
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
def email(author: bytes) -> bytes:
    """Get email of author."""
    r = author.find(b">")
    if r == -1:
        r = None
    return author[author.find(b"<") + 1 : r]


def parse_git_author_information(user_header: bytes) -> tuple[bytes, bytes]:
    """Parse user's name and email address from a Git style author header.

    Converts a header like 'User Name <user@example.com>' to its separate parts.
    """
    return person(user_header), email(user_header)


def get_timestamp_from_git_date_header(date_header: bytes) -> str:
    """Convert a Git patch date header into a timestamp."""
    header_datetime = dateparse(date_header)
    return str(math.floor(header_datetime.timestamp()))


def get_timestamp_from_hg_date_header(date_header: bytes) -> bytes:
    """Return the first part of the `hg export` date header.

    >>> get_timestamp_from_hg_date_header(b"1686621879 14400")
    b"1686621879"
    """
    return date_header.split(b" ")[0]


def build_revision_from_hgexport_patch(patch: bytes) -> Revision:
    """Convert an `hg export` formatted `bytes` patch into a `Revision`."""
    helper = HgPatchHelper(io.BytesIO(patch))

    user = helper.header("User")
    if not user:
        raise ValueError("Patch does not have a `User` header.")

    author, email = parse_git_author_information(user)

    date = helper.header("Date")
    if not date:
        raise ValueError("Patch does not have a `Date` header.")

    timestamp = get_timestamp_from_hg_date_header(date)

    commit_message = helper.commit_description()
    if not commit_message:
        raise ValueError("Patch does not have a commit description.")

    # TODO should we avoid decoding everywhere?
    return Revision.new_from_patch(
        raw_diff=helper.get_diff().decode("utf-8"),
        patch_data={
            "author_name": author.decode("utf-8"),
            "author_email": email.decode("utf-8"),
            "commit_message": helper.commit_description().decode("utf-8"),
            "timestamp": timestamp.decode("utf-8"),
        },
    )


def build_revision_from_git_format_patch(patch: bytes) -> Revision:
    """Turn a `git format-patch` formatted `bytes` patch into a `Revision`."""
    helper = GitPatchHelper(io.BytesIO(patch))

    from_header = helper.header(b"From")
    if not from_header:
        raise ValueError("Patch does not have a `From:` header.")

    author, email = parse_git_author_information(from_header)

    date = helper.header(b"Date")
    if not date:
        raise ValueError("Patch does not have a `Date:` header.")

    timestamp = get_timestamp_from_git_date_header(date)

    return Revision.new_from_patch(
        raw_diff=helper.get_diff().decode("utf-8"),
        patch_data={
            "author_name": author.decode("utf-8"),
            "author_email": email.decode("utf-8"),
            "commit_message": helper.commit_description().decode("utf-8"),
            "timestamp": timestamp,
        },
    )


def convert_json_patch_to_bytes(patch: str) -> bytes:
    """Convert from the base64 encoded patch to `bytes`."""
    return base64.b64decode(patch.encode("ascii"))


def parse_revisions_from_request(
    patches: list[str], patch_format: str
) -> list[Revision]:
    """Convert a set of base64 encoded patches to `Revision` objects."""
    patches_bytes = (convert_json_patch_to_bytes(patch) for patch in patches)

    if patch_format == "hgexport":
        return [build_revision_from_hgexport_patch(patch) for patch in patches_bytes]

    if patch_format == "git-format-patch":
        return [build_revision_from_git_format_patch(patch) for patch in patches_bytes]

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
