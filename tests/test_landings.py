# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import copy
import json
import os
from unittest.mock import MagicMock

import pytest
from freezegun import freeze_time

from landoapi import patches
from landoapi.mocks.canned_responses.auth0 import CANNED_USERINFO
from landoapi.models.landing import Landing, LandingStatus
from landoapi.repos import Repo, SCM_LEVEL_3
from landoapi.transplant_client import TransplantClient


def assert_landings_equal_ignoring_dates(a, b):
    """Asserts two landings are equal ignoring dates.

    We ignore dates in our comparisons because they are calculated in
    the database rather than python and freezing them would be
    complicated.
    """
    a = copy.deepcopy(a)
    b = copy.deepcopy(b)
    for k in ('created_at', 'updated_at'):
        assert k in a and k in b
        del a[k]
        del b[k]

    assert a == b


def test_landing_revision_saves_data_in_db(
    db, client, phabdouble, transfactory, s3, auth0_mock
):
    # Id of a Landing object is created as a result of a POST request to
    # /landings endpoint of Lando API
    landing_id = 1
    # Id of the landing in Autoland is created as a result of a POST request to
    # /autoland endpoint. It is provided by Transplant API
    land_request_id = 3

    repo = phabdouble.repo()
    diff = phabdouble.diff()
    revision = phabdouble.revision(diff=diff, repo=repo)
    transfactory.mock_successful_response(land_request_id)

    response = client.post(
        '/landings',
        json={
            'revision_id': 'D{}'.format(revision['id']),
            'diff_id': diff['id'],
        },
        headers=auth0_mock.mock_headers,
    )
    assert response.status_code == 202
    assert response.content_type == 'application/json'
    # Id of the Landing object in Lando API
    assert response.json == {'id': landing_id}

    # Get Landing object by its id
    landing = Landing.query.get(landing_id)
    assert landing.id == landing_id
    assert landing.revision_id == revision['id']
    assert landing.diff_id == diff['id']
    assert landing.status == LandingStatus.submitted
    assert landing.active_diff_id == diff['id']
    assert landing.request_id == land_request_id


def test_landing_without_auth0_permissions(client, auth0_mock, phabdouble, db):
    auth0_mock.userinfo = CANNED_USERINFO['NO_CUSTOM_CLAIMS']

    repo = phabdouble.repo(name='mozilla-central')
    diff = phabdouble.diff()
    revision = phabdouble.revision(diff=diff, repo=repo)
    response = client.post(
        '/landings',
        json={
            'revision_id': 'D{}'.format(revision['id']),
            'diff_id': diff['id'],
        },
        headers=auth0_mock.mock_headers,
    )

    assert response.status_code == 400
    assert response.json['blockers'][0]['id'] == 'E002'


def test_landing_revision_calls_transplant_service(
    db, client, phabdouble, monkeypatch, s3, auth0_mock, get_phab_client
):
    repo = phabdouble.repo(name='mozilla-central')
    diff = phabdouble.diff()
    revision = phabdouble.revision(diff=diff, repo=repo)
    patch_url = patches.url(
        'landoapi.test.bucket', patches.name(revision['id'], diff['id'])
    )

    tsclient = MagicMock(spec=TransplantClient)
    tsclient().land.return_value = 1
    monkeypatch.setattr('landoapi.api.landings.TransplantClient', tsclient)
    client.post(
        '/landings',
        json={
            'revision_id': 'D{}'.format(revision['id']),
            'diff_id': diff['id'],
        },
        headers=auth0_mock.mock_headers,
    )
    tsclient().land.assert_called_once_with(
        revision_id=revision['id'],
        ldap_username='tuser@example.com',
        patch_urls=[patch_url],
        tree='mozilla-central',
        pingback='{}/landings/update'.format(os.getenv('PINGBACK_HOST_URL')),
        push_bookmark=''
    )


