# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import requests
from typing import Optional
from flask import current_app


def bmo_default_headers() -> dict[str, str]:
    """Returns a `dict` containing the default REST API headers."""
    return {
        "User-Agent": "Lando-API",
        "X-Bugzilla-API-Key": current_app.config["BUGZILLA_API_KEY"],
    }


def bugzilla(
    method: str, path: str, *args, headers: Optional[dict] = None, **kwargs
) -> requests.Response:
    """Send an HTTP `GET` request to BMO."""
    url = f"{current_app.config['BUGZILLA_URL']}/rest/{path}"

    common_headers = bmo_default_headers()
    if headers:
        common_headers.update(headers)

    return requests.request(method, url, *args, headers=headers, **kwargs)


def search_bugs(bug_ids: set[int]) -> set[int]:
    """Search for bugs with given IDs on BMO."""
    params = {
        "id": ",".join(str(bug) for bug in sorted(bug_ids)),
        "include_fields": "id",
    }

    resp = bugzilla(
        "GET",
        "bug",
        headers=bmo_default_headers(),
        params=params,
    )

    bugs = resp.json()["bugs"]

    return {int(bug["id"]) for bug in bugs}


def get_status_code_for_bug(bug_id: int) -> int:
    """Given a bug ID, get the status code returned from BMO when attempting to access the bug."""
    try:
        resp = bugzilla("GET", f"bug/{bug_id}")
        code = resp.status_code
    except requests.exceptions.HTTPError as exc:
        code = exc.response.status_code

    return code


def get_bug(params: dict) -> dict:
    """Retrieve bug information from the BMO REST API endpoint."""
    resp_get = bugzilla("GET", "lando/uplift", params=params)
    resp_get.raise_for_status()

    return resp_get.json()


def update_bug(json: dict) -> requests.Response:
    """Update a BMO bug."""
    if "ids" not in json or not json["ids"]:
        raise ValueError("Need bug values to be able to update!")

    resp_put = bugzilla("PUT", "lando/uplift", json=json)
    resp_put.raise_for_status()

    return resp_put
