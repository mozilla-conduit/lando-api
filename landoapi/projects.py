# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging

from typing import Optional

from landoapi.cache import cache, DEFAULT_CACHE_KEY_TIMEOUT_SECONDS
from landoapi.phabricator import result_list_to_phid_dict, PhabricatorClient

logger = logging.getLogger(__name__)


SEC_PROJ_SLUG = "secure-revision"
CHECKIN_PROJ_SLUG = "check-in_needed"

# Testing tag slugs. Revisions need one of these tags to remove the respective warnings.
TESTING_TAG_PROJ_SLUGS = (
    "testing-approved",
    "testing-exception-elsewhere",
    "testing-exception-other",
    "testing-exception-ui",
    "testing-exception-unchanged",
)
# A repo with a "testing-policy" project will have testing policy warnings enabled.
TESTING_POLICY_PROJ_SLUG = "testing-policy"

# The name of the Phabricator project containing members of the Secure
# Bug Approval Process.
# See https://wiki.mozilla.org/Security/Bug_Approval_Process.
SEC_APPROVAL_PROJECT_SLUG = "sec-approval"

# The name of the Phabricator project containing members of the Release
# Management team, to approve uplift requests
RELMAN_PROJECT_SLUG = "release-managers"


def project_search(
    phabricator: PhabricatorClient, project_phids: list[str]
) -> dict[str, dict]:
    """Return a dictionary mapping phid to project data from a project.search.

    Args:
        phabricator: A PhabricatorClient instance.
        project_phids: A list of project phids to search.
    """
    if not project_phids:
        return {}

    project_phids = list(project_phids)
    project_phids.sort()
    cache_key = ",".join(project_phids)

    if cache.has(cache_key):
        return cache.get(cache_key)

    projects = phabricator.call_conduit(
        "project.search", constraints={"phids": project_phids}
    )
    result = result_list_to_phid_dict(phabricator.expect(projects, "data"))
    cache.set(cache_key, result, timeout=DEFAULT_CACHE_KEY_TIMEOUT_SECONDS)
    return result


def get_project_phid(
    project_slug: str, phabricator: PhabricatorClient, allow_empty_result: bool = True
) -> Optional[str]:
    """Looks up a project's PHID.

    Args:
        project_slug: The name of the project we want the PHID for.
        phabricator: A PhabricatorClient instance.
        allow_empty_result: Should a missing project return None?
            Defaults to True.

    Raises:
        PhabricatorCommunicationException if the project could not be found and
         `allow_empty_result` is False.

    Returns:
        A string with the project's PHID or None if the project isn't found.
    """
    key = f"PROJECT_{project_slug}"
    if cache.has(key):
        return cache.get(key)

    project = phabricator.single(
        phabricator.call_conduit(
            "project.search", constraints={"slugs": [project_slug]}
        ),
        "data",
        none_when_empty=allow_empty_result,
    )

    value = phabricator.expect(project, "phid") if project else None
    cache.set(key, value, timeout=DEFAULT_CACHE_KEY_TIMEOUT_SECONDS)
    return value


def get_secure_project_phid(phabricator: PhabricatorClient) -> Optional[str]:
    """Return a phid for the project indicating revision security."""
    return get_project_phid(SEC_PROJ_SLUG, phabricator)


def get_checkin_project_phid(phabricator: PhabricatorClient) -> Optional[str]:
    """Return a phid for the project indicating check-in is needed."""
    return get_project_phid(CHECKIN_PROJ_SLUG, phabricator)


def get_testing_policy_phid(phabricator: PhabricatorClient) -> Optional[str]:
    """Return a phid for the project indicating testing policy."""
    return get_project_phid(TESTING_POLICY_PROJ_SLUG, phabricator)


def get_testing_tag_project_phids(
    phabricator: PhabricatorClient,
) -> Optional[list[str]]:
    """Return phids for the testing tag projects."""
    tags = [get_project_phid(slug, phabricator) for slug in TESTING_TAG_PROJ_SLUGS]
    return [t for t in tags if t is not None]


def get_sec_approval_project_phid(phabricator: PhabricatorClient) -> Optional[str]:
    """Return a phid for the sec-approval group's project.

    Args:
        phabricator: A PhabricatorClient instance.

    Returns:
        A string phid if the project is found, otherwise None.
    """
    return get_project_phid(SEC_APPROVAL_PROJECT_SLUG, phabricator)


def get_release_managers(phab: PhabricatorClient) -> Optional[dict]:
    """Load the release-managers group details from Phabricator"""
    groups = phab.call_conduit(
        "project.search",
        attachments={"members": True},
        constraints={"slugs": [RELMAN_PROJECT_SLUG]},
    )
    return phab.single(groups, "data")
