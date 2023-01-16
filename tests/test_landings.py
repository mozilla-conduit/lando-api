# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import io

import pytest
import textwrap
import unittest.mock as mock

from landoapi import patches
from landoapi.hg import AUTOFORMAT_COMMIT_MESSAGE, HgRepo
from landoapi.landing_worker import LandingWorker
from landoapi.models.landing_job import LandingJob, LandingJobStatus
from landoapi.models.transplant import Transplant, TransplantStatus
from landoapi.repos import Repo, SCM_LEVEL_3


@pytest.fixture
def upload_patch():
    """A fixture that fake uploads a patch"""

    def _upload_patch(number, patch=PATCH_NORMAL_1):
        patches.upload(
            number,
            number,
            patch,
            "landoapi.test.bucket",
            aws_access_key=None,
            aws_secret_key=None,
        )

    return _upload_patch


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

PATCH_NORMAL_3 = r"""
# HG changeset patch
# User Test User <test@example.com>
# Date 0 0
#      Thu Jan 01 00:00:00 1970 +0000
# Diff Start Line 7
add another file.
diff --git a/test.txt b/test.txt
deleted file mode 100644
--- a/test.txt
+++ /dev/null
@@ -1,1 +0,0 @@
-TEST
diff --git a/blah.txt b/blah.txt
new file mode 100644
--- /dev/null
+++ b/blah.txt
@@ -0,0 +1,1 @@
+TEST
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

PATCH_FORMATTING_PATTERN_PASS = r"""
# HG changeset patch
# User Test User <test@example.com>
# Date 0 0
#      Thu Jan 01 00:00:00 1970 +0000
# Diff Start Line 7
add formatting config

diff --git a/.lando.ini b/.lando.ini
new file mode 100644
--- /dev/null
+++ b/.lando.ini
@@ -0,0 +1,3 @@
+[autoformat]
+enabled = True
+
diff --git a/mach b/mach
new file mode 100755
--- /dev/null
+++ b/mach
@@ -0,0 +1,30 @@
+#!/usr/bin/env python3
+# This Source Code Form is subject to the terms of the Mozilla Public
+# License, v. 2.0. If a copy of the MPL was not distributed with this
+# file, You can obtain one at http://mozilla.org/MPL/2.0/.
+
+# Fake formatter that rewrites text to mOcKiNg cAse
+
+import pathlib
+import sys
+
+HERE = pathlib.Path(__file__).resolve().parent
+
+def split_chars(string) -> list:
+    return [char for char in string]
+
+
+if __name__ == "__main__":
+    testtxt = HERE / "test.txt"
+    if not testtxt.exists():
+        sys.exit(0)
+    with testtxt.open() as f:
+        stdin_content = f.read()
+    stdout_content = []
+
+    for i, word in enumerate(split_chars(stdin_content)):
+        stdout_content.append(word.upper() if i % 2 == 0 else word.lower())
+
+    with testtxt.open("w") as f:
+        f.write("".join(stdout_content))
+    sys.exit(0)

""".strip()

PATCH_FORMATTING_PATTERN_FAIL = r"""
# HG changeset patch
# User Test User <test@example.com>
# Date 0 0
#      Thu Jan 01 00:00:00 1970 +0000
# Diff Start Line 7
add formatting config

diff --git a/.lando.ini b/.lando.ini
new file mode 100644
--- /dev/null
+++ b/.lando.ini
@@ -0,0 +1,3 @@
+[autoformat]
+enabled = True
+
diff --git a/mach b/mach
new file mode 100755
--- /dev/null
+++ b/mach
@@ -0,0 +1,9 @@
+#!/usr/bin/env python3
+# This Source Code Form is subject to the terms of the Mozilla Public
+# License, v. 2.0. If a copy of the MPL was not distributed with this
+# file, You can obtain one at http://mozilla.org/MPL/2.0/.
+
+# Fake formatter that fails to run.
+import sys
+sys.exit("MACH FAILED")
+

