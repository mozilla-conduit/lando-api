# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Tests related to the Security Bug Approval Process.

See https://wiki.mozilla.org/Security/Bug_Approval_Process.
"""
import inspect
from unittest.mock import ANY, patch

from landoapi.models import SecApprovalRequest
from landoapi.phabricator import PhabricatorClient
from landoapi.secapproval import (
    parse_comment,
    search_sec_approval_request_for_comment,
    send_sanitized_commit_message_for_review,
)

dedent = inspect.cleandoc


def test_send_sanitized_commit_message(app, phabdouble, sec_approval_project):
    phab = phabdouble.get_phabricator_client()
    r = phabdouble.revision()

    with patch.object(phab, "call_conduit", wraps=phab.call_conduit) as spy:
        send_sanitized_commit_message_for_review(r["phid"], "my message", phab)
        sec_approval_phid = sec_approval_project["phid"]
        spy.assert_called_with(
            "differential.revision.edit",
            objectIdentifier=r["phid"],
            transactions=[
                {"type": "comment", "value": ANY},
                {"type": "reviewers.add", "value": [f"blocking({sec_approval_phid})"]},
            ],
        )


def test_build_sec_approval_request_obj(phabdouble):
    revision = phabdouble.api_object_for(phabdouble.revision())
    # Simulate the transactions that take place when a sec-approval request
    # is made for a revision in Phabricator.
    transactions = [
        {"phid": "PHID-XACT-DREV-faketxn1", "type": "comment", "value": ANY},
        {
            "phid": "PHID-XACT-DREV-faketxn2",
            "type": "reviewers.add",
            "value": ["blocking(bar)"],
        },
    ]

    sec_approval_request = SecApprovalRequest.build(revision, transactions)

    assert sec_approval_request.comment_candidates == [
        "PHID-XACT-DREV-faketxn1",
        "PHID-XACT-DREV-faketxn2",
    ]
    assert sec_approval_request.revision_id == revision["id"]
    assert sec_approval_request.diff_phid == revision["fields"]["diffPHID"]


def test_find_txn_with_comment_in_phabricator(phabdouble):
    phab = phabdouble.get_phabricator_client()
    # A sec-approval request adds a comment to a revision.
    mock_comment = phabdouble.comment("my sec-approval request")
    revision = phabdouble.revision()

    # Add the two sec-approval request transactions to Phabricator. This also links the
    # comment transaction to the revision.
    comment_txn = phabdouble.api_object_for(
        phabdouble.transaction("comment", revision, comments=[mock_comment])
    )
    review_txn = phabdouble.api_object_for(
        phabdouble.transaction("reviewers.add", revision)
    )

    # Fetch our comment transaction
    comment = PhabricatorClient.single(comment_txn, "comments")

    # Add the sec-approval request transactions to the database.
    revision = phabdouble.api_object_for(revision)
    sec_approval_request = SecApprovalRequest.build(revision, [comment_txn, review_txn])

    # Search the list of sec-approval transactions for the comment.
    matching_comment = search_sec_approval_request_for_comment(
        phab, sec_approval_request
    )

    assert matching_comment == comment


def test_parse_well_formed_comment(phabdouble):
    msg = (
        "\n"
        "please approve my new commit message preamble\n"
        "\n"
        "```\n"
        "my new commit title\n"
        "```"
    )
    comment = _get_comment(phabdouble, msg)
    comment_description = parse_comment(comment)
    assert comment_description.title == "my new commit title"


def _get_comment(phabdouble, msg):
    """Retrieve the Phabricator API representation of a raw comment string."""
    revision = phabdouble.revision()
    mock_comment = phabdouble.comment(msg)
    phabdouble.transaction("dummy", revision, comments=[mock_comment])
    transaction = phabdouble.api_object_for(
        phabdouble.transaction("dummy", revision, comments=[mock_comment])
    )
    comment = PhabricatorClient.single(transaction, "comments")
    return comment
