# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging
from collections import namedtuple

from landoapi.phabricator import (
    PhabricatorClient,
    result_list_to_phid_dict,
    RevisionStatus,
)

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


RevisionData = namedtuple(
    'RevisionData', ('revisions', 'diffs', 'repositories')
)


def request_extended_revision_data(phab, revision_phids):
    """Return a RevisionData containing extended data for revisions.

    Args:
        phab: A landoapi.phabricator.PhabricatorClient.
        revision_phids: List of String PHIDs for revisions.

    Returns:
        A RevisionData containing extended data for a set of revisions.
    """
    if not revision_phids:
        return RevisionData({}, {}, {})

    revs = phab.call_conduit(
        'differential.revision.search',
        constraints={'phids': revision_phids},
        attachments={
            'reviewers': True,
            'reviewers-extra': True,
        },
        limit=len(revision_phids),
    )
    phab.expect(revs, 'data', len(revision_phids) - 1)
    revs = result_list_to_phid_dict(phab.expect(revs, 'data'))

    diffs = phab.call_conduit(
        'differential.diff.search',
        constraints={
            'phids':
            [phab.expect(r, 'fields', 'diffPHID') for r in revs.values()]
        },
        attachments={'commits': True},
        limit=len(revs),
    )
    phab.expect(diffs, 'data', len(revision_phids) - 1)
    diffs = result_list_to_phid_dict(phab.expect(diffs, 'data'))

    repo_phids = [
        phab.expect(r, 'fields', 'repositoryPHID') for r in revs.values()
    ] + [phab.expect(d, 'fields', 'repositoryPHID') for d in diffs.values()]
    repo_phids = {phid for phid in repo_phids if phid is not None}
    if repo_phids:
        repos = phab.call_conduit(
            'diffusion.repository.search',
            constraints={
                'phids': [phid for phid in repo_phids],
            },
            limit=len(repo_phids),
        )
        phab.expect(repos, 'data', len(repo_phids) - 1)
        repos = result_list_to_phid_dict(phab.expect(repos, 'data'))
    else:
        repos = {}

    return RevisionData(revs, diffs, repos)


def calculate_landable_subgraphs(revision_data, edges, landable_repos):
    """Return a list of landable DAG paths.

    Args:
        revision_data: A RevisionData with data for all phids present
            in `edges`.
        edges: a set of tuples (child, parent) each representing an edge
        between two nodes. `child` and `parent` are also string
        PHIDs.
        landable_repos: a set of string PHIDs for repositories that
        are supported for landing.

    Returns:
        A list of lists with each sub-list being a series of PHID strings
        which identify a DAG path. These paths are the set of landable
        paths in the revision stack.
    """
    # We need to walk from the roots to the heads to build the landable
    # subgraphs so identify the roots and build adjacency lists
    children = {phid: set() for phid in revision_data.revisions}
    parents = {phid: set() for phid in revision_data.revisions}
    roots = set(revision_data.revisions.keys())
    for child, parent in edges:
        roots.discard(child)
        children[parent].add(child)
        parents[child].add(parent)

    # We only want to consider paths starting from the open children of the
    # first revision found with open children, along the path from a root.
    # So grab the status for all revisions.
    statuses = {
        phid: RevisionStatus.from_status(
            PhabricatorClient.expect(revision, 'fields', 'status', 'value')
        )
        for phid, revision in revision_data.revisions.items()
    }

    # Identify all the open children of the first revision with open
    # children on our paths from a root, these become our new `roots`.
    to_process = roots
    roots = set()
    while to_process:
        phid = to_process.pop()
        if not statuses[phid].closed:
            roots.add(phid)
            continue

        to_process.update(children[phid])

    # Because `roots` may no longer contain just true roots of the DAG,
    # a "root" could be the descendent of another. Filter out these "roots".
    to_process = set()
    for root in roots:
        to_process.update(children[root])
    while to_process:
        phid = to_process.pop()
        roots.discard(phid)
        to_process.update(children[phid])

    # Filter out roots that have a repository we don't support landing to.
    # This will take care of filtering all unsupported repository revisions
    # since multiple revisions along a path are not supported.
    roots = {
        root
        for root in roots
        if PhabricatorClient.expect(
            revision_data.revisions[root], 'fields', 'repositoryPHID'
        ) in landable_repos
    }

    # Now we can walk from the roots and find the end of each path that
    # is landable.
    def is_valid_next_revision(path_tip, child):
        other_open_parents = [
            p
            for p in parents[child] if p != path_tip and not statuses[p].closed
        ]
        repos_match = (
            PhabricatorClient.expect(
                revision_data.revisions[path_tip], 'fields', 'repositoryPHID'
            ) == PhabricatorClient.expect(
                revision_data.revisions[child], 'fields', 'repositoryPHID'
            )
        )
        return (
            not statuses[child].closed and not other_open_parents and
            repos_match
        )

    paths = []
    to_process = [[root] for root in roots]
    while to_process:
        path = to_process.pop()

        valid_children = [
            child for child in children[path[-1]]
            if is_valid_next_revision(path[-1], child)
        ]
        if valid_children:
            to_process.extend([path + [child] for child in valid_children])
        else:
            paths.append(path)

    return paths
