# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import json
import pytest
from tests.canned_responses.lando_api.revisions import *
from tests.utils import phid_for_response

pytestmark = pytest.mark.usefixtures('docker_env_vars')


def test_get_revision(client, phabfactory):
    phabfactory.user()
    phabfactory.revision()
    response = client.get('/revisions/D1?api_key=api-key')
    assert response.status_code == 200
    assert response.content_type == 'application/json'
    assert response.json == CANNED_LANDO_REVISION_1


def test_get_revision_with_no_parents(client, phabfactory):
    phabfactory.user()
    phabfactory.revision(depends_on=[])
    response = client.get('/revisions/D1?api_key=api-key')
    assert response.status_code == 200
    assert response.content_type == 'application/json'
    assert response.json['parent_revisions'] == []


def test_get_revision_with_parents(client, phabfactory):
    phabfactory.user()
    rev1 = phabfactory.revision(id='D1')
    phabfactory.revision(id='D2', depends_on=rev1)
    response = client.get('/revisions/D2?api_key=api-key')
    assert response.status_code == 200
    assert response.content_type == 'application/json'
    assert len(response.json['parent_revisions']) == 1
    parent_revision = response.json['parent_revisions'][0]
    assert parent_revision['phid'] == phid_for_response(rev1)


def test_get_revision_returns_404(client, phabfactory):
    response = client.get('/revisions/D9000?api_key=api-key')
    assert response.status_code == 404
    assert response.content_type == 'application/problem+json'
    assert response.json == CANNED_LANDO_REVISION_NOT_FOUND
