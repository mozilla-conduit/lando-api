# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import datetime
import enum
import logging

from sqlalchemy.dialects.postgresql import array
from sqlalchemy.dialects.postgresql.json import JSONB

from landoapi.models.base import Base
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


class Transplant(Base):
    """Represents a request to Autoland Transplant."""

    __tablename__ = "transplants"

    # Autoland Transplant request ID.
    request_id = db.Column(db.Integer, unique=True)

    status = db.Column(
        db.Enum(TransplantStatus), nullable=False, default=TransplantStatus.aborted
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
