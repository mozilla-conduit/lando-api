# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Tests for the PhabricatorClient
"""

import pytest
import requests
import requests_mock

from landoapi.phabricator_client import (
    PhabricatorClient, PhabricatorAPIException
)

from tests.utils import first_result_in_response, phab_url, phid_for_response
from tests.canned_responses.phabricator.errors import (
    CANNED_EMPTY_RESULT, CANNED_ERROR_1
)
from tests.canned_responses.phabricator.repos import (
    CANNED_REPO_MOZCENTRAL, CANNED_REPO_SEARCH_MOZCENTRAL
)
from tests.canned_responses.phabricator.revisions import (
    CANNED_EMPTY_REVIEWERS_ATT_RESPONSE, CANNED_REVISION_1,
    CANNED_EMPTY_REVISION_SEARCH, CANNED_TWO_REVIEWERS_SEARCH_RESPONSE
)
from tests.canned_responses.phabricator.users import (
    CANNED_USER_SEARCH_TWO_USERS, CANNED_USER_WHOAMI_1, CANNED_USER_SEARCH_1
)

pytestmark = pytest.mark.usefixtures('docker_env_vars')


def test_get_revision_with_200_response(phabfactory):
    revision_response = phabfactory.revision(id='D1234')
    expected_revision = first_result_in_response(revision_response)
    phab = PhabricatorClient(api_key='api-key')
    revision = phab.get_revision(id=1234)
    assert revision == expected_revision


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


def test_get_user_returns_with_200_response(phabfactory):
    user_response = phabfactory.user()
    expected_user = first_result_in_response(user_response)
    phid = phid_for_response(user_response)

    phab = PhabricatorClient(api_key='api-key')
    user = phab.get_user(phid)

    assert user == expected_user


def test_get_repo_returns_with_200_response(phabfactory):
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


def test_get_author_for_revision(phabfactory):
    user_response = phabfactory.user()
    phabfactory.revision(id='D5')
    expected_user = first_result_in_response(user_response)

    phab = PhabricatorClient(api_key='api-key')
    revision = phab.get_revision(id=5)
    author = phab.get_revision_author(revision)

    assert author == expected_user


def test_get_repo_info_by_phid_no_repo():
    phab = PhabricatorClient(api_key='api-key')
    with requests_mock.mock() as m:
        m.get(
            phab_url('diffusion.repository.search'),
            status_code=200,
            json={
                'result': {
                    'data': []
                },
                'error_info': None,
                'error_code': None
            }
        )
        repo = phab.get_repo_info_by_phid('anything')

    assert repo is None


def test_get_repo_info_by_phid(phabfactory):
    phabfactory.repo()
    expected_repo = CANNED_REPO_SEARCH_MOZCENTRAL['result']['data'][0]
    phab = PhabricatorClient(api_key='api-key')
    repo = phab.get_repo_info_by_phid('PHID-REPO-mozillacentral')

    assert repo == expected_repo


def test_get_repo_for_revision(phabfactory):
    phabfactory.revision(id='D5')
    expected_repo = CANNED_REPO_SEARCH_MOZCENTRAL['result']['data'][0]

    phab = PhabricatorClient(api_key='api-key')
    revision = phab.get_revision(id=5)
    repo = phab.get_revision_repo(revision)

    assert repo == expected_repo


def test_get_rawdiff_by_id(phabfactory):
    patch = "diff --git a/hello.c b/hello.c..."
    # The raw patch's diffID is encoded in the Diff URI.
    phabfactory.diff(id='12345', patch=patch)
    phab = PhabricatorClient(api_key='api-key')
    returned_patch = phab.get_rawdiff('12345')
    assert returned_patch == patch


def test_get_diff_by_id(phabfactory):
    expected = phabfactory.diff(id='9001')
    phab = PhabricatorClient(api_key='api-key')
    result = phab.get_diff(id='9001')
    assert result == expected['result']['9001']


def test_check_connection_success():
    phab = PhabricatorClient(api_key='api-key')
    success_json = CANNED_EMPTY_RESULT.copy()
    with requests_mock.mock() as m:
        m.get(phab_url('conduit.ping'), status_code=200, json=success_json)
        phab.check_connection()
        assert m.called


def test_raise_exception_if_ping_encounters_connection_error():
    phab = PhabricatorClient(api_key='api-key')
    with requests_mock.mock() as m:
        # Test with the generic ConnectionError, which is a superclass for
        # other connection error types.
        m.get(phab_url('conduit.ping'), exc=requests.ConnectionError)

        with pytest.raises(PhabricatorAPIException):
            phab.check_connection()
        assert m.called


def test_raise_exception_if_api_ping_times_out():
    phab = PhabricatorClient(api_key='api-key')
    with requests_mock.mock() as m:
        # Test with the generic Timeout exception, which all other timeout
        # exceptions derive from.
        m.get(phab_url('conduit.ping'), exc=requests.Timeout)

        with pytest.raises(PhabricatorAPIException):
            phab.check_connection()
        assert m.called


def test_raise_exception_if_api_returns_error_json_response():
    phab = PhabricatorClient(api_key='api-key')
    error_json = {
        "result": None,
        "error_code": "ERR-CONDUIT-CORE",
        "error_info": "BOOM"
    }

    with requests_mock.mock() as m:
        # Test with the generic Timeout exception, which all other timeout
        # exceptions derive from.
        m.get(phab_url('conduit.ping'), status_code=500, json=error_json)

        with pytest.raises(PhabricatorAPIException):
            phab.check_connection()
        assert m.called


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


def test_get_reviewers_no_revision():
    phab = PhabricatorClient(api_key='api-key')
    with requests_mock.mock() as m:
        m.get(
            phab_url('differential.revision.search'),
            status_code=200,
            json=CANNED_EMPTY_REVISION_SEARCH
        )
        result = phab.get_reviewers(1)

    assert result == {}


def test_get_reviewers_no_reviewers():
    phab = PhabricatorClient(api_key='api-key')
    with requests_mock.mock() as m:
        m.get(
            phab_url('differential.revision.search'),
            status_code=200,
            json=CANNED_EMPTY_REVIEWERS_ATT_RESPONSE
        )
        result = phab.get_reviewers(1)

    assert result == {}


def test_get_reviewers_two_reviewers():
    phab = PhabricatorClient(api_key='api-key')
    with requests_mock.mock() as m:
        m.get(
            phab_url('differential.revision.search'),
            status_code=200,
            json=CANNED_TWO_REVIEWERS_SEARCH_RESPONSE
        )
        m.get(
            phab_url('user.search'),
            status_code=200,
            json=CANNED_USER_SEARCH_TWO_USERS
        )
        result = phab.get_reviewers(1)

    assert len(result.keys()) == 2
    assert result['PHID-USER-2']['fields']['username'] == 'foo'
    assert result['PHID-USER-3']['fields']['username'] == 'bar'


def test_get_reviewers_reviewers_and_users_dont_match():
    phab = PhabricatorClient(api_key='api-key')
    with requests_mock.mock() as m:
        # Returns 2 reviewers
        m.get(
            phab_url('differential.revision.search'),
            status_code=200,
            json=CANNED_TWO_REVIEWERS_SEARCH_RESPONSE
        )
        # returns only 1 reviewer
        m.get(
            phab_url('user.search'),
            status_code=200,
            json=CANNED_USER_SEARCH_1
        )
        result = phab.get_reviewers(1)

    assert len(result.keys()) == 2
    assert result['PHID-USER-2']['fields']['username'] == 'johndoe'
    assert result['PHID-USER-2']['phid'] == 'PHID-USER-2'
    assert result['PHID-USER-2']['reviewerPHID'] == 'PHID-USER-2'
    assert 'fields' not in result['PHID-USER-3']
    assert 'phid' not in result['PHID-USER-3']
    assert result['PHID-USER-3']['reviewerPHID'] == 'PHID-USER-3'
