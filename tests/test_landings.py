# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from unittest import mock
import pytest
import textwrap

from landoapi.hg import HgRepo
from landoapi.workers.landing_worker import LandingWorker
from landoapi.models.landing_job import LandingJob, LandingJobStatus
from landoapi.models.revisions import Revision, RevisionStatus as RS, RevisionLandingJob
from landoapi.models.transplant import Transplant, TransplantStatus
from landoapi.repos import Repo, SCM_LEVEL_3


@pytest.fixture
def create_revision():
    """A fixture that creates and stores a revision."""

    def _revision(patch, number=None, landing_job=None, **kwargs):
        number = number or Revision.query.value
        revision = Revision(revision_id=number, diff_id=number, **kwargs)
        revision.store_patch_hash(patch.encode("utf-8"))
        with revision.patch_cache_path.open("wb") as f:
            f.write(patch.encode("utf-8"))
        return revision

    return _revision


def test_update_landing(db, client):
    _create_transplant(db, 1, 1, 1, status=TransplantStatus.submitted)
    response = client.post(
        "/landings/update",
        json={"request_id": 1, "landed": True, "result": "sha123"},
        headers=[("API-Key", "someapikey")],
    )

    assert response.status_code == 200

    # Ensure DB access isn't using uncommitted data.
    db.session.close()

    transplant = Transplant.query.get(1)
    assert transplant.status == TransplantStatus.landed


def test_update_landing_bad_request_id(db, client):
    _create_transplant(db, 1, 1, 1, status=TransplantStatus.submitted)
    response = client.post(
        "/landings/update",
        json={"request_id": 2, "landed": True, "result": "sha123"},
        headers=[("API-Key", "someapikey")],
    )

    assert response.status_code == 404


def test_update_landing_bad_api_key(db, client):
    response = client.post(
        "/landings/update",
        json={"request_id": 1, "landed": True, "result": "sha123"},
        headers=[("API-Key", "wrongapikey")],
    )

    assert response.status_code == 403


def test_update_landing_no_api_key(db, client):
    response = client.post(
        "/landings/update", json={"request_id": 1, "landed": True, "result": "sha123"}
    )

    assert response.status_code == 400


def test_pingback_disabled(db, client, config):
    config["PINGBACK_ENABLED"] = "n"

    response = client.post(
        "/landings/update",
        json={"request_id": 1, "landed": True, "result": "sha123"},
        headers=[("API-Key", "someapikey")],
    )

    assert response.status_code == 403


def test_pingback_no_api_key_header(db, client, config):
    config["PINGBACK_ENABLED"] = "y"

    response = client.post(
        "/landings/update", json={"request_id": 1, "landed": True, "result": "sha123"}
    )

    assert response.status_code == 400


def test_pingback_incorrect_api_key(db, client, config):
    config["PINGBACK_ENABLED"] = "y"

    response = client.post(
        "/landings/update",
        json={"request_id": 1, "landed": True, "result": "sha123"},
        headers=[("API-Key", "thisisanincorrectapikey")],
    )

    assert response.status_code == 403


def _create_transplant(
    db,
    request_id=1,
    revision_id=1,
    diff_id=1,
    requester_email="tuser@example.com",
    tree="mozilla-central",
    repository_url="http://hg.test",
    status=TransplantStatus.submitted,
):
    transplant = Transplant(
        request_id=request_id,
        revision_to_diff_id={str(revision_id): diff_id},
        revision_order=[str(revision_id)],
        requester_email=requester_email,
        tree=tree,
        repository_url=repository_url,
        status=status,
    )
    db.session.add(transplant)
    db.session.commit()
    return transplant


PATCH_NORMAL_1 = r"""
# HG changeset patch
# User Test User <test@example.com>
# Date 0 0
#      Thu Jan 01 00:00:00 1970 +0000
# Diff Start Line 7
add another file.
diff --git a/test.txt b/test.txt
--- a/test.txt
+++ b/test.txt
@@ -1,1 +1,2 @@
 TEST
+adding another line
""".strip()

PATCH_NORMAL_2 = r"""
# HG changeset patch
# User Test User <test@example.com>
# Date 0 0
#      Thu Jan 01 00:00:00 1970 +0000
# Diff Start Line 7
add another file.
diff --git a/test.txt b/test.txt
--- a/test.txt
+++ b/test.txt
@@ -1,2 +1,3 @@
 TEST
 adding another line
+adding one more line
""".strip()

