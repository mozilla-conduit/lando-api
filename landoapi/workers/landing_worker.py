# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import logging
import re

from flask import current_app

import kombu

from landoapi import patches
from landoapi.commit_message import parse_bugs
from landoapi.hg import (
    AutoformattingException,
    HgRepo,
    LostPushRace,
    NoDiffStartLine,
    PatchConflict,
    TreeApprovalRequired,
    TreeClosed,
    REJECTS_PATH,
)
from landoapi.models.configuration import ConfigurationKey
from landoapi.models.landing_job import LandingJob, LandingJobStatus, LandingJobAction
from landoapi.notifications import (
    notify_user_of_bug_update_failure,
    notify_user_of_landing_failure,
)
from landoapi.repos import (
    Repo,
    repo_clone_subsystem,
)
from landoapi.storage import db, SQLAlchemy
from landoapi.tasks import phab_trigger_repo_update
from landoapi.treestatus import (
    TreeStatus,
    treestatus_subsystem,
)
from landoapi.uplift import (
    update_bugs_for_uplift,
)
from landoapi.workers.base import Worker

logger = logging.getLogger(__name__)


@contextmanager
def job_processing(worker: LandingWorker, job: LandingJob, db: SQLAlchemy):
    """Mutex-like context manager that manages job processing miscellany.

    This context manager facilitates graceful worker shutdown, tracks the duration of
    the current job, and commits changes to the DB at the very end.

    Args:
        worker: the landing worker that is processing jobs
        job: the job currently being processed
        db: active database session
    """
    start_time = datetime.now()
    try:
        yield
    finally:
        job.duration_seconds = (datetime.now() - start_time).seconds
        db.session.commit()