""".strip()

PATCH_FORMATTED_1 = r"""
# HG changeset patch
# User Test User <test@example.com>
# Date 0 0
#      Thu Jan 01 00:00:00 1970 +0000
# Diff Start Line 7
bug 123: add another file for formatting 1

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
    s3,
    mock_repo_config,
    hg_server,
    hg_clone,
    treestatusdouble,
    monkeypatch,
    upload_patch,
):
    treestatus = treestatusdouble.get_treestatus_client()
    treestatusdouble.open_tree("mozilla-central")
    repo = Repo(
        tree="mozilla-central",
        url=hg_server,
        access_group=SCM_LEVEL_3,
        push_path=hg_server,
        pull_path=hg_server,
        legacy_transplant=False,
    )
    hgrepo = HgRepo(hg_clone.strpath)
    upload_patch(1)
    upload_patch(2)
    job = LandingJob(
        status=LandingJobStatus.IN_PROGRESS,
        requester_email="test@example.com",
        repository_name="mozilla-central",
        revision_to_diff_id={"1": 1, "2": 2},
        revision_order=["1", "2"],
        attempts=1,
    )

    worker = LandingWorker(sleep_seconds=0.01)

    # Mock `phab_trigger_repo_update` so we can make sure that it was called.
    mock_trigger_update = mock.MagicMock()
    monkeypatch.setattr(
        "landoapi.landing_worker.LandingWorker.phab_trigger_repo_update",
        mock_trigger_update,
    )

    assert worker.run_job(job, repo, hgrepo, treestatus, "landoapi.test.bucket")
    assert job.status == LandingJobStatus.LANDED
    assert len(job.landed_commit_id) == 40
    assert (
        mock_trigger_update.call_count == 1
    ), "Successful landing should trigger Phab repo update."


def test_lose_push_race(
    app, db, s3, mock_repo_config, hg_server, hg_clone, treestatusdouble, upload_patch
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
    upload_patch(1, patch=PATCH_PUSH_LOSER)
    job = LandingJob(
        id=1234,
        status=LandingJobStatus.IN_PROGRESS,
        requester_email="test@example.com",
        repository_name="mozilla-central",
        revision_to_diff_id={"1": 1},
        revision_order=["1"],
        attempts=1,
    )

    worker = LandingWorker(sleep_seconds=0)

    assert not worker.run_job(job, repo, hgrepo, treestatus, "landoapi.test.bucket")
    assert job.status == LandingJobStatus.DEFERRED


def test_failed_landing_job_notification(
    app,
    db,
    s3,
    mock_repo_config,
    hg_server,
    hg_clone,
    treestatusdouble,
    monkeypatch,
    upload_patch,
):
    """Ensure that a failed landings triggers a user notification."""
    treestatus = treestatusdouble.get_treestatus_client()
    treestatusdouble.open_tree("mozilla-central")
    repo = Repo(
        "mozilla-central", SCM_LEVEL_3, "", hg_server, hg_server, True, hg_server, False
    )
    hgrepo = HgRepo(hg_clone.strpath)
    upload_patch(1)
    upload_patch(2)
    job = LandingJob(
        status=LandingJobStatus.IN_PROGRESS,
        requester_email="test@example.com",
        repository_name="mozilla-central",
        revision_to_diff_id={"1": 1, "2": 2},
        revision_order=["1", "2"],
        attempts=1,
    )

    worker = LandingWorker(sleep_seconds=0.01)

    # Mock `hgrepo.update_repo` so we can force a failed landing.
    mock_update_repo = mock.MagicMock()
    mock_update_repo.side_effect = Exception("Forcing a failed landing")
    monkeypatch.setattr(hgrepo, "update_repo", mock_update_repo)

    # Mock `notify_user_of_landing_failure` so we can make sure that it was called.
    mock_notify = mock.MagicMock()
    monkeypatch.setattr(
        "landoapi.landing_worker.notify_user_of_landing_failure", mock_notify
    )

    assert worker.run_job(job, repo, hgrepo, treestatus, "landoapi.test.bucket")
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
    s3,
    mock_repo_config,
    hg_server,
    hg_clone,
    treestatusdouble,
    monkeypatch,
    upload_patch,
):
    """Tests automated formatting happy path where formatters made no changes."""
    tree = "mozilla-central"
    treestatus = treestatusdouble.get_treestatus_client()
    treestatusdouble.open_tree(tree)
    repo = Repo(
        tree=tree,
        url=hg_server,
        push_path=hg_server,
        pull_path=hg_server,
        access_group=SCM_LEVEL_3,
        autoformat_enabled=True,
    )

    hgrepo = HgRepo(hg_clone.strpath)

    upload_patch(1, patch=PATCH_FORMATTING_PATTERN_PASS)
    upload_patch(2, patch=PATCH_NORMAL_3)
    job = LandingJob(
        status=LandingJobStatus.IN_PROGRESS,
        requester_email="test@example.com",
        repository_name=tree,
        revision_to_diff_id={"1": 1, "2": 2},
        revision_order=["1", "2"],
        attempts=1,
    )

    worker = LandingWorker(sleep_seconds=0.01)

    # Mock `phab_trigger_repo_update` so we can make sure that it was called.
    mock_trigger_update = mock.MagicMock()
    monkeypatch.setattr(
        "landoapi.landing_worker.LandingWorker.phab_trigger_repo_update",
        mock_trigger_update,
    )

    assert worker.run_job(job, repo, hgrepo, treestatus, "landoapi.test.bucket")
    assert (
        job.status == LandingJobStatus.LANDED
    ), "Successful landing should set `LANDED` status."
    assert (
        mock_trigger_update.call_count == 1
    ), "Successful landing should trigger Phab repo update."
    assert (
        job.formatted_replacements is None
    ), "Autoformat making no changes should leave `formatted_replacements` empty."


