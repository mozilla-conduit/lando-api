# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""
This module provides the definitions for custom revision/diff warnings.

The `DiffWarning` model provides a warning that is associated with a particular
Phabricator diff that is associated with a particular revision.
"""

from __future__ import annotations

import enum
import logging

from sqlalchemy.dialects.postgresql.json import JSONB

from landoapi.hgexports import build_patch_for_revision
from landoapi.models.base import Base
from landoapi.storage import db

logger = logging.getLogger(__name__)


@enum.unique
class DiffWarningStatus(enum.Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


@enum.unique
class DiffWarningGroup(enum.Enum):
    GENERAL = "GENERAL"
    LINT = "LINT"


class Revision(Base):
    """
    A representation of a revision in the database referencing a Phabricator revision.
    """

    # revision_id and diff_id map to Phabricator IDs (integers).
    revision_id = db.Column(db.Integer, nullable=False, unique=True)
    diff_id = db.Column(db.Integer, nullable=False)

    # The actual patch.
    patch_bytes = db.Column(db.LargeBinary, nullable=False, default=b"")

    # Patch metadata, such as author, timestamp, etc...
    patch_data = db.Column(JSONB, nullable=False, default=dict)

    def __repr__(self):
        """Return a human-readable representation of the instance."""
        return (
            f"<{self.__class__.__name__}: {self.id} "
            f"[D{self.revision_id}-{self.diff_id}]>"
        )

    @classmethod
    def get_from_revision_id(cls, revision_id: int) -> "Revision" | None:
        """Return a Revision object from a given ID."""
        return cls.query.filter(Revision.revision_id == revision_id).one_or_none()

    def set_patch(self, raw_diff: bytes, patch_data: dict[str, str]):
        """Given a raw_diff and patch data, build the patch and store it."""
        self.patch_data = patch_data
        patch = build_patch_for_revision(raw_diff, **self.patch_data)
        self.patch_bytes = patch.encode("utf-8")


class DiffWarning(Base):
    """Represents a warning message associated with a particular diff and revision."""

    # A Phabricator revision and diff ID (NOTE: revision ID does not include a prefix.)
    revision_id = db.Column(db.Integer, nullable=False)
    diff_id = db.Column(db.Integer, nullable=False)

    # An arbitary dictionary of data that will be determined by the client.
    # It is up to the UI to interpret this data and show it to the user.
    data = db.Column(JSONB, nullable=False)

    # Whether the warning is active or archived. This is used in filters.
    status = db.Column(
        db.Enum(DiffWarningStatus), nullable=False, default=DiffWarningStatus.ACTIVE
    )

    # The "type" of warning. This is mainly to group warnings when querying the API.
    group = db.Column(db.Enum(DiffWarningGroup), nullable=False)

    def serialize(self):
        """Return a JSON serializable dictionary."""
        return {
            "id": self.id,
            "diff_id": self.diff_id,
            "revision_id": self.revision_id,
            "status": self.status.value,
            "group": self.group.value,
            "data": self.data,
        }
