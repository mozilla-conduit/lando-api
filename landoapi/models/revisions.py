# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""
This module provides the definitions for custom revision/diff warnings.

The `DiffWarning` model provides a warning that is associated with a particular
Phabricator diff that is associated with a particular revision.
"""

from datetime import datetime
import enum
import logging

from sqlalchemy.dialects.postgresql.json import JSONB

from landoapi.models.base import Base
from landoapi.storage import db
from landoapi.hgexports import build_patch_for_revision
from landoapi.phabricator import PhabricatorClient
import os

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
    revision_id = db.Column(db.Integer, nullable=False, unique=True)
    diff_id = db.Column(db.Integer, nullable=False)
    repo_name = db.Column(db.String(254), nullable=False)
    is_stale = db.Column(db.Boolean, default=True, nullable=False)

    patch = db.Column(db.Text, nullable=False, default="")
    data = db.Column(JSONB, nullable=False, default=dict)

    # TODO: Handle multiple revisions in a stack.

    def store_patch(self):
        phab = PhabricatorClient(
            os.getenv("PHABRICATOR_URL"), os.getenv("PHABRICATOR_UNPRIVILEGED_API_KEY")
        )
        raw_diff = phab.call_conduit("differential.getrawdiff", diffID=self.diff_id)
        patch = build_patch_for_revision(
            raw_diff,
            "Lando",
            "lando@lando",
            "System commit",
            int(datetime.now().timestamp()),
        )
        self.patch = patch
        db.session.add(self)
        db.session.commit()

    def serialize(self):
        return {
            "revision_id": self.revision_id,
            "diff_id": self.diff_id,
            "repo_name": self.repo_name,
            "is_stale": self.is_stale,
            "data": self.data,
        }


class DiffWarning(Base):
    """Represents a warning message associated with a particular diff and revision."""

    # A Phabricator revision and diff ID (NOTE: revision ID does not inlude a prefix.)
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
