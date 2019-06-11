# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Models related to the sec-approval process.

See See https://wiki.mozilla.org/Security/Bug_Approval_Process.
"""

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from landoapi.storage import db


class SecApprovalRevision(db.Model):
    """Represents a revision that has a secure commit message comment."""

    __tablename__ = "secapproval_revisions"

    id = db.Column(db.Integer, primary_key=True)

    # The Phabricator revision PHID that has a sec-approval request.
    phid = db.Column(db.String(128), nullable=False, unique=True)

    review_requests = relationship("SecApprovalRequestEvent", back_populates="revision")


class SecApprovalRequestEvent(db.Model):
    """Represents an event that added a sec-approval comment to a revision."""

    __tablename__ = "secapproval_request_events"

    id = db.Column(db.Integer, primary_key=True)

    # The revision that this event applies to.
    revision_id = db.Column(
        db.Integer, db.ForeignKey("secapproval_revisions.id"), nullable=False
    )

    # Timestamp used to find the latest event in the series.
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=db.func.now()
    )

    revision = relationship("SecApprovalRevision", back_populates="review_requests")

    comment_candidates = db.Column(JSONB, nullable=False)
