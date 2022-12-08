# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from landoapi.phabricator import RevisionStatus
from landoapi.repos import get_repos_for_env
from landoapi.stacks import (
    RevisionStack,
    build_stack_graph,
    calculate_landable_subgraphs,
    get_landable_repos_for_revision_data,
    request_extended_revision_data,
)


def test_build_stack_graph_single_node(phabdouble):
    phab = phabdouble.get_phabricator_client()
    revision = phabdouble.revision()

    nodes, edges = build_stack_graph(phab, revision["phid"])
    assert len(nodes) == 1
    assert nodes.pop() == revision["phid"]
    assert not edges


def test_build_stack_graph_two_nodes(phabdouble):
    phab = phabdouble.get_phabricator_client()
    r1 = phabdouble.revision()
    r2 = phabdouble.revision(depends_on=[r1])

    nodes, edges = build_stack_graph(phab, r1["phid"])
    assert nodes == {r1["phid"], r2["phid"]}
    assert len(edges) == 1
    assert edges == {(r2["phid"], r1["phid"])}

    # Building from either revision should result in same graph.
    nodes2, edges2 = build_stack_graph(phab, r2["phid"])
    assert nodes2 == nodes
    assert edges2 == edges


def _build_revision_graph(phabdouble, dep_list):
    revisions = []

    for deps in dep_list:
        revisions.append(
            phabdouble.revision(depends_on=[revisions[dep] for dep in deps])
        )

    return revisions


def test_build_stack_graph_multi_root_multi_head_multi_path(phabdouble):
    phab = phabdouble.get_phabricator_client()

    # Revision stack to construct:
    # *     revisions[10]
    # | *   revisions[9]
    # |/
    # *     revisions[8]
    # |\
    # | *   revisions[7]
    # * |   revisions[6]
    # * |   revisions[5]
    # | *   revisions[4]
    # |/
    # *     revisions[3]
    # |\
    # | *   revisions[2]
    # | *   revisions[1]
    # *     revisions[0]

    # fmt: off
    revisions = _build_revision_graph(
        phabdouble, [
            [],
            [],
            [1],
            [0, 2],
            [3],
            [3],
            [5],
            [4],
            [6, 7],
            [8],
            [8],
        ]
    )
    # fmt: on

    nodes, edges = build_stack_graph(phab, revisions[0]["phid"])
    assert nodes == {r["phid"] for r in revisions}
    assert edges == {
        (revisions[2]["phid"], revisions[1]["phid"]),
        (revisions[3]["phid"], revisions[2]["phid"]),
        (revisions[3]["phid"], revisions[0]["phid"]),
        (revisions[4]["phid"], revisions[3]["phid"]),
        (revisions[5]["phid"], revisions[3]["phid"]),
        (revisions[6]["phid"], revisions[5]["phid"]),
        (revisions[7]["phid"], revisions[4]["phid"]),
        (revisions[8]["phid"], revisions[6]["phid"]),
        (revisions[8]["phid"], revisions[7]["phid"]),
        (revisions[9]["phid"], revisions[8]["phid"]),
        (revisions[10]["phid"], revisions[8]["phid"]),
    }

    for r in revisions[1:]:
        nodes2, edges2 = build_stack_graph(phab, r["phid"])
        assert nodes2 == nodes
        assert edges2 == edges


def test_build_stack_graph_disconnected_revisions_not_included(phabdouble):
    phab = phabdouble.get_phabricator_client()

    revisions = _build_revision_graph(
        phabdouble,
        [
            # Graph A.
            [],
            [0],
            [1],
            # Graph B.
            [],
            [3],
        ],
    )

    # Graph A.
    nodes, edges = build_stack_graph(phab, revisions[0]["phid"])
    assert nodes == {r["phid"] for r in revisions[:3]}
    assert edges == {
        (revisions[1]["phid"], revisions[0]["phid"]),
        (revisions[2]["phid"], revisions[1]["phid"]),
    }

    # Graph B.
    nodes, edges = build_stack_graph(phab, revisions[3]["phid"])
    assert nodes == {r["phid"] for r in revisions[3:]}
    assert edges == {(revisions[4]["phid"], revisions[3]["phid"])}


