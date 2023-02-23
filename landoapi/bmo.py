# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import requests

from flask import current_app


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

    first_bug = json["ids"][0]

    resp_put = requests.put(
        f"{bmo_uplift_endpoint()}/{first_bug}", headers=bmo_default_headers(), json=json
    )
    resp_put.raise_for_status()

    return resp_put
