# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
from __future__ import annotations

import logging
import re
from contextlib import contextmanager
from datetime import datetime
from io import BytesIO
from typing import Any

import kombu

from landoapi.commit_message import parse_bugs
from landoapi.hg import (
    REJECTS_PATH,
    AutoformattingException,
    HgRepo,
    LostPushRace,
    NoDiffStartLine,
    PatchConflict,
    TreeApprovalRequired,
    TreeClosed,
)
from landoapi.models.configuration import ConfigurationKey
from landoapi.models.landing_job import LandingJob, LandingJobAction, LandingJobStatus
from landoapi.notifications import (
    notify_user_of_bug_update_failure,
    notify_user_of_landing_failure,
)
from landoapi.repos import (
    Repo,
    repo_clone_subsystem,
)
from landoapi.storage import SQLAlchemy, db
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
    def STOP_KEY(self) -> ConfigurationKey:
        """Return the configuration key that prevents the worker from starting."""
        return ConfigurationKey.LANDING_WORKER_STOPPED

    @property
    def PAUSE_KEY(self) -> ConfigurationKey:
        """Return the configuration key that pauses the worker."""
        return ConfigurationKey.LANDING_WORKER_PAUSED

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_job_finished = None
        self.refresh_enabled_repos()

    def loop(self):
        logger.debug(
            f"{len(self.applicable_repos)} applicable repos: {self.applicable_repos}"
        )

        # Check if any closed trees reopened since the beginning of this iteration
        if len(self.enabled_repos) != len(self.applicable_repos):
            self.refresh_enabled_repos()

        if self.last_job_finished is False:
            logger.info("Last job did not complete, sleeping.")
            self.throttle(self.sleep_seconds)
            self.refresh_enabled_repos()

        job = LandingJob.next_job_for_update_query(
            repositories=self.enabled_repos
        ).first()

        if job is None:
            db.session.commit()
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

    def process_merge_conflict(
        self,
        exception: PatchConflict,
        repo: Repo,
        hgrepo: HgRepo,
        revision_id: int,
    ) -> dict[str, Any]:
        """Extract and parse merge conflict data from exception into a usable format."""
        failed_paths, reject_paths = self.extract_error_data(str(exception))

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
                "path": path[0],
                "url": f"{repo.pull_path}/file/{path[1].decode('utf-8')}/{path[0]}",
                "changeset_id": path[1].decode("utf-8"),
            }
            for path in failed_path_changesets
        ]
        breakdown["reject_paths"] = {}
        for path in reject_paths:
            reject = {"path": path}
            try:
                with open(REJECTS_PATH / hgrepo.path[1:] / path, "r") as f:
                    reject["content"] = f.read()
            except Exception as e:
                logger.exception(e)
            # Use actual path of file to store reject data, by removing
            # `.rej` extension.
            breakdown["reject_paths"][path[:-4]] = reject
        return breakdown

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
    ) -> bool:
        """Run a given LandingJob and return appropriate boolean state.

        Running a landing job goes through the following steps:
        - Check treestatus.
        - Update local repo with latest and prepare for import.
        - Apply each patch to the repo.
        - Perform additional processes and checks (e.g., code formatting).
        - Push changes to remote repo.

        Returns:
            True: The job finished processing and is in a permanent state.
            False: The job encountered a temporary failure and should be tried again.
        """
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
                hgrepo.update_repo(repo.pull_path, target_cset=job.target_cset)
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

            # Run through the patches one by one and try to apply them.
            for revision in job.revisions:
                patch_buf = BytesIO(revision.patch_bytes)

                try:
                    hgrepo.apply_patch(patch_buf)
                except PatchConflict as exc:
                    breakdown = self.process_merge_conflict(
                        exc, repo, hgrepo, revision.revision_id
                    )
                    job.error_breakdown = breakdown

                    message = (
                        f"Problem while applying patch in revision {revision.revision_id}:\n\n"
                        f"{str(exc)}"
                    )
                    job.transition_status(
                        LandingJobAction.FAIL, message=message, commit=True, db=db
                    )
                    self.notify_user_of_landing_failure(job)
                    return True
                except NoDiffStartLine:
                    message = (
                        "Lando encountered a malformed patch, please try again. "
                        "If this error persists please file a bug: "
                        "Patch without a diff start line."
                    )
                    logger.error(message)
                    job.transition_status(
                        LandingJobAction.FAIL,
                        message=message,
                        commit=True,
                        db=db,
                    )
                    self.notify_user_of_landing_failure(job)
                    return True
                except Exception as e:
                    message = (
                        f"Aborting, could not apply patch buffer for {revision.revision_id}."
                        f"\n{e}"
                    )
                    logger.exception(message)
                    job.transition_status(
                        LandingJobAction.FAIL,
                        message=message,
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
                    replacements = hgrepo.format_stack(len(changeset_titles), bug_ids)

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

            repo_info = f"tree: {repo.tree}, push path: {repo.push_path}"
            try:
                hgrepo.push(
                    repo.push_path,
                    bookmark=repo.push_bookmark or None,
                    force_push=repo.force_push,
                )
            except (TreeClosed, TreeApprovalRequired, LostPushRace) as e:
                message = (
                    f"`Temporary error ({e.__class__}) "
                    f"encountered while pushing to {repo_info}"
                )
                job.transition_status(
                    LandingJobAction.DEFER, message=message, commit=True, db=db
                )
                return False  # Try again, this is a temporary failure.
            except Exception as e:
                message = f"Unexpected error while pushing to {repo.push_path}.\n{e}"
                job.transition_status(
                    LandingJobAction.FAIL,
                    message=message,
                    commit=True,
                    db=db,
                )
                self.notify_user_of_landing_failure(job)
                return True  # Do not try again, this is a permanent failure.

        job.transition_status(
            LandingJobAction.LAND, commit_id=commit_id, commit=True, db=db
        )

        # Extra steps for post-uplift landings.
        if repo.approval_required:
            try:
                # If we just landed an uplift, update the relevant bugs as appropriate.
                update_bugs_for_uplift(
                    repo.short_name,
                    hgrepo.read_checkout_file("config/milestone.txt"),
                    repo.milestone_tracking_flag_template,
                    bug_ids,
                )
            except Exception as e:
                # The changesets will have gone through even if updating the bugs fails. Notify
                # the landing user so they are aware and can update the bugs themselves.
                self.notify_user_of_bug_update_failure(job, e)

        # Trigger update of repo in Phabricator so patches are closed quicker.
        # Especially useful on low-traffic repositories.
        if repo.phab_identifier:
            self.phab_trigger_repo_update(repo.phab_identifier)

        return True