def test_request_extended_revision_data_single_revision_no_repo(phabdouble):
    phab = phabdouble.get_phabricator_client()

    diff = phabdouble.diff()
    revision = phabdouble.revision(diff=diff)
    data = request_extended_revision_data(phab, [revision["phid"]])

    assert revision["phid"] in data.revisions
    assert diff["phid"] in data.diffs
    assert not data.repositories


def test_request_extended_revision_data_single_revision_with_repo(phabdouble):
    phab = phabdouble.get_phabricator_client()

    repo = phabdouble.repo()
    diff = phabdouble.diff()
    revision = phabdouble.revision(diff=diff, repo=repo)
    data = request_extended_revision_data(phab, [revision["phid"]])

    assert revision["phid"] in data.revisions
    assert diff["phid"] in data.diffs
    assert repo["phid"] in data.repositories


def test_request_extended_revision_data_no_revisions(phabdouble):
    phab = phabdouble.get_phabricator_client()
    data = request_extended_revision_data(phab, [])

    assert not data.revisions
    assert not data.diffs
    assert not data.repositories


def test_request_extended_revision_data_gets_latest_diff(phabdouble):
    phab = phabdouble.get_phabricator_client()

    first_diff = phabdouble.diff()
    revision = phabdouble.revision(diff=first_diff)
    latest_diff = phabdouble.diff(revision=revision)
    data = request_extended_revision_data(phab, [revision["phid"]])

    assert revision["phid"] in data.revisions
    assert first_diff["phid"] not in data.diffs
    assert latest_diff["phid"] in data.diffs


def test_request_extended_revision_data_diff_and_revision_repo(phabdouble):
    phab = phabdouble.get_phabricator_client()

    repo1 = phabdouble.repo(name="repo1")
    repo2 = phabdouble.repo(name="repo2")
    diff = phabdouble.diff(repo=repo1)
    revision = phabdouble.revision(diff=diff, repo=repo2)
    data = request_extended_revision_data(phab, [revision["phid"]])

    assert revision["phid"] in data.revisions
    assert diff["phid"] in data.diffs
    assert repo1["phid"] in data.repositories
    assert repo2["phid"] in data.repositories


def test_request_extended_revision_data_unrelated_revisions(phabdouble):
    phab = phabdouble.get_phabricator_client()

    repo1 = phabdouble.repo(name="repo1")
    diff1 = phabdouble.diff(repo=repo1)
    r1 = phabdouble.revision(diff=diff1, repo=repo1)

    repo2 = phabdouble.repo(name="repo2")
    diff2 = phabdouble.diff(repo=repo2)
    r2 = phabdouble.revision(diff=diff2, repo=repo2)

    data = request_extended_revision_data(phab, [r1["phid"], r2["phid"]])

    assert r1["phid"] in data.revisions
    assert r2["phid"] in data.revisions
    assert diff1["phid"] in data.diffs
    assert diff2["phid"] in data.diffs
    assert repo1["phid"] in data.repositories
    assert repo2["phid"] in data.repositories


def test_request_extended_revision_data_stacked_revisions(phabdouble):
    phab = phabdouble.get_phabricator_client()

    repo = phabdouble.repo()

    diff1 = phabdouble.diff(repo=repo)
    r1 = phabdouble.revision(diff=diff1, repo=repo)

    diff2 = phabdouble.diff(repo=repo)
    r2 = phabdouble.revision(depends_on=[r1], diff=diff2, repo=repo)

    data = request_extended_revision_data(phab, [r1["phid"], r2["phid"]])

    assert r1["phid"] in data.revisions
    assert r2["phid"] in data.revisions
    assert diff1["phid"] in data.diffs
    assert diff2["phid"] in data.diffs
    assert repo["phid"] in data.repositories

    data = request_extended_revision_data(phab, [r1["phid"]])

    assert r1["phid"] in data.revisions
    assert r2["phid"] not in data.revisions
    assert diff1["phid"] in data.diffs
    assert diff2["phid"] not in data.diffs
    assert repo["phid"] in data.repositories


def test_calculate_landable_subgraphs_no_edges_open(phabdouble):
    phab = phabdouble.get_phabricator_client()

    repo = phabdouble.repo()
    revision = phabdouble.revision(repo=repo)
    ext_data = request_extended_revision_data(phab, [revision["phid"]])

    landable, _ = calculate_landable_subgraphs(ext_data, [], {repo["phid"]})

    assert len(landable) == 1
    assert landable[0] == [revision["phid"]]


