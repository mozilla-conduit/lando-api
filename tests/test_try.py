# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import base64

import pytest

from landoapi.hg import HgRepo
from landoapi.hgexports import (
    get_timestamp_from_git_date_header,
    parse_git_author_information,
)
from landoapi.models.landing_job import LandingJob, LandingJobStatus
from landoapi.repos import SCM_LEVEL_1, Repo
from landoapi.workers.landing_worker import LandingWorker

PATCH_DIFF = rb"""
diff --git a/test.txt b/test.txt
--- a/test.txt
+++ b/test.txt
@@ -1,1 +1,2 @@
 TEST
+adding another line
""".lstrip()

PATCH_WITHOUT_STARTLINE = rb"""
# HG changeset patch
# User Test User <test@example.com>
# Date 0 0
#      Thu Jan 01 00:00:00 1970 +0000
add another file.
diff --git a/test.txt b/test.txt
--- a/test.txt
+++ b/test.txt
@@ -1,1 +1,2 @@
 TEST
+adding another line
""".lstrip()

GIT_PATCH = rb"""From 0f5a3c99e12c1e9b0e81bed245fe537961f89e57 Mon Sep 17 00:00:00 2001
From: Connor Sheehan <sheehan@mozilla.com>
Date: Wed, 6 Jul 2022 16:36:09 -0400
Subject: [PATCH] add another file

add another file to the repo.
---
 landoui/errorhandlers.py | 8 +
 1 file changed, 1 insertions(+), 0 deletion(-)

diff --git a/test.txt b/test.txt
--- a/test.txt
+++ b/test.txt
@@ -1,1 +1,2 @@
 TEST
+adding another line
--
2.31.1
"""


def test_get_timestamp_from_date():
    assert (
        get_timestamp_from_git_date_header("Wed, 6 Jul 2022 16:36:09 -0400")
        == "1657139769"
    ), "Timestamp from `git format-patch` should properly convert to `str`."


def test_parse_git_author_information_well_formed():
    assert parse_git_author_information("User Name <user@example.com>") == (
        "User Name",
        "user@example.com",
    ), "Name and email information should be parsed into separate strings."


def test_parse_git_author_information_no_email():
    assert parse_git_author_information("ffxbld") == (
        "ffxbld",
        "",
    ), "Name without email address should return the username and empty email."


def test_try_api_requires_data(db, client, auth0_mock, mocked_repo_config):
    try_push_json = {
        "base_commit": "abc",
        "patch_format": "hgexport",
        "patches": [],
    }
    response = client.post(
        "/try/patches", json=try_push_json, headers=auth0_mock.mock_headers
    )
    assert (
        response.status_code == 400
    ), "Try push without 40-character base commit should return 400."

    try_push_json["base_commit"] = "abcabcabcaabcabcabcaabcabcabcaabcabcabca"
    response = client.post(
        "/try/patches", json=try_push_json, headers=auth0_mock.mock_headers
    )
    assert response.status_code == 400, "Try push without patches should return 400."


def test_try_api_patch_decode_error(
    app,
    db,
    hg_server,
    hg_clone,
    new_treestatus_tree,
    client,
    auth0_mock,
    mocked_repo_config,
):
    """Test when a patch can't be decoded."""
    new_treestatus_tree(tree="mozilla-central", status="open")

    try_push_json = {
        # The only node in the test repo.
        "base_commit": "0da79df0ffff88e0ad6fa3e27508bcf5b2f2cec4",
        "patch_format": "hgexport",
        "patches": ["x!!`"],
    }
    response = client.post(
        "/try/patches", json=try_push_json, headers=auth0_mock.mock_headers
    )
    assert response.status_code == 400, "Improperly encoded patch should return 400."
    assert (
        response.json["title"] == "Patch decoding error."
    ), "Response should indicate the patch could not be decoded."


@pytest.mark.parametrize(
    "patch_format,patch_content",
    [
        ("hgexport", GIT_PATCH),
        ("git-format-patch", PATCH_WITHOUT_STARTLINE),
    ],
)
def test_try_api_patch_format_mismatch(
    app,
    db,
    hg_server,
    hg_clone,
    new_treestatus_tree,
    client,
    auth0_mock,
    mocked_repo_config,
    patch_format,
    patch_content,
):
    """Test what happens when a patch does not match the passed format."""
    new_treestatus_tree(tree="mozilla-central", status="open")

    try_push_json = {
        # The only node in the test repo.
        "base_commit": "0da79df0ffff88e0ad6fa3e27508bcf5b2f2cec4",
        "patch_format": patch_format,
        "patches": [
            base64.b64encode(patch_content).decode("ascii"),
        ],
    }
    response = client.post(
        "/try/patches", json=try_push_json, headers=auth0_mock.mock_headers
    )
    assert (
        response.status_code == 400
    ), "A patch which does not match the passed format should return 400."
    assert (
        response.json["title"] == "Improper patch format."
    ), "Response should indicate the patch could not be decoded."


