# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Models related to the sec-approval process.

See See https://wiki.mozilla.org/Security/Bug_Approval_Process.
"""

from sqlalchemy.dialects.postgresql.json import JSONB

from landoapi.models.base import Base
from landoapi.phabricator import PhabricatorClient
from landoapi.storage import db


class SecApprovalRequest(Base):
    """Represents an event that added a sec-approval comment to a revision."""

    __tablename__ = "secapproval_requests"

    # The revision ID that this event applies to.
    revision_id = db.Column(db.Integer, nullable=False, index=True)

    # The active diff PHID when sec-approval was requested.
    diff_phid = db.Column(db.Text, nullable=False)

    # A JSON array of string transaction PHIDs that may be sec-approval request
    # comments. An extra call to Phabricator needs to be made to tell if the
    # transaction PHID is for a Revision comment or for something else.
    #
    # e.g. ["PHID-XACT-DREV-abc123", "PHID-XACT-DREV-def345"]
    comment_candidates = db.Column(JSONB, nullable=False)

    @classmethod
    def build(cls, revision: dict, transactions: list[dict]) -> "SecApprovalRequest":
        """Build a `SecApprovalRequest` object for a transaction list.

        Args:
            revision: The Phabricator API revision object that we requested
                sec-approval for.
            transactions: A list Phabricator transaction data results related to the
                sec-approval event that we want to save.

        Returns:
            A `SecApprovalRequest` that is ready to be added to the session.
        """
        possible_comment_phids = []
        for transaction in transactions:
            phid = PhabricatorClient.expect(transaction, "phid")
            possible_comment_phids.append(phid)

        return cls(
            revision_id=revision["id"],
            diff_phid=PhabricatorClient.expect(revision, "fields", "diffPHID"),
            comment_candidates=possible_comment_phids,
        )

    @classmethod
    def most_recent_request_for_revision(cls, revision: dict) -> "SecApprovalRequest":
        """Return the most recent sec-approval request for a Phabricator Revision."""
        return (
            cls.query.filter_by(revision_id=revision["id"])
            .order_by(cls.created_at.desc())
            .first()
        )
