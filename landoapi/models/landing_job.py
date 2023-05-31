# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import datetime
import enum
import logging
import os
from typing import (
    Any,
    Iterable,
    Optional,
)

import flask_sqlalchemy
from sqlalchemy import or_
from sqlalchemy.dialects.postgresql import array
from sqlalchemy.dialects.postgresql.json import JSONB

from landoapi.models.base import Base
from landoapi.models.revisions import Revision, revision_landing_job
from landoapi.storage import db

logger = logging.getLogger(__name__)

DEFAULT_GRACE_SECONDS = int(os.environ.get("DEFAULT_GRACE_SECONDS", 60 * 2))


@enum.unique
class LandingJobStatus(enum.Enum):
    """Status of a landing job.

    NOTE: The definiton order is important as this enum is
    used in a database column definition. This column is used in
    "ORDER BY" clauses when querying the table so any change to
    this class definition could break things. See the `status`
    column of `LandingJob`.
    """

    # Initial creation state.
    SUBMITTED = "SUBMITTED"

    # Actively being processed.
    IN_PROGRESS = "IN_PROGRESS"

    # Temporarily failed after processing
    DEFERRED = "DEFERRED"

    # Automatic finished states.
    FAILED = "FAILED"
    LANDED = "LANDED"

    # Manually cancelled state.
    CANCELLED = "CANCELLED"


@enum.unique
class LandingJobAction(enum.Enum):
    """Various actions that can be applied to a LandingJob.

    Actions affect the status and other fields on the LandingJob object.
    """

    # Land a job (i.e. success!)
    LAND = "LAND"

    # Defer landing to a later time (i.e. temporarily failed)
    DEFER = "DEFER"

    # A permanent issue occurred and this requires user intervention
    FAIL = "FAIL"

    # A user has requested a cancellation
    CANCEL = "CANCEL"


