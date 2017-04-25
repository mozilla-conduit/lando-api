# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import pytest
from landoapi.app import create_app


@pytest.fixture
def app():
    app = create_app()
    return app.app


def test_app(client):
    assert client.get('/revisions/').status_code == 200