SYMLINK_PATCH = rb"""
From 751ad4b6ba7299815974d200e34832a007a4b4c0 Mon Sep 17 00:00:00 2001
From: Connor Sheehan <cosheehan@mozilla.com>
Date: Wed, 8 May 2024 13:32:11 -0400
Subject: [PATCH] add regular file and symlink file

---
 blahfile_real    | 1 +
 blahfile_symlink | 1 +
 2 files changed, 2 insertions(+)
 create mode 100644 blahfile_real
 create mode 120000 blahfile_symlink

diff --git a/blahfile_real b/blahfile_real
new file mode 100644
index 0000000..907b308
--- /dev/null
+++ b/blahfile_real
@@ -0,0 +1 @@
+blah
diff --git a/blahfile_symlink b/blahfile_symlink
new file mode 120000
index 0000000..55faaf5
--- /dev/null
+++ b/blahfile_symlink
@@ -0,0 +1 @@
+/home/sheehan/blahfile
\ No newline at end of file
--
2.45.1

""".lstrip()

TRY_TASK_CONFIG_PATCH = rb"""
From 888efb4b038a85a8788f25dbb69ff03f0fd58dce Mon Sep 17 00:00:00 2001
From: Connor Sheehan <cosheehan@mozilla.com>
Date: Wed, 8 May 2024 14:47:10 -0400
Subject: [PATCH] add try task config

---
 blah.json            | 1 +
 try_task_config.json | 1 +
 2 files changed, 2 insertions(+)
 create mode 100644 blah.json
 create mode 100644 try_task_config.json

diff --git a/blah.json b/blah.json
new file mode 100644
index 0000000..663cbc2
--- /dev/null
+++ b/blah.json
@@ -0,0 +1 @@
+{"123":"456"}
diff --git a/try_task_config.json b/try_task_config.json
new file mode 100644
index 0000000..e44d36d
--- /dev/null
+++ b/try_task_config.json
@@ -0,0 +1 @@
+{"env": {"TRY_SELECTOR": "fuzzy"}, "version": 1, "tasks": ["source-test-cram-tryselect"]}
--
2.45.1

""".lstrip()


def test_symlink_diff_inspect(
    app,
    db,
    hg_server,
    hg_clone,
    new_treestatus_tree,
    client,
    auth0_mock,
    mocked_repo_config,
):
    try_push_json = {
        # The only node in the test repo.
        "base_commit": "0da79df0ffff88e0ad6fa3e27508bcf5b2f2cec4",
        "patch_format": "git-format-patch",
        "patches": [
            base64.b64encode(SYMLINK_PATCH).decode("ascii"),
        ],
    }

    response = client.post(
        "/try/patches", json=try_push_json, headers=auth0_mock.mock_headers
    )
    assert (
        response.status_code == 400
    ), "Try push which fails diff checks should return 400."

    assert response.json["title"] == "Errors found in pre-submission patch checks."
    assert response.json["detail"] == (
        "Patch failed checks:\n\n"
        "  - Revision introduces symlinks in the files `blahfile_symlink`."
    ), "Details message should indicate an introduced symlink."


def test_try_task_config_diff_inspect(
    app,
    db,
    hg_server,
    hg_clone,
    new_treestatus_tree,
    client,
    auth0_mock,
    mocked_repo_config,
):
    try_push_json = {
        # The only node in the test repo.
        "base_commit": "0da79df0ffff88e0ad6fa3e27508bcf5b2f2cec4",
        "patch_format": "git-format-patch",
        "patches": [
            base64.b64encode(TRY_TASK_CONFIG_PATCH).decode("ascii"),
        ],
    }

    response = client.post(
        "/try/patches", json=try_push_json, headers=auth0_mock.mock_headers
    )
    assert (
        response.status_code == 201
    ), "Try push with a `try_task_config.json` should be accepted."


