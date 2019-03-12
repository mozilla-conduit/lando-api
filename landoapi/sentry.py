# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging

from raven.contrib.flask import Sentry

from landoapi.systems import Subsystem

logger = logging.getLogger(__name__)
sentry = Sentry()


class SentrySubsystem(Subsystem):
    name = "sentry"

    def init_app(self, app):
        super().init_app(app)

        sentry_dsn = self.flask_app.config.get("SENTRY_DSN")
        logger.info("sentry status", extra={"enabled": bool(sentry_dsn)})
        sentry.init_app(self.flask_app, dsn=sentry_dsn)

        # Set these attributes directly because their keyword arguments can't be
        # passed into Sentry.__init__() or make_client().
        sentry.client.release = self.flask_app.config.get("VERSION").get(
            "version", "0.0.0"
        )
        sentry.client.environment = self.flask_app.config.get("ENVIRONMENT")
        sentry.client.processors = (
            "raven.processors.SanitizePasswordsProcessor",
            "raven.processors.RemoveStackLocalsProcessor",
        )


sentry_subsystem = SentrySubsystem()
