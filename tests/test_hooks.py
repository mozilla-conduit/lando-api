# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
from landoapi.hooks import initialize_hooks
from landoapi.phabricator import (
    PhabricatorAPIException,
    PhabricatorCommunicationException,
)


def test_app_wide_headers_set(client):
    response = client.get("/__version__")
    assert response.status_code == 200
    assert "X-Frame-Options" in response.headers
    assert "X-Content-Type-Options" in response.headers
    assert "Content-Security-Policy" in response.headers

    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Content-Security-Policy"] == "default-src 'none'"


def test_app_wide_headers_csp_report_uri(client, config):
    config["CSP_REPORTING_URL"] = None
    response = client.get("/__version__")
    assert response.status_code == 200
    assert "report-uri" not in response.headers["Content-Security-Policy"]

    config["CSP_REPORTING_URL"] = "/__cspreport__"
    response = client.get("/__version__")
    assert response.status_code == 200
    assert "report-uri /__cspreport__" in (response.headers["Content-Security-Policy"])


def test_phabricator_api_exception_handled(app, client):
    # We need to tell Flask to handle exceptions as if it were in a production
    # environment.
    app.config["PROPAGATE_EXCEPTIONS"] = False
    initialize_hooks(app)

    @app.route("/__testing__/phab_exception1")
    def phab_exception1():
        raise PhabricatorAPIException("OOPS!")

    @app.route("/__testing__/phab_exception2")
    def phab_exception2():
        raise PhabricatorCommunicationException("OOPS!")

    response = client.get("__testing__/phab_exception1")
    assert response.status_code == 500
    assert response.json["title"] == "Phabricator Error"

    response = client.get("__testing__/phab_exception2")
    assert response.status_code == 500
    assert response.json["title"] == "Phabricator Error"
