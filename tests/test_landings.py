# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import json
import os
import pytest

from unittest.mock import MagicMock

from landoapi.hgexportbuilder import build_patch_for_revision
from landoapi.models.landing import Landing, TRANSPLANT_JOB_LANDED
from landoapi.phabricator_client import PhabricatorClient
from landoapi.transplant_client import TransplantClient

from tests.canned_responses.lando_api.revisions import *
from tests.canned_responses.lando_api.landings import *
from tests.utils import phab_url, form_matcher


def test_landing_revision_saves_data_in_db(
    db, client, phabfactory, transfactory, s3
):
    # Id of the landing in Autoland is created as a result of a POST request to
    # /autoland endpoint. It is provided by Transplant API
    land_request_id = 3
    # Id of a Landing object is created as a result of a POST request to
    # /landings endpoint of Lando API
    landing_id = 1
    # Id of the diff existing in Phabricator
    diff_id = 2

    diff = phabfactory.diff(id=diff_id)
    phabfactory.revision(active_diff=diff)
    transfactory.create_autoland_response(land_request_id)

    response = client.post(
        '/landings?api_key=api-key',
        data=json.dumps({
            'revision_id': 'D1',
            'diff_id': diff_id
        }),
        content_type='application/json'
    )
    assert response.status_code == 202
    assert response.content_type == 'application/json'
    # Id of the Landing object in Lando API
    assert response.json == {'id': landing_id}

    # Get Landing object by its id
    landing = Landing.query.get(landing_id)
    landing.request_id = land_request_id
    assert landing.serialize() == CANNED_LANDING_FACTORY_1


def test_landing_revision_calls_transplant_service(
    db, client, phabfactory, monkeypatch, s3
):
    # Mock the phabricator response data
    phabfactory.revision()

    # Build the patch we expect to see
    phabclient = PhabricatorClient('someapi')
    revision = phabclient.get_revision('D1')
    diff_id = phabclient.get_diff(phid=revision['activeDiffPHID'])['id']
    gitdiff = phabclient.get_rawdiff(diff_id)
    author = phabclient.get_revision_author(revision)
    hgpatch = build_patch_for_revision(gitdiff, author, revision)
    patch_url = 's3://landoapi.test.bucket/L1_D1_1.patch'

    # The repo we expect to see
    repo_uri = phabclient.get_revision_repo(revision)['uri']

    tsclient = MagicMock(spec=TransplantClient)
    tsclient().land.return_value = 1
    monkeypatch.setattr('landoapi.models.landing.TransplantClient', tsclient)
    client.post(
        '/landings?api_key=api-key',
        data=json.dumps({
            'revision_id': 'D1',
            'diff_id': int(diff_id)
        }),
        content_type='application/json'
    )
    tsclient().land.assert_called_once_with(
        'ldap_username@example.com', [patch_url], repo_uri,
        '{}/landings/update'.format(os.getenv('PINGBACK_HOST_URL'))
    )
    body = s3.Object('landoapi.test.bucket',
                     'L1_D1_1.patch').get()['Body'].read().decode("utf-8")
    assert body == hgpatch


def test_get_transplant_status(db, client):
    Landing(1, 'D1', 1, active_diff_id=1, status='started').save()
    response = client.get('/landings/1')
    assert response.status_code == 200
    assert response.content_type == 'application/json'
    assert response.json == CANNED_LANDING_1


def test_land_nonexisting_revision_returns_404(client, phabfactory, s3):
    response = client.post(
        '/landings?api_key=api-key',
        data=json.dumps({
            'revision_id': 'D900',
            'diff_id': 1
        }),
        content_type='application/json'
    )
    assert response.status_code == 404
    assert response.content_type == 'application/problem+json'
    assert response.json == CANNED_LANDO_REVISION_NOT_FOUND


def test_land_nonexisting_diff_returns_404(db, client, phabfactory):
    # This shouldn't really happen - it would be a bug in Phabricator.
    # There is a repository which active diff does not exist.
    diff = {
        'id': '9000',
        'uri': '{url}/differential/diff/9000/'.format(
            url=os.getenv('PHABRICATOR_URL')
        )
    }  # yapf: disable
    phabfactory.revision(active_diff={'result': {'9000': diff}})
    phabfactory.mock.get(
        phab_url('phid.query'),
        status_code=404,
        additional_matcher=form_matcher('phids[]', 'PHID-DIFF-9000'),
        json={
            'error_info': '',
            'error_code': None,
            'result': {
                'PHID-DIFF-9000': diff
            }
        }
    )

    response = client.post(
        '/landings?api_key=api-key',
        data=json.dumps({
            'revision_id': 'D1',
            'diff_id': 9000
        }),
        content_type='application/json'
    )
    assert response.status_code == 404
    assert response.content_type == 'application/problem+json'
    assert response.json == CANNED_LANDO_DIFF_NOT_FOUND


