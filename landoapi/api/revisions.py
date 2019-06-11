# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import logging

from connexion import problem
from flask import g

from landoapi import auth
from landoapi.decorators import require_phabricator_api_key
from landoapi.projects import get_secure_project_phid
from landoapi.revisions import revision_is_secure
from landoapi.secapproval import (
    save_sec_approval_request_event,
    send_sanitized_commit_message_for_review,
)

logger = logging.getLogger(__name__)


@auth.require_auth0(scopes=("lando",))
@require_phabricator_api_key(optional=False)
def submit_sanitized_commit_message(data=None):
    """Update a Revision with a sanitized commit message.

    Args:
        revision_phid: The PHID of the revision that will have a sanitized commit
            message.
        sanitized_message: The sanitized commit message.
    """
    phab = g.phabricator

    revision_phid = data["revision_phid"]
    alt_message = data["sanitized_message"]

    logger.debug(
        "Got request to update revision with a sanitized message",
        extra=dict(revision_phid=revision_phid, sanitized_message=alt_message),
    )

    if not alt_message:
        return problem(
            400,
            "Empty commit message text",
            "The sanitized commit message text cannot be empty",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
        )

    # FIXME: this is repeated in numerous places in the code. Needs refactoring!
    revision = phab.call_conduit(
        "differential.revision.search",
        constraints={"phids": [revision_phid]},
        attachments={"projects": True},
    )
    revision = phab.single(revision, "data", none_when_empty=True)
    if revision is None:
        return problem(
            404,
            "Revision not found",
            "The requested revision does not exist",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404",
        )

    # Only secure revisions are allowed to follow the sec-approval process.
    if not revision_is_secure(revision, get_secure_project_phid(phab)):
        return problem(
            400,
            "Operation only allowed for secure revisions",
            "Only security-sensitive revisions can be given sanitized commit messages",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
        )

    resulting_transactions = send_sanitized_commit_message_for_review(
        revision["phid"], alt_message, phab
    )

    # Save the transactions that added the sec-approval comment so we can
    # quickly fetch the comment from Phabricator later in the process.
    #
    # NOTE: Each call to Phabricator returns two transactions: one for adding the
    # comment and one for adding the reviewer.  We don't know which transaction is
    # which at this point so we record both of them.
    save_sec_approval_request_event(revision["phid"], resulting_transactions)

    return "OK", 200
