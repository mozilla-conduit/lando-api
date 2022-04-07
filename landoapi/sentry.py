# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging

import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration

from landoapi.systems import Subsystem

logger = logging.getLogger(__name__)


class SentrySubsystem(Subsystem):
    name = "sentry"

    def init_app(self, app):
        super().init_app(app)

        sentry_dsn = self.flask_app.config.get("SENTRY_DSN")
        logger.info("sentry status", extra={"enabled": bool(sentry_dsn)})
        sentry_sdk.init(
            dsn=sentry_dsn,
            integrations=[FlaskIntegration()],
            traces_sample_rate=1.0,
            release=self.flask_app.config.get("VERSION").get("version", "0.0.0"),
        )


sentry_subsystem = SentrySubsystem()