def test_try_api_unknown_patch_format(
    app,
    db,
    hg_server,
    hg_clone,
    new_treestatus_tree,
    client,
    auth0_mock,
    mocked_repo_config,
):
    """Test when `patch_format` isn't one of the accepted values."""
    new_treestatus_tree(tree="mozilla-central", status="open")

    try_push_json = {
        # The only node in the test repo.
        "base_commit": "0da79df0ffff88e0ad6fa3e27508bcf5b2f2cec4",
        "patch_format": "blah",
        "patches": [
            base64.b64encode(PATCH_WITHOUT_STARTLINE).decode("ascii"),
        ],
    }
    response = client.post(
        "/try/patches", json=try_push_json, headers=auth0_mock.mock_headers
    )
    assert (
        response.status_code == 400
    ), "Unknown `patch_format` value should return 400."


def test_try_api_success_hgexport(
    app,
    db,
    hg_server,
    hg_clone,
    new_treestatus_tree,
    client,
    auth0_mock,
    mocked_repo_config,
):
    new_treestatus_tree(tree="mozilla-central", status="open")

    try_push_json = {
        # The only node in the test repo.
        "base_commit": "0da79df0ffff88e0ad6fa3e27508bcf5b2f2cec4",
        "patch_format": "hgexport",
        "patches": [
            base64.b64encode(PATCH_WITHOUT_STARTLINE).decode("ascii"),
        ],
    }
    response = client.post(
        "/try/patches", json=try_push_json, headers=auth0_mock.mock_headers
    )
    assert response.status_code == 201, "Successful try push should return 201."
    assert (
        "id" in response.json
    ), "Response should include the ID of the new landing job."

    queue_items = LandingJob.job_queue_query(
        repositories=["try"], grace_seconds=0
    ).all()
    assert len(queue_items) == 1, "Try push should have created 1 landing job."

    # Run the landing job.
    job = queue_items[0]

    repo = Repo(
        tree="try",
        url=hg_server,
        access_group=SCM_LEVEL_1,
        push_path=hg_server,
        pull_path=hg_server,
        short_name="try",
        is_phabricator_repo=False,
        force_push=True,
    )

    worker = LandingWorker(sleep_seconds=0.01)
    hgrepo = HgRepo(hg_clone.strpath)

    assert worker.run_job(job, repo, hgrepo)
    assert job.status == LandingJobStatus.LANDED
    assert len(job.landed_commit_id) == 40
    assert (
        job.target_commit_hash == "0da79df0ffff88e0ad6fa3e27508bcf5b2f2cec4"
    ), "Target changeset should match the passed value."

    # Test the revision content matches expected.
    assert len(job.revisions) == 1, "Job should have landed a single revision."
    revision = job.revisions[0]
    assert (
        revision.patch_data["author_name"] == "Test User"
    ), "Patch author should be parsed from `User` header."
    assert (
        revision.patch_data["author_email"] == "test@example.com"
    ), "Email address should be parsed from `User` header."
    assert revision.patch_data["commit_message"] == (
        "add another file."
    ), "Commit message should be parsed from patch."
    assert (
        revision.patch_data["timestamp"] == "0"
    ), "Timestamp should be parsed from `Date` header."
    assert revision.patch_bytes == (
        b"# HG changeset patch\n"
        b"# User Test User <test@example.com>\n"
        b"# Date 0 +0000\n"
        b"# Diff Start Line 6\n"
        b"add another file.\n"
        b"\n"
        b"diff --git a/test.txt b/test.txt\n"
        b"--- a/test.txt\n"
        b"+++ b/test.txt\n"
        b"@@ -1,1 +1,2 @@\n"
        b" TEST\n"
        b"+adding another line\n"
    ), "Patch diff should be parsed from patch body."