class LandingJob(Base):
    """State for a landing job."""

    # The postgres enum column which this definition results in
    # uses an enum type where the order matches the order of
    # values at definition time. Since python `enum.Enum` is
    # ordered, the resulting column will have the same order
    # as the definition order of the enum. This can be relied
    # on for comparisons or things like queries with ORDER BY.
    status = db.Column(db.Enum(LandingJobStatus), nullable=True, default=None)

    # revision_to_diff_id and revision_order are deprecated and kept for historical reasons.
    revision_to_diff_id = db.Column(JSONB, nullable=True)
    revision_order = db.Column(JSONB, nullable=True)

    # Text describing errors when status != LANDED.
    error = db.Column(db.Text(), default="")

    # Error details in a dictionary format, listing failed merges, etc...
    # E.g. {
    #    "failed_paths": [{"path": "...", "url": "..."}],
    #     "reject_paths": [{"path": "...", "content": "..."}]
    # }
    error_breakdown = db.Column(JSONB, nullable=True)

    # LDAP email of the user who requested transplant.
    requester_email = db.Column(db.String(254), nullable=False)

    # Lando's name for the repository.
    repository_name = db.Column(db.Text(), nullable=False)

    # URL of the repository revisions are to land to.
    repository_url = db.Column(db.Text(), default="")

    # Identifier for the most descendent commit created by this landing.
    landed_commit_id = db.Column(db.Text(), default="")

    # Number of attempts made to complete the job.
    attempts = db.Column(db.Integer, nullable=False, default=0)

    # Priority of the job. Higher values are processed first.
    priority = db.Column(db.Integer, nullable=False, default=0)

    # Duration of job from start to finish
    duration_seconds = db.Column(db.Integer, default=0)

    # JSON array of changeset hashes which replaced reviewed changesets
    # after autoformatting.
    # eg.
    #    ["", ""]
    formatted_replacements = db.Column(JSONB, nullable=True)

    # Identifier of the published commit which this job should land on top of.
    target_cset = db.Column(db.Text(), nullable=True)

    revisions = db.relationship(
        "Revision",
        secondary=revision_landing_job,
        back_populates="landing_jobs",
        order_by="revision_landing_job.columns.index",
    )

    @property
    def landed_revisions(self) -> dict:
        """Return revision and diff ID mapping associated with the landing job."""
        revision_ids = [revision.id for revision in self.revisions]
        revision_to_diff_ids_query = (
            revision_landing_job.select()
            .join(Revision)
            .where(
                revision_landing_job.c.revision_id.in_(revision_ids),
                revision_landing_job.c.landing_job_id == self.id,
            )
            .with_only_columns(Revision.revision_id, revision_landing_job.c.diff_id)
            .order_by(revision_landing_job.c.index)
        )
        return dict(list(db.session.execute(revision_to_diff_ids_query)))

    @property
    def serialized_landing_path(self):
        """Return landing path based on associated revisions or legacy fields."""
        if self.revisions:
            return [
                {
                    "revision_id": "D{}".format(revision_id),
                    "diff_id": diff_id,
                }
                for revision_id, diff_id in self.landed_revisions.items()
            ]
        else:
            return [
                {"revision_id": "D{}".format(r), "diff_id": self.revision_to_diff_id[r]}
                for r in self.revision_order
            ]

    @property
    def head_revision(self) -> str:
        """Human-readable representation of the branch head's Phabricator revision ID."""
        return f"D{self.revisions[-1].revision_id}"

    @classmethod
    def revisions_query(cls, revisions: Iterable[str]) -> flask_sqlalchemy.BaseQuery:
        """
        Return all landing jobs associated with a given list of revisions.

        Older records do not have associated revisions, but rather have a JSONB field
        that stores revisions and diff IDs. Both associated revisions and revisions that
        appear in the revision_to_diff_id are used to fetch landing jobs.
        """

        revisions = [str(int(r)) for r in revisions]
        return cls.query.filter(
            or_(
                cls.revisions.any(Revision.revision_id.in_(revisions)),
                cls.revision_to_diff_id.has_any(array(revisions)),
            )
        )

    @classmethod
    def job_queue_query(
        cls,
        repositories: Optional[Iterable[str]] = None,
        grace_seconds: int = DEFAULT_GRACE_SECONDS,
    ) -> flask_sqlalchemy.BaseQuery:
        """Return a query which selects the queued jobs.

        Args:
            repositories (iterable): A list of repository names to use when filtering
                the landing job search query.
            grace_seconds (int): Ignore landing jobs that were submitted after this
                many seconds ago.
        """
        applicable_statuses = (
            LandingJobStatus.SUBMITTED,
            LandingJobStatus.IN_PROGRESS,
            LandingJobStatus.DEFERRED,
        )
        q = cls.query.filter(cls.status.in_(applicable_statuses))

        if repositories:
            q = q.filter(cls.repository_name.in_(repositories))

        if grace_seconds:
            now = datetime.datetime.now(datetime.timezone.utc)
            grace_cutoff = now - datetime.timedelta(seconds=grace_seconds)
            q = q.filter(cls.created_at < grace_cutoff)

        # Any `LandingJobStatus.IN_PROGRESS` job is first and there should
        # be a maximum of one (per repository). For
        # `LandingJobStatus.SUBMITTED` jobs, higher priority items come first
        # and then we order by creation time (older first).
        q = q.order_by(cls.status.desc(), cls.priority.desc(), cls.created_at)

        return q

    @classmethod
    def next_job_for_update_query(
        cls, repositories: Optional[str] = None
    ) -> flask_sqlalchemy.BaseQuery:
        """Return a query which selects the next job and locks the row."""
        query = cls.job_queue_query(repositories=repositories)

        # Returned rows should be locked for updating, this ensures the next
        # job can be claimed.
        query = query.with_for_update()

        return query

    def add_revisions(self, revisions: list[Revision]):
        """Associate a list of revisions with job."""
        for revision in revisions:
            self.revisions.append(revision)

    def sort_revisions(self, revisions: list[Revision]):
        """Sort the associated revisions based on provided list."""
        if len(revisions) != len(self.revisions):
            raise ValueError("List of revisions does not match associated revisions")

        # Update association table records with correct index values.
        for index, revision in enumerate(revisions):
            db.session.execute(
                revision_landing_job.update()
                .where(revision_landing_job.c.landing_job_id == self.id)
                .where(
                    revision_landing_job.c.revision_id == revision.id,
                )
                .values(index=index)
            )

    def set_landed_revision_diffs(self):
        """Assign diff_ids, if available, to each association row."""
        # Update association table records with current diff_id values.
        for revision in self.revisions:
            db.session.execute(
                revision_landing_job.update()
                .where(
                    revision_landing_job.c.landing_job_id == self.id,
                    revision_landing_job.c.revision_id == revision.id,
                )
                .values(diff_id=revision.diff_id)
            )

    def transition_status(
        self,
        action: LandingJobAction,
        commit: bool = False,
        db: Optional[flask_sqlalchemy.SQLAlchemy] = None,
        **kwargs,
    ):
        """Change the status and other applicable fields according to actions.

        Args:
            action (LandingJobAction): the action to take, e.g. "land" or "fail"
            commit (bool): whether to commit the changes to the database or not
            db (SQLAlchemy.db): the database to commit to
            **kwargs:
                Additional arguments required by each action, e.g. `message` or
                `commit_id`.
        """
        actions = {
            LandingJobAction.LAND: {
                "required_params": ["commit_id"],
                "status": LandingJobStatus.LANDED,
            },
            LandingJobAction.FAIL: {
                "required_params": ["message"],
                "status": LandingJobStatus.FAILED,
            },
            LandingJobAction.DEFER: {
                "required_params": ["message"],
                "status": LandingJobStatus.DEFERRED,
            },
            LandingJobAction.CANCEL: {
                "required_params": [],
                "status": LandingJobStatus.CANCELLED,
            },
        }

        if action not in actions:
            raise ValueError(f"{action} is not a valid action")

        required_params = actions[action]["required_params"]
        if sorted(required_params) != sorted(kwargs.keys()):
            missing_params = required_params - kwargs.keys()
            raise ValueError(f"Missing {missing_params} params")

        if commit and db is None:
            raise ValueError("db is required when commit is set to True")

        self.status = actions[action]["status"]

        if action in (LandingJobAction.FAIL, LandingJobAction.DEFER):
            self.error = kwargs["message"]

        if action == LandingJobAction.LAND:
            self.landed_commit_id = kwargs["commit_id"]

        if commit:
            db.session.commit()

    def serialize(self) -> dict[str, Any]:
        """Return a JSON compatible dictionary."""
        return {
            "id": self.id,
            "status": self.status.value,
            "landing_path": self.serialized_landing_path,
            "error_breakdown": self.error_breakdown,
            "details": (
                self.error or self.landed_commit_id
                if self.status in (LandingJobStatus.FAILED, LandingJobStatus.CANCELLED)
                else self.landed_commit_id or self.error
            ),
            "requester_email": self.requester_email,
            "tree": self.repository_name,
            "repository_url": self.repository_url,
            "created_at": (
                self.created_at.astimezone(datetime.timezone.utc).isoformat()
            ),
            "updated_at": (
                self.updated_at.astimezone(datetime.timezone.utc).isoformat()
            ),
        }


def add_job_with_revisions(revisions: list[Revision], **params: Any) -> LandingJob:
    """Creates a new job and associates provided revisions with it."""
    job = LandingJob(**params)
    db.session.add(job)
    add_revisions_to_job(revisions, job)
    return job


def add_revisions_to_job(revisions: list[Revision], job: LandingJob):
    """Given an existing job, add and sort provided revisions."""
    job.add_revisions(revisions)
    db.session.commit()
    job.sort_revisions(revisions)
    db.session.commit()