def test_push_bookmark_sent_when_supported_repo(
    db, client, phabdouble, monkeypatch, s3, auth0_mock, get_phab_client,
    mock_repo_config
):
    # Mock the repo to have a push bookmark.
    mock_repo_config(
        {
            'test': {
                'mozilla-central': Repo('mozilla-central', SCM_LEVEL_3, '@')
            },
        }
    )

    # Mock the phabricator response data
    repo = phabdouble.repo(name='mozilla-central')
    diff = phabdouble.diff()
    revision = phabdouble.revision(diff=diff, repo=repo)
    patch_url = patches.url(
        'landoapi.test.bucket', patches.name(revision['id'], diff['id'])
    )

    tsclient = MagicMock(spec=TransplantClient)
    tsclient().land.return_value = 1
    monkeypatch.setattr('landoapi.api.landings.TransplantClient', tsclient)
    client.post(
        '/landings',
        json={
            'revision_id': 'D{}'.format(revision['id']),
            'diff_id': diff['id'],
        },
        headers=auth0_mock.mock_headers,
    )
    tsclient().land.assert_called_once_with(
        revision_id=revision['id'],
        ldap_username='tuser@example.com',
        patch_urls=[patch_url],
        tree='mozilla-central',
        pingback='{}/landings/update'.format(os.getenv('PINGBACK_HOST_URL')),
        push_bookmark='@'
    )


@pytest.mark.parametrize(
    'mock_error_method', [
        'mock_http_error_response',
        'mock_connection_error_response',
        'mock_malformed_data_response',
    ]
)
def test_transplant_error_responds_with_502(
    app, db, client, phabdouble, transfactory, s3, auth0_mock,
    mock_error_method
):
    diff = phabdouble.diff()
    revision = phabdouble.revision(diff=diff, repo=phabdouble.repo())
    getattr(transfactory, mock_error_method)()

    response = client.post(
        '/landings',
        json={
            'revision_id': 'D{}'.format(revision['id']),
            'diff_id': diff['id'],
        },
        headers=auth0_mock.mock_headers,
    )

    assert response.status_code == 502
    assert response.json['title'] == 'Landing not created'


def test_land_wrong_revision_id_format(db, client, phabdouble, auth0_mock):
    diff = phabdouble.diff()
    revision = phabdouble.revision(diff=diff, repo=phabdouble.repo())

    response = client.post(
        '/landings',
        json={
            'revision_id': revision['id'],
            'diff_id': diff['id'],
        },
        headers=auth0_mock.mock_headers,
    )
    assert response.status_code == 400

    response = client.post(
        '/landings',
        json={
            'revision_id': str(revision['id']),
            'diff_id': diff['id'],
        },
        headers=auth0_mock.mock_headers,
    )
    assert response.status_code == 400


def test_land_diff_not_in_revision(db, client, phabdouble, s3, auth0_mock):
    repo = phabdouble.repo()
    diff1 = phabdouble.diff()
    revision1 = phabdouble.revision(diff=diff1, repo=repo)
    diff2 = phabdouble.diff()
    phabdouble.revision(diff=diff2, repo=repo)

    response = client.post(
        '/landings',
        json={
            'revision_id': 'D{}'.format(revision1['id']),
            'diff_id': diff2['id'],
        },
        headers=auth0_mock.mock_headers,
    )
    assert response.json['title'] == 'Diff not related to the revision'
    assert response.status_code == 400


def test_get_transplant_status(db, client, phabdouble):
    diff = phabdouble.diff()
    revision = phabdouble.revision(diff=diff, repo=phabdouble.repo())

    _create_landing(
        db,
        request_id=1,
        revision_id=revision['id'],
        diff_id=diff['id'],
        status=LandingStatus.submitted
    )
    response = client.get('/landings/1')
    data = response.json
    assert response.status_code == 200
    assert response.content_type == 'application/json'
    assert data['request_id'] == 1
    assert data['revision_id'] == 'D{}'.format(revision['id'])
    assert data['diff_id'] == diff['id']
    assert data['status'] == 'submitted'
    assert not data['error_msg']


def test_land_nonexisting_revision_returns_404(
    db, client, phabdouble, s3, auth0_mock
):
    response = client.post(
        '/landings',
        json={'revision_id': 'D900',
              'diff_id': 1},
        headers=auth0_mock.mock_headers,
    )
    assert response.status_code == 404
    assert response.content_type == 'application/problem+json'
    assert response.json['title'] == 'Revision not found'


