# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import json
import pytest

from landoapi.models.storage import db as _db
from landoapi.models.landing import (Landing, TRANSPLANT_JOB_STARTED)

from tests.canned_responses.phabricator.revisions import *
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


def test_landing_revision(db, client, phabfactory):
    phabfactory.user()
    phabfactory.revision()
    response = client.post(
        '/landings?api_key=api-key',
        data=json.dumps({
            'revision_id': 'D1'
        }),
        content_type='application/json'
    )
    assert response.status_code == 202
    assert response.content_type == 'application/json'
    assert response.json == {'id': 1}

    # test saved data
    landing = Landing.query.get(1)
    assert landing.serialize() == {
        'id': 1,
        'request_id': 1,
        'revision_id': 'D1',
        'status': TRANSPLANT_JOB_STARTED
    }

    response = client.post(
        '/landings?api_key=api-key',
        data=json.dumps({
            'revision_id': 'D1'
        }),
        content_type='application/json'
    )
    assert response.status_code == 202
    assert response.content_type == 'application/json'
    assert response.json == {'id': 2}

    # test saved data
    landing = Landing.query.get(2)
    assert landing.serialize() == {
        'id': 2,
        'request_id': 2,
        'revision_id': 'D1',
        'status': TRANSPLANT_JOB_STARTED
    }


def test_get_transplant_status(db, client):
    Landing(1, 'D1', 'started').save(True)
    response = client.get('/landings/1')
    assert response.status_code == 200
    assert response.content_type == 'application/json'
    assert response.json == CANNED_LANDING_1


def test_land_nonexisting_revision_returns_404(db, client, phabfactory):
    response = client.post(
        '/landings?api_key=api-key',
        data=json.dumps({
            'revision_id': 'D900'
        }),
        content_type='application/json'
    )
    assert response.status_code == 404
    assert response.content_type == 'application/problem+json'
    assert response.json == CANNED_LANDO_REVISION_NOT_FOUND


def test_get_jobs(db, client):
    Landing(1, 'D1', 'started').save(True)
    Landing(2, 'D1', 'finished').save(True)
    Landing(3, 'D2', 'started').save(True)
    Landing(4, 'D1', 'started').save(True)
    Landing(5, 'D2', 'finished').save(True)

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
