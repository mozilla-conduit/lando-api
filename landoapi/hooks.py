# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import logging
import time
from typing import Optional

from connexion import FlaskApi, problem
from flask import (
    Flask,
    Response,
    current_app,
    g,
    request,
)

from landoapi.models.configuration import ConfigurationKey, ConfigurationVariable
from landoapi.phabricator import PhabricatorAPIException
from landoapi.sentry import sentry_sdk

logger = logging.getLogger(__name__)
request_logger = logging.getLogger("request.summary")


def check_maintenance() -> Optional[Response]:
    """Returns a 503 error if the API maintenance flag is on."""
    excepted_endpoints = (
        "dockerflow.heartbeat",
        "dockerflow.version",
        "dockerflow.lbheartbeat",
    )
    treestatus_api_prefix = "landoapi_api_treestatus"
    if request.endpoint in excepted_endpoints or request.endpoint.startswith(
        treestatus_api_prefix
    ):
        return

    in_maintenance = ConfigurationVariable.get(
        ConfigurationKey.API_IN_MAINTENANCE, False
    )
    if in_maintenance:
        return FlaskApi.get_response(
            problem(
                503,
                "API IN MAINTENANCE",
                f"The API is in maintenance, please try again later. {request.endpoint}",
                type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/503",
            )
        )


def set_app_wide_headers(response: Response) -> Response:
    local_dev = current_app.config.get("ENVIRONMENT") == "localdev"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"

    csp = ["default-src 'none'"]
    if local_dev:
        # Serve an appropriate CSP for swagger UI when
        # developing locally.
        csp.extend(
            [
                "script-src 'self' 'unsafe-inline'",
                "connect-src 'self'",
                "img-src 'self'",
                "style-src 'self' 'unsafe-inline'",
            ]
        )

    report_uri = current_app.config.get("CSP_REPORTING_URL")
    if report_uri:
        csp.append("report-uri {}".format(report_uri))

    response.headers["Content-Security-Policy"] = "; ".join(csp)

    return response


def request_logging_before_request():
    g._request_start_timestamp = time.time()


def request_logging_after_request(response: Response) -> Response:
    summary = {
        "errno": 0 if response.status_code < 400 else 1,
        "agent": request.headers.get("User-Agent", ""),
        "lang": request.headers.get("Accept-Language", ""),
        "method": request.method,
        "path": request.path,
        "code": response.status_code,
    }

    start = g.get("_request_start_timestamp", None)
    if start is not None:
        summary["t"] = int(1000 * (time.time() - start))

    request_logger.info("request summary", extra=summary)

    return response


def handle_phabricator_api_exception(exc: PhabricatorAPIException) -> Response:
    sentry_sdk.capture_exception()
    logger.error(
        "phabricator exception",
        extra={"error_code": exc.error_code, "error_info": exc.error_info},
        exc_info=exc,
    )

    if current_app.propagate_exceptions:
        # Mimic the behaviour of Flask.handle_exception() and re-raise the full
        # traceback in test and debug environments.
        raise exc

    return FlaskApi.get_response(
        problem(
            500,
            "Phabricator Error",
            "An unexpected error was received from Phabricator",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500",
        )
    )


def initialize_hooks(flask_app: Flask):
    flask_app.after_request(set_app_wide_headers)
    flask_app.before_request(check_maintenance)
    flask_app.before_request(request_logging_before_request)
    flask_app.after_request(request_logging_after_request)

    flask_app.register_error_handler(
        PhabricatorAPIException, handle_phabricator_api_exception
    )
