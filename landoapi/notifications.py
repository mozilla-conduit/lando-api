# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging

import kombu

from landoapi.tasks import send_landing_failure_email

logger = logging.getLogger(__name__)


def notify_user_of_landing_failure(transplant):
    """Send out user notifications that a Landing failed.

    Args:
        transplant: The Transplant database object that error'd out.

    Raises:
        kombu.exceptions.OperationalError if there is a problem connecting to the Celery
        job queue.
    """
    try:
        send_landing_failure_email.apply_async(
            (transplant.requester_email, transplant.head_revision, transplant.error),
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
    except kombu.exceptions.OperationalError as e:
        logger.error(
            f"No notifications were sent for request {transplant.request_id} to "
            f"address {transplant.requester_email} because of an exception connecting "
            f"to the Celery job system. Reason: {e} "
        )
        # Let the exception bubble up to any callers.  If the caller was an API call
        # from the Transplant service then the HTTP error code will cause the Transplant
        # service to wait and retry the request.
        raise
