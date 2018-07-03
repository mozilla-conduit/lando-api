# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging

logger = logging.getLogger(__name__)


def build_stack_graph(phab, revision_phid):
    """Return a graph representation of a revision stack.

    This function is expensive and can make up to approximately
    n/2 calls to phabricator for a linear stack where n is the
    number of revisions in the stack.

    Args:
        phab: A landoapi.phabricator.PhabricatorClient.
        revision_phid: String PHID of a revision in the stack.

    Returns:
        A tuple of (nodes, edges). `nodes` is a set of strings
        PHIDs corresponding to revisions in the stack. `edges` is
        a set of tuples (child, parent) each representing an edge
        between two nodes. `child` and `parent` are also string
        PHIDs.
    """
    phids = set()
    new_phids = {revision_phid}
    edges = []

    # Repeatedly request all related edges, adding connected revisions
    # each time until no new revisions are found.
    while new_phids:
        phids.update(new_phids)
        edges = phab.call_conduit(
            'edge.search',
            types=['revision.parent', 'revision.child'],
            sourcePHIDs=[phid for phid in phids],
            limit=10000,
        )
        edges = phab.expect(edges, 'data')
        new_phids = set()
        for edge in edges:
            new_phids.add(edge['sourcePHID'])
            new_phids.add(edge['destinationPHID'])

        new_phids = new_phids - phids

    # Treat the stack like a commit DAG, we only care about edges going
    # from child to parent. This is enough to represent the graph.
    edges = {
        (edge['sourcePHID'], edge['destinationPHID'])
        for edge in edges if edge['edgeType'] == 'revision.parent'
    }

    return phids, edges
