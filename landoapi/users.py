# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from landoapi.phabricator import result_list_to_phid_dict


def user_search(phabricator, user_phids):
    """Return a dictionary mapping phid to user information from a user.search.

    Args:
        phabricator: A PhabricatorClient instance.
        user_phids: A list of user phids to search.
    """
    if not user_phids:
        return {}

    users = phabricator.call_conduit("user.search", constraints={"phids": user_phids})
    return result_list_to_phid_dict(phabricator.expect(users, "data"))
