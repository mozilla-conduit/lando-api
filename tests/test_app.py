# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import json

import pytest
from landoapi.app import create_app


@pytest.fixture
def versionfile(tmpdir):
    """Provide a temporary version.json on disk."""
    v = tmpdir.mkdir('app').join('version.json')
    v.write(
        json.dumps(
            {
                'source': 'https://github.com/mozilla-conduit/lando-api',
                'version': '0.0.0',
                'commit': '',
                'build': 'test',
            }
        )
    )
    return v


@pytest.fixture
def app(versionfile):
    """Needed for pytest-flask."""
    app = create_app(versionfile.strpath)
    return app.app


def test_app(client):
    assert client.get('/revisions/').status_code == 200


def test_dockerflow_lb_endpoint_returns_200(client):
    assert client.get('/__lbheartbeat__').status_code == 200


def test_dockerflow_version_endpoint_response(client):
    response = client.get('/__version__')
    assert response.status_code == 200
    assert response.content_type == 'application/json'


def test_dockerflow_version_matches_disk_contents(client, versionfile):
    response = client.get('/__version__')
    assert response.json == json.load(versionfile.open())
