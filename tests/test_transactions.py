# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from landoapi.transactions import transaction_search, get_inline_comments


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


def test_find_transaction_by_object_name(phabdouble):
    phab = phabdouble.get_phabricator_client()
    revision = phabdouble.revision()
    txn = phabdouble.transaction("dummy", revision)
    name = f"D{revision['id']}"
    assert list(transaction_search(phab, name)) == [txn]


def test_find_transaction_by_phid(phabdouble):
    phab = phabdouble.get_phabricator_client()
    revision = phabdouble.revision()
    txn = phabdouble.transaction("dummy", revision)
    phid = revision["phid"]
    assert list(transaction_search(phab, phid)) == [txn]


def test_get_inline_comments(phabdouble):
    phab = phabdouble.get_phabricator_client()
    revision = phabdouble.revision()
    txn = phabdouble.transaction(
        transaction_type="inline",
        object=revision,
        comments=["this is done"],
        fields={"isDone": True},
    )
    # get_inline_comments should filter out unrelated transaction types.
    phabdouble.transaction("dummy", revision)
    name = f"D{revision['id']}"

    assert list(get_inline_comments(phab, name)) == [txn]
