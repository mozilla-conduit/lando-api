# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging
from collections import namedtuple
from typing import (
    List,
    Set,
    Tuple,
)

from landoapi.phabricator import (
    PhabricatorClient,
    result_list_to_phid_dict,
    RevisionStatus,
)

logger = logging.getLogger(__name__)


def build_stack_graph(
    phab: PhabricatorClient, revision_phid: str
) -> Tuple[Set[str], Set[Tuple[str, str]]]:
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
            "edge.search",
            types=["revision.parent", "revision.child"],
            sourcePHIDs=[phid for phid in phids],
            limit=10000,
        )
        edges = phab.expect(edges, "data")
        new_phids = set()
        for edge in edges:
            new_phids.add(edge["sourcePHID"])
            new_phids.add(edge["destinationPHID"])

        new_phids = new_phids - phids

    # Treat the stack like a commit DAG, we only care about edges going
    # from child to parent. This is enough to represent the graph.
    edges = {
        (edge["sourcePHID"], edge["destinationPHID"])
        for edge in edges
        if edge["edgeType"] == "revision.parent"
    }

    return phids, edges


RevisionData = namedtuple("RevisionData", ("revisions", "diffs", "repositories"))


def request_extended_revision_data(
    phab: PhabricatorClient, revision_phids: List[str]
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
            constraints={"phids": [phid for phid in repo_phids]},
            limit=len(repo_phids),
        )
        phab.expect(repos, "data", len(repo_phids) - 1)
        repos = result_list_to_phid_dict(phab.expect(repos, "data"))
    else:
        repos = {}

    return RevisionData(revs, diffs, repos)


def calculate_landable_subgraphs(
    revision_data, edges, landable_repos, *, other_checks=[]
):
    """Return a list of landable DAG paths.

    Args:
        revision_data: A RevisionData with data for all phids present
            in `edges`.
        edges: a set of tuples (child, parent) each representing an edge
            between two nodes. `child` and `parent` are also string
            PHIDs.
        landable_repos: a set of string PHIDs for repositories that
            are supported for landing.
        other_checks: An iterable of callables which will be executed
            for each revision to determine if it should be blocked. These
            checks must not rely on the structure the stack graph takes,
            instead they may check only properties specific to a single
            revision. If a revision is blocked for other reasons it's
            possible that a check may not be called for that revision. The
            callables must have the following signature:
                Args:
                    revision: A dictionary of revision data.
                    diff: A dictionary of diff data for the diff of the
                        given revision.
                    repo: A dictionary of repository data for the repository
                        the revision applies to.
                Returns:
                    None if the check passed and doesn't block the revision,
                    a string containing the reason if the check fails and
                    should block.

    Returns:
        A 2-tuple of (landable_paths, blockers). landable_paths is
        a list of lists with each sub-list being a series of PHID strings
        which identify a DAG path. These paths are the set of landable
        paths in the revision stack. blockers is a dictionary mapping
        revision phid to a string reason for that revision being blocked.
        Revisions appearing in landable_paths will not have an entry
        in blockers.
    """
    # We need to indicate why a revision isn't landable, so keep track
    # of the reason whenever we remove a revision from consideration.
    blocked = {}

    def block(node, reason):
        if node not in blocked:
            blocked[node] = reason

    # We won't land anything that has a repository we don't support, so make
    # a pass over all the revisions and block these.
    for phid, revision in revision_data.revisions.items():
        repo = PhabricatorClient.expect(revision, "fields", "repositoryPHID")
        if not repo:
            block(
                phid,
                "Revision's repository unset. Specify a target using"
                '"Edit revision" in Phabricator',
            )
            continue

        if repo not in landable_repos:
            block(phid, "Repository is not supported by Lando.")

    # We only want to consider paths starting from the open revisions
    # do grab the status for all revisions.
    statuses = {
        phid: RevisionStatus.from_status(
            PhabricatorClient.expect(revision, "fields", "status", "value")
        )
        for phid, revision in revision_data.revisions.items()
    }

    # Mark all closed revisions as blocked.
    for phid, status in statuses.items():
        if status.closed:
            block(phid, "Revision is closed.")

    # We need to walk from the roots to the heads to build the landable
    # subgraphs so identify the roots and insantiate a RevisionStack
    # to use its adjacency lists.
    stack = RevisionStack(set(revision_data.revisions.keys()), edges)
    roots = {phid for phid in stack.nodes if not stack.parents[phid]}

    # All of the roots may not be open so we need to walk from them
    # and find the first open revision along each path.
    to_process = roots
    roots = set()
    while to_process:
        phid = to_process.pop()
        if not statuses[phid].closed:
            roots.add(phid)
            continue

        to_process.update(stack.children[phid])

    # Because `roots` may no longer contain just true roots of the DAG,
    # a "root" could be the descendent of another. Filter out these "roots".
    to_process = set()
    for root in roots:
        to_process.update(stack.children[root])
    while to_process:
        phid = to_process.pop()
        roots.discard(phid)
        to_process.update(stack.children[phid])

    # Filter out roots that we have blocked already.
    roots = roots - blocked.keys()

    # Do a pass over the roots to check if they're blocked, so we only
    # start landable paths with unblocked roots.
    to_process = roots
    roots = set()
    for root in to_process:
        reason = _blocked_by(
            root, revision_data, statuses, stack, blocked, other_checks=other_checks
        )
        if reason is None:
            roots.add(root)
        else:
            block(root, reason)

    # Now walk from the unblocked roots to identify landable paths.
    landable = roots.copy()
    paths = []
    to_process = [[root] for root in roots]
    while to_process:
        path = to_process.pop()

        valid_children = []
        for child in stack.children[path[-1]]:
            if statuses[child].closed:
                continue

            reason = _blocked_by(
                child,
                revision_data,
                statuses,
                stack,
                blocked,
                other_checks=other_checks,
            )
            if reason is None:
                valid_children.append(child)
                landable.add(child)
            else:
                block(child, reason)

        if valid_children:
            to_process.extend([path + [child] for child in valid_children])
        else:
            paths.append(path)

    # Do one final pass to set blocked for anything that's not landable and
    # and hasn't already been marked blocked. These are the descendents we
    # never managed to reach walking the landable paths.
    for phid in stack.nodes - landable - set(blocked.keys()):
        block(phid, "Has an open ancestor revision that is blocked.")

    return paths, blocked


