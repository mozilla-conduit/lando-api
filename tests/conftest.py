# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import json

import pytest
import requests_mock

from landoapi.app import create_app
from tests.factories import PhabResponseFactory


@pytest.fixture
def docker_env_vars(monkeypatch):
    """Monkeypatch environment variables that we'd get running under docker."""
    monkeypatch.setenv('PHABRICATOR_URL', 'http://phabricator.test')
    monkeypatch.setenv('TRANSPLANT_URL', 'http://autoland.test')
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    monkeypatch.setenv('HOST_URL', 'http://lando-api.test')


@pytest.fixture
def phabfactory():
    """Mock the Phabricator service and build fake response objects."""
    with requests_mock.mock() as m:
        yield PhabResponseFactory(m)


@pytest.fixture
def versionfile(tmpdir):
    """Provide a temporary version.json on disk."""
    v = tmpdir.mkdir('app').join('version.json')
    v.write(
        json.dumps(
            {
                'source': 'https://github.com/mozilla-conduit/lando-api',
                'version': '0.0.0',
                'commit': '',
                'build': 'test',
            }
        )
    )
    return v


@pytest.fixture
def disable_migrations(monkeypatch):
    """Disable the Alembic DB migrations system in the app during testing."""

    class StubAlembic:
        def __init__(self):
            pass

        def init_app(self, app):
            pass

    monkeypatch.setattr('landoapi.app.alembic', StubAlembic())


@pytest.fixture
def app(versionfile, docker_env_vars, disable_migrations):
    """Needed for pytest-flask."""
    app = create_app(versionfile.strpath)
    return app.app
