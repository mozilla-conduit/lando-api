# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import json
import logging
import os
from types import SimpleNamespace

import boto3
import flask.testing
import pytest
import requests_mock
from flask import current_app
from moto import mock_s3

from landoapi.app import create_app
from landoapi.landings import tokens_are_equal
from landoapi.mocks.auth import MockAuth0, TEST_JWKS
from landoapi.phabricator_client import PhabricatorClient
from landoapi.storage import db as _db

from tests.factories import PhabResponseFactory, TransResponseFactory


class JSONClient(flask.testing.FlaskClient):
    """Custom Flask test client that sends JSON by default.

    HTTP methods have a 'json=...' keyword that will JSON-encode the
    given data.

    All requests' content-type is automatically set to 'application/json'
    unless overridden.
    """

    def open(self, *args, **kwargs):
        """Send a HTTP request.

        Args:
            json: An object to be JSON-encoded. Cannot be used at the same time
                as the 'data' keyword arg.
            content_type: optional, will override the default
                of 'application/json'.
        """
        assert not (('data' in kwargs) and ('json' in kwargs))
        kwargs.setdefault('content_type', 'application/json')
        if 'json' in kwargs:
            kwargs['data'] = json.dumps(kwargs['json'], sort_keys=True)
            del kwargs['json']
        return super(JSONClient, self).open(*args, **kwargs)


@pytest.fixture
def docker_env_vars(monkeypatch):
    """Monkeypatch environment variables that we'd get running under docker."""
    monkeypatch.setenv('ENV', 'test')
    monkeypatch.setenv(
        'DATABASE_URL',
        'postgresql://postgres:password@lando-api.db/lando_api_test'
    )
    monkeypatch.setenv('PHABRICATOR_URL', 'http://phabricator.test')
    monkeypatch.setenv('TRANSPLANT_URL', 'http://autoland.test')
    monkeypatch.setenv('TRANSPLANT_API_KEY', 'someapikey')
    monkeypatch.setenv('TRANSPLANT_USERNAME', 'autoland')
    monkeypatch.setenv('TRANSPLANT_PASSWORD', 'autoland')
    monkeypatch.setenv('PINGBACK_ENABLED', 'y')
    monkeypatch.setenv('PINGBACK_HOST_URL', 'http://lando-api.test')
    monkeypatch.setenv('PATCH_BUCKET_NAME', 'landoapi.test.bucket')
    monkeypatch.delenv('AWS_ACCESS_KEY', raising=False)
    monkeypatch.delenv('AWS_SECRET_KEY', raising=False)
    monkeypatch.setenv('OIDC_IDENTIFIER', 'lando-api')
    monkeypatch.setenv('OIDC_DOMAIN', 'lando-api.auth0.test')
    monkeypatch.delenv('CACHE_REDIS_HOST', raising=False)
    monkeypatch.delenv('CSP_REPORTING_URL', raising=False)


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
def app(
    versionfile, docker_env_vars, disable_migrations, disable_log_output,
    mocked_tree_mapping
):
    """Needed for pytest-flask."""
    app = create_app(versionfile.strpath)
    flask_app = app.app
    # Turn on exception propagation.
    # See http://flask.pocoo.org/docs/0.12/api/#flask.Flask.test_client
    flask_app.testing = True

    flask_app.test_client_class = JSONClient

    return flask_app


@pytest.fixture
def db(app):
    """Reset database for each test."""
    with app.app_context():
        _db.init_app(app)
        _db.create_all()
        yield _db
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def s3(docker_env_vars):
    """Provide s3 mocked connection."""
    bucket = os.getenv('PATCH_BUCKET_NAME')
    with mock_s3():
        s3 = boto3.resource('s3')
        # We need to create the bucket since this is all in Moto's
        # 'virtual' AWS account
        s3.create_bucket(Bucket=bucket)
        yield s3


@pytest.fixture
def jwks(monkeypatch):
    monkeypatch.setattr(
        'landoapi.auth.get_jwks', lambda *args, **kwargs: TEST_JWKS
    )


@pytest.fixture
def auth0_mock(jwks, monkeypatch):
    mock_auth0 = MockAuth0()
    mock_userinfo_response = SimpleNamespace(
        status_code=200, json=lambda: mock_auth0.userinfo
    )
    monkeypatch.setattr(
        'landoapi.auth.fetch_auth0_userinfo',
        lambda token: mock_userinfo_response
    )
    return mock_auth0


@pytest.fixture
def mocked_tree_mapping(monkeypatch):
    monkeypatch.setattr(
        'landoapi.models.landing.TREE_MAPPING',
        {'mozilla-central': 'mozilla-central'}
    )


@pytest.fixture
def set_confirmation_token_comparison(monkeypatch):
    mem = {
        'set': False,
        'val': None,
    }

    def set_value(val):
        mem['set'] = True
        mem['val'] = val

    monkeypatch.setattr(
        'landoapi.landings.tokens_are_equal',
        lambda t1, t2: mem['val'] if mem['set'] else tokens_are_equal(t1, t2)
    )
    return set_value


@pytest.fixture
def get_phab_client(app):
    def get_client(api_key=None):
        api_key = (
            api_key or current_app.config['PHABRICATOR_UNPRIVILEGED_API_KEY']
        )
        return PhabricatorClient(
            current_app.config['PHABRICATOR_URL'], api_key
        )

    return get_client
