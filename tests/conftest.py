# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import json
import os
from types import SimpleNamespace

import redis
import sqlalchemy
import boto3
import flask.testing
import pytest
import requests_mock
from flask import current_app
from moto import mock_s3

from landoapi.app import create_app
from landoapi.cache import cache
from landoapi.landings import tokens_are_equal as l_tokens_are_equal
from landoapi.mocks.auth import MockAuth0, TEST_JWKS
from landoapi.phabricator import PhabricatorClient
from landoapi.repos import Repo, SCM_LEVEL_3
from landoapi.storage import db as _db
from landoapi.transplants import tokens_are_equal as t_tokens_are_equal

from tests.factories import TransResponseFactory
from tests.mocks import PhabricatorDouble


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
        assert not (("data" in kwargs) and ("json" in kwargs))
        kwargs.setdefault("content_type", "application/json")
        if "json" in kwargs:
            kwargs["data"] = json.dumps(kwargs["json"], sort_keys=True)
            del kwargs["json"]
        return super(JSONClient, self).open(*args, **kwargs)


# Are we running tests under local docker-compose or under CI?
# Assume that if we are running in an environment with the external services we
# need then the appropriate variables will be present in the environment.
#
# Set this as a module-level variable so that we can query os.environ without any
# monkeypatch modifications.
EXTERNAL_SERVICES_SHOULD_BE_PRESENT = (
    "DATABASE_URL" in os.environ or os.getenv("CI") or "CACHE_REDIS_HOST" in os.environ
)


@pytest.fixture
def docker_env_vars(monkeypatch):
    """Monkeypatch environment variables that we'd get running under docker."""
    monkeypatch.setenv("ENV", "test")
    # Overwrite any externally set DATABASE_URL with a unittest-only database URL.
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://postgres:password@lando-api.db/lando_api_test"
    )
    monkeypatch.setenv("PHABRICATOR_URL", "http://phabricator.test")
    monkeypatch.setenv(
        "PHABRICATOR_UNPRIVILEGED_API_KEY", "api-thiskeymustbe32characterslen"
    )
    monkeypatch.setenv("TRANSPLANT_URL", "http://autoland.test")
    monkeypatch.setenv("TRANSPLANT_API_KEY", "someapikey")
    monkeypatch.setenv("TRANSPLANT_USERNAME", "autoland")
    monkeypatch.setenv("TRANSPLANT_PASSWORD", "autoland")
    monkeypatch.setenv("PINGBACK_ENABLED", "y")
    monkeypatch.setenv("PINGBACK_HOST_URL", "http://lando-api.test")
    monkeypatch.setenv("PATCH_BUCKET_NAME", "landoapi.test.bucket")
    monkeypatch.delenv("AWS_ACCESS_KEY", raising=False)
    monkeypatch.delenv("AWS_SECRET_KEY", raising=False)
    monkeypatch.setenv("OIDC_IDENTIFIER", "lando-api")
    monkeypatch.setenv("OIDC_DOMAIN", "lando-api.auth0.test")
    # Explicitly shut off cache use for all tests.  Tests can re-enable the cache
    # with the redis_cache fixture.
    monkeypatch.delenv("CACHE_REDIS_HOST", raising=False)
    monkeypatch.delenv("CSP_REPORTING_URL", raising=False)


@pytest.fixture
def request_mocker():
    """Yield a requests Mocker for response factories."""
    with requests_mock.mock() as m:
        yield m


@pytest.fixture
def phabdouble(monkeypatch):
    """Mock the Phabricator service and build fake response objects."""
    yield PhabricatorDouble(monkeypatch)


@pytest.fixture
def transfactory(request_mocker):
    """Mock Transplant service."""
    yield TransResponseFactory(request_mocker)


@pytest.fixture
def versionfile(tmpdir):
    """Provide a temporary version.json on disk."""
    v = tmpdir.mkdir("app").join("version.json")
    v.write(
        json.dumps(
            {
                "source": "https://github.com/mozilla-conduit/lando-api",
                "version": "0.0.0",
                "commit": "",
                "build": "test",
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

    monkeypatch.setattr("landoapi.app.alembic", StubAlembic())


@pytest.fixture
def app(versionfile, docker_env_vars, disable_migrations, mocked_repo_config):
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
        try:
            _db.engine.connect()
        except sqlalchemy.exc.OperationalError:
            if EXTERNAL_SERVICES_SHOULD_BE_PRESENT:
                raise
            else:
                pytest.skip("Could not connect to PostgreSQL")
        _db.create_all()
        yield _db
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def s3(docker_env_vars):
    """Provide s3 mocked connection."""
    bucket = os.getenv("PATCH_BUCKET_NAME")
    with mock_s3():
        s3 = boto3.resource("s3")
        # We need to create the bucket since this is all in Moto's
        # 'virtual' AWS account
        s3.create_bucket(Bucket=bucket)
        yield s3


@pytest.fixture
def jwks(monkeypatch):
    monkeypatch.setattr("landoapi.auth.get_jwks", lambda *args, **kwargs: TEST_JWKS)


@pytest.fixture
def auth0_mock(jwks, monkeypatch):
    mock_auth0 = MockAuth0()
    mock_userinfo_response = SimpleNamespace(
        status_code=200, json=lambda: mock_auth0.userinfo
    )
    monkeypatch.setattr(
        "landoapi.auth.fetch_auth0_userinfo", lambda token: mock_userinfo_response
    )
    return mock_auth0


@pytest.fixture
def mock_repo_config(monkeypatch):
    def set_repo_config(config):
        monkeypatch.setattr("landoapi.repos.REPO_CONFIG", config)

    return set_repo_config


@pytest.fixture
def mocked_repo_config(mock_repo_config):
    mock_repo_config(
        {
            "test": {
                "mozilla-central": Repo(
                    "mozilla-central", SCM_LEVEL_3, "", "http://hg.test"
                )
            }
        }
    )


@pytest.fixture
def set_confirmation_token_comparison(monkeypatch):
    mem = {"set": False, "val": None}

    def set_value(val):
        mem["set"] = True
        mem["val"] = val

    monkeypatch.setattr(
        "landoapi.landings.tokens_are_equal",
        lambda t1, t2: mem["val"] if mem["set"] else l_tokens_are_equal(t1, t2),
    )
    monkeypatch.setattr(
        "landoapi.transplants.tokens_are_equal",
        lambda t1, t2: mem["val"] if mem["set"] else t_tokens_are_equal(t1, t2),
    )
    return set_value


@pytest.fixture
def get_phab_client(app):
    def get_client(api_key=None):
        api_key = api_key or current_app.config["PHABRICATOR_UNPRIVILEGED_API_KEY"]
        return PhabricatorClient(current_app.config["PHABRICATOR_URL"], api_key)

    return get_client


@pytest.fixture
def redis_cache(app):
    with app.app_context():
        cache.init_app(
            app, config={"CACHE_TYPE": "redis", "CACHE_REDIS_HOST": "redis.cache"}
        )
        try:
            cache.clear()
        except redis.exceptions.ConnectionError:
            if EXTERNAL_SERVICES_SHOULD_BE_PRESENT:
                raise
            else:
                pytest.skip("Could not connect to Redis")
        yield cache
        cache.clear()
        cache.init_app(
            app, config={"CACHE_TYPE": "null", "CACHE_NO_NULL_WARNING": True}
        )
