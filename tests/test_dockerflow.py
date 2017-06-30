# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import json
import requests

import requests_mock

from tests.canned_responses.phabricator.revisions import CANNED_EMPTY_RESULT
from tests.utils import phab_url


def test_dockerflow_lb_endpoint_returns_200(client):
    assert client.get('/__lbheartbeat__').status_code == 200


def test_dockerflow_version_endpoint_response(client):
    response = client.get('/__version__')
    assert response.status_code == 200
    assert response.content_type == 'application/json'


def test_dockerflow_version_matches_disk_contents(client, versionfile):
    response = client.get('/__version__')
    assert response.json == json.load(versionfile.open())


def test_heartbeat_returns_200_if_phabricator_api_is_up(client):
    json_response = CANNED_EMPTY_RESULT.copy()
    with requests_mock.mock() as m:
        m.get(phab_url('conduit.ping'), status_code=200, json=json_response)

        response = client.get('/__heartbeat__')

        assert m.called
        assert response.status_code == 200


def test_heartbeat_returns_http_502_if_phabricator_ping_returns_error(client):
    error_json = {
        "result": None,
        "error_code": "ERR-CONDUIT-CORE",
        "error_info": "BOOM"
    }

    with requests_mock.mock() as m:
        m.get(phab_url('conduit.ping'), status_code=500, json=error_json)

        response = client.get('/__heartbeat__')

        assert m.called
        assert response.status_code == 502
