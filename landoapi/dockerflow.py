# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Endpoints to make this service comply with Cloud Ops' Dockerflow
specification.  See https://github.com/mozilla-services/Dockerflow for details.
"""

import json
import logging

from flask import Blueprint, current_app, jsonify

from landoapi import health

logger = logging.getLogger(__name__)

dockerflow = Blueprint('dockerflow', __name__)


@dockerflow.after_request
def disable_caching(response):
    """Disable caching on a response and return it."""
    response.cache_control.no_cache = True
    response.cache_control.no_store = True
    response.cache_control.must_revalidate = True
    return response


@dockerflow.route('/__heartbeat__')
def heartbeat():
    """Perform an in-depth service health check.

    This should check all the services that this service depends on
    and return a 200 iff those services and the app itself are
    performing normally. Return a 5XX if something goes wrong.
    """
    healthy, service_healths = health.run_checks()

    status = 200 if healthy else 502
    return jsonify({'healthy': healthy, 'services': service_healths}), status


@dockerflow.route('/__lbheartbeat__')
def lbheartbeat():
    """Perform health check for load balancing.

    Since this is for load balancer checks it should not check
    backing services.
    """
    return '', 200


@dockerflow.route('/__version__')
def version():
    """Respond with version information as defined by /app/version.json."""
    try:
        with open(current_app.config['VERSION_PATH']) as f:
            return jsonify(json.load(f))
    except (IOError, ValueError):
        # TODO log error
        return 'Unable to load version.json', 500
