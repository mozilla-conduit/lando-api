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
""".strip()

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
""".strip()

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
""".strip()


def test_get_timestamp_from_date():
    assert (
        get_timestamp_from_git_date_header("Wed, 6 Jul 2022 16:36:09 -0400")
        == "1657139769"
    ), "Timestamp from `git format-patch` should properly convert to `str`."


def test_parse_git_author_information():
    assert parse_git_author_information("User Name <user@example.com>") == (
        "User Name",
        "user@example.com",
    ), "Name and email information should be parsed into separate strings."


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
    treestatusdouble,
    client,
    auth0_mock,
    mocked_repo_config,
):
    """Test when a patch can't be decoded."""
    treestatus = treestatusdouble.get_treestatus_client()
    treestatusdouble.open_tree("mozilla-central")

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
    treestatusdouble,
    client,
    auth0_mock,
    mocked_repo_config,
    patch_format,
    patch_content,
):
    """Test what happens when a patch does not match the passed format."""
    treestatus = treestatusdouble.get_treestatus_client()
    treestatusdouble.open_tree("mozilla-central")

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


def test_try_api_unknown_patch_format(
    app,
    db,
    hg_server,
    hg_clone,
    treestatusdouble,
    client,
    auth0_mock,
    mocked_repo_config,
):
    """Test when `patch_format` isn't one of the accepted values."""
    treestatus = treestatusdouble.get_treestatus_client()
    treestatusdouble.open_tree("mozilla-central")

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
    treestatusdouble,
    client,
    auth0_mock,
    mocked_repo_config,
):
    treestatus = treestatusdouble.get_treestatus_client()
    treestatusdouble.open_tree("mozilla-central")

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

    assert worker.run_job(job, repo, hgrepo, treestatus)
    assert job.status == LandingJobStatus.LANDED
    assert len(job.landed_commit_id) == 40
    assert (
        job.target_commit_hash == "0da79df0ffff88e0ad6fa3e27508bcf5b2f2cec4"
    ), "Target changeset should match the passed value."


def test_try_api_success_gitformatpatch(
    app,
    db,
    hg_server,
    hg_clone,
    treestatusdouble,
    client,
    auth0_mock,
    mocked_repo_config,
):
    treestatus = treestatusdouble.get_treestatus_client()
    treestatusdouble.open_tree("mozilla-central")

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

    assert worker.run_job(job, repo, hgrepo, treestatus)
    assert job.status == LandingJobStatus.LANDED
    assert len(job.landed_commit_id) == 40
    assert (
        job.target_commit_hash == "0da79df0ffff88e0ad6fa3e27508bcf5b2f2cec4"
    ), "Target changeset should match the passed value."