def test_calculate_landable_subgraphs_no_edges_closed(phabdouble):
    phab = phabdouble.get_phabricator_client()

    repo = phabdouble.repo()
    revision = phabdouble.revision(repo=repo, status=RevisionStatus.PUBLISHED)
    ext_data = request_extended_revision_data(phab, [revision["phid"]])

    landable, _ = calculate_landable_subgraphs(ext_data, [], {repo["phid"]})

    assert not landable


def test_calculate_landable_subgraphs_closed_root(phabdouble):
    phab = phabdouble.get_phabricator_client()

    repo = phabdouble.repo()
    r1 = phabdouble.revision(repo=repo, status=RevisionStatus.PUBLISHED)
    r2 = phabdouble.revision(repo=repo, depends_on=[r1])

    nodes, edges = build_stack_graph(phab, r1["phid"])
    ext_data = request_extended_revision_data(phab, [r1["phid"], r2["phid"]])

    landable, _ = calculate_landable_subgraphs(ext_data, edges, {repo["phid"]})
    assert landable == [[r2["phid"]]]


def test_calculate_landable_subgraphs_closed_root_child_merges(phabdouble):
    phab = phabdouble.get_phabricator_client()

    repo = phabdouble.repo()
    r1 = phabdouble.revision(repo=repo)
    r2 = phabdouble.revision(repo=repo, depends_on=[r1])
    r3 = phabdouble.revision(repo=repo, status=RevisionStatus.PUBLISHED)
    r4 = phabdouble.revision(repo=repo, depends_on=[r2, r3])

    nodes, edges = build_stack_graph(phab, r1["phid"])
    ext_data = request_extended_revision_data(
        phab, [r1["phid"], r2["phid"], r3["phid"], r4["phid"]]
    )

    landable, _ = calculate_landable_subgraphs(ext_data, edges, {repo["phid"]})
    assert [r3["phid"]] not in landable
    assert [r3["phid"], r4["phid"]] not in landable
    assert [r4["phid"]] not in landable
    assert landable == [[r1["phid"], r2["phid"], r4["phid"]]]


def test_calculate_landable_subgraphs_stops_multiple_repo_paths(phabdouble):
    phab = phabdouble.get_phabricator_client()

    repo1 = phabdouble.repo(name="repo1")
    repo2 = phabdouble.repo(name="repo2")
    r1 = phabdouble.revision(repo=repo1)
    r2 = phabdouble.revision(repo=repo1, depends_on=[r1])
    r3 = phabdouble.revision(repo=repo2, depends_on=[r2])

    nodes, edges = build_stack_graph(phab, r1["phid"])
    ext_data = request_extended_revision_data(
        phab, [r1["phid"], r2["phid"], r3["phid"]]
    )

    landable, _ = calculate_landable_subgraphs(
        ext_data, edges, {repo1["phid"], repo2["phid"]}
    )
    assert landable == [[r1["phid"], r2["phid"]]]


def test_calculate_landable_subgraphs_allows_distinct_repo_paths(phabdouble):
    phab = phabdouble.get_phabricator_client()

    repo1 = phabdouble.repo(name="repo1")
    r1 = phabdouble.revision(repo=repo1)
    r2 = phabdouble.revision(repo=repo1, depends_on=[r1])

    repo2 = phabdouble.repo(name="repo2")
    r3 = phabdouble.revision(repo=repo2)
    r4 = phabdouble.revision(repo=repo2, depends_on=[r3])

    r5 = phabdouble.revision(repo=repo1, depends_on=[r2, r4])

    nodes, edges = build_stack_graph(phab, r1["phid"])
    ext_data = request_extended_revision_data(
        phab, [r1["phid"], r2["phid"], r3["phid"], r4["phid"], r5["phid"]]
    )

    landable, _ = calculate_landable_subgraphs(
        ext_data, edges, {repo1["phid"], repo2["phid"]}
    )
    assert len(landable) == 2
    assert [r1["phid"], r2["phid"]] in landable
    assert [r3["phid"], r4["phid"]] in landable


