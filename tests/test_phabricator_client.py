# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Tests for the PhabricatorClient
"""
import pytest
import requests_mock

from landoapi.phabricator_client import PhabricatorClient, \
    PhabricatorAPIException

from tests.utils import *
from tests.canned_responses.phabricator.revisions import *
from tests.canned_responses.phabricator.users import *
from tests.canned_responses.phabricator.repos import *
from tests.canned_responses.phabricator.errors import *


def test_get_revision_with_200_response():
    phab = PhabricatorClient(api_key='api-key')
    with requests_mock.mock() as m:
        m.get(
            phab_url('differential.query'),
            status_code=200,
            json=CANNED_REVISION_1
        )
        revision = phab.get_revision(id=CANNED_REVISION_1['result'][0]['id'])
        assert revision == CANNED_REVISION_1['result'][0]


def test_get_current_user_with_200_response():
    phab = PhabricatorClient(api_key='api-key')
    with requests_mock.mock() as m:
        m.get(
            phab_url('user.whoami'),
            status_code=200,
            json=CANNED_USER_WHOAMI_1
        )
        user = phab.get_current_user()
        assert user == CANNED_USER_WHOAMI_1['result']


def test_get_user_returns_with_200_response():
    phab = PhabricatorClient(api_key='api-key')
    with requests_mock.mock() as m:
        m.get(phab_url('user.query'), status_code=200, json=CANNED_USER_1)
        user = phab.get_user(phid=CANNED_USER_1['result'][0]['phid'])
        assert user == CANNED_USER_1['result'][0]


def test_get_repo_returns_with_200_response():
    phab = PhabricatorClient(api_key='api-key')
    with requests_mock.mock() as m:
        m.get(
            phab_url('phid.query'),
            status_code=200,
            json=CANNED_REPO_MOZCENTRAL
        )
        canned_response_repo = \
            list(CANNED_REPO_MOZCENTRAL['result'].values())[0]
        repo = phab.get_repo(phid=canned_response_repo['phid'])
        assert repo == canned_response_repo


def test_phabricator_exception():
    """ Ensures that the PhabricatorClient converts JSON errors from Phabricator
    into proper exceptions with the error_code and error_message in tact.
    """
    phab = PhabricatorClient(api_key='api-key')
    with requests_mock.mock() as m:
        m.get(
            phab_url('differential.query'),
            status_code=200,
            json=CANNED_ERROR_1
        )
        with pytest.raises(PhabricatorAPIException) as e_info:
            phab.get_revision(id=CANNED_REVISION_1['result'][0]['id'])
        assert e_info.value.error_code == CANNED_ERROR_1['error_code']
        assert e_info.value.error_info == CANNED_ERROR_1['error_info']
