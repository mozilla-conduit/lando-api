# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import json
import os
import pytest

from unittest.mock import MagicMock

from landoapi.hgexportbuilder import build_patch_for_revision
from landoapi.models.landing import Landing, TRANSPLANT_JOB_LANDED
from landoapi.models.storage import db as _db
from landoapi.phabricator_client import PhabricatorClient
from landoapi.transplant_client import TransplantClient

from tests.canned_responses.lando_api.revisions import *
from tests.canned_responses.lando_api.landings import *


@pytest.fixture
def db(app):
    """Reset database for each test."""
    with app.app_context():
        _db.init_app(app)
        _db.create_all()
        # we just created.
        yield _db
        _db.session.remove()
        _db.drop_all()


def test_landing_revision_saves_data_in_db(db, client, phabfactory):
    phabfactory.user()
    phabfactory.revision()
    response = client.post(
        '/landings?api_key=api-key',
        data=json.dumps({
            'revision_id': 'D1',
            'diff_id': 1
        }),
        content_type='application/json'
    )
    assert response.status_code == 202
    assert response.content_type == 'application/json'
    assert response.json == {'id': 1}

    # test saved data
    landing = Landing.query.get(1)
    assert landing.serialize() == CANNED_LANDING_FACTORY_1


def test_landing_revision_calls_transplant_service(
    db, client, phabfactory, monkeypatch
):
    # Mock the phabricator response data
    phabfactory.user()
    phabfactory.revision()

    # Build the patch we expect to see
    phabclient = PhabricatorClient('someapi')
    revision = phabclient.get_revision('D1')
    diff_id = phabclient.get_diff_id(revision['activeDiffPHID'])
    gitdiff = phabclient.get_latest_revision_diff_text(revision)
    author = phabclient.get_revision_author(revision)
    hgpatch = build_patch_for_revision(gitdiff, author, revision)

    # The repo we expect to see
    repo_uri = phabclient.get_revision_repo(revision)['uri']

    tsclient = MagicMock(spec=TransplantClient)
    tsclient().land.return_value = 1
    monkeypatch.setattr('landoapi.models.landing.TransplantClient', tsclient)

    client.post(
        '/landings?api_key=api-key',
        data=json.dumps({
            'revision_id': 'D1',
            'diff_id': diff_id
        }),
        content_type='application/json'
    )
    tsclient().land.assert_called_once_with(
        'ldap_username@example.com', hgpatch, repo_uri,
        '%s/landings/1/update' % os.environ['HOST_URL']
    )


def test_get_transplant_status(db, client):
    Landing(1, 'D1', 1, 'started').save()
    response = client.get('/landings/1')
    assert response.status_code == 200
    assert response.content_type == 'application/json'
    assert response.json == CANNED_LANDING_1


def test_land_nonexisting_revision_returns_404(db, client, phabfactory):
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


def test_get_jobs(db, client):
    Landing(1, 'D1', 1, 'started').save()
    Landing(2, 'D1', 2, 'finished').save()
    Landing(3, 'D2', 3, 'started').save()
    Landing(4, 'D1', 4, 'started').save()
    Landing(5, 'D2', 5, 'finished').save()

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
    Landing(1, 'D1', 1, 'started').save()

    response = client.post(
        '/landings/1/update',
        data=json.dumps({
            'request_id': 1,
            'landed': True,
            'result': 'sha123'
        }),
        content_type='application/json'
    )

    assert response.status_code == 202
    response = client.get('/landings/1')
    assert response.json['status'] == TRANSPLANT_JOB_LANDED


def test_update_landing_bad_id(db, client):
    Landing(1, 'D1', 1, 'started').save()

    response = client.post(
        '/landings/2/update',
        data=json.dumps({
            'request_id': 1,
            'landed': True,
            'result': 'sha123'
        }),
        content_type='application/json'
    )

    assert response.status_code == 404


def test_update_landing_bad_request_id(db, client):
    Landing(1, 'D1', 1, 'started').save()

    response = client.post(
        '/landings/1/update',
        data=json.dumps({
            'request_id': 2,
            'landed': True,
            'result': 'sha123'
        }),
        content_type='application/json'
    )

    assert response.status_code == 404
