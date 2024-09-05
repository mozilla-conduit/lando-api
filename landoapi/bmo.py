# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import requests
from typing import Optional
from flask import current_app


def api_request(
    method: str,
    path: str,
    *args,
    authenticated: bool = False,
    headers: Optional[dict] = None,
    **kwargs,
) -> requests.Response:
    """Send an HTTP request to BMO.

    `method` is the HTTP method to use, ie `GET`, `POST`, etc.
    `path` is the REST API endpoint to send the request to.
    `authenticated` indicates if the privileged Lando Automation API key should be
      used.
    `headers` is the set of HTTP headers to pass to the request.

    All other arguments in *args and **kwargs are passed through to `requests.request`.
    """
    url = f"{current_app.config['BUGZILLA_URL']}/rest/{path}"

    common_headers = {
        "User-Agent": "Lando-API",
    }
    if headers:
        common_headers.update(headers)

    if authenticated:
        common_headers["X-Bugzilla-API-Key"] = current_app.config["BUGZILLA_API_KEY"]

    return requests.request(method, url, *args, headers=headers, **kwargs)


def search_bugs(bug_ids: set[int]) -> set[int]:
    """Search for bugs with given IDs on BMO."""
    params = {
        "id": ",".join(str(bug) for bug in sorted(bug_ids)),
        "include_fields": "id",
    }

    resp = api_request(
        "GET",
        "bug",
        params=params,
    )

    bugs = resp.json()["bugs"]

    return {int(bug["id"]) for bug in bugs}


def get_status_code_for_bug(bug_id: int) -> int:
    """Given a bug ID, get the status code returned from BMO when attempting to access the bug."""
    try:
        resp = api_request("GET", f"bug/{bug_id}")
        code = resp.status_code
    except requests.exceptions.HTTPError as exc:
        code = exc.response.status_code

    return code


def uplift_get_bug(params: dict) -> dict:
    """Retrieve bug information from the Lando Uplift Automation endpoint."""
    resp_get = api_request("GET", "lando/uplift", authenticated=True, params=params)
    resp_get.raise_for_status()

    return resp_get.json()


def uplift_update_bug(json: dict) -> requests.Response:
    """Update a BMO bug via the Lando Uplift Automation endpoint."""
    if "ids" not in json or not json["ids"]:
        raise ValueError("Need bug values to be able to update!")

    resp_put = api_request("PUT", "lando/uplift", authenticated=True, json=json)
    resp_put.raise_for_status()

    return resp_put
