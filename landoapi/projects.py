# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging

from landoapi.cache import cache
from landoapi.phabricator import result_list_to_phid_dict

logger = logging.getLogger(__name__)

SEC_PROJ_SLUG = "secure-revision"
SEC_PROJ_CACHE_KEY = "secure-project-phid"
SEC_PROJ_CACHE_TIMEOUT = 86400  # 60s * 60m * 24h
CHECKIN_PROJ_SLUG = "check-in_needed"
CHECKIN_PROJ_CACHE_KEY = "checkin-project-phid"
CHECKIN_PROJ_CACHE_TIMEOUT = 86400  # 60s * 60m * 24h


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


@cache.cached(key_prefix=SEC_PROJ_CACHE_KEY, timeout=SEC_PROJ_CACHE_TIMEOUT)
def get_secure_project_phid(phabricator):
    """Return a phid for the project indicating revision security.

    Args:
        phabricator: A PhabricatorClient instance.

    Returns:
        A string phid if the project is found, otherwise None.
    """
    project = phabricator.single(
        phabricator.call_conduit(
            "project.search", constraints={"slugs": [SEC_PROJ_SLUG]}
        ),
        "data",
        none_when_empty=True,
    )

    if project is None:
        logger.warning(
            "Could not find a phid for the secure project",
            extra=dict(slug=SEC_PROJ_SLUG),
        )
        return None

    return phabricator.expect(project, "phid")


@cache.cached(key_prefix=CHECKIN_PROJ_CACHE_KEY, timeout=CHECKIN_PROJ_CACHE_TIMEOUT)
def get_checkin_project_phid(phabricator):
    """Return a phid for the project indicating check-in is needed.

    Args:
        phabricator: A PhabricatorClient instance.

    Returns:
        A string phid if the project is found, otherwise None.
    """
    project = phabricator.single(
        phabricator.call_conduit(
            "project.search", constraints={"slugs": [CHECKIN_PROJ_SLUG]}
        ),
        "data",
        none_when_empty=True,
    )

    if project is None:
        logger.warning(
            "Could not find a phid for the Check-in Needed project",
            extra=dict(slug=CHECKIN_PROJ_SLUG),
        )
        return None

    return phabricator.expect(project, "phid")
