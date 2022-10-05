# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from landoapi.repos import Repo, SCM_LEVEL_3
from landoapi.models.configuration import ConfigurationVariable, VariableType
from landoapi.models.revisions import Revision, RevisionStatus as RS
from landoapi.workers.revision_worker import get_active_repos, get_stacks, parse_diff
from landoapi.workers.revision_worker import Supervisor, Processor

import pytest


test_diff = """
# HG changeset patch
# User Zeid <zeid@mozilla.com>
# Date 1664985824 14400
#      Wed Oct 05 12:03:44 2022 -0400
# Node ID 13f48e0bc7dd18b4a8b9c365ad91554f3d59c559
# Parent  73335005b10f0bc8ed3778c0798b382c8b0a15ff
multiple changes

diff --git a/a b/a
--- a/a
+++ b/a
@@ -1,2 +1,1 @@
first line
-second line
diff --git a/b b/b
deleted file mode 100644
--- a/b
+++ /dev/null
@@ -1,1 +0,0 @@
-first line
diff --git a/d b/d
new file mode 100644
 """.strip()


@pytest.fixture
def repos_dict():
    repo_config = {
        "repoA": Repo(
            short_name="repoA",
            tree="repo-A",
            url="http://hg.test",
            use_revision_worker=True,
            access_group=None,
        ),
        "repoB": Repo(
            short_name="repoB",
            tree="repo-B",
            url="http://hg.test",
            use_revision_worker=False,
            access_group=None,
        ),
    }
    return repo_config


def test_get_active_repos(phabdouble, db, repos_dict):
    """Only repos that have `use_revision_worker` set to `True` should be returned."""
    repoA = phabdouble.repo(name="repoA")
    phabdouble.repo(name="repoB")

    test = get_active_repos(repos_dict.values())
    assert test == [repoA["phid"]]


def test_get_stacks(phabdouble):
    repo = phabdouble.repo(name="test-repo")

    d1a = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1a, repo=repo)

    d2 = phabdouble.diff()
    r2 = phabdouble.revision(diff=d2, repo=repo, depends_on=[r1])

    d3 = phabdouble.diff()
    r3 = phabdouble.revision(diff=d3, repo=repo, depends_on=[r1])

    d4 = phabdouble.diff()
    r4 = phabdouble.revision(diff=d4, repo=repo)

    phab = phabdouble.get_phabricator_client()
    revisions = phab.call_conduit("differential.revision.search")["data"]
    test = get_stacks({r["phid"]: r for r in revisions})
    assert len(test) == 2
    test.sort(key=lambda x: len(x.nodes))

    assert list(test[0].nodes) == [r4["phid"]]
    assert sorted(list(test[1].nodes)) == sorted([r1["phid"], r2["phid"], r3["phid"]])

    assert len(test[0].edges) == 0
    assert sorted(list(test[1].edges)) == sorted(
        [(r1["phid"], r2["phid"]), (r1["phid"], r3["phid"])]
    )


def test_get_phab_revisions(phabdouble, db):
    # TODO
    pass


def test_parse_diff():
    """The provided patch should yield all filenames modified in the diff."""
    test = parse_diff(test_diff)
    assert test == {"a", "b", "d"}


def test_workers_integration(
    app,
    db,
    mock_repo_config,
    hg_server,
    hg_clone,
    treestatusdouble,
    phabdouble,
    monkeypatch,
    create_revision,
):
    from landoapi.repos import repo_clone_subsystem

    treestatusdouble.open_tree("repoA")
    mock_repo_config(
        {
            "test": {
                "repoA": Repo(
                    tree="mozilla-central",
                    url=hg_server,
                    access_group=SCM_LEVEL_3,
                    push_path=hg_server,
                    pull_path=hg_server,
                    use_revision_worker=True,
                )
            }
        }
    )

    # Mock the phabricator response data
    repo = phabdouble.repo(name="repoA")

    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=repo)

    d2 = phabdouble.diff()
    phabdouble.revision(diff=d2, repo=repo, depends_on=[r1])

    d3 = phabdouble.diff()
    phabdouble.revision(diff=d3, repo=repo)

    app.config["REPOS_TO_LAND"] = "repoA"
    repo_clone_subsystem.ready()

    assert Revision.query.count() == 0

    worker = Supervisor()
    worker.start(max_loops=1)

    revisions = Revision.query.all()
    assert len(revisions) == 3
    assert set(r.status for r in revisions) == {RS.READY_FOR_PREPROCESSING}

    ConfigurationVariable.set(Processor.CAPACITY_KEY, VariableType.INT, "3")

    worker = Processor()
    worker.start(max_loops=1)

    # TODO: add more tests here for:
    # - updating stack configuration (i.e. ensure that revisions are updated downstream)
    # - updating diffs and ensuring the patch cache is updated correctly
    # - integrating with the landing worker and seeing this workflow to the end
    # - mots preprocessing/querying
