# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import requests
from flask import current_app


def bmo_search_bug_endpoint() -> str:
    """Returns the BMO bug search endpoint URL."""
    return f"{current_app.config['BUGZILLA_URL']}/rest/bug"


def search_bugs(bug_ids: set[int]) -> set[int]:
    """Search for bugs with given IDs on BMO."""
    bug_search_endpoint = bmo_search_bug_endpoint()
    params = {
        "id": ",".join(str(bug) for bug in sorted(bug_ids)),
        "include_fields": "id",
    }

    resp = requests.get(
        bug_search_endpoint,
        headers=bmo_default_headers(),
        params=params,
    )

    bugs = resp.json()["bugs"]

    return {int(bug["id"]) for bug in bugs}


def get_status_code_for_bug(bug_id: int) -> int:
    """Given a bug ID, get the status code returned from BMO when attempting to access the bug."""
    bug_endpoint = f"{bmo_search_bug_endpoint()}/{bug_id}"

    try:
        resp = requests.get(bug_endpoint)
        code = resp.status_code
    except requests.exceptions.HTTPError as exc:
        code = exc.response.status_code

    return code


def bmo_uplift_endpoint() -> str:
    """Returns the BMO uplift endpoint url for bugs."""
    return f"{current_app.config['BUGZILLA_URL']}/rest/lando/uplift"


def bmo_default_headers() -> dict[str, str]:
    """Returns a `dict` containing the default REST API headers."""
    return {
        "User-Agent": "Lando-API",
        "X-Bugzilla-API-Key": current_app.config["BUGZILLA_API_KEY"],
    }


def get_bug(params: dict) -> requests.Response:
    """Retrieve bug information from the BMO REST API endpoint."""
    resp_get = requests.get(
        bmo_uplift_endpoint(), headers=bmo_default_headers(), params=params
    )
    resp_get.raise_for_status()

    return resp_get


def update_bug(json: dict) -> requests.Response:
    """Update a BMO bug."""
    if "ids" not in json or not json["ids"]:
        raise ValueError("Need bug values to be able to update!")

    resp_put = requests.put(
        bmo_uplift_endpoint(), headers=bmo_default_headers(), json=json
    )
    resp_put.raise_for_status()

    return resp_put
