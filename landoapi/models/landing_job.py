# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import datetime
import enum
import logging

from sqlalchemy.dialects.postgresql import array
from sqlalchemy.dialects.postgresql.json import JSONB

from landoapi.storage import db

logger = logging.getLogger(__name__)


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
    SUBMITTED = "submitted"

    # Actively being processed.
    IN_PROGRESS = "in_progress"

    # Automatic finished states.
    FAILED = "failed"
    LANDED = "landed"

    # Manually cancelled state.
    CANCELLED = "cancelled"


class LandingJob(db.Model):
    """State for a landing job."""

    __tablename__ = "landing_jobs"

    # Internal request ID.
    id = db.Column(db.Integer, primary_key=True)

    # The postgres enum column which this definition results in
    # uses an enum type where the order matches the order of
    # values at definition time. Since python `enum.Enum` is
    # ordered, the resulting column will have the same order
    # as the definition order of the enum. This can be relied
    # on for comparisons or things like queries with ORDER BY.
    status = db.Column(
        db.Enum(LandingJobStatus), nullable=False, default=LandingJobStatus.SUBMITTED
    )
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=db.func.now()
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=db.func.now(),
        onupdate=db.func.now(),
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

    # LDAP email of the user who requested transplant.
    requester_email = db.Column(db.String(254), nullable=False)

    # Lando's name for the repository.
    repository_name = db.Column(db.Text(), nullable=False)

    # URL of the repository revisions are to land to.
    repository_url = db.Column(db.Text(), default="")

    # Identifier for the most descendent commit created by this landing.
    landed_commit_id = db.Column(db.Text(), default="")

    # JSON list of bug ids tied to the revisions at creation time.
    bug_ids = db.Column(JSONB, nullable=False)

    # Number of attempts made to complete the job.
    attempts = db.Column(db.Integer, nullable=False, default=0)

    # Priority of the job. Higher values are processed first.
    priority = db.Column(db.Integer, nullable=False, default=0)

    def __repr__(self):
        return "<LandingJob: %s>" % self.id

    @property
    def landing_path(self):
        return [(int(r), self.revision_to_diff_id[r]) for r in self.revision_order]

    @property
    def head_revision(self):
        """Human-readable representation of the branch head's Phabricator revision ID.
        """
        assert (
            self.revision_order
        ), "head_revision should never be called without setting self.revision_order!"
        return "D" + self.revision_order[-1]

    @classmethod
    def revisions_query(cls, revisions):
        revisions = [str(int(r)) for r in revisions]
        return cls.query.filter(cls.revision_to_diff_id.has_any(array(revisions)))

    @classmethod
    def job_queue_query(cls, repositories=None):
        """Return a query which selects the queued jobs."""
        q = cls.query.filter(
            cls.status.in_([LandingJobStatus.IN_PROGRESS, LandingJobStatus.SUBMITTED])
        )

        if repositories:
            q = q.filter(cls.repository_name.in_(repositories))

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

    def landed(self, commit_id):
        """Mark the job as landed."""
        self.status = LandingJobStatus.LANDED
        self.landed_commit_id = commit_id

    def failed_transient(self, msg):
        """Mark the job as transiently failed."""
        self.status = LandingJobStatus.IN_PROGRESS
        self.error = msg

    def failed_permanent(self, msg):
        """Mark the job as permanently failed."""
        self.status = LandingJobStatus.FAILED
        self.error = msg

    def serialize(self):
        """Return a JSON compatible dictionary."""
        return {
            "id": self.id,
            "status": self.status.value,
            "landing_path": [
                {"revision_id": "D{}".format(r), "diff_id": self.revision_to_diff_id[r]}
                for r in self.revision_order
            ],
            "details": (
                self.error or self.result
                if self.status in (LandingJobStatus.FAILED, LandingJobStatus.CANCELLED)
                else self.result or self.error
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
