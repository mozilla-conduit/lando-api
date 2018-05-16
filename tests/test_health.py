# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from unittest.mock import Mock

import redis
import requests
from sqlalchemy.exc import SQLAlchemyError

from landoapi import health
from landoapi.phabricator import PhabricatorAPIException

from tests.utils import trans_url


def test_database_healthy(db):
    assert not health.check_database()


def test_database_unhealthy(db, monkeypatch):
    mock_db = Mock(db)
    monkeypatch.setattr('landoapi.health.db', mock_db)

    mock_db.engine.connect.side_effect = SQLAlchemyError
    assert health.check_database()


def test_phabricator_healthy(app, phabdouble):
    assert not health.check_phabricator()


def test_phabricator_unhealthy(app, monkeypatch):
    def raises(*args, **kwargs):
        raise PhabricatorAPIException

    monkeypatch.setattr(
        'landoapi.phabricator.PhabricatorClient.call_conduit', raises
    )
    assert health.check_phabricator()


def test_transplant_healthy(app, request_mocker):
    request_mocker.get(
        trans_url(''), status_code=200, text='Welcome to Autoland'
    )
    assert not health.check_transplant()


def test_transplant_unhealthy(app, request_mocker):
    request_mocker.get(trans_url(''), exc=requests.ConnectTimeout)
    assert health.check_transplant()


def test_cache_healthy(redis_cache):
    assert not health.check_cache()


def test_cache_unhealthy_configuration():
    assert health.check_cache()


def test_cache_unhealthy_service(redis_cache, monkeypatch):
    mock_cache = Mock(redis_cache)
    mock_cache.cache._client.ping.side_effect = redis.TimeoutError
    monkeypatch.setattr('landoapi.health.cache', mock_cache)
    monkeypatch.setattr('landoapi.health.RedisCache', type(mock_cache.cache))

    errors = health.check_cache()
    assert errors
    assert errors[0].startswith('RedisError:')


def test_auth0_healthy(app, jwks):
    assert not health.check_auth0()


def test_auth0_unhealthy(app):
    assert health.check_auth0()
