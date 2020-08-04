# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
from contextlib import contextmanager

import logging
import os
import re
import signal
import subprocess
import time

from flask import current_app

from landoapi import patches
from landoapi.hg import (
    HgRepo,
    LostPushRace,
    NoDiffStartLine,
    PatchConflict,
    TreeApprovalRequired,
    TreeClosed,
)
from landoapi.models.landing_job import LandingJob, LandingJobStatus, LandingJobAction
from landoapi.notifications import notify_user_of_landing_failure
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
        SSH_PRIVATE_KEY_ENV_KEY = "SSH_PRIVATE_KEY"

        self.sleep_seconds = sleep_seconds
        config_keys = ["AWS_SECRET_KEY", "AWS_ACCESS_KEY", "PATCH_BUCKET_NAME"]
        self.config = {k: current_app.config[k] for k in config_keys}

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

        # Fetch ssh private key from the environment. Note that this key should be
        # stored in standard format including all new lines and new line at the end
        # of the file.
        self.ssh_private_key = os.environ.get(SSH_PRIVATE_KEY_ENV_KEY)
        if not self.ssh_private_key:
            logger.warning(f"No {SSH_PRIVATE_KEY_ENV_KEY} present in environment.")

        # Catch kill signals so that the worker can initiate shutdown procedure
        signal.signal(signal.SIGINT, self.exit_gracefully)
        signal.signal(signal.SIGTERM, self.exit_gracefully)

    @staticmethod
    def _setup_ssh(ssh_private_key):
        """Add a given private ssh key to ssh agent.

        SSH keys are needed in order to push to repositories that have an ssh
        push path.

        The private key should be passed as it is in the key file, including all
        new line characters and the new line character at the end.

        Args:
            ssh_private_key (str): A string representing the private SSH key file.
        """
        # Set all the correct environment variables
        agent_process = subprocess.run(
            ["ssh-agent", "-s"], capture_output=True, universal_newlines=True
        )

        # This pattern will match keys and values, and ignore everything after the
        # semicolon. For example, the output of `agent_process` is of the form:
        #     SSH_AUTH_SOCK=/tmp/ssh-c850kLXXOS5e/agent.120801; export SSH_AUTH_SOCK;
        #     SSH_AGENT_PID=120802; export SSH_AGENT_PID;
        #     echo Agent pid 120802;
        pattern = re.compile("(.+)=([^;]*)")
        for key, value in pattern.findall(agent_process.stdout):
            logger.info(f"_setup_ssh: setting {key} to {value}")
            os.environ[key] = value

        # Add private SSH key to agent
        # NOTE: ssh-add seems to output everything to stderr, including upon exit 0.
        add_process = subprocess.run(
            ["ssh-add", "-"],
            input=ssh_private_key,
            capture_output=True,
            universal_newlines=True,
        )
        if add_process.returncode != 0:
            raise Exception(add_process.stderr)
        logger.info("Added private SSH key from environment.")

    def refresh_enabled_repos(self):
        self.enabled_repos = [
            r
            for r in self.applicable_repos
            if treestatus_subsystem.client.is_open(repo_clone_subsystem.repos[r].tree)
        ]
        logger.info(f"{len(self.enabled_repos)} enabled repos: {self.enabled_repos}")

    def start(self):
        logger.info("Landing worker starting")
        logger.info(
            f"{len(self.applicable_repos)} applicable repos: {self.applicable_repos}"
        )

        if self.ssh_private_key:
            self._setup_ssh(self.ssh_private_key)

        self.running = True

        # Initialize state
        self.refresh_enabled_repos()
        last_job_finished = True

        while self.running:
            # Check if any closed trees reopened since the beginning of this iteration
            if len(self.enabled_repos) != len(self.applicable_repos):
                self.refresh_enabled_repos()

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
                time.sleep(self.sleep_seconds)
                continue

            with job_processing(self):
                job.status = LandingJobStatus.IN_PROGRESS
                job.attempts += 1
                db.session.commit()

                repo = repo_clone_subsystem.repos[job.repository_name]
                hgrepo = HgRepo(
                    str(repo_clone_subsystem.repo_paths[job.repository_name]),
                    config=repo.config_override,
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

    @staticmethod
    def notify_user_of_landing_failure(job):
        """Wrapper around notify_user_of_landing_failure for convenience.

        Args:
            job (LandingJob): A LandingJob instance to use when fetching the
                notification parameters.
        """
        notify_user_of_landing_failure(
            job.requester_email, job.head_revision, job.error, job.id
        )

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
        except LostPushRace:
            logger.info(f"LandingJob {job.id} lost push race, deferring")
            job.transition_status(
                LandingJobAction.DEFER,
                message=f"Lost push race when pushing to {repo.push_path}.",
                commit=True,
                db=db,
            )
            return False
        except NoDiffStartLine:
            logger.exception("Patch without a diff start line.")
            message = (
                "Lando encountered a malformed patch, please try again. "
                "If this error persists please file a bug."
            )
            job.transition_status(
                LandingJobAction.FAIL, message=message, commit=True, db=db
            )
            self.notify_user_of_landing_failure(job)
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
            self.notify_user_of_landing_failure(job)
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
            self.notify_user_of_landing_failure(job)
            return True
        finally:
            del os.environ["AUTOLAND_REQUEST_USER"]

        job.transition_status(LandingJobAction.LAND, commit_id=commit_id)
        db.session.commit()
        return True
