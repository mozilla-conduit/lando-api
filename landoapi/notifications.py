# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging

from landoapi.tasks import log_landing_failure

logger = logging.getLogger(__name__)


def notify_user_of_landing_failure(request_id: int, error_msg: str):
    """Send out user notifications that a Landing failed.

    Args:
        request_id: The request that error'd out.
        error_msg: The error message returned by the Transplant service.

    Raises:
        kombu.exceptions.OperationalError if there is a problem connecting to the Celery
        job queue.
    """
    log_landing_failure.apply_async(
        (request_id, error_msg),
        retry=True,
        # This policy will result in 3 connection retries if the job queue
        # is down. The current web request's response will be delayed 600ms
        # with retries before Kombu gives up and raises an exception.
        retry_policy={
            "max_retries": 3,
            "interval_start": 0,
            "interval_step": 0.2,
            "interval_max": 0.2,
        },
    )
