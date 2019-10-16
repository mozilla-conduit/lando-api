# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Functions for working with Phabricator transactions."""
from typing import Iterator, NewType

from landoapi.phabricator import PhabricatorClient

# Type for a Phabricator API Transaction returned by the transaction.search operation.
Transaction = NewType("Transaction", dict)
# Type for list entries in the "comments" list of a transaction returned from the
# Phabricator API transaction.search operation.
Comment = NewType("Comment", dict)


def transaction_search(
    phabricator, object_identifier, transaction_phids=None, limit=100
) -> Iterator[Transaction]:
    """Yield the Phabricator transactions related to an object.

    See https://phabricator.services.mozilla.com/conduit/method/transaction.search/.

    If the transaction list is larger that one page of API results then the generator
    will call the Phabricator API successive times to fetch the full transaction list.

    Args:
        phabricator: A PhabricatorClient instance.
        object_identifier: An object identifier (PHID or monogram) whose transactions
            we want to fetch.
        transaction_phids: An optional list of specific transactions PHIDs we want to
            find for the given object_identifier.
        limit: Integer keyword, limit the number of records retrieved per API call.
            Default is 100 records.

    Returns:
        Yields individual transactions.
    """
    next_page_start = None

    if transaction_phids:
        constraints = {"phids": transaction_phids}
    else:
        constraints = {}

    while True:
        transactions = phabricator.call_conduit(
            "transaction.search",
            objectIdentifier=object_identifier,
            constraints=constraints,
            limit=limit,
            after=next_page_start,
        )

        yield from PhabricatorClient.expect(transactions, "data")

        next_page_start = PhabricatorClient.expect(transactions, "cursor", "after")

        if next_page_start is None:
            # This was the last page of results.
            return


def get_raw_comments(transaction):
    """Return a list of 'raw' comment bodies in a Phabricator transaction.

    A single transaction can have multiple comment bodies: e.g. a top-level comment
    and a couple of inline comments along with it.

    See https://phabricator.services.mozilla.com/conduit/method/transaction.search/.
    """
    return [
        PhabricatorClient.expect(comment, "content", "raw")
        for comment in PhabricatorClient.expect(transaction, "comments")
    ]
