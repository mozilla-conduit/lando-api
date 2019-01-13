# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from landoapi.phabricator import result_list_to_phid_dict


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
