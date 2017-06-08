# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
from urllib.parse import parse_qs

import requests_mock

from tests.utils import *
from tests.canned_responses.phabricator.revisions import *
from tests.canned_responses.phabricator.users import *
from tests.canned_responses.phabricator.repos import *
from tests.canned_responses.lando_api.revisions import *


def test_get_revision_with_no_parents(client):
    with requests_mock.mock() as m:
        m.get(phab_url('user.query'), status_code=200, json=CANNED_USER_1)
        m.get(
            phab_url('differential.query'),
            status_code=200,
            json=__phabricator_revision_stub
        )
        m.get(
            phab_url('phid.query'),
            status_code=200,
            json=CANNED_REPO_MOZCENTRAL
        )
        response = client.get('/revisions/D1?api_key=api-key')
        assert response.status_code == 200
        assert response.content_type == 'application/json'
        assert response.json == CANNED_LANDO_REVISION_1


def test_get_revision_with_parents(client):
    with requests_mock.mock() as m:
        m.get(phab_url('user.query'), status_code=200, json=CANNED_USER_1)
        m.get(
            phab_url('differential.query'),
            status_code=200,
            json=__phabricator_revision_stub
        )
        m.get(
            phab_url('phid.query'),
            status_code=200,
            json=CANNED_REPO_MOZCENTRAL
        )
        response = client.get('/revisions/D2?api_key=api-key')
        assert response.status_code == 200
        assert response.content_type == 'application/json'
        assert response.json == CANNED_LANDO_REVISION_2


def test_get_revision_returns_404(client):
    with requests_mock.mock() as m:
        m.get(
            phab_url('differential.query'),
            status_code=200,
            json=CANNED_REVISION_EMPTY
        )
        response = client.get('/revisions/D9000?api_key=api-key')
        assert response.status_code == 404
        assert response.content_type == 'application/problem+json'
        assert response.json == CANNED_LANDO_REVISION_NOT_FOUND


def test_landing_revision(client):
    with requests_mock.mock() as m:
        m.get(phab_url('user.query'), status_code=200, json=CANNED_USER_1)
        m.get(
            phab_url('differential.query'),
            status_code=200,
            json=__phabricator_revision_stub
        )
        m.get(
            phab_url('phid.query'),
            status_code=200,
            json=CANNED_REPO_MOZCENTRAL
        )
        response = client.post('/revisions/D1/transplants?api_key=api-key')
        assert response.status_code == 202
        assert response.content_type == 'application/json'
        assert response.json == {}


def test_land_nonexisting_revision_returns_404(client):
    with requests_mock.mock() as m:
        m.get(
            phab_url('differential.query'),
            status_code=200,
            json=CANNED_REVISION_EMPTY
        )
        response = client.post('/revisions/D9000/transplants?api_key=api-key')
        assert response.status_code == 404
        assert response.content_type == 'application/problem+json'
        assert response.json == CANNED_LANDO_REVISION_NOT_FOUND


def __phabricator_revision_stub(request, context):
    form = parse_qs(request.text)
    if form.get('ids[]') and form['ids[]'][0]:
        if form['ids[]'][0] == '1':
            return CANNED_REVISION_1
        elif form['ids[]'][0] == '2':
            return CANNED_REVISION_2
    elif form.get('phids[]') and form['phids[]'][0]:
        if form['phids[]'][0] == 'PHID-DREV-1':
            return CANNED_REVISION_1
        elif form['phids[]'][0] == 'PHID-DREV-2':
            return CANNED_REVISION_2
    assert False
