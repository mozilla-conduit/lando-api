# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging
import os
import time

from landoapi import patches
from landoapi.hg import (
    HgRepo,
    NoDiffStartLine,
    PatchConflict,
    TreeClosed,
    TreeApprovalRequired,
)
from landoapi.models.landing_job import LandingJob, LandingJobStatus
from landoapi.repos import repo_clone_subsystem
from landoapi.storage import db
from landoapi.treestatus import treestatus_subsystem

logger = logging.getLogger(__name__)


def worker():
    from flask import current_app

    logger.info("Landing worker started")

    enabled_repos = list(repo_clone_subsystem.repos)
    skip_sleep = True

    # TODO: Graceful shutdown, complete the currently running job.
    # Process jobs until killed.
    # TODO: Ensure there are no other landing workers before processing
    # jobs. A job may be executed twice in parralel if a second worker
    # is accidentally started.
    while True:
        if not skip_sleep:
            logger.info("Sleeping between jobs.")
            time.sleep(5)

        # TODO: Check which of the enabled_repos are open in treestatus and
        # only query for those. As-is a worker with multiple repositories
        # enabled can be blocked for all work even if only a single tree
        # is closed.
        job = LandingJob.next_job_for_update_query(repositories=enabled_repos).first()
        if job is None:
            logger.info("Landing job queue empty")
            time.sleep(5)
            continue

        # Start the job and commit to release the lock on the row.
        job.status = LandingJobStatus.IN_PROGRESS
        job.attempts += 1
        db.session.commit()

        repo_name = job.repository_name
        repo = repo_clone_subsystem.repos[repo_name]
        hgrepo = HgRepo(str(repo_clone_subsystem.repo_paths[repo_name]))

        logger.info("Starting landing job", extra={"id": job.id})
        skip_sleep = execute_job(
            job,
            repo,
            hgrepo,
            treestatus_subsystem.client,
            current_app.config["PATCH_BUCKET_NAME"],
            aws_access_key=current_app.config["AWS_ACCESS_KEY"],
            aws_secret_key=current_app.config["AWS_SECRET_KEY"],
        )

        # Finalize job
        db.session.commit()
        logger.info("Finished processing landing job", extra={"id": job.id})

    logger.info("Landing worker exiting")


def execute_job(
    job, repo, hgrepo, treestatus, patch_bucket, *, aws_access_key, aws_secret_key
):
    if not treestatus.is_open(repo.tree):
        job.failed_transient(f"Tree {repo.tree} is closed - retrying later.")
        return False

    try:
        # Set the environment variable the `set_landing_system.py` hg
        # extension will use to send the push user override.
        os.environ["AUTOLAND_REQUEST_USER"] = job.requester_email

        with hgrepo:
            hgrepo.update_repo(repo.pull_path)

            for revision_id, diff_id in job.landing_path:
                patch_buf = patches.download(
                    revision_id,
                    diff_id,
                    patch_bucket,
                    aws_access_key=aws_access_key,
                    aws_secret_key=aws_secret_key,
                )
                hgrepo.apply_patch(patch_buf)

            commit_id = hgrepo.run_hg(["log", "-r", ".", "-T", "{node}"])
            hgrepo.push(repo.push_path, bookmark=repo.push_bookmark or None)

    except NoDiffStartLine:
        logger.exception("Patch without a diff start line.")
        job.failed_permanent(
            "Lando encountered a malformed patch, please try again. "
            "If this error persists please file a bug."
        )
        return True
    except PatchConflict as exc:
        job.failed_permanent(
            "We're sorry, Lando could not rebase your "
            "commits for you automatically. Please manually "
            "rebase your commits and try again.\n\n"
            f"{str(exc)}"
        )
        return True
    except TreeClosed:
        job.failed_transient(f"Tree {repo.tree} is closed - retrying later.")
        return False
    except TreeApprovalRequired:
        job.failed_transient(f"Tree {repo.tree} requires approval - retrying later.")
        return False
    except Exception:
        logger.exception("Unexpected landing error.")
        job.failed_permanent(f"An unexpected error occured while landing.")
        return True
    finally:
        del os.environ["AUTOLAND_REQUEST_USER"]

    job.landed(commit_id)
    return True