PATCH_PUSH_LOSER = r"""
# HG changeset patch
# User Test User <test@example.com>
# Date 0 0
#      Thu Jan 01 00:00:00 1970 +0000
# Fail HG Import LOSE_PUSH_RACE
# Diff Start Line 8
add another file.
diff --git a/test.txt b/test.txt
--- a/test.txt
+++ b/test.txt
@@ -1,1 +1,2 @@
 TEST
+adding one more line again
""".strip()

PATCH_FORMATTING_PATTERN = r"""
# HG changeset patch
# User Test User <test@example.com>
# Date 0 0
#      Thu Jan 01 00:00:00 1970 +0000
# Diff Start Line 7
add formatting config

diff --git a/.lando.ini b/.lando.ini
--- /dev/null
+++ b/.lando.ini
@@ -0,0 +1,3 @@
+[fix]
+fakefmt:pattern = set:**.txt
+fail:pattern = set:**.txt
""".strip()

PATCH_FORMATTED_1 = r"""
# HG changeset patch
# User Test User <test@example.com>
# Date 0 0
#      Thu Jan 01 00:00:00 1970 +0000
# Diff Start Line 7
add another file for formatting 1

diff --git a/test.txt b/test.txt
--- a/test.txt
+++ b/test.txt
@@ -1,1 +1,4 @@
 TEST
+
+
+adding another line
""".strip()

PATCH_FORMATTED_2 = r"""
# HG changeset patch
# User Test User <test@example.com>
# Date 0 0
#      Thu Jan 01 00:00:00 1970 +0000
# Diff Start Line 7
add another file for formatting 2

diff --git a/test.txt b/test.txt
--- a/test.txt
+++ b/test.txt
@@ -2,3 +2,4 @@ TEST

 
 adding another line
+add one more line
""".strip()  # noqa: W293

TESTTXT_FORMATTED_1 = b"""
TeSt


aDdInG AnOtHeR LiNe
""".lstrip()

TESTTXT_FORMATTED_2 = b"""
TeSt


aDdInG AnOtHeR LiNe
aDd oNe mOrE LiNe
""".lstrip()


def test_integrated_execute_job(
    app,
    db,
    mock_repo_config,
    hg_server,
    hg_clone,
    treestatusdouble,
    monkeypatch,
    create_revision,
):
    treestatus = treestatusdouble.get_treestatus_client()
    treestatusdouble.open_tree("mozilla-central")
    repo = Repo(
        tree="mozilla-central",
        url=hg_server,
        access_group=SCM_LEVEL_3,
        push_path=hg_server,
        pull_path=hg_server,
    )
    hgrepo = HgRepo(hg_clone.strpath)
    job = LandingJob(
        status=LandingJobStatus.IN_PROGRESS,
        requester_email="test@example.com",
        repository_name="mozilla-central",
        attempts=1,
    )

    db.session.add(job)
    db.session.commit()

    revision_1 = create_revision(PATCH_NORMAL_1, 1, status=RS.READY, landing_job=job.id)
    revision_2 = create_revision(PATCH_NORMAL_1, 2, status=RS.READY, landing_job=job.id)

    db.session.add(revision_1)
    db.session.add(revision_2)
    db.session.commit()

    db.session.add(RevisionLandingJob(landing_job_id=job.id, revision_id=revision_1.id))
    db.session.add(RevisionLandingJob(landing_job_id=job.id, revision_id=revision_2.id))
    db.session.commit()

    worker = LandingWorker(sleep_seconds=0.01)

    # Mock `phab_trigger_repo_update` so we can make sure that it was called.
    mock_trigger_update = mock.MagicMock()
    monkeypatch.setattr(
        "landoapi.workers.landing_worker.LandingWorker.phab_trigger_repo_update",
        mock_trigger_update,
    )

    assert worker.run_job(job, repo, hgrepo, treestatus)
    assert job.status == LandingJobStatus.LANDED
    assert len(job.landed_commit_id) == 40
    assert (
        mock_trigger_update.call_count == 1
    ), "Successful landing should trigger Phab repo update."


