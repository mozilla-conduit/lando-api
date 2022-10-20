# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from io import BytesIO
import logging
import re

import hglib
import kombu

from landoapi.hg import (
    HgRepo,
    LostPushRace,
    NoDiffStartLine,
    PatchConflict,
    TreeApprovalRequired,
    TreeClosed,
    REJECTS_PATH,
)
from landoapi.models.landing_job import LandingJob, LandingJobStatus, LandingJobAction
from landoapi.notifications import (
    notify_user_of_bug_update_failure,
    notify_user_of_landing_failure,
)
from landoapi.models.revisions import Revision, RevisionStatus
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
from landoapi.workers import Worker

logger = logging.getLogger(__name__)


@contextmanager
def job_processing(job: LandingJob, db: SQLAlchemy):
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
    PAUSE_KEY = "LANDING_WORKER_PAUSED"
    STOP_KEY = "LANDING_WORKER_STOPPED"

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
            self.throttle(self.sleep_seconds)
            return

        with job_processing(job, db):
            job.status = LandingJobStatus.IN_PROGRESS
            job.attempts += 1

            # Make sure the status and attempt count are updated in the database
            db.session.commit()

            repo = repo_clone_subsystem.repos[job.repository_name]
            hgrepo = HgRepo(
                str(repo_clone_subsystem.repo_paths[job.repository_name]),
                config=repo.config_override,
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

    def process_merge_conflict(self, exception, repo, hgrepo, revision_id):
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
        """Run a job.

        Returns: False if the job should be retried, True otherwise.
        """
        if not treestatus.is_open(repo.tree):
            job.transition_status(
                LandingJobAction.DEFER,
                message=f"Tree {repo.tree} is closed - retrying later.",
                commit=True,
                db=db,
            )
            return False

        # Landing worker can wait for revision worker to mark everything as "READY"
        # before continuing with the landing. To do this, we can loop and wait until all
        # revisions are marked as ready. In the future this will need to also account for
        # merge conflicts within the context of a stack.

        if repo.use_revision_worker and job.has_non_ready_revisions():
            job.transition_status(
                LandingJobAction.DEFER,
                message=f"{job} has non ready revisions - retrying later.",
                commit=True,
                db=db,
            )
            return False

        with hgrepo.for_push(job.requester_email):
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

            # Load all patches.
            patch_bufs = []
            for revision in job.get_revisions():
                patch = revision.patch.encode("utf-8")
                if not revision.verify_patch_hash(patch):
                    message = "Aborting, patch has changed since landing trigger."
                    logger.error(message)
                    job.transition_status(
                        LandingJobAction.FAIL,
                        message=message,
                        commit=True,
                        db=db,
                    )
                    self.notify_user_of_landing_failure(job)
                    job.fail_revisions()
                    # TODO makes sure that repos that do not use
                    # revision worker will force-update patch on
                    # next request.
                    return True
                patch_bufs.append((revision, patch))

            for revision, patch in patch_bufs:
                try:
                    hgrepo.apply_patch(BytesIO(patch))
                except PatchConflict as exc:
                    breakdown = self.process_merge_conflict(exc, repo, hgrepo, revision)
                    message = (
                        f"Problem while applying patch in revision {revision.revision_id}:\n\n"
                        f"{str(exc)}"
                    )
                    job.error_breakdown = breakdown

                    job.transition_status(
                        LandingJobAction.FAIL, message=message, commit=True, db=db
                    )
                    self.notify_user_of_landing_failure(job)
                    job.fail_revisions()
                    db.session.commit()
                    return True
                except Exception as e:
                    # verify below line
                    if e is NoDiffStartLine:
                        message = (
                            "Lando encountered a malformed patch, please try again. "
                            "If this error persists please file a bug: "
                            "Patch without a diff start line."
                        )
                    else:
                        message = (
                            f"Aborting, could not apply patch buffer for "
                            f"{revision.revision_id}, {revision.diff_id}."
                        )
                    logger.exception(message)
                    job.transition_status(
                        LandingJobAction.FAIL,
                        message=message + f"\n{e}",
                        commit=True,
                        db=db,
                    )
                    job.fail_revisions()
                    db.session.commit()
                    self.notify_user_of_landing_failure(job)
                    return True
                revision.status = RevisionStatus.LANDING
                db.session.commit()

            # Run `hg fix` configured formatters if enabled
            if repo.autoformat_enabled:
                try:
                    replacements = hgrepo.format()

                    # If autoformatting changed any changesets, note those in the job.
                    if replacements:
                        job.formatted_replacements = replacements

                except hglib.error.CommandError as exc:
                    message = (
                        "Lando failed to format your patch for conformity with our "
                        "formatting policy. Please see the details below.\n\n"
                        f"{str(exc)}"
                    )

                    logger.exception(message)

                    job.transition_status(
                        LandingJobAction.FAIL, message=message, commit=True, db=db
                    )
                    self.notify_user_of_landing_failure(job)
                    job.fail_revisions()
                    db.session.commit()
                    return False

            # Get the changeset hash of the first node.
            commit_id = hgrepo.run_hg(["log", "-r", ".", "-T", "{node}"]).decode(
                "utf-8"
            )

            # Get the changeset titles for the stack. We do this here since the
            # changesets will not be part of the `stack()` revset after pushing.
            changeset_titles = (
                hgrepo.run_hg(["log", "-r", "stack()", "-T", "{desc|firstline}\n"])
                .decode("utf-8")
                .splitlines()
            )
            temporary_exceptions = {
                TreeClosed: f"Tree {repo.tree} is closed - retrying later.",
                TreeApprovalRequired: f"Tree {repo.tree} requires approval - retrying later.",
                LostPushRace: f"Lost push race when pushing to {repo.push_path}.",
            }

            try:
                hgrepo.push(repo.push_path, bookmark=repo.push_bookmark or None)
            except Exception as e:
                try_again = e.__class__ in temporary_exceptions
                message = temporary_exceptions.get(
                    e.__class__, f"Unexpected error while pushing to {repo.push_path}."
                )

                if try_again:
                    job.transition_status(
                        LandingJobAction.DEFER, message=message, commit=True, db=db
                    )
                else:
                    job.transition_status(
                        LandingJobAction.FAIL,
                        message=f"{message}\n{e}",
                        commit=True,
                        db=db,
                    )
                    self.notify_user_of_landing_failure(job)
                    job.fail_revisions()
                return not try_again

        job.land_revisions()
        job.transition_status(LandingJobAction.LAND, commit_id=commit_id)
        db.session.commit()

        # Extra steps for post-uplift landings.
        if repo.approval_required:
            try:
                # If we just landed an uplift, update the relevant bugs as appropriate.
                update_bugs_for_uplift(
                    repo.short_name,
                    hgrepo.read_checkout_file("config/milestone.txt"),
                    changeset_titles,
                )
            except Exception as e:
                # The changesets will have gone through even if updating the bugs fails. Notify
                # the landing user so they are aware and can update the bugs themselves.
                self.notify_user_of_bug_update_failure(job, e)

        # TODO: fix this query, it is too broad.
        # We only need to mark revisions that may be affected by this job as stale.
        stale_revisions = Revision.query.filter(
            Revision.status != RevisionStatus.LANDED,
            Revision.repo_name == job.repository_name,
        )
        stale_revisions.update({"status": RevisionStatus.STALE})
        db.session.commit()
        # Stale comment?
        # stopped here -- need to add commit to every data update, and figure out
        # why status enum is not being set correctly.

        # Trigger update of repo in Phabricator so patches are closed quicker.
        # Especially useful on low-traffic repositories.
        self.phab_trigger_repo_update(repo.phab_identifier)

        return True