def _blocked_by(phid, revision_data, statuses, stack, blocked, *, other_checks=[]):
    # If this revision has already been marked as blocked just return
    # the reason that was given previously.
    if phid in blocked:
        return blocked[phid]

    parents = stack.parents[phid]
    open_parents = {p for p in parents if not statuses[p].closed}
    if len(open_parents) > 1:
        return "Depends on multiple open parents."

    for parent in open_parents:
        if parent in blocked:
            return "Depends on D{} which is open and blocked.".format(
                PhabricatorClient.expect(revision_data[parent], "id")
            )

    if open_parents:
        assert len(open_parents) == 1
        parent = open_parents.pop()
        if (
            revision_data.revisions[phid]["fields"]["repositoryPHID"]
            != revision_data.revisions[parent]["fields"]["repositoryPHID"]
        ):
            return (
                "Depends on D{} which is open and has a different repository."
            ).format(revision_data.revisions[parent]["id"])

    # Perform extra blocker checks that don't depend on the
    # structure of the stack graph.
    revision = revision_data.revisions[phid]
    diff = revision_data.diffs[revision["fields"]["diffPHID"]]
    repo = revision_data.repositories[revision["fields"]["repositoryPHID"]]
    for check in other_checks:
        result = check(revision=revision, diff=diff, repo=repo)
        if result:
            return result

    return None


class RevisionStack:
    def __init__(self, nodes, edges):
        self.nodes = nodes
        self.edges = edges

        self.children = {phid: set() for phid in self.nodes}
        self.parents = {phid: set() for phid in self.nodes}
        for child, parent in self.edges:
            self.children[parent].add(child)
            self.parents[child].add(parent)


def get_landable_repos_for_revision_data(revision_data, supported_repos):
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
