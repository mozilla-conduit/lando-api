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
class TransplantStatus(enum.Enum):
    """Status of the landing request."""

    # Legacy value
    aborted = "aborted"

    # Set from pingback
    submitted = "submitted"
    landed = "landed"
    failed = "failed"


class Transplant(db.Model):
    """Represents a request to Autoland Transplant."""

    __tablename__ = "transplants"

    # Internal request ID.
    id = db.Column(db.Integer, primary_key=True)

    # Autoland Transplant request ID.
    request_id = db.Column(db.Integer, unique=True)

    status = db.Column(
        db.Enum(TransplantStatus), nullable=False, default=TransplantStatus.aborted
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

    # Text describing errors when not landed.
    error = db.Column(db.Text(), default="")

    # Revision (sha) of the head of the push.
    result = db.Column(db.Text(), default="")

    # LDAP email of the user who requested transplant.
    requester_email = db.Column(db.String(254))

    # URL of the repository revisions are to land to.
    repository_url = db.Column(db.Text(), default="")

    # Treestatus tree name the revisions are to land to.
    tree = db.Column(db.String(128))

    def __repr__(self):
        return "<Transplant: %s>" % self.id

    def update_from_transplant(self, landed, error="", result=""):
        """Set the status from pingback request."""
        self.error = error
        self.result = result
        if not landed:
            self.status = (
                TransplantStatus.failed if error else TransplantStatus.submitted
            )
        else:
            self.status = TransplantStatus.landed

    @property
    def landing_path(self):
        return [(int(r), self.revision_to_diff_id[r]) for r in self.revision_order]

    @classmethod
    def revisions_query(cls, revisions):
        revisions = [str(int(r)) for r in revisions]
        return cls.query.filter(cls.revision_to_diff_id.has_any(array(revisions)))

    @classmethod
    def is_revision_submitted(cls, revision_id):
        """Check if revision is successfully submitted.

        Args:
            revision_id: The integer id of the revision.

        Returns:
            Transplant object or False if not submitted.
        """
        transplants = (
            cls.revisions_query([revision_id])
            .filter_by(status=TransplantStatus.submitted)
            .all()
        )

        if not transplants:
            return False

        return transplants[0]

    @classmethod
    def legacy_latest_landed(cls, revision_id):
        """DEPRECATED Return the latest Landing that is landed, or None.

        Args:
            revision_id: The integer id of the revision.

        Returns:
            Latest transplant object with status landed, or None if
            none exist.
        """
        return (
            cls.revisions_query([revision_id])
            .filter_by(status=TransplantStatus.landed)
            .order_by(cls.updated_at.desc())
            .first()
        )

    def serialize(self):
        """Return a JSON compatible dictionary."""
        return {
            "id": self.id,
            "request_id": self.request_id,
            "status": self.status.value,
            "landing_path": [
                {"revision_id": "D{}".format(r), "diff_id": self.revision_to_diff_id[r]}
                for r in self.revision_order
            ],
            "details": (
                self.error or self.result
                if self.status in (TransplantStatus.failed, TransplantStatus.aborted)
                else self.result or self.error
            ),
            "requester_email": self.requester_email,
            "tree": self.tree,
            "repository_url": self.repository_url,
            "created_at": (
                self.created_at.astimezone(datetime.timezone.utc).isoformat()
            ),
            "updated_at": (
                self.updated_at.astimezone(datetime.timezone.utc).isoformat()
            ),
        }

    def legacy_serialize(self):
        """DEPRECATED Serialize to JSON compatible dictionary."""

        revision_id = None
        diff_id = None
        if self.revision_order is not None:
            revision_id = self.revision_order[-1]

        if revision_id is not None and self.revision_to_diff_id is not None:
            diff_id = self.revision_to_diff_id.get(revision_id)

        return {
            "id": self.id,
            "revision_id": "D{}".format(revision_id),
            "request_id": self.request_id,
            "diff_id": diff_id,
            "active_diff_id": diff_id,
            "status": self.status.value,
            "error_msg": self.error,
            "result": self.result,
            "requester_email": self.requester_email,
            "tree": self.tree,
            "tree_url": self.repository_url or "",
            "created_at": (
                self.created_at.astimezone(datetime.timezone.utc).isoformat()
            ),
            "updated_at": (
                self.updated_at.astimezone(datetime.timezone.utc).isoformat()
            ),
        }