def test_calculate_landable_subgraphs_different_repo_parents(phabdouble):
    phab = phabdouble.get_phabricator_client()

    repo1 = phabdouble.repo(name="repo1")
    r1 = phabdouble.revision(repo=repo1)

    repo2 = phabdouble.repo(name="repo2")
    r2 = phabdouble.revision(repo=repo2)

    r3 = phabdouble.revision(repo=repo2, depends_on=[r1, r2])

    nodes, edges = build_stack_graph(phab, r1["phid"])
    ext_data = request_extended_revision_data(
        phab, [r1["phid"], r2["phid"], r3["phid"]]
    )

    landable, _ = calculate_landable_subgraphs(
        ext_data, edges, {repo1["phid"], repo2["phid"]}
    )
    assert len(landable) == 2
    assert [r1["phid"]] in landable
    assert [r2["phid"]] in landable


def test_calculate_landable_subgraphs_different_repo_closed_parent(phabdouble):
    phab = phabdouble.get_phabricator_client()

    repo1 = phabdouble.repo(name="repo1")
    r1 = phabdouble.revision(repo=repo1, status=RevisionStatus.PUBLISHED)

    repo2 = phabdouble.repo(name="repo2")
    r2 = phabdouble.revision(repo=repo2)

    r3 = phabdouble.revision(repo=repo2, depends_on=[r1, r2])

    nodes, edges = build_stack_graph(phab, r1["phid"])
    ext_data = request_extended_revision_data(
        phab, [r1["phid"], r2["phid"], r3["phid"]]
    )

    landable, _ = calculate_landable_subgraphs(
        ext_data, edges, {repo1["phid"], repo2["phid"]}
    )
    assert len(landable) == 1
    assert [r2["phid"], r3["phid"]] in landable


def test_calculate_landable_subgraphs_diverging_paths_merge(phabdouble):
    phab = phabdouble.get_phabricator_client()

    repo = phabdouble.repo()
    r1 = phabdouble.revision(repo=repo)

    r2 = phabdouble.revision(repo=repo, depends_on=[r1])
    r3 = phabdouble.revision(repo=repo, depends_on=[r2])

    r4 = phabdouble.revision(repo=repo, depends_on=[r1])
    r5 = phabdouble.revision(repo=repo, depends_on=[r4])

    r6 = phabdouble.revision(repo=repo, depends_on=[r1])

    r7 = phabdouble.revision(repo=repo, depends_on=[r3, r5, r6])

    nodes, edges = build_stack_graph(phab, r1["phid"])
    ext_data = request_extended_revision_data(
        phab,
        [
            r1["phid"],
            r2["phid"],
            r3["phid"],
            r4["phid"],
            r5["phid"],
            r6["phid"],
            r7["phid"],
        ],
    )

    landable, _ = calculate_landable_subgraphs(ext_data, edges, {repo["phid"]})
    assert len(landable) == 3
    assert [r1["phid"], r2["phid"], r3["phid"]] in landable
    assert [r1["phid"], r4["phid"], r5["phid"]] in landable
    assert [r1["phid"], r6["phid"]] in landable