def test_try_api_success_gitformatpatch(
    app,
    db,
    hg_server,
    hg_clone,
    new_treestatus_tree,
    client,
    auth0_mock,
    mocked_repo_config,
):
    new_treestatus_tree(tree="mozilla-central", status="open")

    try_push_json = {
        # The only node in the test repo.
        "base_commit": "0da79df0ffff88e0ad6fa3e27508bcf5b2f2cec4",
        "patch_format": "git-format-patch",
        "patches": [
            base64.b64encode(GIT_PATCH).decode("ascii"),
        ],
    }
    response = client.post(
        "/try/patches", json=try_push_json, headers=auth0_mock.mock_headers
    )
    assert response.status_code == 201, "Successful try push should return 201."
    assert (
        "id" in response.json
    ), "Response should include the ID of the new landing job."

    queue_items = LandingJob.job_queue_query(
        repositories=["try"], grace_seconds=0
    ).all()
    assert len(queue_items) == 1, "Try push should have created 1 landing job."

    # Run the landing job.
    job = queue_items[0]

    repo = Repo(
        tree="try",
        url=hg_server,
        access_group=SCM_LEVEL_1,
        push_path=hg_server,
        pull_path=hg_server,
        short_name="try",
        is_phabricator_repo=False,
        force_push=True,
    )

    worker = LandingWorker(sleep_seconds=0.01)
    hgrepo = HgRepo(hg_clone.strpath)

    # Assert the job landed against the expected commit hash.
    assert worker.run_job(job, repo, hgrepo)
    assert job.status == LandingJobStatus.LANDED
    assert len(job.landed_commit_id) == 40
    assert (
        job.target_commit_hash == "0da79df0ffff88e0ad6fa3e27508bcf5b2f2cec4"
    ), "Target changeset should match the passed value."

    # Test the revision content matches expected.
    assert len(job.revisions) == 1, "Job should have landed a single revision."
    revision = job.revisions[0]
    assert (
        revision.patch_data["author_name"] == "Connor Sheehan"
    ), "Patch author should be parsed from `From` header."
    assert (
        revision.patch_data["author_email"] == "sheehan@mozilla.com"
    ), "Email address should be parsed from `From` header."
    assert revision.patch_data["commit_message"] == (
        "add another file\n\nadd another file to the repo."
    ), "Multi-line commit message should be parsed from patch."
    assert (
        revision.patch_data["timestamp"] == "1657139769"
    ), "Timestamp should be parsed from `Date` header."
    assert revision.patch_bytes == (
        b"# HG changeset patch\n"
        b"# User Connor Sheehan <sheehan@mozilla.com>\n"
        b"# Date 1657139769 +0000\n"
        b"# Diff Start Line 8\n"
        b"add another file\n"
        b"\n"
        b"add another file to the repo.\n"
        b"\n"
        b"diff --git a/test.txt b/test.txt\n"
        b"--- a/test.txt\n"
        b"+++ b/test.txt\n"
        b"@@ -1,1 +1,2 @@\n"
        b" TEST\n"
        b"+adding another line\n"
    ), "Patch diff should be parsed from patch body."


def test_hgrepo_git2hg_conversion(app, db, tmp_path, monkeypatch):
    """Test cinnabar git2hg SHA conversion."""
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    hgrepo = HgRepo(str(repo_path), native_git_source="https://example.com")

    # Simulate cinnabar path
    hgrepo.cinnabar_path.mkdir()

    # Mock git command
    monkeypatch.setattr(hgrepo, "run_git", lambda args: "convertedhgsha1234567890")

    result = hgrepo.git_to_hg("gitsha1234567890")
    assert result == "convertedhgsha1234567890"


def test_update_cinnabar_repo_runs_fetch(app, db, tmp_path, monkeypatch):
    """Ensure cinnabar fetch is called on update."""
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    hgrepo = HgRepo(str(repo_path), native_git_source="https://example.com")
    hgrepo.cinnabar_path.mkdir()

    called = {"git": {}, "hg": {}}

    def fake_run_git(args):
        called["git"]["args"] = args
        return "ok"

    def fake_run_hg(args):
        called["hg"]["args"] = args
        return "ok"

    def fake_bookmarks(*args, **kwargs):
        return ["bookmark1", "bookmark2", "bookmark3"]

    monkeypatch.setattr(hgrepo, "get_bookmarks", fake_bookmarks)
    monkeypatch.setattr(hgrepo, "run_hg", fake_run_hg)
    monkeypatch.setattr(hgrepo, "run_git", fake_run_git)
    hgrepo.update_cinnabar_repo("test_source")

    assert called["hg"]["args"] == ["pull", "test_source"]

    assert called["git"]["args"] == [
        "cinnabar",
        "fetch",
        "hg::test_source",
        "bookmark1",
        "bookmark2",
        "bookmark3",
    ]


def test_try_push_invalid_base_commit_vcs(app, db, client, auth0_mock):
    try_push_json = {
        "base_commit": "a" * 40,
        "base_commit_vcs": "banana",
        "patch_format": "git-format-patch",
        "patches": [
            base64.b64encode(GIT_PATCH).decode("ascii"),
        ],
    }

    response = client.post(
        "/try/patches", json=try_push_json, headers=auth0_mock.mock_headers
    )

    assert response.status_code == 400
    assert "base_commit_vcs" in response.json["detail"]
