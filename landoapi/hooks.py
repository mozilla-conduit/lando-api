# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from flask import current_app


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


def initialize_hooks(flask_app):
    flask_app.after_request(set_app_wide_headers)
