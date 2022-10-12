# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from landoapi.phabricator import RevisionStatus
from landoapi.repos import repo_clone_subsystem
from landoapi.repos import Repo, SCM_LEVEL_3
from landoapi.hg import HgRepo
from landoapi.models.configuration import ConfigurationVariable, VariableType
from landoapi.models.revisions import Revision, RevisionLandingJob, RevisionStatus as RS
from landoapi.models.landing_job import LandingJob, LandingJobStatus
from landoapi.workers.revision_worker import get_active_repos, get_stacks, parse_diff
from landoapi.workers.revision_worker import Supervisor, Processor
from landoapi.workers.landing_worker import LandingWorker

import pytest

initial_diff = """
diff --git a/a b/a
new file mode 100644
--- /dev/null
+++ b/a
@@ -0,0 +1,2 @@
+first line
+second line
diff --git a/b b/b
new file mode 100644
--- /dev/null
+++ b/b
@@ -0,0 +1,1 @@
+first line
diff --git a/c b/c
new file mode 100644
""".strip()

second_diff = """
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

third_diff = """
diff --git a/c b/c
deleted file mode 100644
diff --git a/d b/d
deleted file mode 100644
""".strip()


@pytest.fixture
def new_diff():
    def _new_diff(filename):
        return f"""
        diff --git a/{filename} b/{filename}
        new file mode 100644
        --- /dev/null
        +++ b/{filename}
        @@ -0,0 +1,2 @@
        +first line
        +second line
        """.strip()

    return _new_diff


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


@pytest.fixture
def setup_repo(mock_repo_config, phabdouble, app, hg_server):
    def _setup():
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
        repo = phabdouble.repo(name="repoA")
        app.config["REPOS_TO_LAND"] = "repoA"
        repo_clone_subsystem.ready()
        return repo

    return _setup


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
    test = parse_diff(second_diff)
    assert test == {"a", "b", "d"}


def test_workers_integration(
    app,
    db,
    phabdouble,
    setup_repo,
    hg_clone,
    treestatusdouble,
):
    """This test runs through the entire workflow of supervisor + processor workers.

    - Create a stack with three revisions
    - Ensure that the revisions are picked up by the Supervisor worker
    - Ensure that the revisions are marked as READY_FOR_PREPROCESSING
    - Verify that the diffs are added correctly
    - Verify that the stack is represented correctly in the database
    - Run Processor worker
    - Verify that the revisions are processed and marked as READY
    - Update a single revision with a new diff
    - Verify that the successor revisions are marked as stale
    - Verify that the successor revisions are marked as READY afterwards
    """
    repo = setup_repo()
    treestatus = treestatusdouble.get_treestatus_client()
    treestatusdouble.open_tree("repoA")
    hgrepo = HgRepo(hg_clone.strpath)

    Revision.clear_patch_directory()

    r1 = phabdouble.revision(diff=phabdouble.diff(rawdiff=initial_diff), repo=repo)
    r2 = phabdouble.revision(
        diff=phabdouble.diff(rawdiff=second_diff), repo=repo, depends_on=[r1]
    )
    r3 = phabdouble.revision(
        diff=phabdouble.diff(rawdiff=third_diff), repo=repo, depends_on=[r2]
    )

    assert Revision.query.count() == 0

    supervisor = Supervisor()
    supervisor.start(max_loops=1)

    revisions = Revision.query.all()
    assert len(revisions) == 3
    assert set(r.status for r in revisions) == {RS.READY_FOR_PREPROCESSING}

    revision_1 = Revision.query.filter(Revision.revision_id == r1["id"]).one()
    revision_2 = Revision.query.filter(Revision.revision_id == r2["id"]).one()
    revision_3 = Revision.query.filter(Revision.revision_id == r3["id"]).one()

    # Check that all the patches are correct.
    assert "\n".join(revision_1.patch.splitlines()[6:]) == initial_diff
    assert "\n".join(revision_2.patch.splitlines()[6:]) == second_diff
    assert "\n".join(revision_3.patch.splitlines()[6:]) == third_diff

    # Check that stack is correct
    assert revision_1.predecessor == None
    assert revision_2.predecessor == revision_1
    assert revision_3.predecessor == revision_2

    assert revision_3.predecessors == [revision_1, revision_2]
    assert revision_2.predecessors == [revision_1]

    assert revision_1.linear_stack == revision_2.linear_stack
    assert revision_2.linear_stack == revision_3.linear_stack
    assert revision_3.linear_stack == [revision_1, revision_2, revision_3]

    ConfigurationVariable.set(Processor.CAPACITY_KEY, VariableType.INT, "3")
    ConfigurationVariable.set(Processor.THROTTLE_KEY, VariableType.INT, "0")

    processor = Processor()
    processor.start(max_loops=1)

    revisions = Revision.query.all()
    assert len(revisions) == 3
    assert set(r.status for r in revisions) == {RS.READY}

    # Update revision 2 with a new diff.
    phabdouble.diff(rawdiff=second_diff, revision=r2)

    # We expect revisions 2 and 3 to be marked as stale.
    supervisor.start(max_loops=1)
    revision_1 = Revision.query.filter(Revision.revision_id == r1["id"]).one()
    revision_2 = Revision.query.filter(Revision.revision_id == r2["id"]).one()
    revision_3 = Revision.query.filter(Revision.revision_id == r3["id"]).one()
    assert revision_1.status == RS.READY
    assert revision_2.status == RS.STALE
    assert revision_3.status == RS.STALE

    # After processing we expect everything to be back to ready state.
    processor.start(max_loops=1)

    revision_1 = Revision.query.filter(Revision.revision_id == r1["id"]).one()
    revision_2 = Revision.query.filter(Revision.revision_id == r2["id"]).one()
    revision_3 = Revision.query.filter(Revision.revision_id == r3["id"]).one()
    assert revision_1.status == RS.READY
    assert revision_2.status == RS.READY
    assert revision_3.status == RS.READY

    # The next few steps mimic what the transplant API endpoint does.
    # Create a landing job to try and land these revisions.
    job = LandingJob(
        status=LandingJobStatus.CREATED,
        requester_email="test@example.com",
        repository_name="repoA",
    )

    db.session.add(job)

    # Commit to get job ID.
    db.session.commit()

    for index, revision in enumerate([revision_1, revision_2, revision_3]):
        revision.status = RS.QUEUED
        db.session.add(
            RevisionLandingJob(
                index=index, landing_job_id=job.id, revision_id=revision.id
            )
        )
        db.session.commit()

    job.status = LandingJobStatus.SUBMITTED
    db.session.commit()

    worker = LandingWorker(sleep_seconds=0)

    worker.run_job(job, repo_clone_subsystem.repos["repoA"], hgrepo, treestatus)


def test_workers_integration_fail_with_merge_conflict(
    app,
    db,
    phabdouble,
    setup_repo,
    hg_clone,
    treestatusdouble,
):
    """
    Runs the same steps as the previous test, but tries to apply the second patch twice.
    """
    repo = setup_repo()

    Revision.clear_patch_directory()

    r1 = phabdouble.revision(diff=phabdouble.diff(rawdiff=initial_diff), repo=repo)
    r2 = phabdouble.revision(
        diff=phabdouble.diff(rawdiff=second_diff), repo=repo, depends_on=[r1]
    )
    r3 = phabdouble.revision(
        diff=phabdouble.diff(rawdiff=second_diff), repo=repo, depends_on=[r2]
    )

    assert Revision.query.count() == 0

    supervisor = Supervisor()
    supervisor.start(max_loops=1)

    revisions = Revision.query.all()
    assert len(revisions) == 3
    assert set(r.status for r in revisions) == {RS.READY_FOR_PREPROCESSING}

    revision_1 = Revision.query.filter(Revision.revision_id == r1["id"]).one()
    revision_2 = Revision.query.filter(Revision.revision_id == r2["id"]).one()
    revision_3 = Revision.query.filter(Revision.revision_id == r3["id"]).one()

    # Check that all the patches are correct.
    assert "\n".join(revision_1.patch.splitlines()[6:]) == initial_diff
    assert "\n".join(revision_2.patch.splitlines()[6:]) == second_diff
    assert "\n".join(revision_3.patch.splitlines()[6:]) == second_diff

    # Check that stack is correct
    assert revision_1.predecessor == None
    assert revision_2.predecessor == revision_1
    assert revision_3.predecessor == revision_2

    assert revision_3.predecessors == [revision_1, revision_2]
    assert revision_2.predecessors == [revision_1]

    assert revision_1.linear_stack == revision_2.linear_stack
    assert revision_2.linear_stack == revision_3.linear_stack
    assert revision_3.linear_stack == [revision_1, revision_2, revision_3]

    ConfigurationVariable.set(Processor.CAPACITY_KEY, VariableType.INT, "3")
    ConfigurationVariable.set(Processor.THROTTLE_KEY, VariableType.INT, "0")

    processor = Processor()
    processor.start(max_loops=1)

    revisions = Revision.query.all()
    assert len(revisions) == 3

    revision_1 = Revision.query.filter(Revision.revision_id == r1["id"]).one()
    revision_2 = Revision.query.filter(Revision.revision_id == r2["id"]).one()
    revision_3 = Revision.query.filter(Revision.revision_id == r3["id"]).one()
    assert revision_1.status == RS.READY
    assert revision_2.status == RS.READY
    assert revision_3.status == RS.PROBLEM


def test_workers_integration_modify_stacks_simple(
    app,
    db,
    phabdouble,
    setup_repo,
    hg_clone,
    treestatusdouble,
    new_diff,
):
    """
    Change the stack dependency and make sure it is reflected in Lando Revisions.
    """
    repo = setup_repo()

    Revision.clear_patch_directory()

    # Create some random revisions that are unrelated to increment revision IDs.
    phabdouble.revision(
        diff=phabdouble.diff(rawdiff=new_diff("file-a")),
        repo=repo,
        status=RevisionStatus.ABANDONED,
    )
    phabdouble.revision(
        diff=phabdouble.diff(rawdiff=new_diff("file-a")),
        repo=repo,
        status=RevisionStatus.ABANDONED,
    )
    phabdouble.revision(
        diff=phabdouble.diff(rawdiff=new_diff("file-a")),
        repo=repo,
        status=RevisionStatus.ABANDONED,
    )
    phabdouble.revision(
        diff=phabdouble.diff(rawdiff=new_diff("file-a")),
        repo=repo,
        status=RevisionStatus.ABANDONED,
    )

    r1 = phabdouble.revision(
        diff=phabdouble.diff(rawdiff=new_diff("file-1")), repo=repo
    )

    r2 = phabdouble.revision(
        diff=phabdouble.diff(rawdiff=new_diff("file-2")), repo=repo, depends_on=[r1]
    )
    r3 = phabdouble.revision(
        diff=phabdouble.diff(rawdiff=new_diff("file-3")), repo=repo, depends_on=[r1]
    )
    r4 = phabdouble.revision(
        diff=phabdouble.diff(rawdiff=new_diff("file-4")), repo=repo, depends_on=[r1, r2]
    )

    assert Revision.query.count() == 0

    supervisor = Supervisor()
    supervisor.start(max_loops=1)

    revision_1 = Revision.query.filter(Revision.revision_id == r1["id"]).one()
    revision_2 = Revision.query.filter(Revision.revision_id == r2["id"]).one()
    revision_3 = Revision.query.filter(Revision.revision_id == r3["id"]).one()
    revision_4 = Revision.query.filter(Revision.revision_id == r4["id"]).one()

    assert revision_1.status == RS.READY_FOR_PREPROCESSING
    assert revision_2.status == RS.READY_FOR_PREPROCESSING
    assert revision_3.status == RS.READY_FOR_PREPROCESSING
    assert revision_4.status == RS.PROBLEM
    assert revision_4.data["error"] == "Revision has more than one predecessor."

    # Check that stack is correct
    assert revision_1.predecessor == None
    assert not revision_1.data.get("predecessor")
    assert revision_2.predecessor == revision_1
    assert revision_2.data["predecessor"] == [r1["id"]]
    assert revision_3.predecessor == revision_1
    assert revision_3.data["predecessor"] == [r1["id"]]
    assert revision_4.predecessor == None
    assert sorted(revision_4.data["predecessor"]) == sorted([r1["id"], r2["id"]])

    # Modify stack so that it is linear, then re-check Lando.

    phabdouble.update_revision_dependencies(r3["phid"], depends_on=[r2])
    phabdouble.update_revision_dependencies(r4["phid"], depends_on=[r3])

    supervisor.start(max_loops=1)

    revision_1 = Revision.query.filter(Revision.revision_id == r1["id"]).one()
    revision_2 = Revision.query.filter(Revision.revision_id == r2["id"]).one()
    revision_3 = Revision.query.filter(Revision.revision_id == r3["id"]).one()
    revision_4 = Revision.query.filter(Revision.revision_id == r4["id"]).one()

    assert revision_1.predecessor == None
    assert revision_2.predecessor == revision_1
    assert revision_3.predecessor == revision_2
    assert revision_4.predecessor == revision_3

    assert not revision_1.data.get("predecessor")
    assert revision_2.data["predecessor"] == [r1["id"]]
    assert revision_3.data["predecessor"] == [r2["id"]]
    assert revision_4.data["predecessor"] == [r3["id"]]
