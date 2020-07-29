# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import mock
import pytest

from landoapi import patches
from landoapi.hg import HgRepo
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


def test_update_landing_bad_api_key(client):
    response = client.post(
        "/landings/update",
        json={"request_id": 1, "landed": True, "result": "sha123"},
        headers=[("API-Key", "wrongapikey")],
    )

    assert response.status_code == 403


def test_update_landing_no_api_key(client):
    response = client.post(
        "/landings/update", json={"request_id": 1, "landed": True, "result": "sha123"}
    )

    assert response.status_code == 400


def test_pingback_disabled(client, config):
    config["PINGBACK_ENABLED"] = "n"

    response = client.post(
        "/landings/update",
        json={"request_id": 1, "landed": True, "result": "sha123"},
        headers=[("API-Key", "someapikey")],
    )

    assert response.status_code == 403


def test_pingback_no_api_key_header(client, config):
    config["PINGBACK_ENABLED"] = "y"

    response = client.post(
        "/landings/update", json={"request_id": 1, "landed": True, "result": "sha123"}
    )

    assert response.status_code == 400


def test_pingback_incorrect_api_key(client, config):
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


def test_integrated_execute_job(
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

    assert worker.run_job(job, repo, hgrepo, treestatus, "landoapi.test.bucket")
    assert job.status is LandingJobStatus.LANDED
    assert len(job.landed_commit_id) == 40


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
    upload_patch(3, patch=PATCH_PUSH_LOSER)
    job = LandingJob(
        id=1234,
        status=LandingJobStatus.IN_PROGRESS,
        requester_email="test@example.com",
        repository_name="mozilla-central",
        revision_to_diff_id={"3": 3},
        revision_order=["3"],
        attempts=1,
    )

    worker = LandingWorker(sleep_seconds=0)

    assert not worker.run_job(job, repo, hgrepo, treestatus, "landoapi.test.bucket")
    assert job.status is LandingJobStatus.DEFERRED


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
    """Ensure that a failed landings triggers a user notification.
    """
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
    assert job.status is LandingJobStatus.FAILED
    assert mock_notify.call_count == 1
