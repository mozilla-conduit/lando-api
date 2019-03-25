# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging
import smtplib
import ssl

from flask import current_app

from landoapi.celery import celery
from landoapi.email import make_failure_email
from landoapi.smtp import smtp

logger = logging.getLogger(__name__)


@celery.task(
    # Auto-retry for errors from the SMTP socket connection. Don't log
    # stack traces.  All other exceptions will log a stack trace and cause an
    # immediate job failure without retrying.
    autoretry_for=(IOError, smtplib.SMTPException, ssl.SSLError),
    # Seconds to wait between retries.
    default_retry_delay=60,
    # Retry sending the notification for three days.  This is the same effort
    # that SMTP servers use for their outbound mail queues.
    max_retries=60 * 24 * 3,
    # Don't store the success or failure results.
    ignore_result=True,
    # Don't ack jobs until the job is complete. This should only come up if a worker
    # dies suddenly in the middle of an email job.  If it does die then it is possible
    # for the user to get two emails (harmless), which is better than them receiving
    # no emails.
    acks_late=True,
)
def send_landing_failure_email(recipient_email: str, revision_id: str, error_msg: str):
    """Tell a user that the Transplant service couldn't land their code.

    Args:
        recipient_email: The email of the user receiving the failure notification.
        revision_id: The Phabricator Revision ID that failed to land. e.g. D12345
        error_msg: The error message returned by the Transplant service.
    """
    if smtp.suppressed:
        logger.warning(
            f"Email sending suppressed: application config has disabled "
            f"all mail sending (recipient was: {recipient_email})"
        )
        return

    if not smtp.recipient_allowed(recipient_email):
        logger.info(
            f"Email sending suppressed: recipient {recipient_email} not whitelisted"
        )
        return

    with smtp.connection() as c:
        c.send_message(
            make_failure_email(
                smtp.default_from,
                recipient_email,
                revision_id,
                error_msg,
                current_app.config["LANDO_UI_URL"],
            )
        )

    logger.info(f"Notification email sent to {recipient_email}")
