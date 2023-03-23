# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import logging
from urllib.parse import urlparse

from landoapi.systems import Subsystem

logger = logging.getLogger(__name__)


class LandoUISubsystem(Subsystem):
    name = "lando_ui"

    def ready(self) -> bool | str:
        url = urlparse(self.flask_app.config["LANDO_UI_URL"])
        if not url.scheme or not url.netloc:
            return "Invalid LANDO_UI_URL, missing a scheme and/or hostname"

        return True


lando_ui_subsystem = LandoUISubsystem()
