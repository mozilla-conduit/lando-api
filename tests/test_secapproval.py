# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Tests related to the Security Bug Approval Process.

See https://wiki.mozilla.org/Security/Bug_Approval_Process.
"""
from unittest.mock import ANY, patch

from landoapi.models import SecApprovalRequest
from landoapi.secapproval import send_sanitized_commit_message_for_review


def test_send_sanitized_commit_message(phabdouble, sec_approval_project):
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
    phab = phabdouble.get_phabricator_client()
    built_revision = phabdouble.revision()
    response = phab.call_conduit(
        "differential.revision.search", constraints={"phid": built_revision["phid"]}
    )
    api_revision = phab.single(response, "data")
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

    sec_approval_request = SecApprovalRequest.build(api_revision, transactions)

    assert sec_approval_request.comment_candidates == [
        "PHID-XACT-DREV-faketxn1",
        "PHID-XACT-DREV-faketxn2",
    ]
    assert sec_approval_request.revision_id == api_revision["id"]
    assert sec_approval_request.diff_phid == api_revision["fields"]["diffPHID"]
