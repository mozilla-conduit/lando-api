# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging
import smtplib
from contextlib import contextmanager

from landoapi.systems import Subsystem

logger = logging.getLogger(__name__)


class SMTP:
    def __init__(self, app=None):
        self.flask_app = None
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        self.flask_app = app

    @property
    def suppressed(self):
        return (
            self.flask_app is None
            or bool(self.flask_app.config.get("MAIL_SUPPRESS_SEND"))
            or not self.flask_app.config.get("MAIL_SERVER")
        )

    @property
    def default_from(self):
        return self.flask_app.config.get("MAIL_FROM") or "mozphab-prod@mozilla.com"

    @contextmanager
    def connection(self):
        if self.suppressed:
            raise ValueError("Supressed SMTP has no connection")

        host = self.flask_app.config.get("MAIL_SERVER") or None
        port = self.flask_app.config.get("MAIL_PORT") or None
        use_ssl = self.flask_app.config.get("MAIL_USE_SSL")
        use_tls = self.flask_app.config.get("MAIL_USE_TLS")

        username = self.flask_app.config.get("MAIL_USERNAME") or None
        password = self.flask_app.config.get("MAIL_PASSWORD") or None

        smtp_class = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
        c = smtp_class(host, port)

        try:
            if use_tls:
                c.starttls()
            if username and password:
                c.login(username, password)
            yield c
        finally:
            c.close()

    def recipient_allowed(self, email):
        if self.flask_app is None:
            return True

        whitelist = self.flask_app.config.get("MAIL_RECIPIENT_WHITELIST") or None
        if whitelist is None:
            return True

        return email in whitelist


smtp = SMTP()


class SMTPSubsystem(Subsystem):
    name = "SMTP"

    def init_app(self, app):
        super().init_app(app)
        smtp.init_app(app)

    def ready(self):
        if smtp.suppressed:
            logger.warning(
                "SMTP is suppressed, assuming ready",
                extra={
                    "MAIL_SERVER": self.flask_app.config.get("MAIL_SERVER"),
                    "MAIL_SUPPRESS_SEND": self.flask_app.config.get(
                        "MAIL_SUPPRESS_SEND"
                    ),
                },
            )
            return True

        # Attempt an smtp connection.
        with smtp.connection():
            return True


smtp_subsystem = SMTPSubsystem()
