# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import pytest

from landoapi.models.landing_job import LandingJob, LandingJobStatus


@pytest.fixture
def landing_job(db):
    def _landing_job(status, requester_email="tuser@example.com"):
        job = LandingJob(
            status=status,
            revision_to_diff_id={},
            revision_order=[],
            requester_email=requester_email,
            repository_name="",
        )
        db.session.add(job)
        db.session.commit()
        return job

    return _landing_job


def test_cancel_landing_job_cancels_when_submitted(db, client, landing_job, auth0_mock):
    """Test happy path; cancelling a job that has not started yet."""
    job = landing_job(LandingJobStatus.SUBMITTED)
    response = client.put(
        f"/landing_jobs/{job.id}",
        json={"status": LandingJobStatus.CANCELLED.value},
        headers=auth0_mock.mock_headers,
    )

    assert response.status_code == 200
    assert response.json["id"] == job.id
    assert job.status == LandingJobStatus.CANCELLED


def test_cancel_landing_job_cancels_when_deferred(db, client, landing_job, auth0_mock):
    """Test happy path; cancelling a job that has been deferred."""
    job = landing_job(LandingJobStatus.DEFERRED)
    response = client.put(
        f"/landing_jobs/{job.id}",
        json={"status": LandingJobStatus.CANCELLED.value},
        headers=auth0_mock.mock_headers,
    )

    assert response.status_code == 200
    assert response.json["id"] == job.id
    assert job.status == LandingJobStatus.CANCELLED


def test_cancel_landing_job_fails_in_progress(db, client, landing_job, auth0_mock):
    """Test trying to cancel a job that is in progress fails."""
    job = landing_job(LandingJobStatus.IN_PROGRESS)
    response = client.put(
        f"/landing_jobs/{job.id}",
        json={"status": LandingJobStatus.CANCELLED.value},
        headers=auth0_mock.mock_headers,
    )

    assert response.status_code == 400
    assert response.json["detail"] == (
        "Landing job status (LandingJobStatus.IN_PROGRESS) does not allow cancelling."
    )
    assert job.status == LandingJobStatus.IN_PROGRESS


def test_cancel_landing_job_fails_not_owner(db, client, landing_job, auth0_mock):
    """Test trying to cancel a job that is created by a different user."""
    job = landing_job(LandingJobStatus.SUBMITTED, "anotheruser@example.org")
    response = client.put(
        f"/landing_jobs/{job.id}",
        json={"status": LandingJobStatus.CANCELLED.value},
        headers=auth0_mock.mock_headers,
    )

    assert response.status_code == 403
    assert response.json["detail"] == ("User not authorized to update landing job 1")
    assert job.status == LandingJobStatus.SUBMITTED


def test_cancel_landing_job_fails_not_found(db, client, landing_job, auth0_mock):
    """Test trying to cancel a job that does not exist."""
    response = client.put(
        f"/landing_jobs/1",
        json={"status": LandingJobStatus.CANCELLED.value},
        headers=auth0_mock.mock_headers,
    )

    assert response.status_code == 404
    assert response.json["detail"] == ("A landing job with ID 1 was not found.")


def test_cancel_landing_job_fails_bad_input(db, client, landing_job, auth0_mock):
    """Test trying to send an invalid status to the update endpoint."""
    job = landing_job(LandingJobStatus.SUBMITTED)
    response = client.put(
        f"/landing_jobs/{job.id}",
        json={"status": LandingJobStatus.IN_PROGRESS.value},
        headers=auth0_mock.mock_headers,
    )

    assert response.status_code == 400
    assert response.json["detail"] == (
        "'IN_PROGRESS' is not one of ['CANCELLED'] - 'status'"
    )
    assert job.status == LandingJobStatus.SUBMITTED


def test_landing_job_acquire_job_job_queue_query(db):
    REPO_NAME = "test-repo"
    jobs = [
        LandingJob(
            status=LandingJobStatus.SUBMITTED,
            requester_email="test@example.com",
            repository_name=REPO_NAME,
            revision_to_diff_id={"1": 1},
            revision_order=["1"],
        ),
        LandingJob(
            status=LandingJobStatus.SUBMITTED,
            requester_email="test@example.com",
            repository_name=REPO_NAME,
            revision_to_diff_id={"2": 2},
            revision_order=["2"],
        ),
        LandingJob(
            status=LandingJobStatus.SUBMITTED,
            requester_email="test@example.com",
            repository_name=REPO_NAME,
            revision_to_diff_id={"3": 3},
            revision_order=["3"],
        ),
    ]
    for job in jobs:
        db.session.add(job)
        db.session.commit()

    # Queue order should match the order the jobs were created in.
    for qjob, job in zip(LandingJob.job_queue_query(repositories=[REPO_NAME]), jobs):
        assert qjob is job

    # Update the last job to be in progress and mark the middle job to be
    # cancelled so that the queue changes.
    jobs[2].status = LandingJobStatus.IN_PROGRESS
    jobs[1].status = LandingJobStatus.CANCELLED
    db.session.commit()

    # The now IN_PROGRESS job should be first, and the cancelled job should
    # not appear in the queue.
    queue_items = LandingJob.job_queue_query(
        repositories=[REPO_NAME], grace_seconds=0
    ).all()
    assert len(queue_items) == 2
    assert queue_items[0] is jobs[2]
    assert queue_items[1] is jobs[0]
    assert jobs[1] not in queue_items
