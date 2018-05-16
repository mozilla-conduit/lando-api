# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import json

from tests.utils import phab_url, trans_url


def test_dockerflow_lb_endpoint_returns_200(client):
    assert client.get('/__lbheartbeat__').status_code == 200


def test_dockerflow_version_endpoint_response(client):
    response = client.get('/__version__')
    assert response.status_code == 200
    assert response.content_type == 'application/json'


def test_dockerflow_version_matches_disk_contents(client, versionfile):
    response = client.get('/__version__')
    assert response.json == json.load(versionfile.open())


def test_heartbeat_returns_200(
    client, db, phabdouble, request_mocker, redis_cache, s3, jwks
):
    request_mocker.get(
        trans_url(''), status_code=200, text='Welcome to Autoland'
    )
    assert client.get('/__heartbeat__').status_code == 200


def test_heartbeat_returns_http_502_if_phabricator_ping_returns_error(
    client, request_mocker, redis_cache, s3, jwks
):
    error_json = {
        "result": None,
        "error_code": "ERR-CONDUIT-CORE",
        "error_info": "BOOM"
    }

    request_mocker.get(
        trans_url(''), status_code=200, text='Welcome to Autoland'
    )
    request_mocker.get(
        phab_url('conduit.ping'), status_code=500, json=error_json
    )
    response = client.get('/__heartbeat__')

    assert request_mocker.called
    assert response.status_code == 502
