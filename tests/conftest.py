# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import json

import logging
import pytest
import requests_mock

from landoapi.app import create_app
from tests.factories import PhabResponseFactory, TransResponseFactory


@pytest.fixture
def docker_env_vars(monkeypatch):
    """Monkeypatch environment variables that we'd get running under docker."""
    monkeypatch.setenv('PHABRICATOR_URL', 'http://phabricator.test')
    monkeypatch.setenv('TRANSPLANT_URL', 'http://autoland.test')
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    monkeypatch.setenv('HOST_URL', 'http://lando-api.test')
    monkeypatch.setenv('TRANSPLANT_API_KEY', 'someapikey')
    monkeypatch.setenv('PINGBACK_ENABLED', 'y')


@pytest.fixture
def request_mocker():
    """Yield a requests Mocker for response factories."""
    with requests_mock.mock() as m:
        yield m


@pytest.fixture
def phabfactory(request_mocker):
    """Mock the Phabricator service and build fake response objects."""
    yield PhabResponseFactory(request_mocker)


@pytest.fixture
def transfactory(request_mocker):
    """Mock Transplant service."""
    yield TransResponseFactory(request_mocker)


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
def disable_log_output():
    """Disable Python standard logging output to the console."""
    logging.disable(logging.CRITICAL)


@pytest.fixture
def app(versionfile, docker_env_vars, disable_migrations, disable_log_output):
    """Needed for pytest-flask."""
    app = create_app(versionfile.strpath)
    return app.app
