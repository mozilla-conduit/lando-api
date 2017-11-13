# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import flask
import pytest

from connexion.lifecycle import ConnexionResponse

from landoapi.decorators import require_phabricator_api_key
from landoapi.phabricator_client import PhabricatorClient


def noop(*args, **kwargs):
    return ConnexionResponse(status_code=200)


@pytest.mark.parametrize(
    'optional,valid_key,status', [
        (False, None, 401),
        (False, False, 403),
        (False, True, 200),
        (True, None, 200),
        (True, False, 403),
        (True, True, 200)
    ]
)  # yapf: disable
def test_require_phabricator_api_key(
    monkeypatch, app, optional, valid_key, status
):
    headers = []
    if valid_key is not None:
        headers.append(('X-Phabricator-API-Key', 'custom-key'))
        monkeypatch.setattr(
            'landoapi.decorators.PhabricatorClient.verify_api_key',
            lambda *args, **kwargs: valid_key
        )

    with app.test_request_context('/', headers=headers):
        resp = require_phabricator_api_key(optional=optional)(noop)()
        if status == 200:
            assert isinstance(flask.g.phabricator, PhabricatorClient)
        if valid_key:
            assert flask.g.phabricator.api_key == 'custom-key'

    assert resp.status_code == status
