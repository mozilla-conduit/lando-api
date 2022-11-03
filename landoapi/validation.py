# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import re

from connexion import ProblemException

REVISION_ID_RE = re.compile(r"^D(?P<id>[1-9][0-9]*)$")


def revision_id_to_int(revision_id: str) -> int:
    m = REVISION_ID_RE.match(revision_id)
    if m is None:
        raise ProblemException(
            400,
            "Bad Request",
            'Revision IDs must be of the form "D<integer>"',
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
        )

    return int(m.group("id"))


def parse_landing_path(landing_path: list[dict]) -> list[tuple[int, int]]:
    """Convert a list of landing path dicts with `str` values into a list of int tuples."""
    try:
        return [
            (revision_id_to_int(item["revision_id"]), int(item["diff_id"]))
            for item in landing_path
        ]
    except (ValueError, TypeError) as e:
        raise ProblemException(
            400,
            "Landing Path Malformed",
            f"The provided landing_path was malformed.\n{str(e)}",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
        )


def is_valid_email(email: str) -> bool:
    """Given a string, determines if it is a valid email.

    For the prefix, it will check for alphanumeric characters and acceptable
    special characters (.-_), but still ensure an alphanumeric comes before
    the @ symbol.

    For the suffix, it will check for an alphanumeric subdomain and accept hyphens.
    It then checks the TLD to make sure it only contains alphabet characters with
    a minimum length of two.

    Pattern modified from:
    https://stackabuse.com/python-validate-email-address-with-regular-expressions-regex
    """
    accepted_email_re = re.compile(
        r"([A-Za-z\d\-_.])*[A-Za-z\d]+@[A-Za-z\d\-]+(\.[A-Z|a-z]{2,})+"
    )
    return accepted_email_re.match(email) is not None
