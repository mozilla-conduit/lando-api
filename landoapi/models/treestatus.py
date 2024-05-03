# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""
This module provides the definitions for Treestatus data.
"""

import copy
import enum
from typing import (
    Any,
)

from sqlalchemy.dialects.postgresql.json import JSONB
from sqlalchemy.orm import (
    relationship,
)

from landoapi.models.base import (
    Base,
    db,
)


class TreeCategory(enum.Enum):
    """Categories of the various trees.

    Note: the definition order is in order of importance for display in the UI.
    Note: this class also exists in Lando-UI, and should be updated in both places.
    """

    DEVELOPMENT = "development"
    RELEASE_STABILIZATION = "release_stabilization"
    TRY = "try"
    COMM_REPOS = "comm_repos"
    OTHER = "other"


class TreeStatus(enum.Enum):
    """Allowable statuses of a tree."""

    OPEN = "open"
    CLOSED = "closed"
    APPROVAL_REQUIRED = "approval required"

    def is_open(self) -> bool:
        """Return `True` if Lando should consider this status as open for landing.

        A repo is considered open for landing when the state is "open" or
        "approval required". For the "approval required" status Lando will enforce
        the appropriate Phabricator group review for approval (`release-managers`)
        and the hg hook will enforce `a=<reviewer>` is present in the commit message.
        """
        return self in {TreeStatus.OPEN, TreeStatus.APPROVAL_REQUIRED}


def get_default_tree():
    return {
        "category": TreeCategory.OTHER,
        "reason": "New tree",
        "status": TreeStatus.CLOSED,
        "tags": [],
        "log_id": None,
    }


def load_last_state(last_state_orig: dict) -> dict:
    """Ensure that structure of last_state is backwards compatible."""
    last_state = copy.deepcopy(last_state_orig)
    default_tree = get_default_tree()

    for field in [
        "status",
        "reason",
        "tags",
        "log_id",
        "current_status",
        "current_reason",
        "current_tags",
        "current_log_id",
    ]:
        if field in last_state:
            continue
        if field.startswith("current_"):
            last_state[field] = default_tree[field[len("current_") :]]
        else:
            last_state[field] = default_tree[field]

    return last_state


class Tree(Base):
    """A Tree that is managed via Treestatus."""

    # Name of the tree.
    tree = db.Column(db.String(64), index=True, unique=True, nullable=False)

    # The current status of the tree.
    status = db.Column(db.Enum(TreeStatus), default=TreeStatus.OPEN, nullable=False)

    # A string indicating the reason behind the current tree status.
    reason = db.Column(db.Text, default="", nullable=False)

    # A temporary message attached to the tree.
    message_of_the_day = db.Column(db.Text, default="", nullable=False)

    # A category assigned to the tree.
    category = db.Column(
        db.Enum(TreeCategory), default=TreeCategory.OTHER, nullable=False
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert a `Tree` into a `dict`, preserving `Enum` types."""
        return {
            "category": self.category,
            "message_of_the_day": self.message_of_the_day,
            "reason": self.reason,
            "status": self.status,
            "tree": self.tree,
        }

    def to_json(self) -> dict[str, Any]:
        """Convert a `Tree` into a JSON representation, converting enums to strings."""
        return {
            "category": self.category.value,
            "message_of_the_day": self.message_of_the_day,
            "reason": self.reason,
            "status": self.status.value,
            "tree": self.tree,
        }


class Log(Base):
    """A log of changes to a Tree."""

    # The name of the tree which this log entry belongs to.
    tree = db.Column(
        db.String(64), db.ForeignKey(Tree.tree), nullable=False, index=True
    )

    # A string representing the user who updated the tree.
    changed_by = db.Column(db.Text, nullable=False)

    # The status which the tree has been set to.
    status = db.Column(db.Enum(TreeStatus), nullable=False)

    # A string describing why the status has changed.
    reason = db.Column(db.Text, nullable=False)

    # A set of tags (strings) which are attached to this log entry.
    # The field is a JSON-encoded list.
    tags = db.Column(JSONB, nullable=False, default=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "reason": self.reason,
            "status": self.status.value,
            "tags": self.tags,
            "tree": self.tree,
            "when": self.created_at.isoformat(),
            "who": self.changed_by,
        }


class StatusChange(Base):
    """A change of status which applies to trees."""

    # The user who changed the tree status.
    changed_by = db.Column(db.Text, nullable=False)

    # A string describing the reason the tree's status was changed.
    reason = db.Column(db.Text, nullable=False)

    # The status the trees were changed to.
    status = db.Column(db.Enum(TreeStatus), nullable=False)

    # A back references to a `StatusChangeTree` list.
    trees: list["StatusChangeTree"] = relationship(
        "StatusChangeTree", back_populates="stack"
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "reason": self.reason,
            "status": self.status.value,
            "trees": [tree.to_dict() for tree in self.trees],
            "when": self.created_at.isoformat(),
            "who": self.changed_by,
        }


class StatusChangeTree(Base):
    """A tree (ie a "stack") of status changes."""

    # The StatusChange that corresponds to this tree.
    stack_id = db.Column(db.Integer, db.ForeignKey(StatusChange.id), index=True)

    # The name of the tree this StatusChange applies to.
    tree = db.Column(
        db.String(64), db.ForeignKey(Tree.tree), nullable=False, index=True
    )

    # A JSON object containing the previous state of the tree before
    # applying this change.
    last_state = db.Column(JSONB, nullable=False)

    # A backreference to the `StatusChange` model.
    stack: "StatusChange" = relationship("StatusChange", back_populates="trees")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "last_state": load_last_state(self.last_state),
            "tree": self.tree,
        }
