# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging
import smtplib
from email.message import EmailMessage

import flask
from celery import Celery
from celery.signals import (
    after_task_publish,
    heartbeat_sent,
    task_failure,
    task_retry,
    task_success,
)
from datadog import statsd
from flask import current_app

TRANSPLANT_FAILURE_EMAIL_TEMPLATE = """
Your request to land {phab_revision_id} failed.

See {lando_revision_url} for details.

Reason:
{reason}
""".strip()

logger = logging.getLogger(__name__)


class FlaskCelery(Celery):
    """Celery which executes task in a flask app context."""

    def __init__(self, *args, **kwargs):
        # Avoid passing the flask app to base Celery.
        flask_app = kwargs.pop("app", None)

        super().__init__(*args, **kwargs)

        # Important to run this after __init__ since task_cls
        # argument to base Celery can change what we're basing on.
        self._flask_override_task_class()

        if flask_app is not None:
            self.init_app(flask_app)

    @property
    def dispatch_disabled(self):
        """Will the Celery job system dispatch tasks to the workers?"""
        return bool(self.app.config.get("DISABLE_CELERY"))

    def init_app(self, app, config=None):
        """Initialize with a flask app."""
        self.app = app

        config = config or {}
        self.conf.update(main=app.import_name, **config)

        if self.dispatch_disabled:
            logger.warning(
                "DISABLE_CELERY application configuration variable set, the Celery job "
                "system has been disabled! Any features that depend on the job system "
                "will not function."
            )

    def _flask_override_task_class(self):
        """Change Task class to one which executes in a flask context."""
        # Define a Task subclass that saves a reference to self in the Task object so
        # the task object can find self.app (the Flask application object) even if
        # self.app hasn't been set yet.
        #
        # We need to delay all of the task's calls to self.app using a custom Task class
        # because the reference to self.app may not be valid at the time the Celery
        # application object creates it set of Task objects.  The programmer may
        # set self.app via the self.init_app() method at any time in the future.
        #
        # self.app is expected to be valid and usable by Task objects after the web
        # application is fully initialized and ready to serve requests.
        BaseTask = self.Task
        celery_self = self

        class FlaskTask(BaseTask):
            """A Celery Task subclass that has a reference to a Flask app."""

            def __call__(self, *args, **kwargs):
                # Override immediate calling of tasks, such as mytask().  This call
                # method is used by the Celery worker process.
                if flask.has_app_context():
                    return super().__call__(*args, **kwargs)

                with celery_self.app.app_context():
                    return super().__call__(*args, **kwargs)

            def apply_async(self, *args, **kwargs):
                # Override delayed calling of tasks, such as mytask.apply_async().
                # This call method is used by the Celery app when it wants to
                # schedule a job for eventual execution on a worker.
                if celery_self.dispatch_disabled:
                    return None
                else:
                    return super().apply_async(*args, **kwargs)

        self.Task = FlaskTask


celery = FlaskCelery()


@celery.task(ignore_result=True)
def send_landing_failure_email(recipient_email: str, revision_id: str, error_msg: str):
    """Tell a user that the Transplant service couldn't land their code.

    Args:
        recipient_email: The email of the user receiving the failure notification.
        revision_id: The Phabricator Revision ID that failed to land. e.g. D12345
        error_msg: The error message returned by the Transplant service.
    """
    if current_app.config.get("MAIL_SUPPRESS_SEND"):
        logger.warning(
            f"Email sending suppressed: application config has disabled "
            f"all mail sending (recipient was: {recipient_email})"
        )
        return

    whitelist = current_app.config.get("MAIL_RECIPIENT_WHITELIST")
    if whitelist and recipient_email not in whitelist:
        logger.info(
            f"Email sending suppressed: recipient {recipient_email} not found in "
            f"MAIL_RECIPIENT_WHITELIST"
        )
        return

    with smtplib.SMTP(
        current_app.config.get("MAIL_SERVER"), current_app.config.get("MAIL_PORT")
    ) as smtp:
        smtp.send_message(
            make_failure_email(
                recipient_email,
                revision_id,
                error_msg,
                current_app.config["LANDO_UI_URL"],
            )
        )

    logger.info(f"Notification email sent to {recipient_email}")


def make_failure_email(
    recipient_email: str, revision_id: str, error_msg: str, lando_ui_url: str
) -> EmailMessage:
    """Build a failure EmailMessage.

    Args:
        recipient_email: The email of the user receiving the failure notification.
        revision_id: The Phabricator Revision ID that failed to land. e.g. D12345
        error_msg: The error message returned by the Transplant service.
        lando_ui_url: The base URL of the Lando website. e.g. https://lando.test
    """
    msg = EmailMessage()
    msg["From"] = "mozphab-prod@mozilla.com"
    msg["To"] = recipient_email
    msg["Subject"] = f"Lando: Landing of {revision_id} failed!"
    lando_revision_url = f"{lando_ui_url}/{revision_id}/"
    msg.set_content(
        TRANSPLANT_FAILURE_EMAIL_TEMPLATE.format(
            phab_revision_id=revision_id,
            lando_revision_url=lando_revision_url,
            reason=error_msg,
        )
    )
    return msg


##
#
# Signal handlers
#
##


@after_task_publish.connect
def count_task_published(**kwargs):
    statsd.increment("lando-api.celery.tasks_published")


@heartbeat_sent.connect
def count_heartbeat(**kwargs):
    statsd.increment("lando-api.celery.heartbeats_from_workers")


@task_success.connect
def count_task_success(**kwargs):
    statsd.increment("lando-api.celery.tasks_succeeded")


@task_failure.connect
def count_task_failure(**kwargs):
    statsd.increment("lando-api.celery.tasks_failed")


@task_retry.connect
def count_task_retried(**kwargs):
    statsd.increment("lando-api.celery.tasks_retried")
