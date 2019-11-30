# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import logging

from connexion import problem
from flask import g
from landoapi import auth
from landoapi.decorators import require_phabricator_api_key
from landoapi.models import SecApprovalRequest
from landoapi.phabricator import PhabricatorClient
from landoapi.projects import get_secure_project_phid
from landoapi.revisions import revision_is_secure
from landoapi.secapproval import build_transactions_for_request
from landoapi.storage import db
from landoapi.validation import revision_id_to_int

logger = logging.getLogger(__name__)


@auth.require_auth0(scopes=("lando",))
@require_phabricator_api_key(optional=False)
def request_sec_approval(data=None):
    """Request Security Approval from the Firefox security team for a Revision.

    Kicks off the sec-approval process.

    See https://wiki.mozilla.org/Security/Bug_Approval_Process.
    """
    phab = g.phabricator

    revision_id = revision_id_to_int(data["revision_id"])

    # FIXME: this is repeated in numerous places in the code. Needs refactoring!
    revision = phab.call_conduit(
        "differential.revision.search",
        constraints={"ids": [revision_id]},
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

    form_content = data.get("form_content", "")
    alt_message = data.get("sanitized_message", "")

    update_existing_request = SecApprovalRequest.exists_for_revision(revision)
    create_new_request = not update_existing_request

    if create_new_request and not form_content:
        return problem(
            400,
            "Empty sec-approval request form",
            "The sec-approval form content cannot be empty",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
        )
    elif create_new_request and not revision_is_secure(
        revision, get_secure_project_phid(phab)
    ):
        return problem(
            400,
            "Operation only allowed for secure revisions",
            "Only security-sensitive revisions can ask for sec-approval",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
        )
    elif update_existing_request and form_content:
        return problem(
            400,
            "Sec-approval request already in progress",
            "You cannot submit a sec-approval request form for a revision where a "
            "sec-approval request is already in progress.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
        )
    elif update_existing_request and not alt_message:
        return problem(
            400,
            "Empty commit message text",
            "The sanitized commit message text cannot be empty",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
        )

    logger.info(
        "Got request for sec-approval review of revision",
        extra=dict(
            revision_phid=revision_id,
            update_existing_request=update_existing_request,
            form_was_submitted=bool(form_content),
            alt_message_was_submitted=bool(alt_message),
        ),
    )

    if form_content:
        _submit_form_and_request_approval(form_content, phab, revision)
        alt_message_candidate_txn_ids = []
        sa_request = SecApprovalRequest.build(revision, alt_message_candidate_txn_ids)
        db.session.add(sa_request)

    if alt_message:
        alt_message_candidate_txn_ids = _submit_alt_message_and_request_approval(
            alt_message, phab, revision
        )
        # NOTE: Each call to Phabricator returns at least two transactions: one for
        # adding the comment and one for adding the reviewer.  We don't know which
        # transaction holds our secure commit message at this point so we record all of
        # them.
        sa_request = SecApprovalRequest.build(revision, alt_message_candidate_txn_ids)
        db.session.add(sa_request)

    db.session.commit()

    return {}, 200


def _submit_form_and_request_approval(form_content, phab, revision):
    desired_edits = build_transactions_for_request(
        form_content, "", get_secure_project_phid(phab)
    )
    phab.call_conduit(
        "differential.revision.edit",
        objectIdentifier=(revision["phid"]),
        transactions=desired_edits,
    )


def _submit_alt_message_and_request_approval(alt_message, phab, revision):
    desired_edits = build_transactions_for_request(
        "", alt_message, get_secure_project_phid(phab)
    )
    response = phab.call_conduit(
        "differential.revision.edit",
        objectIdentifier=(revision["phid"]),
        transactions=desired_edits,
    )
    return PhabricatorClient.expect(response, "transactions")