def test_calculate_landable_subgraphs_complex_graph(phabdouble):
    phab = phabdouble.get_phabricator_client()

    repoA = phabdouble.repo(name="repoA")
    repoB = phabdouble.repo(name="repoB")
    repoC = phabdouble.repo(name="repoC")

    # Revision stack to construct:
    # *         rB4
    # |\
    # | *       rB3
    # * |       rB2 (CLOSED)
    #   | *     rC1
    #   |/
    #   *       rA10
    #  /|\
    # * | |     rB1
    #   | *     rA9 (CLOSED)
    #   *       rA8
    #   | *     rA7
    #   |/
    #   *       rA6
    #  /|
    # | *       rA5
    # | *       rA4
    # * |\      rA3 (CLOSED)
    # | * |     rA2
    #  \|/
    #   *       rA1 (CLOSED)

    rA1 = phabdouble.revision(repo=repoA, status=RevisionStatus.PUBLISHED)
    rA2 = phabdouble.revision(repo=repoA, depends_on=[rA1])
    rA3 = phabdouble.revision(
        repo=repoA, status=RevisionStatus.PUBLISHED, depends_on=[rA1]
    )
    rA4 = phabdouble.revision(repo=repoA, depends_on=[rA1, rA2])
    rA5 = phabdouble.revision(repo=repoA, depends_on=[rA4])
    rA6 = phabdouble.revision(repo=repoA, depends_on=[rA3, rA5])
    rA7 = phabdouble.revision(repo=repoA, depends_on=[rA6])
    rA8 = phabdouble.revision(repo=repoA, depends_on=[rA6])
    rA9 = phabdouble.revision(repo=repoA, status=RevisionStatus.PUBLISHED)

    rB1 = phabdouble.revision(repo=repoB)

    rA10 = phabdouble.revision(repo=repoA, depends_on=[rA8, rA9, rB1])

    rC1 = phabdouble.revision(repo=repoC, depends_on=[rA10])

    rB2 = phabdouble.revision(repo=repoB, status=RevisionStatus.PUBLISHED)
    rB3 = phabdouble.revision(repo=repoB, depends_on=[rA10])
    rB4 = phabdouble.revision(repo=repoB, depends_on=[rB2, rB3])

    nodes, edges = build_stack_graph(phab, rA1["phid"])
    ext_data = request_extended_revision_data(
        phab,
        [
            rA1["phid"],
            rA2["phid"],
            rA3["phid"],
            rA4["phid"],
            rA5["phid"],
            rA6["phid"],
            rA7["phid"],
            rA8["phid"],
            rA9["phid"],
            rA10["phid"],
            rB1["phid"],
            rB2["phid"],
            rB3["phid"],
            rB4["phid"],
            rC1["phid"],
        ],
    )

    landable, _ = calculate_landable_subgraphs(
        ext_data, edges, {repoA["phid"], repoB["phid"]}
    )
    assert len(landable) == 3
    assert [rA2["phid"], rA4["phid"], rA5["phid"], rA6["phid"], rA7["phid"]] in landable
    assert [rA2["phid"], rA4["phid"], rA5["phid"], rA6["phid"], rA8["phid"]] in landable
    assert [rB1["phid"]] in landable


def test_calculate_landable_subgraphs_extra_check(phabdouble):
    phab = phabdouble.get_phabricator_client()

    repo = phabdouble.repo()
    r1 = phabdouble.revision(repo=repo)
    r2 = phabdouble.revision(repo=repo, depends_on=[r1])
    r3 = phabdouble.revision(repo=repo, depends_on=[r2])
    r4 = phabdouble.revision(repo=repo, depends_on=[r3])

    nodes, edges = build_stack_graph(phab, r1["phid"])
    ext_data = request_extended_revision_data(
        phab, [r1["phid"], r2["phid"], r3["phid"], r4["phid"]]
    )

    REASON = "Blocked by custom check."

    def custom_check(*, revision, diff, repo):
        return REASON if revision["id"] == r3["id"] else None

    landable, blocked = calculate_landable_subgraphs(
        ext_data, edges, {repo["phid"]}, other_checks=[custom_check]
    )
    assert landable == [[r1["phid"], r2["phid"]]]
    assert r3["phid"] in blocked and r4["phid"] in blocked
    assert blocked[r3["phid"]] == REASON


def test_calculate_landable_subgraphs_missing_repo(phabdouble):
    """Test to assert a missing repository for a revision is
    blocked with an appropriate error
    """
    phab = phabdouble.get_phabricator_client()
    repo1 = phabdouble.repo()
    r1 = phabdouble.revision(repo=None)

    nodes, edges = build_stack_graph(phab, r1["phid"])
    revision_data = request_extended_revision_data(phab, [r1["phid"]])

    landable, blocked = calculate_landable_subgraphs(
        revision_data, edges, {repo1["phid"]}
    )

    repo_unset_warning = (
        "Revision's repository unset. Specify a target using"
        '"Edit revision" in Phabricator'
    )

    assert not landable
    assert r1["phid"] in blocked
    assert blocked[r1["phid"]] == repo_unset_warning


