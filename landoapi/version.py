# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import json
import logging
import os

logger = logging.getLogger(__name__)


def version():
    version = {
        "source": "https://github.com/mozilla-conduit/lando-api",
        "version": "0.0.0",
        "commit": "",
        "build": "dev",
    }

    # Read the version information.
    path = os.getenv("VERSION_PATH", "/app/version.json")
    try:
        with open(path) as f:
            version = json.load(f)
    except (IOError, ValueError):
        logger.warning(f"version file ({path}) could not be loaded, assuming dev")

    return version