def test_land_nonexisting_diff_returns_404(db, client, phabdouble, auth0_mock):
    diff = phabdouble.diff()
    revision = phabdouble.revision(diff=diff, repo=phabdouble.repo())
    diff_404 = 9000
    assert diff['id'] != diff_404

    response = client.post(
        '/landings',
        json={
            'revision_id': 'D{}'.format(revision['id']),
            'diff_id': diff_404,
        },
        headers=auth0_mock.mock_headers,
    )

    assert response.status_code == 404
    assert response.json['title'] == 'Diff not found'


def test_land_inactive_diff_without_acknowledgement_fails(
    db, client, phabdouble, transfactory, auth0_mock,
    set_confirmation_token_comparison
):
    diff1 = phabdouble.diff()
    revision = phabdouble.revision(diff=diff1, repo=phabdouble.repo())
    phabdouble.diff(revision=revision)

    transfactory.mock_successful_response()
    set_confirmation_token_comparison(False)
    response = client.post(
        '/landings',
        json={
            'revision_id': 'D{}'.format(revision['id']),
            'diff_id': diff1['id'],
        },
        headers=auth0_mock.mock_headers,
    )
    assert response.status_code == 400
    assert response.json['title'] == 'Unacknowledged Warnings'
    assert response.json['warnings'][0]['id'] == 'W001'


def test_land_with_open_parent(db, client, phabdouble, auth0_mock):
    repo = phabdouble.repo()
    diff = phabdouble.diff()
    revision = phabdouble.revision(
        diff=diff, repo=repo, depends_on=[phabdouble.revision(repo=repo)]
    )

    response = client.post(
        '/landings',
        json={
            'revision_id': 'D{}'.format(revision['id']),
            'diff_id': diff['id'],
        },
        headers=auth0_mock.mock_headers,
    )
    assert response.status_code == 400
    assert response.json['title'] == 'Landing is Blocked'
    assert response.json['blockers'][0]['id'] == 'E004'


@freeze_time('2017-11-02T00:00:00')
def test_get_jobs_by_revision_id(db, client, phabdouble):
    repo = phabdouble.repo()
    diff1 = phabdouble.diff()
    revision1 = phabdouble.revision(diff=diff1, repo=repo)
    diff2 = phabdouble.diff(revision=revision1)

    diff3 = phabdouble.diff()
    revision2 = phabdouble.revision(diff=diff3, repo=repo)

    diff4 = phabdouble.diff(revision=revision1)
    diff5 = phabdouble.diff(revision=revision2)

    _create_landing(
        db, 1, revision1['id'], diff1['id'], status=LandingStatus.submitted
    )
    _create_landing(
        db, 2, revision1['id'], diff2['id'], status=LandingStatus.landed
    )
    _create_landing(
        db, 3, revision2['id'], diff3['id'], status=LandingStatus.submitted
    )
    _create_landing(
        db, 4, revision1['id'], diff4['id'], status=LandingStatus.submitted
    )
    _create_landing(
        db, 5, revision2['id'], diff5['id'], status=LandingStatus.landed
    )

    response = client.get('/landings?revision_id=D1')
    assert response.status_code == 200
    # Check that only the 3 landings associated with revision D1 are returned.
    assert len(response.json) == 3

    for a, b in zip(
        response.json, [
            {
                'id': 1,
                'request_id': 1,
                'revision_id': 'D1',
                'diff_id': 1,
                'status': 'submitted',
                'active_diff_id': 1,
                'error_msg': '',
                'result': '',
                'requester_email': 'tuser@example.com',
                'tree': 'mozilla-central',
                'created_at': '2017-11-02T00:00:00+00:00',
                'updated_at': '2017-11-02T00:00:00+00:00',
            }, {
                'id': 2,
                'request_id': 2,
                'revision_id': 'D1',
                'diff_id': 2,
                'status': 'landed',
                'active_diff_id': 2,
                'error_msg': '',
                'result': '',
                'requester_email': 'tuser@example.com',
                'tree': 'mozilla-central',
                'created_at': '2017-11-02T00:00:00+00:00',
                'updated_at': '2017-11-02T00:00:00+00:00',
            }, {
                'id': 4,
                'request_id': 4,
                'revision_id': 'D1',
                'diff_id': 4,
                'status': 'submitted',
                'active_diff_id': 4,
                'error_msg': '',
                'result': '',
                'requester_email': 'tuser@example.com',
                'tree': 'mozilla-central',
                'created_at': '2017-11-02T00:00:00+00:00',
                'updated_at': '2017-11-02T00:00:00+00:00',
            }
        ]
    ):
        assert_landings_equal_ignoring_dates(a, b)


