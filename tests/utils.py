# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import json
import os
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


def phab_matcher(indicies, value):
    """Return a requests-mock matcher for data in phabricator params.

    `indicies` should be an iterable of keys which will be accessed from
    the phabricator parameters in order.
    """

    def match(request):
        params = json.loads(parse_qs(request.text).get('params', ['{}'])[0])
        for i in indicies:
            try:
                params = params[i]
            except (IndexError, KeyError):
                return False

        return value == params

    return match


def phab_list_matcher(indicies, items):
    """Return a matcher from indicies to a list of items."""

    def match(request):
        params = json.loads(parse_qs(request.text).get('params', ['{}'])[0])
        for i in indicies:
            try:
                params = params[i]
            except (IndexError, KeyError):
                return False

        return set(items) == set(params)

    return match