class LandingWorker(Worker):
    @property
    @staticmethod
    def STOP_KEY() -> str:
        """Return the configuration key that prevents the worker from starting."""
        return ConfigurationKey.LANDING_WORKER_STOPPED

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        config_keys = [
            "AWS_SECRET_KEY",
            "AWS_ACCESS_KEY",
            "PATCH_BUCKET_NAME",
            "S3_ENDPOINT_URL",
        ]

        self.config = {k: current_app.config[k] for k in config_keys}
        self.last_job_finished = None
        self.refresh_enabled_repos()

    def loop(self):
        logger.debug(
            f"{len(self.applicable_repos)} applicable repos: {self.applicable_repos}"
        )

        # Check if any closed trees reopened since the beginning of this iteration
        if len(self.enabled_repos) != len(self.applicable_repos):
            self.refresh_enabled_repos()

        if not self.last_job_finished:
            logger.info("Last job did not complete, sleeping.")
            self.throttle(self.sleep_seconds)
            self.refresh_enabled_repos()

        job = LandingJob.next_job_for_update_query(
            repositories=self.enabled_repos
        ).first()

        if job is None:
            self.throttle(self.sleep_seconds)
            return

        with job_processing(self, job, db):
            job.status = LandingJobStatus.IN_PROGRESS
            job.attempts += 1

            # Make sure the status and attempt count are updated in the database
            db.session.commit()

            repo = repo_clone_subsystem.repos[job.repository_name]
            hgrepo = HgRepo(
                str(repo_clone_subsystem.repo_paths[job.repository_name]),
            )

            logger.info("Starting landing job", extra={"id": job.id})
            self.last_job_finished = self.run_job(
                job,
                repo,
                hgrepo,
                treestatus_subsystem.client,
                current_app.config["PATCH_BUCKET_NAME"],
            )
            logger.info("Finished processing landing job", extra={"id": job.id})

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

    @staticmethod
    def notify_user_of_bug_update_failure(job, exception):
        """Wrapper around notify_user_of_bug_update_failure for convenience.

        Args:
            job (LandingJob): A LandingJob instance to use when fetching the
                notification parameters.
        """
        notify_user_of_bug_update_failure(
            job.requester_email,
            job.head_revision,
            f"Failed to update Bugzilla after landing uplift revisions: {str(exception)}",
            job.id,
        )

    @staticmethod
    def phab_trigger_repo_update(phab_identifier: str):
        """Wrapper around `phab_trigger_repo_update` for convenience.

        Args:
            phab_identifier: `str` to be passed to Phabricator to identify
            repo.
        """
        try:
            # Send a Phab repo update task to Celery.
            phab_trigger_repo_update.apply_async(args=(phab_identifier,))
        except kombu.exceptions.OperationalError as e:
            # Log the exception but continue gracefully.
            # The repo will eventually update.
            logger.exception("Failed sending repo update task to Celery.")
            logger.exception(e)

    @staticmethod
    def extract_error_data(exception: str) -> tuple[list[str], list[str]]:
        """Extract rejected hunks and file paths from exception message."""
        # RE to capture .rej file paths.
        rejs_re = re.compile(
            r"^\d+ out of \d+ hunks FAILED -- saving rejects to file (.+)$",
            re.MULTILINE,
        )

        # TODO: capture reason for patch failure, e.g. deleting non-existing file, or
        # adding a pre-existing file, etc...
        reject_paths = rejs_re.findall(exception)

        # Collect all failed paths by removing `.rej` extension.
        failed_paths = [path[:-4] for path in reject_paths]

        return failed_paths, reject_paths

    def run_job(
        self,
        job: LandingJob,
        repo: Repo,
        hgrepo: HgRepo,
        treestatus: TreeStatus,
        patch_bucket: str,
    ) -> bool:
        if not treestatus.is_open(repo.tree):
            job.transition_status(
                LandingJobAction.DEFER,
                message=f"Tree {repo.tree} is closed - retrying later.",
                commit=True,
                db=db,
            )
            return False

        with hgrepo.for_push(job.requester_email):
            # Update local repo.
            try:
                hgrepo.update_repo(repo.pull_path)
            except Exception as e:
                message = f"Unexpected error while fetching repo from {repo.pull_path}."
                logger.exception(message)
                job.transition_status(
                    LandingJobAction.FAIL,
                    message=message + f"\n{e}",
                    commit=True,
                    db=db,
                )
                self.notify_user_of_landing_failure(job)
                return True

            # Download all patches locally from S3.
            patch_bufs = []
            for revision_id, diff_id in job.landing_path:
                try:
                    patch_buf = patches.download(
                        revision_id,
                        diff_id,
                        patch_bucket,
                        aws_access_key=self.config["AWS_ACCESS_KEY"],
                        aws_secret_key=self.config["AWS_SECRET_KEY"],
                        endpoint_url=self.config["S3_ENDPOINT_URL"],
                    )
                except Exception as e:
                    message = (
                        f"Aborting, could not fetch {revision_id}, {diff_id} from S3."
                    )
                    logger.exception(message)
                    job.transition_status(
                        LandingJobAction.FAIL,
                        message=message + f"\n{e}",
                        commit=True,
                        db=db,
                    )
                    self.notify_user_of_landing_failure(job)
                    return True
                patch_bufs.append((revision_id, patch_buf))

            # Run through the patches one by one and try to apply them.
            for revision_id, patch_buf in patch_bufs:
                try:
                    hgrepo.apply_patch(patch_buf)
                except PatchConflict as exc:
                    failed_paths, reject_paths = self.extract_error_data(str(exc))

                    # Find last commits to touch each failed path.
                    failed_path_changesets = [
                        (
                            path,
                            hgrepo.run_hg(
                                [
                                    "log",
                                    "--cwd",
                                    hgrepo.path,
                                    "--template",
                                    "{node}",
                                    "-l",
                                    "1",
                                    path,
                                ]
                            ),
                        )
                        for path in failed_paths
                    ]

                    breakdown = {
                        "revision_id": revision_id,
                        "content": None,
                        "reject_paths": None,
                    }

                    breakdown["failed_paths"] = [
                        {
                            "path": r[0],
                            "url": f"{repo.pull_path}/file/{r[1].decode('utf-8')}/{r[0]}",
                            "changeset_id": r[1].decode("utf-8"),
                        }
                        for r in failed_path_changesets
                    ]
                    breakdown["reject_paths"] = {}
                    for r in reject_paths:
                        reject = {"path": r}
                        try:
                            with open(REJECTS_PATH / hgrepo.path[1:] / r, "r") as f:
                                reject["content"] = f.read()
                        except Exception as e:
                            logger.exception(e)
                        # Use actual path of file to store reject data, by removing
                        # `.rej` extension.
                        breakdown["reject_paths"][r[:-4]] = reject

                    message = (
                        f"Problem while applying patch in revision {revision_id}:\n\n"
                        f"{str(exc)}"
                    )
                    job.error_breakdown = breakdown

                    job.transition_status(
                        LandingJobAction.FAIL, message=message, commit=True, db=db
                    )
                    self.notify_user_of_landing_failure(job)
                    return True
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
                except Exception as e:
                    message = (
                        f"Aborting, could not apply patch buffer for {revision_id}."
                    )
                    logger.exception(message)
                    job.transition_status(
                        LandingJobAction.FAIL,
                        message=message + f"\n{e}",
                        commit=True,
                        db=db,
                    )
                    self.notify_user_of_landing_failure(job)
                    return True

            # Get the changeset titles for the stack.
            changeset_titles = (
                hgrepo.run_hg(["log", "-r", "stack()", "-T", "{desc|firstline}\n"])
                .decode("utf-8")
                .splitlines()
            )

            # Parse bug numbers from commits in the stack.
            bug_ids = [
                str(bug) for title in changeset_titles for bug in parse_bugs(title)
            ]

            # Run automated code formatters if enabled.
            if repo.autoformat_enabled:
                try:
                    replacements = hgrepo.format_stack(len(patch_bufs), bug_ids)

                    # If autoformatting added any changesets, note those in the job.
                    if replacements:
                        job.formatted_replacements = replacements

                except AutoformattingException as exc:
                    message = (
                        "Lando failed to format your patch for conformity with our "
                        "formatting policy. Please see the details below.\n\n"
                        f"{exc.details()}"
                    )

                    logger.exception(message)

                    job.transition_status(
                        LandingJobAction.FAIL, message=message, commit=True, db=db
                    )
                    self.notify_user_of_landing_failure(job)
                    return False

            # Get the changeset hash of the first node.
            commit_id = hgrepo.run_hg(["log", "-r", ".", "-T", "{node}"]).decode(
                "utf-8"
            )

            try:
                hgrepo.push(repo.push_path, bookmark=repo.push_bookmark or None)
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
            except LostPushRace:
                logger.info(f"LandingJob {job.id} lost push race, deferring")
                job.transition_status(
                    LandingJobAction.DEFER,
                    message=f"Lost push race when pushing to {repo.push_path}.",
                    commit=True,
                    db=db,
                )
                return False
            except Exception as e:
                message = f"Unexpected error while pushing to {repo.push_path}."
                job.transition_status(
                    LandingJobAction.FAIL, message=f"{message}\n{e}", commit=True, db=db
                )
                self.notify_user_of_landing_failure(job)
                return True

        job.transition_status(LandingJobAction.LAND, commit_id=commit_id)
        db.session.commit()

        # Extra steps for post-uplift landings.
        if repo.approval_required:
            try:
                # If we just landed an uplift, update the relevant bugs as appropriate.
                update_bugs_for_uplift(
                    repo.short_name,
                    hgrepo.read_checkout_file("config/milestone.txt"),
                    bug_ids,
                )
            except Exception as e:
                # The changesets will have gone through even if updating the bugs fails. Notify
                # the landing user so they are aware and can update the bugs themselves.
                self.notify_user_of_bug_update_failure(job, e)

        # Trigger update of repo in Phabricator so patches are closed quicker.
        # Especially useful on low-traffic repositories.
        self.phab_trigger_repo_update(repo.phab_identifier)

        return True
