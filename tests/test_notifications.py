# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from landoapi.notifications import notify_user_of_landing_failure
from landoapi.tasks import log_landing_failure


def test_send_failure_notifications(celery_worker):
    notify_user_of_landing_failure(123, "gonzo")


def test_log_failure_task(caplog):
    log_landing_failure(123, "gonzo")
    assert "Transplant request 123 failed! Reason: gonzo" in caplog.text
