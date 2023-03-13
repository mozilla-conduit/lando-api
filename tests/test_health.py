# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from unittest.mock import Mock

import redis
import requests
import pytest
from sqlalchemy.exc import SQLAlchemyError

from landoapi.auth import auth0_subsystem
from landoapi.cache import cache_subsystem
from landoapi.phabricator import PhabricatorAPIException, phabricator_subsystem
from landoapi.storage import db_subsystem
from landoapi.transplant_client import transplant_subsystem

from tests.utils import trans_url


def test_database_healthy(db):
    assert db_subsystem.healthy() is True


def test_database_unhealthy(db, monkeypatch):
    mock_db = Mock(db)
    monkeypatch.setattr("landoapi.storage.db", mock_db)

    mock_db.engine.connect.side_effect = SQLAlchemyError
    assert db_subsystem.healthy() is not True


def test_phabricator_healthy(app, phabdouble):
    assert phabricator_subsystem.healthy() is True


def test_phabricator_unhealthy(app, monkeypatch):
    def raises(*args, **kwargs):
        raise PhabricatorAPIException

    monkeypatch.setattr("landoapi.phabricator.PhabricatorClient.call_conduit", raises)
    assert phabricator_subsystem.healthy() is not True


@pytest.mark.xfail
def test_transplant_healthy(app, request_mocker):
    request_mocker.get(trans_url(""), status_code=200, text="Welcome to Autoland")
    assert transplant_subsystem.healthy() is True


@pytest.mark.xfail
def test_transplant_unhealthy(app, request_mocker):
    request_mocker.get(trans_url(""), exc=requests.ConnectTimeout)
    assert transplant_subsystem.healthy() is not True


def test_cache_healthy(redis_cache):
    assert cache_subsystem.healthy() is True


def test_cache_unhealthy_configuration():
    assert cache_subsystem.healthy() is not True


def test_cache_unhealthy_service(redis_cache, monkeypatch):
    mock_cache = Mock(redis_cache)
    mock_cache.cache._read_client.ping.side_effect = redis.TimeoutError
    monkeypatch.setattr("landoapi.cache.cache", mock_cache)
    monkeypatch.setattr("landoapi.cache.RedisCache", type(mock_cache.cache))

    health = cache_subsystem.healthy()
    assert health is not True
    assert health.startswith("RedisError:")


def test_auth0_healthy(app, jwks):
    assert auth0_subsystem.healthy() is True


def test_auth0_unhealthy(app):
    assert auth0_subsystem.healthy() is not True