def test_lose_push_race(
    app, db, mock_repo_config, hg_server, hg_clone, treestatusdouble, create_revision
):
    treestatus = treestatusdouble.get_treestatus_client()
    treestatusdouble.open_tree("mozilla-central")
    repo = Repo(
        tree="mozilla-central",
        url=hg_server,
        access_group=SCM_LEVEL_3,
        push_path=hg_server,
        pull_path=hg_server,
    )
    hgrepo = HgRepo(hg_clone.strpath)
    job = LandingJob(
        id=1234,
        status=LandingJobStatus.IN_PROGRESS,
        requester_email="test@example.com",
        repository_name="mozilla-central",
        attempts=1,
    )
    db.session.add(job)
    db.session.commit()

    revision_1 = create_revision(
        PATCH_PUSH_LOSER, 1, status=RS.READY, landing_job=job.id
    )
    db.session.add(revision_1)
    db.session.commit()

    db.session.add(RevisionLandingJob(landing_job_id=job.id, revision_id=revision_1.id))
    db.session.commit()

    worker = LandingWorker(sleep_seconds=0)

    assert not worker.run_job(job, repo, hgrepo, treestatus)
    assert job.status == LandingJobStatus.DEFERRED


def test_failed_landing_job_notification(
    app,
    db,
    mock_repo_config,
    hg_server,
    hg_clone,
    treestatusdouble,
    monkeypatch,
    create_revision,
):
    """Ensure that a failed landings triggers a user notification."""
    treestatus = treestatusdouble.get_treestatus_client()
    treestatusdouble.open_tree("mozilla-central")
    repo = Repo(
        "mozilla-central", SCM_LEVEL_3, "", hg_server, hg_server, True, hg_server, False
    )
    hgrepo = HgRepo(hg_clone.strpath)

    job = LandingJob(
        status=LandingJobStatus.IN_PROGRESS,
        requester_email="test@example.com",
        repository_name="mozilla-central",
        attempts=1,
    )

    db.session.add(job)
    db.session.commit()

    revision_1 = create_revision(PATCH_NORMAL_1, 1, status=RS.READY, landing_job=job.id)
    revision_2 = create_revision(PATCH_NORMAL_1, 2, status=RS.READY, landing_job=job.id)

    db.session.add(revision_1)
    db.session.add(revision_2)
    db.session.commit()

    db.session.add(RevisionLandingJob(landing_job_id=job.id, revision_id=revision_1.id))
    db.session.add(RevisionLandingJob(landing_job_id=job.id, revision_id=revision_2.id))
    db.session.commit()

    worker = LandingWorker(sleep_seconds=0.01)

    # Mock `hgrepo.update_repo` so we can force a failed landing.
    mock_update_repo = mock.MagicMock()
    mock_update_repo.side_effect = Exception("Forcing a failed landing")
    monkeypatch.setattr(hgrepo, "update_repo", mock_update_repo)

    # Mock `notify_user_of_landing_failure` so we can make sure that it was called.
    mock_notify = mock.MagicMock()
    monkeypatch.setattr(
        "landoapi.workers.landing_worker.notify_user_of_landing_failure", mock_notify
    )

    assert worker.run_job(job, repo, hgrepo, treestatus)
    assert job.status == LandingJobStatus.FAILED
    assert mock_notify.call_count == 1