def test_format_single_success_changed(
    app,
    db,
    s3,
    mock_repo_config,
    hg_server,
    hg_clone,
    treestatusdouble,
    monkeypatch,
    upload_patch,
):
    """Test formatting a single commit via amending."""
    tree = "mozilla-central"
    treestatus = treestatusdouble.get_treestatus_client()
    treestatusdouble.open_tree(tree)
    repo = Repo(
        tree=tree,
        url=hg_server,
        push_path=hg_server,
        pull_path=hg_server,
        access_group=SCM_LEVEL_3,
        autoformat_enabled=True,
    )

    # Push the `mach` formatting patch.
    hgrepo = HgRepo(hg_clone.strpath)
    with hgrepo.for_push("test@example.com"):
        hgrepo.apply_patch(io.BytesIO(PATCH_FORMATTING_PATTERN_PASS.encode("utf-8")))
        hgrepo.push(repo.push_path)
        pre_landing_tip = hgrepo.run_hg(["log", "-r", "tip", "-T", "{node}"]).decode(
            "utf-8"
        )

    # Upload a patch for formatting.
    upload_patch(2, patch=PATCH_FORMATTED_1)
    job = LandingJob(
        status=LandingJobStatus.IN_PROGRESS,
        requester_email="test@example.com",
        repository_name=tree,
        revision_to_diff_id={"2": 2},
        revision_order=["2"],
        attempts=1,
    )

    worker = LandingWorker(sleep_seconds=0.01)

    # Mock `phab_trigger_repo_update` so we can make sure that it was called.
    mock_trigger_update = mock.MagicMock()
    monkeypatch.setattr(
        "landoapi.landing_worker.LandingWorker.phab_trigger_repo_update",
        mock_trigger_update,
    )

    assert worker.run_job(
        job, repo, hgrepo, treestatus, "landoapi.test.bucket"
    ), "`run_job` should return `True` on a successful run."
    assert (
        job.status == LandingJobStatus.LANDED
    ), "Successful landing should set `LANDED` status."
    assert (
        mock_trigger_update.call_count == 1
    ), "Successful landing should trigger Phab repo update."

    with hgrepo.for_push(job.requester_email):
        repo_root = hgrepo.run_hg(["root"]).decode("utf-8").strip()

        # Get the commit message.
        desc = hgrepo.run_hg(["log", "-r", "tip", "-T", "{desc}"]).decode("utf-8")

        # Get the content of the file after autoformatting.
        tip_content = hgrepo.run_hg(
            ["cat", "--cwd", repo_root, "-r", "tip", "test.txt"]
        )

        # Get the hash behind the tip commit.
        hash_behind_current_tip = hgrepo.run_hg(
            ["log", "-r", "tip^", "-T", "{node}"]
        ).decode("utf-8")

    assert tip_content == TESTTXT_FORMATTED_1, "`test.txt` is incorrect in base commit."

    assert (
        desc == "bug 123: add another file for formatting 1"
    ), "Autoformat via amend should not change commit message."

    assert (
        hash_behind_current_tip == pre_landing_tip
    ), "Autoformat via amending should only land a single commit."


def test_format_stack_success_changed(
    app,
    db,
    s3,
    mock_repo_config,
    hg_server,
    hg_clone,
    treestatusdouble,
    monkeypatch,
    upload_patch,
):
    """Test formatting a stack via an autoformat tip commit."""
    tree = "mozilla-central"
    treestatus = treestatusdouble.get_treestatus_client()
    treestatusdouble.open_tree(tree)
    repo = Repo(
        tree=tree,
        url=hg_server,
        push_path=hg_server,
        pull_path=hg_server,
        access_group=SCM_LEVEL_3,
        autoformat_enabled=True,
    )

    hgrepo = HgRepo(hg_clone.strpath)

    upload_patch(1, patch=PATCH_FORMATTING_PATTERN_PASS)
    upload_patch(2, patch=PATCH_FORMATTED_1)
    upload_patch(3, patch=PATCH_FORMATTED_2)
    job = LandingJob(
        status=LandingJobStatus.IN_PROGRESS,
        requester_email="test@example.com",
        repository_name=tree,
        revision_to_diff_id={"1": 1, "2": 2, "3": 3},
        revision_order=["1", "2", "3"],
        attempts=1,
    )

    worker = LandingWorker(sleep_seconds=0.01)

    # Mock `phab_trigger_repo_update` so we can make sure that it was called.
    mock_trigger_update = mock.MagicMock()
    monkeypatch.setattr(
        "landoapi.landing_worker.LandingWorker.phab_trigger_repo_update",
        mock_trigger_update,
    )

    assert worker.run_job(
        job, repo, hgrepo, treestatus, "landoapi.test.bucket"
    ), "`run_job` should return `True` on a successful run."
    assert (
        job.status == LandingJobStatus.LANDED
    ), "Successful landing should set `LANDED` status."
    assert (
        mock_trigger_update.call_count == 1
    ), "Successful landing should trigger Phab repo update."

    with hgrepo.for_push(job.requester_email):
        repo_root = hgrepo.run_hg(["root"]).decode("utf-8").strip()

        # Get the commit message.
        desc = hgrepo.run_hg(["log", "-r", "tip", "-T", "{desc}"]).decode("utf-8")

        # Get the content of the file after autoformatting.
        rev3_content = hgrepo.run_hg(
            ["cat", "--cwd", repo_root, "-r", "tip", "test.txt"]
        )

    assert (
        rev3_content == TESTTXT_FORMATTED_2
    ), "`test.txt` is incorrect in base commit."

    assert (
        "# ignore-this-changeset" in desc
    ), "Commit message for autoformat commit should contain `# ignore-this-changeset`."

    assert desc == AUTOFORMAT_COMMIT_MESSAGE.format(
        bugs="Bug 123"
    ), "Autoformat commit has incorrect commit message."


