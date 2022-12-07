# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import datetime
import enum
import logging
import os

from typing import Optional

import flask_sqlalchemy

from sqlalchemy.dialects.postgresql import array
from sqlalchemy.dialects.postgresql.json import JSONB

from landoapi.models.base import Base
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
    status = db.Column(
        db.Enum(LandingJobStatus), nullable=False, default=LandingJobStatus.SUBMITTED
    )

    # JSON object mapping string revision id of the form "<int>" (used because
    # json keys may not be integers) to integer diff id. This is used to
    # record the diff id used with each revision and make searching for
    # Transplants that match a set of revisions easy (such as those
    # in a stack).
    # e.g.
    #     {
    #         "1001": 1221,
    #         "1002": 1246,
    #         "1003": 1412
    #     }
    revision_to_diff_id = db.Column(JSONB, nullable=False)

    # JSON array of string revision ids of the form "<int>" (used to match
    # the string type of revision_to_diff_id keys) listing the order
    # of the revisions in the request from most ancestral to most
    # descendant.
    # e.g.
    #     ["1001", "1002", "1003"]
    revision_order = db.Column(JSONB, nullable=False)

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

    @property
    def landing_path(self):
        return [(int(r), self.revision_to_diff_id[r]) for r in self.revision_order]

    @property
    def head_revision(self):
        """Human-readable representation of the branch head's Phabricator revision ID."""
        assert (
            self.revision_order
        ), "head_revision should never be called without setting self.revision_order!"
        return "D" + self.revision_order[-1]

    @classmethod
    def revisions_query(cls, revisions):
        revisions = [str(int(r)) for r in revisions]
        return cls.query.filter(cls.revision_to_diff_id.has_any(array(revisions)))

    @classmethod
    def job_queue_query(cls, repositories=None, grace_seconds=DEFAULT_GRACE_SECONDS):
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
    def next_job_for_update_query(cls, repositories=None):
        """Return a query which selects the next job and locks the row."""
        q = cls.job_queue_query(repositories=repositories)

        # Returned rows should be locked for updating, this ensures the next
        # job can be claimed.
        q = q.with_for_update()

        return q

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

    def serialize(self):
        """Return a JSON compatible dictionary."""
        return {
            "id": self.id,
            "status": self.status.value,
            "landing_path": [
                {"revision_id": "D{}".format(r), "diff_id": self.revision_to_diff_id[r]}
                for r in self.revision_order
            ],
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
