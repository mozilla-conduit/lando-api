# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import base64

from landoapi.hg import HgRepo
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


def test_try_api_requires_data(db, client, auth0_mock, mocked_repo_config):
    try_push_json = {
        "base_commit": "abc",
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


def test_try_api_success(
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
        "patches": [
            {
                "author": "User Test User",
                "author_email": "test@example.com",
                "diff": base64.b64encode(PATCH_DIFF).decode("ascii"),
                "timestamp": "0",
                "commit_message": "add another file.",
            }
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
        phabricator_repo=False,
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