def test_land_inactive_diff_returns_409(db, client, phabfactory, transfactory):
    phabfactory.diff(id=1)
    d2 = phabfactory.diff(id=2)
    phabfactory.revision(active_diff=d2)
    transfactory.create_autoland_response()
    response = client.post(
        '/landings?api_key=api-key',
        data=json.dumps({
            'revision_id': 'D1',
            'diff_id': 1
        }),
        content_type='application/json'
    )
    assert response.status_code == 409
    assert response.content_type == 'application/problem+json'
    assert response.json['title'] == 'Inactive Diff'


def test_override_inactive_diff(db, client, phabfactory, transfactory):
    phabfactory.diff(id=1)
    phabfactory.diff(id=2)
    d3 = phabfactory.diff(id=3)
    phabfactory.revision(active_diff=d3)
    transfactory.create_autoland_response()
    response = client.post(
        '/landings?api_key=api-key',
        data=json.dumps(
            {
                'revision_id': 'D1',
                'diff_id': 1,
                'force_override_of_diff_id': 2
            }
        ),
        content_type='application/json'
    )
    assert response.status_code == 409
    assert response.content_type == 'application/problem+json'
    assert response.json['title'] == 'Overriding inactive diff'


def test_override_active_diff(db, client, phabfactory, transfactory, s3):
    phabfactory.diff(id=1)
    d2 = phabfactory.diff(id=2)
    phabfactory.revision(active_diff=d2)
    transfactory.create_autoland_response()
    response = client.post(
        '/landings?api_key=api-key',
        data=json.dumps(
            {
                'revision_id': 'D1',
                'diff_id': 1,
                'force_override_of_diff_id': 2
            }
        ),
        content_type='application/json'
    )
    assert response.status_code == 202

    landing = Landing.query.get(1)
    assert landing.status == 'started'
    assert landing.active_diff_id == 2
    assert landing.diff_id == 1


def test_get_jobs(db, client):
    Landing(1, 'D1', 1, active_diff_id=1, status='started').save()
    Landing(2, 'D1', 2, active_diff_id=2, status='finished').save()
    Landing(3, 'D2', 3, active_diff_id=3, status='started').save()
    Landing(4, 'D1', 4, active_diff_id=4, status='started').save()
    Landing(5, 'D2', 5, active_diff_id=5, status='finished').save()

    response = client.get('/landings')
    assert response.status_code == 200
    assert len(response.json) == 5

    response = client.get('/landings?revision_id=D1')
    assert response.status_code == 200
    assert len(response.json) == 3
    assert response.json == CANNED_LANDING_LIST_1

    response = client.get('/landings?status=finished')
    assert response.status_code == 200
    assert len(response.json) == 2

    response = client.get('/landings?revision_id=D1&status=finished')
    assert response.status_code == 200
    assert len(response.json) == 1


def test_update_landing(db, client):
    Landing(1, 'D1', 1, status='started').save()

    response = client.post(
        '/landings/update',
        data=json.dumps({
            'request_id': 1,
            'landed': True,
            'result': 'sha123'
        }),
        headers=[('API-Key', 'someapikey')],
        content_type='application/json'
    )

    assert response.status_code == 200
    response = client.get('/landings/1')
    assert response.json['status'] == TRANSPLANT_JOB_LANDED


def test_update_landing_bad_request_id(db, client):
    Landing(1, 'D1', 1, status='started').save()

    response = client.post(
        '/landings/update',
        data=json.dumps({
            'request_id': 2,
            'landed': True,
            'result': 'sha123'
        }),
        headers=[('API-Key', 'someapikey')],
        content_type='application/json'
    )

    assert response.status_code == 404


def test_update_landing_bad_api_key(client):

    response = client.post(
        '/landings/update',
        data=json.dumps({
            'request_id': 1,
            'landed': True,
            'result': 'sha123'
        }),
        headers=[('API-Key', 'wrongapikey')],
        content_type='application/json'
    )

    assert response.status_code == 403


def test_update_landing_no_api_key(client):
    response = client.post(
        '/landings/update',
        data=json.dumps({
            'request_id': 1,
            'landed': True,
            'result': 'sha123'
        }),
        content_type='application/json'
    )

    assert response.status_code == 400


def test_pingback_disabled(client, monkeypatch):
    monkeypatch.setenv('PINGBACK_ENABLED', 'n')

    response = client.post(
        '/landings/update',
        data=json.dumps({
            'request_id': 1,
            'landed': True,
            'result': 'sha123'
        }),
        headers=[('API-Key', 'someapikey')],
        content_type='application/json'
    )

    assert response.status_code == 403