def test_landing_worker__extract_error_data():
    exception_message = textwrap.dedent(
        """\
    patching file toolkit/moz.configure
    Hunk #1 FAILED at 2075
    Hunk #2 FAILED at 2325
    Hunk #3 FAILED at 2340
    3 out of 3 hunks FAILED -- saving rejects to file toolkit/moz.configure.rej
    patching file moz.configure
    Hunk #1 FAILED at 239
    Hunk #2 FAILED at 250
    2 out of 2 hunks FAILED -- saving rejects to file moz.configure.rej
    patching file a/b/c.d
    Hunk #1 FAILED at 656
    1 out of 1 hunks FAILED -- saving rejects to file a/b/c.d.rej
    patching file d/e/f.g
    Hunk #1 FAILED at 6
    1 out of 1 hunks FAILED -- saving rejects to file d/e/f.g.rej
    patching file h/i/j.k
    Hunk #1 FAILED at 4
    1 out of 1 hunks FAILED -- saving rejects to file h/i/j.k.rej
    file G0fvb1RuMQxXNjs already exists
    1 out of 1 hunks FAILED -- saving rejects to file G0fvb1RuMQxXNjs.rej
    unable to find 'abc/def' for patching
    (use '--prefix' to apply patch relative to the current directory)
    1 out of 1 hunks FAILED -- saving rejects to file abc/def.rej
    patching file browser/locales/en-US/browser/browserContext.ftl
    Hunk #1 succeeded at 300 with fuzz 2 (offset -4 lines).
    abort: patch failed to apply"""
    )

    expected_failed_paths = [
        "toolkit/moz.configure",
        "moz.configure",
        "a/b/c.d",
        "d/e/f.g",
        "h/i/j.k",
        "G0fvb1RuMQxXNjs",
        "abc/def",
    ]

    expected_rejects_paths = [
        "toolkit/moz.configure.rej",
        "moz.configure.rej",
        "a/b/c.d.rej",
        "d/e/f.g.rej",
        "h/i/j.k.rej",
        "G0fvb1RuMQxXNjs.rej",
        "abc/def.rej",
    ]

    failed_paths, rejects_paths = LandingWorker.extract_error_data(exception_message)
    assert failed_paths == expected_failed_paths
    assert rejects_paths == expected_rejects_paths


def test_format_patch_success_unchanged(
    app,
    db,
    mock_repo_config,
    hg_server,
    hg_clone,
    treestatusdouble,
    monkeypatch,
    create_revision,
):
    """Tests automated formatting happy path where formatters made no changes."""
    treestatus = treestatusdouble.get_treestatus_client()
    treestatusdouble.open_tree("mozilla-central")
    repo = Repo(
        tree="mozilla-central",
        url=hg_server,
        push_path=hg_server,
        pull_path=hg_server,
        access_group=SCM_LEVEL_3,
        config_override={"fix.fakefmt:command": "cat"},
    )

    hgrepo = HgRepo(hg_clone.strpath, config=repo.config_override)

    job = LandingJob(
        status=LandingJobStatus.IN_PROGRESS,
        requester_email="test@example.com",
        repository_name="mozilla-central",
        attempts=1,
    )

    db.session.add(job)
    db.session.commit()

    revision_1 = create_revision(
        PATCH_FORMATTING_PATTERN, 1, status=RS.READY, landing_job=job.id
    )
    revision_2 = create_revision(
        PATCH_FORMATTED_1, 2, status=RS.READY, landing_job=job.id
    )
    revision_3 = create_revision(
        PATCH_FORMATTED_2, 3, status=RS.READY, landing_job=job.id
    )

    db.session.add(revision_1)
    db.session.add(revision_2)
    db.session.add(revision_3)
    db.session.commit()

    db.session.add(RevisionLandingJob(landing_job_id=job.id, revision_id=revision_1.id))
    db.session.add(RevisionLandingJob(landing_job_id=job.id, revision_id=revision_2.id))
    db.session.add(RevisionLandingJob(landing_job_id=job.id, revision_id=revision_3.id))
    db.session.commit()

    worker = LandingWorker(sleep_seconds=0.01)

    # Mock `phab_trigger_repo_update` so we can make sure that it was called.
    mock_trigger_update = mock.MagicMock()
    monkeypatch.setattr(
        "landoapi.workers.landing_worker.LandingWorker.phab_trigger_repo_update",
        mock_trigger_update,
    )

    assert worker.run_job(job, repo, hgrepo, treestatus)

    assert (
        job.status == LandingJobStatus.LANDED
    ), "Successful landing should set `LANDED` status."
    assert job.formatted_replacements is None
    assert (
        mock_trigger_update.call_count == 1
    ), "Successful landing should trigger Phab repo update."


