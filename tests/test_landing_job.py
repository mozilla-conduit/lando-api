# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from landoapi.models.landing_job import LandingJob, LandingJobStatus


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
