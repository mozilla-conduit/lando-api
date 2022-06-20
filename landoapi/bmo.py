# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import requests

from flask import current_app

BUG_ENDPOINT = f"{current_app.config['BUGZILLA_URL']}/rest/bug"
BMO_API_KEY = current_app.config["BUGZILLA_API_KEY"]
DEFAULT_HEADERS = {"X-Bugzilla-API-Key": BMO_API_KEY}


def get_bug(params: dict) -> requests.Response:
    """Retrieve bug information from the BMO REST API endpoint."""
    resp_get = requests.get(BUG_ENDPOINT, headers=DEFAULT_HEADERS, params=params)
    resp_get.raise_for_status()

    return resp_get


def update_bug(json: dict) -> requests.Response:
    """Update a BMO bug."""
    resp_put = requests.put(BUG_ENDPOINT, headers=DEFAULT_HEADERS, json=json)
    resp_put.raise_for_status()

    return resp_put
