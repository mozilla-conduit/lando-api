# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging

from typing import Optional, List

from landoapi.cache import cache, DEFAULT_CACHE_KEY_TIMEOUT_SECONDS
from landoapi.phabricator import result_list_to_phid_dict, PhabricatorClient

logger = logging.getLogger(__name__)


SEC_PROJ_SLUG = "secure-revision"
SEC_PROJ_CACHE_KEY = "secure-project-phid"
CHECKIN_PROJ_SLUG = "check-in_needed"
CHECKIN_PROJ_CACHE_KEY = "checkin-project-phid"

# Testing tag slugs. Revisions need one of these tags to remove the respective warnings.
TESTING_TAG_PROJ_SLUGS = (
    "testing-approved",
    "testing-exception-elsewhere",
    "testing-exception-other",
    "testing-exception-ui",
    "testing-exception-unchanged",
)
TESTING_TAGS_PROJ_CACHE_KEY = "testing-tag-phids"

# A repo with a "testing-policy" project will have testing policy warnings enabled.
TESTING_POLICY_PROJ_SLUG = "testing-policy"
TESTING_POLICY_PROJ_CACHE_KEY = "testing-policy-phid"

# The name of the Phabricator project containing members of the Secure
# Bug Approval Process.
# See https://wiki.mozilla.org/Security/Bug_Approval_Process.
SEC_APPROVAL_PROJECT_SLUG = "sec-approval"
SEC_APPROVAL_CACHE_KEY = "sec-approval-project-phid"
# The name of the Phabricator project containing members of the Release
# Management team, to approve uplift requests
RELMAN_PROJECT_SLUG = "release-managers"
RELMAN_CACHE_KEY = "release-managers-project-phid"


def project_search(phabricator, project_phids):
    """Return a dictionary mapping phid to project data from a project.search.

    Args:
        phabricator: A PhabricatorClient instance.
        project_phids: A list of project phids to search.
    """
    if not project_phids:
        return {}

    projects = phabricator.call_conduit(
        "project.search", constraints={"phids": project_phids}
    )
    return result_list_to_phid_dict(phabricator.expect(projects, "data"))


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
    project = phabricator.single(
        phabricator.call_conduit(
            "project.search", constraints={"slugs": [project_slug]}
        ),
        "data",
        none_when_empty=allow_empty_result,
    )

    if project is None:
        logger.warning(f"Could not find a project phid", extra=dict(slug=project_slug))
        return None

    return phabricator.expect(project, "phid")


@cache.cached(key_prefix=SEC_PROJ_CACHE_KEY, timeout=DEFAULT_CACHE_KEY_TIMEOUT_SECONDS)
def get_secure_project_phid(phabricator: PhabricatorClient) -> Optional[str]:
    """Return a phid for the project indicating revision security."""
    return get_project_phid(SEC_PROJ_SLUG, phabricator)


@cache.cached(
    key_prefix=CHECKIN_PROJ_CACHE_KEY, timeout=DEFAULT_CACHE_KEY_TIMEOUT_SECONDS
)
def get_checkin_project_phid(phabricator: PhabricatorClient) -> Optional[str]:
    """Return a phid for the project indicating check-in is needed."""
    return get_project_phid(CHECKIN_PROJ_SLUG, phabricator)


@cache.cached(
    key_prefix=TESTING_POLICY_PROJ_CACHE_KEY, timeout=DEFAULT_CACHE_KEY_TIMEOUT_SECONDS
)
def get_testing_policy_phid(phabricator: PhabricatorClient) -> Optional[str]:
    """Return a phid for the project indicating testing policy."""
    return get_project_phid(TESTING_POLICY_PROJ_SLUG, phabricator)


@cache.cached(
    key_prefix=TESTING_TAGS_PROJ_CACHE_KEY, timeout=DEFAULT_CACHE_KEY_TIMEOUT_SECONDS
)
def get_testing_tag_project_phids(
    phabricator: PhabricatorClient,
) -> Optional[List[str]]:
    """Return phids for the testing tag projects."""
    tags = [get_project_phid(slug, phabricator) for slug in TESTING_TAG_PROJ_SLUGS]
    return [t for t in tags if t is not None]


@cache.cached(
    key_prefix=SEC_APPROVAL_CACHE_KEY, timeout=DEFAULT_CACHE_KEY_TIMEOUT_SECONDS
)
def get_sec_approval_project_phid(phabricator: PhabricatorClient) -> Optional[str]:
    """Return a phid for the sec-approval group's project.

    Args:
        phabricator: A PhabricatorClient instance.

    Returns:
        A string phid if the project is found, otherwise None.
    """
    return get_project_phid(SEC_APPROVAL_PROJECT_SLUG, phabricator)


@cache.cached(key_prefix=RELMAN_CACHE_KEY, timeout=DEFAULT_CACHE_KEY_TIMEOUT_SECONDS)
def get_relman_group_phid(phabricator: PhabricatorClient) -> Optional[str]:
    """Return a phid for the relman group's project."""
    return get_project_phid(RELMAN_PROJECT_SLUG, phabricator)
