# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
from contextlib import contextmanager

import logging
import os
import signal
import time

from flask import current_app

from landoapi import patches
from landoapi.hg import (
    HgRepo,
    NoDiffStartLine,
    PatchConflict,
    TreeApprovalRequired,
    TreeClosed,
)
from landoapi.models.landing_job import LandingJob, LandingJobStatus, LandingJobAction
from landoapi.repos import repo_clone_subsystem
from landoapi.storage import db
from landoapi.treestatus import treestatus_subsystem

logger = logging.getLogger(__name__)


@contextmanager
def job_processing(worker):
    """Mutex-like context manager that ensures workers shut down gracefully.

    Args:
        worker (LandingWorker): the landing worker that is processing jobs
    """
    worker.job_processing = True
    try:
        yield
    finally:
        worker.job_processing = False


class LandingWorker:
    def __init__(self, sleep_seconds=5):
        self.sleep_seconds = sleep_seconds
        self.config = {}
        self.config["AWS_SECRET_KEY"] = current_app.config["AWS_SECRET_KEY"]
        self.config["AWS_ACCESS_KEY"] = current_app.config["AWS_ACCESS_KEY"]
        self.config["PATCH_BUCKET_NAME"] = current_app.config["PATCH_BUCKET_NAME"]

        # The list of all repos that are enabled for this worker
        self.applicable_repos = (
            list(repo_clone_subsystem.repos)
            if hasattr(repo_clone_subsystem, "repos")
            else []
        )

        # The list of all repos that have open trees; refreshed when needed via
        # `self.refresh_enabled_repos`.
        self.enabled_repos = []

        # This is True when a worker active, and False when it is shut down
        self.running = False

        # This is True when the worker is busy processing a job
        self.job_processing = False

        # Catch kill signals so that the worker can initiate shutdown procedure
        signal.signal(signal.SIGINT, self.exit_gracefully)
        signal.signal(signal.SIGTERM, self.exit_gracefully)

    def refresh_enabled_repos(self):
        self.enabled_repos = [
            r for r in self.applicable_repos if treestatus_subsystem.client.is_open(r)
        ]
        logger.info(f"{len(self.enabled_repos)} enabled repos")

    def start(self):
        logger.info("Landing worker starting")
        self.running = True
        last_job_finished = True
        self.refresh_enabled_repos()

        while self.running:
            if not last_job_finished:
                logger.info(
                    "Last job did not complete, waiting for {} seconds".format(
                        self.sleep_seconds
                    )
                )
                time.sleep(self.sleep_seconds)
                self.refresh_enabled_repos()

            job = LandingJob.next_job_for_update_query(
                repositories=self.enabled_repos
            ).first()

            if job is None:
                logger.info(
                    "Landing job queue empty, sleeping for {} seconds".format(
                        self.sleep_seconds
                    )
                )
                time.sleep(self.sleep_seconds)
                continue

            with job_processing(self):
                job.status = LandingJobStatus.IN_PROGRESS
                job.attempts += 1
                db.session.commit()

                repo = repo_clone_subsystem.repos[job.repository_name]
                hgrepo = HgRepo(
                    str(repo_clone_subsystem.repo_paths[job.repository_name])
                )

                logger.info("Starting landing job", extra={"id": job.id})
                last_job_finished = self.run_job(
                    job,
                    repo,
                    hgrepo,
                    treestatus_subsystem.client,
                    current_app.config["PATCH_BUCKET_NAME"],
                )

                # Finalize job
                db.session.commit()
                logger.info("Finished processing landing job", extra={"id": job.id})
        logger.info("Landing worker exited")

    def exit_gracefully(self, *args):
        logger.info(f"Landing worker exiting gracefully {args}")
        while self.job_processing:
            time.sleep(self.sleep_seconds)
        self.running = False

    def run_job(self, job, repo, hgrepo, treestatus, patch_bucket):
        if not treestatus.is_open(repo.tree):
            job.transition_status(
                LandingJobAction.DEFER,
                message=f"Tree {repo.tree} is closed - retrying later.",
                commit=True,
                db=db,
            )
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
                        aws_access_key=self.config["AWS_ACCESS_KEY"],
                        aws_secret_key=self.config["AWS_SECRET_KEY"],
                    )
                    hgrepo.apply_patch(patch_buf)

                commit_id = hgrepo.run_hg(["log", "-r", ".", "-T", "{node}"]).decode(
                    "utf-8"
                )
                hgrepo.push(repo.push_path, bookmark=repo.push_bookmark or None)

        except NoDiffStartLine:
            logger.exception("Patch without a diff start line.")
            message = (
                "Lando encountered a malformed patch, please try again. "
                "If this error persists please file a bug."
            )
            job.transition_status(
                LandingJobAction.FAIL, message=message, commit=True, db=db
            )
            return True
        except PatchConflict as exc:
            message = (
                "We're sorry, Lando could not rebase your "
                "commits for you automatically. Please manually "
                "rebase your commits and try again.\n\n"
                f"{str(exc)}"
            )
            job.transition_status(
                LandingJobAction.FAIL, message=message, commit=True, db=db
            )
            return True
        except TreeClosed:
            job.transition_status(
                LandingJobAction.DEFER,
                message=f"Tree {repo.tree} is closed - retrying later.",
                commit=True,
                db=db,
            )
            return False
        except TreeApprovalRequired:
            job.transition_status(
                LandingJobAction.DEFER,
                message=f"Tree {repo.tree} requires approval - retrying later.",
                commit=True,
                db=db,
            )
            return False
        except Exception as e:
            logger.exception("Unexpected landing error.")
            job.transition_status(
                LandingJobAction.FAIL,
                message=f"An unexpected error occured while landing:\n{e}",
                commit=True,
                db=db,
            )
            return True
        finally:
            del os.environ["AUTOLAND_REQUEST_USER"]

        job.transition_status(LandingJobAction.LAND, commit_id=commit_id)
        db.session.commit()
        return True
