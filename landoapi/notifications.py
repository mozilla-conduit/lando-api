# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging

import kombu

from landoapi.tasks import (
    send_bug_update_failure_email,
    send_landing_failure_email,
)

logger = logging.getLogger(__name__)


def notify_user_of_landing_failure(
    email: str, landing_job_identifier: str, error: str, request_id: int
):
    """Send out user notifications that a Landing failed.

    Args:
        email (str): Receipent's email address (e.g. `requester_email`.)
        revision (str): The revision associated with the landing failure.
        error (str): The text of the error associated with the landing failure.
        request_id (int): A unique identifier identifying either a legacy request ID or
            a LandingJob ID.

    Raises:
        kombu.exceptions.OperationalError if there is a problem connecting to the Celery
        job queue.
    """
    try:
        return send_landing_failure_email.apply_async(
            (email, landing_job_identifier, error),
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
            f"No notifications were sent for request {request_id} to "
            f"address {email} because of an exception connecting "
            f"to the Celery job system. Reason: {e} "
        )
        # Let the exception bubble up to any callers.  If the caller was an API call
        # from the Transplant service then the HTTP error code will cause the Transplant
        # service to wait and retry the request.
        raise


def notify_user_of_bug_update_failure(
    email: str, revision: str, error: str, request_id: int
):
    """Send out user notifications that a bug update failed.

    Args:
        email (str): Receipent's email address (e.g. `requester_email`.)
        revision (str): The revision associated with the bug update failure.
        error (str): The text of the error associated with the bug update failure.
        request_id (int): A unique identifier identifying either a legacy request ID or
            a LandingJob ID.

    Raises:
        kombu.exceptions.OperationalError if there is a problem connecting to the Celery
        job queue.
    """
    try:
        return send_bug_update_failure_email.apply_async(
            (email, revision, error),
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
            f"No notifications were sent for request {request_id} to "
            f"address {email} because of an exception connecting "
            f"to the Celery job system. Reason: {e} "
        )
        # Let the exception bubble up to any callers.  If the caller was an API call
        # from the Transplant service then the HTTP error code will cause the Transplant
        # service to wait and retry the request.
        raise
