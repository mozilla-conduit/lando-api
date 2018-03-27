# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os
import re
from urllib.parse import parse_qs


def phab_url(path):
    """ Utility to generate a url to Phabricator's API """
    return '%s/api/%s' % (os.getenv('PHABRICATOR_URL'), path)


def trans_url(path):
    """ Utility to generate a url to Transplant's API """
    return '%s/%s' % (os.getenv('TRANSPLANT_URL'), path)


def first_result_in_response(response_json):
    """Unpack a Phabricator response JSON's first result.

    Returns:
        For {result: {'someid': {values}}} returns the {values} dict.  For
        {result: [{values}, ...]} returns the {values} dict for the first item
        in the result list.
    """
    maybe_list = response_json['result']
    try:
        return maybe_list[0]
    except KeyError:
        # Got a dict of values instead, like from phid.query.
        return list(maybe_list.values()).pop()


def phid_for_response(response_json):
    """Return the PHID field of the first object in a Phabricator result JSON.

    Which result in the JSON is returned follows the rules from the `uncan()`
    function.
    """
    return first_result_in_response(response_json)['phid']


def form_matcher(key, value):
    """Return a requests-mock matcher that matches a key and value in form data.
    """

    def match_form_data(request):
        qs = parse_qs(request.text)
        return value in qs.get(key, '')

    return match_form_data


def form_list_matcher(key, items):
    """Return a matcher for a key to a list of items."""

    item_set = set(items)

    def match_list_data(request):
        qs = parse_qs(request.text)
        matches_key = re.compile(re.escape(key) + r'\[(0|[1-9][0-9]*)\]')
        present = {
            v[0]
            for k, v in qs.items() if matches_key.match(k) is not None
        }
        return present == item_set

    return match_list_data
