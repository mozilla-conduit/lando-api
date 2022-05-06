# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import inspect
from unittest.mock import MagicMock

import pytest

from landoapi.celery import FlaskCelery
from landoapi.email import make_failure_email
from landoapi.models.transplant import Transplant, TransplantStatus
from landoapi.notifications import notify_user_of_landing_failure
from landoapi.tasks import send_landing_failure_email


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

    def close(self):
        pass

    def starttls(self, *args, **kwargs):
        pass

    def login(self, *args, **kwargs):
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
    monkeypatch.setattr("landoapi.smtp.smtplib.SMTP", client)
    return client


def test_send_failure_notification_email_task(app, smtp):
    send_landing_failure_email("sadpanda@failure.test", "D54321", "Rebase failed!")
    assert len(smtp.outbox) == 1


def test_email_content():
    email = make_failure_email(
        "mozphab-prod@mozilla.com",
        "sadpanda@failure.test",
        "D54321",
        "Rebase failed!",
        "https://lando.test",
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


def test_notify_user_of_landing_failure(check_celery, app, celery_app, smtp):
    # Happy-path test for all objects that collaborate to send emails. We don't check
    # for an observable effect of sending emails in this test.
    transplant = Transplant(revision_order=["1"])
    notify_user_of_landing_failure(
        transplant.requester_email,
        transplant.head_revision,
        transplant.error,
        transplant.request_id,
    )


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


def test_transplant_status_update_does_not_notify(db, client, monkeypatch):
    db.session.add(
        Transplant(
            request_id=1,
            revision_to_diff_id={str(1): 1},
            revision_order=[str(1)],
            requester_email="tuser@example.com",
            tree="mozilla-central",
            repository_url="http://hg.test",
            status=TransplantStatus.submitted,
        )
    )
    db.session.commit()

    mock_notify = MagicMock(notify_user_of_landing_failure)
    monkeypatch.setattr(
        "landoapi.api.landings.notify_user_of_landing_failure", mock_notify
    )

    # Send a message that looks like a transplant update for the tree being closed.
    response = client.post(
        "/landings/update",
        json={"request_id": 1, "landed": False, "result": "Tree is closed."},
        headers=[("API-Key", "someapikey")],
    )

    assert response.status_code == 200
    assert not mock_notify.called


def test_transplant_failure_update_notifies(db, client, monkeypatch):
    db.session.add(
        Transplant(
            request_id=1,
            revision_to_diff_id={str(1): 1},
            revision_order=[str(1)],
            requester_email="tuser@example.com",
            tree="mozilla-central",
            repository_url="http://hg.test",
            status=TransplantStatus.submitted,
        )
    )
    db.session.commit()

    mock_notify = MagicMock(notify_user_of_landing_failure)
    monkeypatch.setattr(
        "landoapi.api.landings.notify_user_of_landing_failure", mock_notify
    )

    # Send a message that looks like a transplant failure to land.
    response = client.post(
        "/landings/update",
        json={"request_id": 1, "landed": False, "error_msg": "This failed!"},
        headers=[("API-Key", "someapikey")],
    )

    assert response.status_code == 200
    assert mock_notify.called
