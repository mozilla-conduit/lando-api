# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Construct an application instance that can be referenced by a WSGI server.
"""
from .app import SUBSYSTEMS, construct_app, load_config

config = load_config()
app = construct_app(config, spec=config["API_SPEC"])
for system in SUBSYSTEMS:
    system.init_app(app.app)

# No need to ready check since that should have already been done by
# lando-cli before execing to uwsgi.
