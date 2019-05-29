# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Tests related to the Security Bug Approval Process.

See https://wiki.mozilla.org/Security/Bug_Approval_Process.
"""
from unittest.mock import ANY, patch

import pytest

from landoapi.secapproval import (
    find_secure_commit_message_in_transaction_list,
    format_sanitized_message_comment_for_review,
    parse_comment_for_sanitized_commit_message,
    send_sanitized_commit_message_for_review,
)
from landoapi.transactions import transaction_search


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


def test_find_sanitized_commit_message_in_revision_comments(
    phabdouble, secure_project, sec_approval_project
):
    phab = phabdouble.get_phabricator_client()
    comments = [format_sanitized_message_comment_for_review("secure message")]
    revision = phabdouble.revision(
        projects=[secure_project, sec_approval_project], comments=comments
    )

    transactions = transaction_search(phab, revision["phid"])
    found = find_secure_commit_message_in_transaction_list(transactions)

    assert found


def test_find_sanitized_commit_message_returns_none_if_no_secure_message(
    phabdouble, secure_project, sec_approval_project
):
    phab = phabdouble.get_phabricator_client()
    comments = ["this is not a secure message"]
    revision = phabdouble.revision(
        projects=[secure_project, sec_approval_project], comments=comments
    )

    transactions = transaction_search(phab, revision["phid"])
    found = find_secure_commit_message_in_transaction_list(transactions)

    assert found is None


def test_find_sanitized_commit_message_returns_newest_message(
    phabdouble, secure_project, sec_approval_project
):
    phab = phabdouble.get_phabricator_client()
    old_secure_comment = format_sanitized_message_comment_for_review("old comment")
    new_secure_comment = format_sanitized_message_comment_for_review("new comment")
    # Order is oldest to newest.
    comments = ["foo comment", old_secure_comment, "bar comment", new_secure_comment]
    revision = phabdouble.revision(
        projects=[secure_project, sec_approval_project], comments=comments
    )

    transactions = transaction_search(phab, revision["phid"])
    found = find_secure_commit_message_in_transaction_list(transactions)

    assert found == "new comment"


@pytest.mark.parametrize(
    "secure_message, phabricator_comment, should_parse",
    [
        ["alice", format_sanitized_message_comment_for_review("alice"), True],
        ["bob", "bob", False],
        [
            "charlie",
            format_sanitized_message_comment_for_review("charlie") + "mangled! ",
            False,
        ],
        [
            "dave",
            "mangled! " + format_sanitized_message_comment_for_review("dave"),
            False,
        ],
    ],
)
def test_parse_comment_for_sanitized_commit_message(
    secure_message, phabricator_comment, should_parse
):
    parsed_comment = parse_comment_for_sanitized_commit_message(phabricator_comment)
    if should_parse:
        assert parsed_comment == secure_message
    else:
        assert parsed_comment is None
