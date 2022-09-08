# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import redis
import requests
import sqlalchemy
import boto3
import flask.testing
import pytest
import requests_mock
from flask import current_app
from moto import mock_s3
from pytest_flask.plugin import JSONResponse

from landoapi.app import construct_app, load_config, SUBSYSTEMS
from landoapi.cache import cache, cache_subsystem
from landoapi.mocks.auth import MockAuth0, TEST_JWKS
from landoapi.phabricator import PhabricatorClient
from landoapi.projects import (
    CHECKIN_PROJ_SLUG,
    RELMAN_PROJECT_SLUG,
    SEC_APPROVAL_PROJECT_SLUG,
    SEC_PROJ_SLUG,
)
from landoapi.repos import Repo, SCM_LEVEL_3
from landoapi.storage import db as _db, db_subsystem
from landoapi.tasks import celery
from landoapi.transplants import tokens_are_equal

from tests.factories import TransResponseFactory
from tests.mocks import PhabricatorDouble, TreeStatusDouble


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
def docker_env_vars(versionfile, monkeypatch):
    """Monkeypatch environment variables that we'd get running under docker."""
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("VERSION_PATH", str(versionfile))
    # Overwrite any externally set DATABASE_URL with a unittest-only database URL.
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://postgres:password@lando-api.db/lando_api_test"
    )
    monkeypatch.setenv("LANDO_UI_URL", "http://lando-ui.test")
    monkeypatch.setenv("PHABRICATOR_URL", "http://phabricator.test")
    monkeypatch.setenv("PHABRICATOR_ADMIN_API_KEY", "api-thiskeymustbe32characterslen")
    monkeypatch.setenv(
        "PHABRICATOR_UNPRIVILEGED_API_KEY", "api-thiskeymustbe32characterslen"
    )
    monkeypatch.setenv("BUGZILLA_URL", "http://bmo.test")
    monkeypatch.setenv("BUGZILLA_URL", "asdfasdfasdfasdfasdfasdf")
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
    # Don't suppress email in tests, but point at localhost so that any
    # real attempt would fail.
    monkeypatch.setenv("MAIL_SERVER", "localhost")
    monkeypatch.delenv("MAIL_SUPPRESS_SEND", raising=False)


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
def treestatusdouble(monkeypatch, treestatus_url):
    """Mock the Tree Status service and build fake responses."""
    yield TreeStatusDouble(monkeypatch, treestatus_url)


@pytest.fixture
def secure_project(phabdouble):
    return phabdouble.project(SEC_PROJ_SLUG)


@pytest.fixture
def checkin_project(phabdouble):
    return phabdouble.project(CHECKIN_PROJ_SLUG)


@pytest.fixture
def sec_approval_project(phabdouble):
    return phabdouble.project(SEC_APPROVAL_PROJECT_SLUG)


@pytest.fixture
def release_management_project(phabdouble):
    return phabdouble.project(
        RELMAN_PROJECT_SLUG,
        attachments={"members": {"members": [{"phid": "PHID-USER-1"}]}},
    )


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

        def init_app(self, app, db):
            pass

    monkeypatch.setattr("landoapi.storage.migrate", StubAlembic())


@pytest.fixture
def app(versionfile, docker_env_vars, disable_migrations, mocked_repo_config):
    """Needed for pytest-flask."""
    config = load_config()
    # We need the TESTING setting turned on to get tracebacks when testing API
    # endpoints with the TestClient.
    config["TESTING"] = True
    app = construct_app(config)
    flask_app = app.app
    flask_app.test_client_class = JSONClient
    for system in SUBSYSTEMS:
        system.init_app(flask_app)

    return flask_app


@pytest.fixture
def db(app):
    """Reset database for each test."""
    with app.app_context():
        db_subsystem.init_app(app)
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
                    tree="mozilla-central",
                    url="http://hg.test",
                    access_group=SCM_LEVEL_3,
                    approval_required=False,
                    legacy_transplant=True,
                ),
                "mozilla-uplift": Repo(
                    tree="mozilla-uplift",
                    url="http://hg.test/uplift",
                    access_group=SCM_LEVEL_3,
                    approval_required=True,
                    legacy_transplant=True,
                ),
                "mozilla-new": Repo(
                    tree="mozilla-new",
                    url="http://hg.test/new",
                    access_group=SCM_LEVEL_3,
                    commit_flags=[("VALIDFLAG1", "testing"), ("VALIDFLAG2", "testing")],
                ),
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
        "landoapi.transplants.tokens_are_equal",
        lambda t1, t2: mem["val"] if mem["set"] else tokens_are_equal(t1, t2),
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
        cache_subsystem.init_app(app)
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


