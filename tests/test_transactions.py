# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from landoapi.transactions import get_raw_comments, transaction_search


def test_transaction_search_for_all_transactions(phabdouble):
    phab = phabdouble.get_phabricator_client()
    revision = phabdouble.revision()
    new_txn1 = phabdouble.transaction("dummy", revision)
    new_txn2 = phabdouble.transaction("dummy", revision)
    transactions = list(transaction_search(phab, revision["phid"]))
    assert transactions == [new_txn1, new_txn2]


def test_transaction_search_for_specific_transaction(phabdouble):
    phab = phabdouble.get_phabricator_client()
    revision = phabdouble.revision()
    phabdouble.transaction("dummy", revision)
    target_txn = phabdouble.transaction("dummy", revision)
    transactions = list(
        transaction_search(
            phab, revision["phid"], transaction_phids=[target_txn["phid"]]
        )
    )
    assert transactions == [target_txn]


def test_no_transaction_search_results_returns_empty_list(phabdouble):
    phab = phabdouble.get_phabricator_client()
    transactions = list(transaction_search(phab, "PHID-DREV-aaaaa"))
    assert transactions == []


def test_paginated_transactions_are_fetched_too(phabdouble):
    phab = phabdouble.get_phabricator_client()
    revision = phabdouble.revision()
    new_transactions = list(
        phabdouble.transaction("dummy", revision) for _ in range(10)
    )
    # Limit the retrieved page size to force multiple API calls.
    transactions = list(transaction_search(phab, revision["phid"], limit=1))
    assert transactions == new_transactions


def test_add_comments_to_revision_generates_transactions(phabdouble):
    phab = phabdouble.get_phabricator_client()
    comments = ["yes!", "no?", "~wobble~"]
    revision = phabdouble.revision(comments=comments)
    transactions = list(transaction_search(phab, revision["phid"]))
    txn_comments = [get_raw_comments(t).pop() for t in transactions]
    assert len(transactions) == len(comments)
    assert txn_comments == comments
