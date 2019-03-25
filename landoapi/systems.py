# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging
import sys
import time

logger = logging.getLogger(__name__)


class Subsystem:
    name = None

    def __init__(self, app=None):
        self.flask_app = None

        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        self.flask_app = app

        if "SUBSYSTEMS" not in self.flask_app.config:
            self.flask_app.config["SUBSYSTEMS"] = {}

        self.flask_app.config["SUBSYSTEMS"][self.name] = self

    def ready(self):
        """Return True if ready, a message describing the problem otherwise.

        If `None` is returned it indicates that this Subsystem does not
        require a ready check.
        """
        return None

    def healthy(self):
        """Return True if healthy, a message describing the problem otherwise.

        If `None` is returned it indicates that this Subsystem does not
        require a health check.
        """
        return None

    def ensure_ready(self):
        for attempt in range(30):
            try:
                ready = self.ready()
            except Exception:
                logger.exception(
                    "Subsystem {} threw an exception".format(self.name),
                    extra={"subsystem": self.name},
                )
                ready = False

            if ready is None:
                return
            elif ready is True:
                break

            logger.warning(
                "Subsystem {} is not ready, sleeping.".format(self.name),
                extra={"subsystem": self.name, "reason": ready},
            )
            time.sleep(1 + attempt)
        else:
            logger.error(
                "Subsystem {} is not ready, giving up.".format(self.name),
                extra={"subsystem": self.name},
            )
            sys.exit(1)

        logger.info(
            "Subsystem {} is ready.".format(self.name), extra={"subsystem": self.name}
        )
