# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import logging

from connexion import FlaskApi, problem
from flask import current_app

from landoapi.phabricator import PhabricatorAPIException
from landoapi.sentry import sentry

logger = logging.getLogger(__name__)


def set_app_wide_headers(response):
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-Content-Type-Options'] = 'nosniff'

    csp = [
        "default-src 'none';",
        "script-src 'self' 'unsafe-inline';",
        "connect-src 'self';",
        "img-src 'self';",
        "style-src 'self' 'unsafe-inline';",
    ]
    report_uri = current_app.config.get('CSP_REPORTING_URL')
    report_uri and csp.append("report-uri {};".format(report_uri))
    response.headers['Content-Security-Policy'] = ' '.join(csp)

    return response


def handle_phabricator_api_exception(exc):
    sentry.captureException()
    logger.error(
        {
            'msg': str(exc),
            'error_code': exc.error_code,
            'error_info': exc.error_info,
        }, 'phabricator.exception'
    )
    return FlaskApi.get_response(
        problem(
            500,
            'Phabricator Error',
            'An unexpected error was received from Phabricator',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500'
        )
    )


def initialize_hooks(flask_app):
    flask_app.after_request(set_app_wide_headers)
    flask_app.register_error_handler(
        PhabricatorAPIException,
        handle_phabricator_api_exception,
    )
