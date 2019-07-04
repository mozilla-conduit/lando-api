# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Tests related to the Security Bug Approval Process.

See https://wiki.mozilla.org/Security/Bug_Approval_Process.
"""
from unittest.mock import ANY, patch

from landoapi.secapproval import (
    save_sec_approval_request_event,
    send_sanitized_commit_message_for_review,
)


def test_send_sanitized_commit_message(db, phabdouble, sec_approval_project):
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


def test_save_transactions(db):
    rev_phid = "PHID-DREV-1"
    rev_diff_phid = "PHID-DIFF-4rxpjx4xdzoyfv6pg4nn"
    # Simulate the transactions that take place when a sec-approval request
    # is made for a revision in Phabricator.
    transactions = [
        {"phid": "PHID-XACT-DREV-faketxn1", "type": "comment", "value": ANY},
        {
            "phid": "PHID-XACT-DREV-faketxn2",
            "type": "reviewers.add",
            "value": [f"blocking(bar)"],
        },
    ]

    event = save_sec_approval_request_event(rev_phid, rev_diff_phid, transactions)

    assert event.comment_candidates == [
        "PHID-XACT-DREV-faketxn1",
        "PHID-XACT-DREV-faketxn2",
    ]
    assert event.revision_phid == rev_phid
    assert event.diff_phid == rev_diff_phid