def test_get_landable_repos_for_revision_data(phabdouble, mocked_repo_config):
    phab = phabdouble.get_phabricator_client()

    repo1 = phabdouble.repo(name="mozilla-central")
    repo2 = phabdouble.repo(name="not-mozilla-central")
    r1 = phabdouble.revision(repo=repo1)
    r2 = phabdouble.revision(repo=repo2, depends_on=[r1])

    supported_repos = get_repos_for_env("test")
    revision_data = request_extended_revision_data(phab, [r1["phid"], r2["phid"]])

    landable_repos = get_landable_repos_for_revision_data(
        revision_data, supported_repos
    )
    assert repo1["phid"] in landable_repos
    assert repo2["phid"] not in landable_repos
    assert landable_repos[repo1["phid"]].tree == "mozilla-central"


def test_integrated_stack_endpoint_simple(
    db, client, phabdouble, mocked_repo_config, release_management_project
):
    repo = phabdouble.repo()
    unsupported_repo = phabdouble.repo(name="not-mozilla-central")
    r1 = phabdouble.revision(repo=repo)
    r2 = phabdouble.revision(repo=repo, depends_on=[r1])
    r3 = phabdouble.revision(repo=repo, depends_on=[r1])
    r4 = phabdouble.revision(repo=unsupported_repo, depends_on=[r2, r3])

    response = client.get("/stacks/D{}".format(r3["id"]))
    assert response.status_code == 200

    assert len(response.json["edges"]) == 4
    assert [r2["phid"], r1["phid"]] in response.json["edges"]
    assert [r3["phid"], r1["phid"]] in response.json["edges"]
    assert [r4["phid"], r2["phid"]] in response.json["edges"]
    assert [r4["phid"], r3["phid"]] in response.json["edges"]

    assert len(response.json["landable_paths"]) == 2
    assert [r1["phid"], r2["phid"]] in response.json["landable_paths"]
    assert [r1["phid"], r3["phid"]] in response.json["landable_paths"]

    assert len(response.json["revisions"]) == 4
    revisions = {r["phid"]: r for r in response.json["revisions"]}
    assert r1["phid"] in revisions
    assert r2["phid"] in revisions
    assert r3["phid"] in revisions
    assert r4["phid"] in revisions

    assert revisions[r4["phid"]]["blocked_reason"] == (
        "Repository is not supported by Lando."
    )


def test_integrated_stack_endpoint_repos(
    db, client, phabdouble, mocked_repo_config, release_management_project
):
    repo = phabdouble.repo()
    unsupported_repo = phabdouble.repo(name="not-mozilla-central")
    r1 = phabdouble.revision(repo=repo)
    r2 = phabdouble.revision(repo=repo, depends_on=[r1])
    r3 = phabdouble.revision(repo=repo, depends_on=[r1])
    r4 = phabdouble.revision(repo=unsupported_repo, depends_on=[r2, r3])

    response = client.get("/stacks/D{}".format(r4["id"]))
    assert response.status_code == 200

    assert len(response.json["repositories"]) == 2

    repositories = {r["phid"]: r for r in response.json["repositories"]}
    assert repo["phid"] in repositories
    assert unsupported_repo["phid"] in repositories
    assert repositories[repo["phid"]]["landing_supported"]
    assert not repositories[unsupported_repo["phid"]]["landing_supported"]
    assert repositories[repo["phid"]]["url"] == "http://hg.test"
    assert repositories[unsupported_repo["phid"]]["url"] == (
        "http://phabricator.test/source/not-mozilla-central"
    )


def test_integrated_stack_has_revision_security_status(
    db, client, phabdouble, mock_repo_config, secure_project, release_management_project
):
    repo = phabdouble.repo()
    public_revision = phabdouble.revision(repo=repo)
    secure_revision = phabdouble.revision(
        repo=repo, projects=[secure_project], depends_on=[public_revision]
    )

    response = client.get("/stacks/D{}".format(secure_revision["id"]))
    assert response.status_code == 200

    revisions = {r["phid"]: r for r in response.json["revisions"]}
    assert not revisions[public_revision["phid"]]["is_secure"]
    assert revisions[secure_revision["phid"]]["is_secure"]


def test_revisionstack():
    nodes = ["123", "456", "789"]
    edges = [("123", "456"), ("456", "789")]

    stack = RevisionStack(nodes, edges)

    assert list(stack.base_revisions()) == [
        "789"
    ], "Node `789` should be the base revision."

    assert list(stack.iter_stack_from_base()) == [
        "789",
        "456",
        "123",
    ], "Iterating over the stack from the base should result in the expected order."
