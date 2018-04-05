# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Tests for the PhabricatorClient
"""

import pytest
import requests
import requests_mock

from landoapi.phabricator import (
    CLOSED_STATUSES, OPEN_STATUSES, PhabricatorAPIException, Statuses
)

from tests.utils import first_result_in_response, phab_url, phid_for_response
from tests.canned_responses.phabricator.errors import (
    CANNED_EMPTY_RESULT, CANNED_ERROR_1
)
from tests.canned_responses.phabricator.repos import (
    CANNED_REPO_SEARCH_MOZCENTRAL
)
from tests.canned_responses.phabricator.revisions import (
    CANNED_EMPTY_REVIEWERS_ATT_RESPONSE, CANNED_REVISION_1,
    CANNED_EMPTY_REVISION_SEARCH, CANNED_TWO_REVIEWERS_SEARCH_RESPONSE
)
from tests.canned_responses.phabricator.users import (
    CANNED_USER_SEARCH_TWO_USERS, CANNED_USER_WHOAMI_1, CANNED_USER_SEARCH_1
)

pytestmark = pytest.mark.usefixtures('docker_env_vars')


def test_whoami_with_200_response(get_phab_client):
    phab = get_phab_client(api_key='api-key')
    with requests_mock.mock() as m:
        m.get(
            phab_url('user.whoami'),
            status_code=200,
            json=CANNED_USER_WHOAMI_1
        )
        user = phab.call_conduit('user.whoami')
        assert user == CANNED_USER_WHOAMI_1['result']


def test_user_query_returns_with_200_response(phabfactory, get_phab_client):
    user_response = phabfactory.user()
    expected_user = first_result_in_response(user_response)
    phid = phid_for_response(user_response)

    phab = get_phab_client(api_key='api-key')
    user = phab.call_conduit('user.query', phids=[phid])

    assert len(user) == 1
    assert user[0] == expected_user


def test_get_author_for_revision(phabfactory, get_phab_client):
    user_response = phabfactory.user()
    phabfactory.revision(id='D5')
    expected_user = first_result_in_response(user_response)

    phab = get_phab_client(api_key='api-key')
    revision = phab.call_conduit('differential.query', ids=[5])[0]
    author = phab.call_conduit('user.query', phids=[revision['authorPHID']])

    assert len(author) == 1
    assert author[0] == expected_user


def test_repository_search(phabfactory, get_phab_client):
    phabfactory.repo()
    expected_repo = CANNED_REPO_SEARCH_MOZCENTRAL['result']['data'][0]
    phab = get_phab_client(api_key='api-key')
    repo = phab.call_conduit(
        'diffusion.repository.search',
        constraints={'phids': ['PHID-REPO-mozillacentral']}
    )

    assert repo['data'][0] == expected_repo


def test_repository_search_no_repo(get_phab_client):
    phab = get_phab_client(api_key='api-key')
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
        repo = phab.call_conduit(
            'diffusion.repository.search', constraints={'phids': ['anything']}
        )

    assert not repo['data']


def test_get_rawdiff_by_id(phabfactory, get_phab_client):
    patch = "diff --git a/hello.c b/hello.c..."
    # The raw patch's diffID is encoded in the Diff URI.
    phabfactory.diff(id=12345, patch=patch)
    phab = get_phab_client(api_key='api-key')
    returned_patch = phab.call_conduit('differential.getrawdiff', diffID=12345)
    assert returned_patch == patch


def test_get_diff_by_id(phabfactory, get_phab_client):
    expected = phabfactory.diff(id=9001)
    phab = get_phab_client(api_key='api-key')
    result = phab.call_conduit('differential.querydiffs', ids=[9001])
    assert result['9001'] == expected['result']['9001']


def test_ping_success(get_phab_client):
    phab = get_phab_client(api_key='api-key')
    success_json = CANNED_EMPTY_RESULT.copy()
    with requests_mock.mock() as m:
        m.get(phab_url('conduit.ping'), status_code=200, json=success_json)
        phab.call_conduit('conduit.ping')
        assert m.called


def test_raise_exception_if_ping_encounters_connection_error(get_phab_client):
    phab = get_phab_client(api_key='api-key')
    with requests_mock.mock() as m:
        # Test with the generic ConnectionError, which is a superclass for
        # other connection error types.
        m.get(phab_url('conduit.ping'), exc=requests.ConnectionError)

        with pytest.raises(PhabricatorAPIException):
            phab.call_conduit('conduit.ping')
        assert m.called


def test_raise_exception_if_api_ping_times_out(get_phab_client):
    phab = get_phab_client(api_key='api-key')
    with requests_mock.mock() as m:
        # Test with the generic Timeout exception, which all other timeout
        # exceptions derive from.
        m.get(phab_url('conduit.ping'), exc=requests.Timeout)

        with pytest.raises(PhabricatorAPIException):
            phab.call_conduit('conduit.ping')
        assert m.called


def test_raise_exception_if_api_returns_error_json_response(get_phab_client):
    phab = get_phab_client(api_key='api-key')
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
            phab.call_conduit('conduit.ping')
        assert m.called


def test_phabricator_exception(get_phab_client):
    """ Ensures that the PhabricatorClient converts JSON errors from Phabricator
    into proper exceptions with the error_code and error_message in tact.
    """
    phab = get_phab_client(api_key='api-key')
    with requests_mock.mock() as m:
        m.get(
            phab_url('differential.query'),
            status_code=200,
            json=CANNED_ERROR_1
        )
        with pytest.raises(PhabricatorAPIException) as e_info:
            phab.call_conduit(
                'differential.query',
                ids=[CANNED_REVISION_1['result'][0]['id']]
            )[0]
        assert e_info.value.error_code == CANNED_ERROR_1['error_code']
        assert e_info.value.error_info == CANNED_ERROR_1['error_info']


def test_get_reviewers_no_revision(get_phab_client):
    phab = get_phab_client(api_key='api-key')
    with requests_mock.mock() as m:
        m.get(
            phab_url('differential.revision.search'),
            status_code=200,
            json=CANNED_EMPTY_REVISION_SEARCH
        )
        with pytest.raises(PhabricatorAPIException):
            phab.get_reviewers(1)


def test_get_reviewers_no_reviewers(get_phab_client):
    phab = get_phab_client(api_key='api-key')
    with requests_mock.mock() as m:
        m.get(
            phab_url('differential.revision.search'),
            status_code=200,
            json=CANNED_EMPTY_REVIEWERS_ATT_RESPONSE
        )
        result = phab.get_reviewers(1)

    assert result == {}


def test_get_reviewers_two_reviewers(get_phab_client):
    phab = get_phab_client(api_key='api-key')
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

    assert len(result) == 2
    assert result[0]['fields']['username'] == 'foo'
    assert result[1]['fields']['username'] == 'bar'


def test_get_reviewers_reviewers_and_users_dont_match(get_phab_client):
    phab = get_phab_client(api_key='api-key')
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

    assert len(result) == 2
    assert result[0]['fields']['username'] == 'johndoe'
    assert result[0]['phid'] == 'PHID-USER-2'
    assert result[0]['reviewerPHID'] == 'PHID-USER-2'
    assert 'fields' not in result[1]
    assert 'phid' not in result[1]
    assert result[1]['reviewerPHID'] == 'PHID-USER-3'


def test_no_parent(phabfactory, get_phab_client):
    result = phabfactory.revision()
    revision = result['result'][0]
    phab = get_phab_client(api_key='api-key')

    assert phab.get_first_open_parent_revision(revision) is None


@pytest.mark.parametrize('status', OPEN_STATUSES)
def test_open_parent(status, phabfactory, get_phab_client):
    parent_data = phabfactory.revision(status=status.value)
    parent = parent_data['result'][0]
    result = phabfactory.revision(id='D2', depends_on=parent_data)
    revision = result['result'][0]
    phab = get_phab_client(api_key='api-key')

    assert phab.get_first_open_parent_revision(revision) == parent


def test_open_grandparent(phabfactory, get_phab_client):
    grandparent_data = phabfactory.revision(
        status=Statuses.NEEDS_REVISION.value
    )
    grandparent = grandparent_data['result'][0]
    parent_result = phabfactory.revision(
        id='D2', status=Statuses.CLOSED.value, depends_on=grandparent_data
    )
    result = phabfactory.revision(id='D3', depends_on=parent_result)
    revision = result['result'][0]
    phab = get_phab_client(api_key='api-key')

    assert phab.get_first_open_parent_revision(revision) == grandparent


@pytest.mark.parametrize('status', CLOSED_STATUSES)
def test_no_open_parent(status, phabfactory, get_phab_client):
    parent_result = phabfactory.revision(status=status.value)
    result = phabfactory.revision(id='D2', depends_on=parent_result)
    revision = result['result'][0]
    phab = get_phab_client(api_key='api-key')

    assert phab.get_first_open_parent_revision(revision) is None


def test_get_dependency_tree(phabfactory, get_phab_client):
    grandparent_data = phabfactory.revision(
        status=Statuses.NEEDS_REVISION.value
    )
    grandparent = grandparent_data['result'][0]
    parent_data = phabfactory.revision(
        id='D2', status=Statuses.CLOSED.value, depends_on=grandparent_data
    )
    parent = parent_data['result'][0]
    revision_data = phabfactory.revision(id='D4', depends_on=parent_data)
    revision = revision_data['result'][0]
    phab = get_phab_client(api_key='api-key')

    dependency = phab.get_dependency_tree(revision)
    assert next(dependency) == parent
    assert next(dependency) == grandparent
    with pytest.raises(StopIteration):
        next(dependency)
