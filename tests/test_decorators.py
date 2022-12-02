# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import pytest

from connexion.lifecycle import ConnexionResponse

from landoapi.decorators import require_phabricator_api_key
from landoapi.phabricator import PhabricatorClient


def noop(phab, *args, **kwargs):
    response = ConnexionResponse(status_code=200)
    response.body = phab
    return response


@pytest.mark.parametrize(
    "optional,valid_key,status",
    [
        (False, None, 401),
        (False, False, 403),
        (False, True, 200),
        (True, None, 200),
        (True, False, 403),
        (True, True, 200),
    ],
)
def test_require_phabricator_api_key(monkeypatch, app, optional, valid_key, status):
    headers = []
    if valid_key is not None:
        headers.append(("X-Phabricator-API-Key", "custom-key"))
        monkeypatch.setattr(
            "landoapi.decorators.PhabricatorClient.verify_api_token",
            lambda *args, **kwargs: valid_key,
        )

    with app.test_request_context("/", headers=headers):
        resp = require_phabricator_api_key(optional=optional)(noop)()
        if status == 200:
            assert isinstance(resp.body, PhabricatorClient)
        if valid_key:
            assert resp.body.api_token == "custom-key"

    assert resp.status_code == status
