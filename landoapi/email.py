# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging
from email.message import EmailMessage

logger = logging.getLogger(__name__)

LANDING_FAILURE_EMAIL_TEMPLATE = """
Your request to land {phab_revision_id} failed.

See {lando_revision_url} for details.

Reason:
{reason}
""".strip()


def make_failure_email(
    from_email: str,
    recipient_email: str,
    revision_id: str,
    error_msg: str,
    lando_ui_url: str,
) -> EmailMessage:
    """Build a failure EmailMessage.

    Args:
        recipient_email: The email of the user receiving the failure notification.
        revision_id: The Phabricator Revision ID that failed to land. e.g. D12345
        error_msg: The error message returned by the Transplant service.
        lando_ui_url: The base URL of the Lando website. e.g. https://lando.test
    """
    msg = EmailMessage()
    msg["From"] = from_email
    msg["To"] = recipient_email
    msg["Subject"] = f"Lando: Landing of {revision_id} failed!"
    lando_revision_url = f"{lando_ui_url}/{revision_id}/"
    msg.set_content(
        LANDING_FAILURE_EMAIL_TEMPLATE.format(
            phab_revision_id=revision_id,
            lando_revision_url=lando_revision_url,
            reason=error_msg,
        )
    )
    return msg