def test_no_revision_for_landing(db, client, phabdouble):
    # Create a landing pointing at a revision that will not
    # be returned by phabricator.
    _create_landing(db, 1, 1, 1, status=LandingStatus.submitted)
    response = client.get('/landings/1')
    assert response.status_code == 404


def test_landing_id_as_string(db, client):
    response = client.get('/landings/string')
    assert response.status_code == 404


def test_not_authorized_to_view_landing_by_revision(db, client, phabdouble):
    # Create a landing pointing at a revision which will
    # not be returned by phabricator (like if the user didn't
    # have permissions to view that revision).
    _create_landing(db, 1, 1, 1, status=LandingStatus.submitted)
    response = client.get('/landings?revision_id=D1')
    assert response.status_code == 404


def test_get_jobs_wrong_revision_id_format(db, client):
    _create_landing(db, 1, 1, 1, status=LandingStatus.submitted)
    response = client.get('/landings?revision_id=1')
    assert response.status_code == 400

    response = client.get('/landings?revision_id=d1')
    assert response.status_code == 400


def test_update_landing(db, client):
    _create_landing(db, 1, 1, 1, status=LandingStatus.submitted)
    response = client.post(
        '/landings/update',
        json={'request_id': 1,
              'landed': True,
              'result': 'sha123'},
        headers=[('API-Key', 'someapikey')],
    )

    assert response.status_code == 200
    landing = Landing.query.get(1)
    assert landing.status == LandingStatus.landed


def test_update_landing_bad_request_id(db, client):
    _create_landing(db, 1, 1, 1, status=LandingStatus.submitted)
    response = client.post(
        '/landings/update',
        json={'request_id': 2,
              'landed': True,
              'result': 'sha123'},
        headers=[('API-Key', 'someapikey')],
    )

    assert response.status_code == 404


def test_update_landing_bad_api_key(client):
    response = client.post(
        '/landings/update',
        json={'request_id': 1,
              'landed': True,
              'result': 'sha123'},
        headers=[('API-Key', 'wrongapikey')],
    )

    assert response.status_code == 403


def test_update_landing_no_api_key(client):
    response = client.post(
        '/landings/update',
        json={'request_id': 1,
              'landed': True,
              'result': 'sha123'},
    )

    assert response.status_code == 400


def test_pingback_disabled(client, config):
    config['PINGBACK_ENABLED'] = 'n'

    response = client.post(
        '/landings/update',
        json={'request_id': 1,
              'landed': True,
              'result': 'sha123'},
        headers=[('API-Key', 'someapikey')],
    )

    assert response.status_code == 403


def test_pingback_no_api_key_header(client, config):
    config['PINGBACK_ENABLED'] = 'y'

    response = client.post(
        '/landings/update',
        json={'request_id': 1,
              'landed': True,
              'result': 'sha123'},
    )

    assert response.status_code == 400


def test_pingback_incorrect_api_key(client, config):
    config['PINGBACK_ENABLED'] = 'y'

    response = client.post(
        '/landings/update',
        json={'request_id': 1,
              'landed': True,
              'result': 'sha123'},
        headers=[('API-Key', 'thisisanincorrectapikey')],
    )

    assert response.status_code == 403


def test_typecasting():
    Landing(revision_id='x', diff_id=1, active_diff_id=1)