def test_format_patch_success_changed(
    app,
    db,
    mock_repo_config,
    hg_server,
    hg_clone,
    treestatusdouble,
    monkeypatch,
    create_revision,
):
    """Tests automated formatting happy path where formatters made
    changes before landing.
    """
    treestatus = treestatusdouble.get_treestatus_client()
    treestatusdouble.open_tree("mozilla-central")
    repo = Repo(
        tree="mozilla-central",
        url=hg_server,
        push_path=hg_server,
        pull_path=hg_server,
        access_group=SCM_LEVEL_3,
        config_override={
            "fix.fakefmt:command": "python /app/tests/fake_formatter.py",
            "fix.fakefmt:linerange": "--lines={first}:{last}",
        },
    )

    hgrepo = HgRepo(hg_clone.strpath, config=repo.config_override)

    job = LandingJob(
        status=LandingJobStatus.IN_PROGRESS,
        requester_email="test@example.com",
        repository_name="mozilla-central",
        attempts=1,
    )

    db.session.add(job)
    db.session.commit()

    revision_1 = create_revision(
        PATCH_FORMATTING_PATTERN, 1, status=RS.READY, landing_job=job.id
    )
    revision_2 = create_revision(
        PATCH_FORMATTED_1, 2, status=RS.READY, landing_job=job.id
    )
    revision_3 = create_revision(
        PATCH_FORMATTED_2, 3, status=RS.READY, landing_job=job.id
    )

    db.session.add(revision_1)
    db.session.add(revision_2)
    db.session.add(revision_3)
    db.session.commit()

    db.session.add(RevisionLandingJob(landing_job_id=job.id, revision_id=revision_1.id))
    db.session.add(RevisionLandingJob(landing_job_id=job.id, revision_id=revision_2.id))
    db.session.add(RevisionLandingJob(landing_job_id=job.id, revision_id=revision_3.id))
    db.session.commit()

    worker = LandingWorker(sleep_seconds=0.01)

    # Mock `phab_trigger_repo_update` so we can make sure that it was called.
    mock_trigger_update = mock.MagicMock()
    monkeypatch.setattr(
        "landoapi.workers.landing_worker.LandingWorker.phab_trigger_repo_update",
        mock_trigger_update,
    )

    # The landed commit hashes affected by autoformat
    formatted_replacements = [
        "12be32a8a3ff283e0836b82be959fbd024cf271b",
        "15b05c609cf43b49e7360eaea4de938158d18c6a",
    ]

    assert worker.run_job(
        job, repo, hgrepo, treestatus
    ), "`run_job` should return `True` on a successful run."
    assert (
        job.status == LandingJobStatus.LANDED
    ), "Successful landing should set `LANDED` status."
    assert (
        job.formatted_replacements == formatted_replacements
    ), "Did not correctly save hashes of formatted revisions"
    assert (
        mock_trigger_update.call_count == 1
    ), "Successful landing should trigger Phab repo update."

    with hgrepo.for_push(job.requester_email):
        # Get repo root since `-R` does not change relative directory, so
        # we would need to pass the absolute path to `test.txt`
        repo_root = hgrepo.run_hg(["root"]).decode("utf-8").strip()

        # Get the content of `test.txt`
        rev2_content = hgrepo.run_hg(
            ["cat", "--cwd", repo_root, "-r", "tip^", "test.txt"]
        )
        rev3_content = hgrepo.run_hg(
            ["cat", "--cwd", repo_root, "-r", "tip", "test.txt"]
        )

        # Get the commit hashes
        nodes = (
            hgrepo.run_hg(["log", "-r", "tip^::tip", "-T", "{node}\n"])
            .decode("utf-8")
            .splitlines()
        )

    assert (
        rev2_content == TESTTXT_FORMATTED_1
    ), "`test.txt` is incorrect in base commit."
    assert rev3_content == TESTTXT_FORMATTED_2, "`test.txt` is incorrect in tip commit."

    assert all(
        replacement in nodes for replacement in job.formatted_replacements
    ), "Values in `formatted_replacements` field should be in the landed hashes."


