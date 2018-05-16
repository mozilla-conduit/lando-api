# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import logging

import boto3
import botocore
import requests
from connexion import ProblemException
from flask import current_app
from redis import RedisError
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from werkzeug.contrib.cache import RedisCache

from landoapi import auth
from landoapi.cache import cache
from landoapi.phabricator import (
    PhabricatorClient,
    PhabricatorAPIException,
)
from landoapi.storage import db
from landoapi.transplant_client import TransplantClient

logger = logging.getLogger(__name__)
HEALTH_CHECKS = {}


def run_checks():
    results = {name: check() for name, check in HEALTH_CHECKS.items()}
    healthy = True
    for name, errors in results.items():
        if errors:
            healthy = False
            logger.warning(
                'unhealthy: problem with backing service',
                extra={
                    'service_name': name,
                    'errors': errors,
                }
            )

    return healthy, {name: not errors for name, errors in results.items()}


def health_check(name):
    def decorate(f):
        HEALTH_CHECKS[name] = f
        return f

    return decorate


@health_check('database')
def check_database():
    try:
        with db.engine.connect() as conn:
            conn.execute('SELECT 1;')
    except DBAPIError as exc:
        return ['DBAPIError: {!s}'.format(exc)]
    except SQLAlchemyError as exc:
        return ['SQLAlchemyError: {!s}'.format(exc)]

    return []


@health_check('phabricator')
def check_phabricator():
    try:
        PhabricatorClient(
            current_app.config['PHABRICATOR_URL'],
            current_app.config['PHABRICATOR_UNPRIVILEGED_API_KEY']
        ).call_conduit('conduit.ping')
    except PhabricatorAPIException as exc:
        return ['PhabricatorAPIException: {!s}'.format(exc)]

    return []


@health_check('transplant')
def check_transplant():
    tc = TransplantClient(
        current_app.config['TRANSPLANT_URL'],
        current_app.config['TRANSPLANT_USERNAME'],
        current_app.config['TRANSPLANT_PASSWORD'],
    )
    try:
        resp = tc.ping()
    except requests.RequestException as exc:
        return ['RequestException: {!s}'.format(exc)]

    if resp.status_code != 200:
        return ['Unexpected Status Code: {}'.format(resp.status_code)]

    return []


@health_check('cache')
def check_cache():
    if not isinstance(cache.cache, RedisCache):
        return ['Cache is not configured to use redis']

    # Dirty, but if this breaks in the future we can instead
    # create our own redis-py client with its own connection
    # pool.
    redis = cache.cache._client

    try:
        redis.ping()
    except RedisError as exc:
        return ['RedisError: {!s}'.format(exc)]

    return []


@health_check('s3_bucket')
def check_s3_bucket():
    bucket = current_app.config.get('PATCH_BUCKET_NAME')
    if not bucket:
        return ['PATCH_BUCKET_NAME not configured']

    s3 = boto3.resource(
        's3',
        aws_access_key_id=current_app.config.get('AWS_ACCESS_KEY'),
        aws_secret_access_key=current_app.config.get('AWS_SECRET_KEY')
    )
    try:
        s3.meta.client.head_bucket(Bucket=bucket)
    except botocore.exceptions.ClientError as exc:
        return ['ClientError: {!s}'.format(exc)]
    except botocore.exceptions.BotoCoreError as exc:
        return ['BotoCoreError: {!s}'.format(exc)]

    return []


@health_check('auth0')
def check_auth0():
    try:
        auth.get_jwks()
    except ProblemException as exc:
        return ['Exception when requesting jwks: {}'.format(exc.detail)]

    return []