def test_format_patch_fail(
    app,
    db,
    s3,
    mock_repo_config,
    hg_server,
    hg_clone,
    treestatusdouble,
    monkeypatch,
    upload_patch,
):
    """Tests automated formatting failures before landing."""
    tree = "mozilla-central"
    treestatus = treestatusdouble.get_treestatus_client()
    treestatusdouble.open_tree(tree)
    repo = Repo(
        tree=tree,
        access_group=SCM_LEVEL_3,
        url=hg_server,
        push_path=hg_server,
        pull_path=hg_server,
        autoformat_enabled=True,
    )

    hgrepo = HgRepo(hg_clone.strpath)

    upload_patch(1, patch=PATCH_FORMATTING_PATTERN_FAIL)
    upload_patch(2)
    upload_patch(3)
    job = LandingJob(
        status=LandingJobStatus.IN_PROGRESS,
        requester_email="test@example.com",
        repository_name=tree,
        revision_to_diff_id={"1": 1, "2": 2, "3": 3},
        revision_order=["1", "2", "3"],
        attempts=1,
    )

    worker = LandingWorker(sleep_seconds=0.01)

    # Mock `notify_user_of_landing_failure` so we can make sure that it was called.
    mock_notify = mock.MagicMock()
    monkeypatch.setattr(
        "landoapi.landing_worker.notify_user_of_landing_failure", mock_notify
    )

    assert not worker.run_job(
        job, repo, hgrepo, treestatus, "landoapi.test.bucket"
    ), "`run_job` should return `False` when autoformatting fails."
    assert (
        job.status == LandingJobStatus.FAILED
    ), "Failed autoformatting should set `FAILED` job status."
    assert (
        "Lando failed to format your patch" in job.error
    ), "Error message is not set to show autoformat caused landing failure."
    assert (
        mock_notify.call_count == 1
    ), "User should be notified their landing was unsuccessful due to autoformat."


def test_format_patch_no_landoini(
    app,
    db,
    s3,
    mock_repo_config,
    hg_server,
    hg_clone,
    treestatusdouble,
    monkeypatch,
    upload_patch,
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
        autoformat_enabled=True,
    )

    hgrepo = HgRepo(hg_clone.strpath)

    upload_patch(1)
    upload_patch(2)
    job = LandingJob(
        status=LandingJobStatus.IN_PROGRESS,
        requester_email="test@example.com",
        repository_name="mozilla-central",
        revision_to_diff_id={"1": 1, "2": 2},
        revision_order=["1", "2"],
        attempts=1,
    )

    worker = LandingWorker(sleep_seconds=0.01)

    # Mock `phab_trigger_repo_update` so we can make sure that it was called.
    mock_trigger_update = mock.MagicMock()
    monkeypatch.setattr(
        "landoapi.landing_worker.LandingWorker.phab_trigger_repo_update",
        mock_trigger_update,
    )

    # Mock `notify_user_of_landing_failure` so we can make sure that it was called.
    mock_notify = mock.MagicMock()
    monkeypatch.setattr(
        "landoapi.landing_worker.notify_user_of_landing_failure", mock_notify
    )

    assert worker.run_job(job, repo, hgrepo, treestatus, "landoapi.test.bucket")
    assert (
        job.status == LandingJobStatus.LANDED
    ), "Missing `.lando.ini` should not inhibit landing."
    assert (
        mock_notify.call_count == 0
    ), "Should not notify user of landing failure due to `.lando.ini` missing."
    assert (
        mock_trigger_update.call_count == 1
    ), "Successful landing should trigger Phab repo update."
