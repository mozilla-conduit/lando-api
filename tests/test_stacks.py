# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from landoapi.stacks import build_stack_graph


def test_build_stack_graph_single_node(phabdouble):
    phab = phabdouble.get_phabricator_client()
    revision = phabdouble.revision()

    nodes, edges = build_stack_graph(phab, revision['phid'])
    assert len(nodes) == 1
    assert nodes.pop() == revision['phid']
    assert not edges


def test_build_stack_graph_two_nodes(phabdouble):
    phab = phabdouble.get_phabricator_client()
    r1 = phabdouble.revision()
    r2 = phabdouble.revision(depends_on=[r1])

    nodes, edges = build_stack_graph(phab, r1['phid'])
    assert nodes == {r1['phid'], r2['phid']}
    assert len(edges) == 1
    assert edges == {(r2['phid'], r1['phid'])}

    # Building from either revision should result in same graph.
    nodes2, edges2 = build_stack_graph(phab, r2['phid'])
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

    nodes, edges = build_stack_graph(phab, revisions[0]['phid'])
    assert nodes == {r['phid'] for r in revisions}
    assert edges == {
        (revisions[2]['phid'], revisions[1]['phid']),
        (revisions[3]['phid'], revisions[2]['phid']),
        (revisions[3]['phid'], revisions[0]['phid']),
        (revisions[4]['phid'], revisions[3]['phid']),
        (revisions[5]['phid'], revisions[3]['phid']),
        (revisions[6]['phid'], revisions[5]['phid']),
        (revisions[7]['phid'], revisions[4]['phid']),
        (revisions[8]['phid'], revisions[6]['phid']),
        (revisions[8]['phid'], revisions[7]['phid']),
        (revisions[9]['phid'], revisions[8]['phid']),
        (revisions[10]['phid'], revisions[8]['phid']),
    }

    for r in revisions[1:]:
        nodes2, edges2 = build_stack_graph(phab, r['phid'])
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
            [3]
        ]
    )

    # Graph A.
    nodes, edges = build_stack_graph(phab, revisions[0]['phid'])
    assert nodes == {r['phid'] for r in revisions[:3]}
    assert edges == {
        (revisions[1]['phid'], revisions[0]['phid']),
        (revisions[2]['phid'], revisions[1]['phid']),
    }

    # Graph B.
    nodes, edges = build_stack_graph(phab, revisions[3]['phid'])
    assert nodes == {r['phid'] for r in revisions[3:]}
    assert edges == {
        (revisions[4]['phid'], revisions[3]['phid']),
    }