@pytest.mark.parametrize(
    'status, considered_submitted', [
        (LandingStatus.submitted, True),
        (LandingStatus.landed, False),
        (LandingStatus.failed, False),
        (LandingStatus.aborted, False),
    ]
)
def test_revision_already_submitted(db, status, considered_submitted):
    landing = _create_landing(db, status=status, diff_id=2)
    if considered_submitted:
        assert Landing.is_revision_submitted(1) == landing
    else:
        assert not Landing.is_revision_submitted(1)


@pytest.mark.parametrize(
    'status', [LandingStatus.aborted, LandingStatus.failed]
)
def test_revision_not_submitted(db, status):
    _create_landing(db, status=status)
    assert not Landing.is_revision_submitted(1)


@pytest.mark.parametrize(
    'status', [LandingStatus.aborted, LandingStatus.failed]
)
def test_land_failed_revision(
    db, client, auth0_mock, phabdouble, s3, transfactory, status
):
    diff = phabdouble.diff()
    revision = phabdouble.revision(diff=diff, repo=phabdouble.repo())
    _create_landing(
        db,
        revision_id=revision['id'],
        diff_id=diff['id'],
        status=status,
    )
    transfactory.mock_successful_response(2)

    response = client.post(
        '/landings',
        data=json.dumps(
            {
                'revision_id': 'D{}'.format(revision['id']),
                'diff_id': diff['id'],
            }
        ),
        headers=auth0_mock.mock_headers,
        content_type='application/json'
    )
    assert response.status_code == 202
    assert Landing.is_revision_submitted(revision['id'])


def test_land_submitted_revision(db, client, phabdouble, auth0_mock):
    diff = phabdouble.diff()
    revision = phabdouble.revision(diff=diff, repo=phabdouble.repo())
    _create_landing(
        db,
        revision_id=revision['id'],
        diff_id=diff['id'],
        status=LandingStatus.submitted,
    )
    response = client.post(
        '/landings',
        data=json.dumps(
            {
                'revision_id': 'D{}'.format(revision['id']),
                'diff_id': diff['id'],
            }
        ),
        headers=auth0_mock.mock_headers,
        content_type='application/json'
    )
    assert response.status_code == 400
    assert response.json['title'] == 'Landing is Blocked'
    assert response.json['blockers'][0]['id'] == 'E003'


def test_land_revision_with_no_repo(
    db, client, phabdouble, transfactory, s3, auth0_mock
):
    diff = phabdouble.diff()
    phabdouble.revision(diff=diff)
    transfactory.mock_successful_response()

    response = client.post(
        '/landings',
        json={
            'revision_id': 'D1',
            'diff_id': 1,
        },
        headers=auth0_mock.mock_headers,
    )
    assert response.status_code == 400
    assert response.json['title'] == 'Landing is Blocked'
    assert response.json['blockers'][0]['id'] == 'E005'


def test_land_revision_with_unmapped_repo(
    db, client, phabdouble, transfactory, s3, auth0_mock
):
    repo = phabdouble.repo(name='notsupported')
    diff = phabdouble.diff()
    revision = phabdouble.revision(diff=diff, repo=repo)
    transfactory.mock_successful_response()

    response = client.post(
        '/landings',
        json={
            'revision_id': 'D{}'.format(revision['id']),
            'diff_id': diff['id'],
        },
        headers=auth0_mock.mock_headers,
    )
    assert response.status_code == 400
    assert response.json['title'] == 'Landing is Blocked'
    assert response.json['blockers'][0]['id'] == 'E005'


def _create_landing(
    db,
    request_id=1,
    revision_id=1,
    diff_id=1,
    active_diff_id=None,
    requester_email='tuser@example.com',
    tree='mozilla-central',
    status=LandingStatus.submitted
):
    landing = Landing(
        request_id=request_id,
        revision_id=revision_id,
        diff_id=diff_id,
        active_diff_id=(active_diff_id or diff_id),
        requester_email=requester_email,
        tree=tree,
        status=status
    )
    db.session.add(landing)
    db.session.commit()
    return landing
