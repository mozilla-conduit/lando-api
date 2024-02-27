# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging
from collections import namedtuple
from collections.abc import (
    Iterator,
)

import networkx as nx

from landoapi.phabricator import (
    PhabricatorClient,
    result_list_to_phid_dict,
)
from landoapi.repos import Repo

logger = logging.getLogger(__name__)


def build_stack_graph(revision: dict) -> tuple[set[str], set[tuple[str, str]]]:
    """Return a graph representation of a revision stack.

    Args:
        revision: A dictionary containing Phabricator revision data.

    Returns:
        A tuple of (nodes, edges). `nodes` is a set of strings
        PHIDs corresponding to revisions in the stack. `edges` is
        a set of tuples (child, parent) each representing an edge
        between two nodes. `child` and `parent` are also string
        PHIDs.
    """
    stack_graph = PhabricatorClient.expect(revision, "fields", "stackGraph")
    phids = set(stack_graph.keys())
    edges = set()

    for node, predecessors in stack_graph.items():
        for predecessor in predecessors:
            edges.add((node, predecessor))
    return phids, edges


RevisionData = namedtuple("RevisionData", ("revisions", "diffs", "repositories"))


def request_extended_revision_data(
    phab: PhabricatorClient, revision_phids: list[str]
) -> RevisionData:
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
        "differential.revision.search",
        constraints={"phids": revision_phids},
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
        limit=len(revision_phids),
    )

    if len(revs["data"]) != len(revision_phids):
        raise ValueError("Mismatch in size of returned data.")

    phab.expect(revs, "data", len(revision_phids) - 1)
    revs = result_list_to_phid_dict(phab.expect(revs, "data"))

    diffs = phab.call_conduit(
        "differential.diff.search",
        constraints={
            "phids": [phab.expect(r, "fields", "diffPHID") for r in revs.values()]
        },
        attachments={"commits": True},
        limit=len(revs),
    )
    phab.expect(diffs, "data", len(revision_phids) - 1)
    diffs = result_list_to_phid_dict(phab.expect(diffs, "data"))

    repo_phids = [phab.expect(r, "fields", "repositoryPHID") for r in revs.values()] + [
        phab.expect(d, "fields", "repositoryPHID") for d in diffs.values()
    ]
    repo_phids = {phid for phid in repo_phids if phid is not None}
    if repo_phids:
        repos = phab.call_conduit(
            "diffusion.repository.search",
            attachments={"projects": True},
            constraints={"phids": list(repo_phids)},
            limit=len(repo_phids),
        )
        phab.expect(repos, "data", len(repo_phids) - 1)
        repos = result_list_to_phid_dict(phab.expect(repos, "data"))
    else:
        repos = {}

    return RevisionData(revs, diffs, repos)


class RevisionStack(nx.DiGraph):
    def __init__(self, nodes: set[str], edges: set[tuple[str, str]]):
        super().__init__(
            # Reverse the order of the nodes in the edges set as `networkx`
            # represents `a -> b` as `(a, b)` but Lando uses `(b, a)`.
            (successor, predecessor)
            for predecessor, successor in edges
        )

        # Individually add each node to set the `blocked` attribute.
        for node in nodes:
            self.add_node(node, blocked=[])

    def root_revisions(self) -> Iterator[str]:
        """Iterate over the set of root revisions in the stack.

        A root revision is a revision in a graph with no predecessors.

        For example in this stack, where A has no successors:
        A
        |\
        B C
        | |
        D E

        `set(stack.root_revisions()) == {"D", "E"}`.
        """
        return (node for node, degree in self.in_degree if degree == 0)

    def leaf_revisions(self) -> Iterator[str]:
        """Iterate over the set of root revisions in the stack.

        A leaf revision is a revision in a graph with no successors.

        For example in this stack, where A has no successors:
        A
        |\
        B C
        | |
        D E

        `set(stack.leaf_revisions()) == {"A"}`.
        """
        return (node for node, degree in self.out_degree if degree == 0)

    def iter_stack_from_root(self, dest: str) -> Iterator[str]:
        """Iterate over the revisions in the stack starting from the root.

        Walks from one of the root nodes of the graphs to `dest`. If multiple
        root nodes exist, it will select one naively.
        """
        root = next(self.root_revisions())

        if root == dest:
            yield root
            return

        paths = list(nx.all_simple_paths(self, root, dest))

        if not paths:
            raise ValueError(f"Graph has no paths from {root} to {dest}.")

        if len(paths) > 1:
            raise ValueError(f"Graph has multiple paths from {root} to {dest}: {paths}")

        path = paths[0]

        for node in path:
            yield node

    def landable_paths(self) -> list[list[str]]:
        """Return the landable paths for the given stack."""
        leaf_nodes = list(self.leaf_revisions())

        landable_paths = []
        for root in self.root_revisions():
            # If the root is the same as the leaf node, it is a landable single revision.
            # Add it as a landable path since networkx doesn't consider a single node as a path.
            if root in leaf_nodes:
                landable_paths.append([root])
                continue

            # Find the paths between each landable root and landable leaf node.
            for path in nx.all_simple_paths(self, root, leaf_nodes):
                landable_paths.append(path)

        return landable_paths


def get_landable_repos_for_revision_data(
    revision_data: RevisionData, supported_repos: dict[str, Repo]
) -> dict[str, Repo]:
    """Return a dictionary mapping string PHID to landable Repo

    Args:
        revision_data: A RevisionData.
        supported_repos: A dictionary mapping repository shortname to
        a Repo for repositories lando supports.

    Returns:
        A dictionary where each key is a string PHID for a repository from
        revision_data and the value is a Repo taken from supported_repos.
        Repositories in revision_data which are unsupported will not be
        present in the dictionary.
    """
    repo_phids = {
        PhabricatorClient.expect(revision, "fields", "repositoryPHID")
        for revision in revision_data.revisions.values()
        if PhabricatorClient.expect(revision, "fields", "repositoryPHID")
    }
    repos = {
        phid: supported_repos.get(
            PhabricatorClient.expect(
                revision_data.repositories[phid], "fields", "shortName"
            )
        )
        for phid in repo_phids
        if phid in revision_data.repositories
    }
    return {phid: repo for phid, repo in repos.items() if repo}
