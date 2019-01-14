# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import pytest

from landoapi.notifications import notify_user_of_landing_failure
from landoapi.tasks import log_landing_failure, FlaskCelery


def test_send_failure_notifications(celery_worker):
    notify_user_of_landing_failure(123, "gonzo")


def test_disabling_celery_keeps_tasks_from_executing(app):
    app.config["DISABLE_CELERY"] = True
    celery = FlaskCelery()
    celery.init_app(app)
    assert celery.dispatch_disabled  # Sanity check

    @celery.task
    def dummy_task():
        pytest.fail("The test task should never be executed.")

    dummy_task.apply_async()


def test_log_failure_task(caplog):
    log_landing_failure(123, "gonzo")
    assert "Transplant request 123 failed! Reason: gonzo" in caplog.text
