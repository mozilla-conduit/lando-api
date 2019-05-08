# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging
import smtplib
import ssl
from typing import Optional

from flask import current_app

from landoapi.celery import celery
from landoapi.email import make_failure_email
from landoapi.phabricator import PhabricatorClient, PhabricatorCommunicationException
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


@celery.task(
    autoretry_for=(IOError, PhabricatorCommunicationException),
    default_retry_delay=20,
    max_retries=3 * 20,  # 20 minutes
    acks_late=True,
    ignore_result=True,
)
def admin_remove_phab_project(
    revision_phid: str, project_phid: str, comment: Optional[str] = None
):
    """Remove a project tag from the provided revision.

    Note, this uses administrator privileges and should only be called
    if permissions checking is handled elsewhere.

    Args:
        revision_phid: phid of the revision to remove the project tag from.
        project_phid: phid of the project to remove.
        comment: An optional comment to add when removing the project.
    """
    transactions = [{"type": "projects.remove", "value": [project_phid]}]
    if comment is not None:
        transactions.append({"type": "comment", "value": comment})

    privileged_phab = PhabricatorClient(
        current_app.config["PHABRICATOR_URL"],
        current_app.config["PHABRICATOR_ADMIN_API_KEY"],
    )
    # We only retry for PhabricatorCommunicationException, rather than the
    # base PhabricatorAPIException to treat errors in this implementation as
    # fatal.
    privileged_phab.call_conduit(
        "differential.revision.edit",
        objectIdentifier=revision_phid,
        transactions=transactions,
    )