def test_format_patch_fail(
    app,
    db,
    mock_repo_config,
    hg_server,
    hg_clone,
    treestatusdouble,
    monkeypatch,
    create_revision,
):
    """Tests automated formatting failures before landing."""
    treestatus = treestatusdouble.get_treestatus_client()
    treestatusdouble.open_tree("mozilla-central")
    repo = Repo(
        tree="mozilla-central",
        access_group=SCM_LEVEL_3,
        url=hg_server,
        push_path=hg_server,
        pull_path=hg_server,
        config_override={
            # Force failure by setting a formatter that returns exit code 1
            "fix.fail:command": "exit 1"
        },
    )

    hgrepo = HgRepo(hg_clone.strpath, config=repo.config_override)

    job = LandingJob(
        status=LandingJobStatus.IN_PROGRESS,
        requester_email="test@example.com",
        repository_name="mozilla-central",
        attempts=1,
    )

    db.session.add(job)
    db.session.commit()

    revision_1 = create_revision(
        PATCH_FORMATTING_PATTERN, 1, status=RS.READY, landing_job=job.id
    )
    revision_2 = create_revision(PATCH_NORMAL_1, 2, status=RS.READY, landing_job=job.id)
    revision_3 = create_revision(PATCH_NORMAL_1, 3, status=RS.READY, landing_job=job.id)

    db.session.add(revision_1)
    db.session.add(revision_2)
    db.session.add(revision_3)
    db.session.commit()

    db.session.add(RevisionLandingJob(landing_job_id=job.id, revision_id=revision_1.id))
    db.session.add(RevisionLandingJob(landing_job_id=job.id, revision_id=revision_2.id))
    db.session.add(RevisionLandingJob(landing_job_id=job.id, revision_id=revision_3.id))
    db.session.commit()

    worker = LandingWorker(sleep_seconds=0.01)

    # Mock `notify_user_of_landing_failure` so we can make sure that it was called.
    mock_notify = mock.MagicMock()
    monkeypatch.setattr(
        "landoapi.workers.landing_worker.notify_user_of_landing_failure", mock_notify
    )

    assert not worker.run_job(
        job, repo, hgrepo, treestatus
    ), "`run_job` should return `False` when autoformatting fails."
    assert (
        job.status == LandingJobStatus.FAILED
    ), "Failed autoformatting should set `FAILED` job status."
    assert (
        mock_notify.call_count == 1
    ), "User should be notified their landing was unsuccessful due to autoformat."


def test_format_patch_no_landoini(
    app,
    db,
    mock_repo_config,
    hg_server,
    hg_clone,
    treestatusdouble,
    monkeypatch,
    create_revision,
):
    """Tests behaviour of Lando when the `.lando.ini` file is missing."""
    treestatus = treestatusdouble.get_treestatus_client()
    treestatusdouble.open_tree("mozilla-central")
    repo = Repo(
        tree="mozilla-central",
        access_group=SCM_LEVEL_3,
        url=hg_server,
        push_path=hg_server,
        pull_path=hg_server,
        config_override={
            # If the `.lando.ini` file existed, this formatter would run and fail
            "fix.fail:command": "exit 1"
        },
    )

    hgrepo = HgRepo(hg_clone.strpath, config=repo.config_override)

    job = LandingJob(
        status=LandingJobStatus.IN_PROGRESS,
        requester_email="test@example.com",
        repository_name="mozilla-central",
        attempts=1,
    )

    db.session.add(job)
    db.session.commit()

    revision_1 = create_revision(PATCH_NORMAL_1, 1, status=RS.READY, landing_job=job.id)
    revision_2 = create_revision(PATCH_NORMAL_1, 2, status=RS.READY, landing_job=job.id)

    db.session.add(revision_1)
    db.session.add(revision_2)
    db.session.commit()

    db.session.add(RevisionLandingJob(landing_job_id=job.id, revision_id=revision_1.id))
    db.session.add(RevisionLandingJob(landing_job_id=job.id, revision_id=revision_2.id))
    db.session.commit()

    worker = LandingWorker(sleep_seconds=0.01)

    # Mock `phab_trigger_repo_update` so we can make sure that it was called.
    mock_trigger_update = mock.MagicMock()
    monkeypatch.setattr(
        "landoapi.workers.landing_worker.LandingWorker.phab_trigger_repo_update",
        mock_trigger_update,
    )

    # Mock `notify_user_of_landing_failure` so we can make sure that it was called.
    mock_notify = mock.MagicMock()
    monkeypatch.setattr(
        "landoapi.workers.landing_worker.notify_user_of_landing_failure", mock_notify
    )

    assert worker.run_job(job, repo, hgrepo, treestatus)
    assert (
        job.status == LandingJobStatus.LANDED
    ), "Missing `.lando.ini` should not inhibit landing."
    assert (
        mock_notify.call_count == 0
    ), "Should not notify user of landing failure due to `.lando.ini` missing."
    assert (
        mock_trigger_update.call_count == 1
    ), "Successful landing should trigger Phab repo update."
