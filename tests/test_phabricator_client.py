# # This Source Code Form is subject to the terms of the Mozilla Public
# # License, v. 2.0. If a copy of the MPL was not distributed with this
# # file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
import os
import json
import requests_mock

from tests.utils import versionfile, app

from landoapi.phabricator_client import PhabricatorClient, \
    PhabricatorAPIException


def test_get_revision_returns_200():
    phab = PhabricatorClient(api_key='api-key')
    api_url = '%s/api/differential.query' % os.getenv('PHABRICATOR_URL')

    with requests_mock.mock() as m:
        # TODO finish testing response with actual data
        result = {'result': [{}], 'error_code': None, 'error_info': None}
        m.get(api_url, text=json.dumps(result))
        response = phab.get_revision(id='D123')
        assert response == {}


def test_get_current_user_returns_200():
    pass


def test_get_user_returns_200():
    pass


def test_get_repo_returns_200():
    pass


def test_phabricator_exception():
    pass


def test_request_exception():
    pass
