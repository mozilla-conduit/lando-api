# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import string

from landoapi.transactions import transaction_search, get_raw_comments


def test_transaction_search(phabdouble):
    phab = phabdouble.get_phabricator_client()
    comments = ["yes!", "no?", "~wobble~"]
    # Adding comments to a revision generates transactions and gives us a
    # PHID to retrieve them.
    revision = phabdouble.revision(comments=comments)
    transactions = list(transaction_search(phab, revision["phid"]))
    assert len(transactions) == len(comments)


def test_no_transaction_search_results_returns_empty_list(phabdouble):
    phab = phabdouble.get_phabricator_client()
    # Adding comments to a revision generates transactions and gives us a
    # PHID to retrieve them.
    revision = phabdouble.revision(comments=[])
    transactions = list(transaction_search(phab, revision["phid"]))
    assert transactions == []


def test_paginated_transactions_are_fetched_too(phabdouble):
    phab = phabdouble.get_phabricator_client()
    # Adding comments to a revision generates transactions and gives us a
    # PHID to retrieve them.
    comments = list(string.ascii_letters)
    revision = phabdouble.revision(comments=comments)
    # Limit the retrieved page size to force multiple API calls.
    transactions = list(transaction_search(phab, revision["phid"], limit=1))
    txn_comments = [get_raw_comments(t).pop() for t in transactions]
    assert txn_comments == comments
