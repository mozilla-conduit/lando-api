# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import inspect

import pytest

from landoapi.models import Transplant
from landoapi.notifications import notify_user_of_landing_failure
from landoapi.tasks import FlaskCelery, make_failure_email, send_landing_failure_email


dedent = inspect.cleandoc


class FakeSMTP:
    """A drop-in fake smtplib.SMTP object that records sent messages."""

    def __init__(self):
        self.args = None
        self.outbox = []

    def __call__(self, *args):
        self.args = args
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def send_message(self, msg):
        self.outbox.append(msg)


@pytest.fixture
def check_celery(app):
    """Skip this test if Celery is disabled."""
    if app.config["DISABLE_CELERY"]:
        raise pytest.skip("Celery disabled by DISABLE_CELERY envvar")


@pytest.fixture
def smtp(monkeypatch):
    client = FakeSMTP()
    monkeypatch.setattr("landoapi.tasks.smtplib.SMTP", client)
    return client


def test_send_failure_notification_email_task(app, smtp):
    send_landing_failure_email("sadpanda@failure.test", "D54321", "Rebase failed!")
    assert len(smtp.outbox) == 1


def test_email_content():
    email = make_failure_email(
        "sadpanda@failure.test", "D54321", "Rebase failed!", "https://lando.test"
    )
    assert email["To"] == "sadpanda@failure.test"
    assert email["Subject"] == "Lando: Landing of D54321 failed!"
    expected_body = dedent(
        """
        Your request to land D54321 failed.

        See https://lando.test/D54321/ for details.

        Reason:
        Rebase failed!
        """  # noqa
    )
    assert email.get_content() == expected_body + "\n"


# Use the 'check_celery' fixture before 'celery_worker'!  Otherwise an environment
# mis-configuration could cause the test run to hang.
def test_notify_user_of_landing_failure(check_celery, app, celery_worker, smtp):
    # Happy-path test for all objects that collaborate to send emails. We don't check
    # for an observable effect of sending emails in this test because the
    # celery_worker fixture causes the test to cross threads.  We only ensure the
    # happy-path runs cleanly.
    notify_user_of_landing_failure(Transplant(revision_order=["1"]))


def test_mail_sender_whitelist_rejections(app, smtp):
    app.config["MAIL_RECIPIENT_WHITELIST"] = "alice@example.test"
    send_landing_failure_email("sadpanda@failure.test", "D1", "Rebase failed!")
    assert len(smtp.outbox) == 0


def test_mail_sender_whitelist_allowances(app, smtp):
    app.config["MAIL_RECIPIENT_WHITELIST"] = "alice@example.test"
    send_landing_failure_email("alice@example.test", "D1", "Rebase failed!")
    assert len(smtp.outbox) == 1


def test_mail_suppress_send(app, smtp):
    app.config["MAIL_SUPPRESS_SEND"] = True
    send_landing_failure_email("sadpanda@failure.test", "D1", "Rebase failed!")
    assert len(smtp.outbox) == 0


def test_disabling_celery_keeps_tasks_from_executing(app):
    app.config["DISABLE_CELERY"] = True
    celery = FlaskCelery()
    celery.init_app(app)
    assert celery.dispatch_disabled  # Sanity check

    @celery.task
    def dummy_task():
        pytest.fail("The test task should never be executed.")

    dummy_task.apply_async()