@pytest.fixture
def celery_app(app):
    """Configure our app's Celery instance for use with the celery_worker fixture."""
    # The test suite will fail if we don't override the default worker and
    # default task set.
    # Note: the test worker will fail if we don't specify a result_backend.  The test
    # harness uses the backend for a custom ping() task that it uses as a health check.
    celery.conf.update(broker_url="memory://", result_backend="rpc")
    # Workaround for https://github.com/celery/celery/issues/4032.  If 'tasks.ping' is
    # missing from the loaded task list then the test worker will fail with an
    # AssertionError.
    celery.loader.import_module("celery.contrib.testing.tasks")
    return celery


@pytest.fixture
def treestatus_url():
    """A string holding the Tree Status base URL."""
    return "http://treestatus.test"


def pytest_assertrepr_compare(op, left, right):
    if isinstance(left, JSONResponse) and isinstance(right, int) and op == "==":
        # Hook failures when comparing JSONResponse objects so we get the detailed
        # failure description from inside the response object contents.
        #
        # The following example code would trigger this hook:
        #
        #   response = client.get()
        #   assert response == 200  # Fails if response is HTTP 401, triggers this hook
        return [
            f"Mismatch in status code for response: {left.status_code} != {right}",
            "",
            f"    Response JSON: {left.json}",
        ]


@pytest.fixture
def patch_directory(request):
    return Path(request.fspath.dirname).joinpath("patches")


@pytest.fixture
def hg_test_bundle(request):
    return Path(request.fspath.dirname).joinpath("data", "test-repo.bundle")


@pytest.fixture
def hg_server(hg_test_bundle, tmpdir):
    # TODO: Select open port.
    port = "8000"
    hg_url = "http://localhost:" + port

    repo_dir = tmpdir.mkdir("hg_server")
    subprocess.run(["hg", "clone", hg_test_bundle, repo_dir], check=True, cwd="/")

    serve = subprocess.Popen(
        [
            "hg",
            "serve",
            "--config",
            "web.push_ssl=False",
            "--config",
            "web.allow_push=*",
            "-p",
            port,
            "-R",
            repo_dir,
        ]
    )
    if serve.poll() is not None:
        raise Exception("Failed to start the mercurial server.")
    # Wait until the server is running.
    for _i in range(10):
        try:
            requests.get(hg_url)
        except Exception:
            time.sleep(1)
        break

    yield hg_url
    serve.kill()


@pytest.fixture
def hg_clone(hg_server, tmpdir):
    clone_dir = tmpdir.join("hg_clone")
    subprocess.run(["hg", "clone", hg_server, clone_dir.strpath], check=True)
    return clone_dir


@pytest.fixture
def register_codefreeze_uri(request_mocker):
    request_mocker.register_uri(
        "GET",
        "https://product-details.mozilla.org/1.0/firefox_versions.json",
        json={
            "NEXT_SOFTFREEZE_DATE": "2122-01-01",
            "NEXT_MERGE_DATE": "2122-01-01",
        },
    )


@pytest.fixture
def codefreeze_datetime(request_mocker):
    utc_offset = "-0800"
    dates = {
        "today": datetime(2000, 1, 5, 0, 0, 0, tzinfo=timezone.utc),
        f"two_days_ago {utc_offset}": datetime(2000, 1, 3, 0, 0, 0),
        f"tomorrow {utc_offset}": datetime(2000, 1, 6, 0, 0, 0),
        f"one_month_from_today {utc_offset}": datetime(2000, 2, 3, 0, 0, 0),
        f"one_month_and_two_days_from_today {utc_offset}": datetime(
            2000, 2, 6, 0, 0, 0
        ),
    }

    class Mockdatetime:
        @classmethod
        def now(cls, tz):
            return dates["today"]

        @classmethod
        def strptime(cls, date_string, fmt):
            return dates[f"{date_string}"]

    return Mockdatetime
