# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""
This module provides the definitions for Treestatus data.
"""

import json

from typing import (
    Any,
    Optional,
)

import sqlalchemy.ext.hybrid

from sqlalchemy.orm import (
    relationship,
)

from landoapi.models.base import (
    db,
    Base,
)

DEFAULT_TREE = {"reason": "New tree", "status": "closed", "tags": [], "log_id": None}


def load_last_state(last_state_str: str) -> dict:
    """Ensure that structure of last_state is backwards compatible."""
    last_state = json.loads(last_state_str)

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
            last_state[field] = DEFAULT_TREE[field[len("current_") :]]
        else:
            last_state[field] = DEFAULT_TREE[field]

    return last_state


class Tree(Base):
    """A Tree that is managed via Treestatus."""

    # Name of the tree.
    tree = db.Column(db.String(32), index=True, unique=True)

    # The current status of the tree.
    status = db.Column(db.String(64), default="open", nullable=False)

    # A string indicating the reason behind the current tree status.
    reason = db.Column(db.Text, default="", nullable=False)

    # A temporary message attached to the tree.
    message_of_the_day = db.Column(db.Text, default="", nullable=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_of_the_day": self.message_of_the_day,
            "reason": self.reason,
            "status": self.status,
            "tree": self.tree,
        }


class Log(Base):
    """A log of changes to a Tree."""

    # The name of the three which this log entry belongs to.
    tree = db.Column(db.String(32), nullable=False, index=True)

    # The timestamp the log entry was created.
    when = db.Column(db.DateTime(timezone=True), nullable=False, index=True)

    # A string representing the user who updated the tree.
    who = db.Column(db.Text, nullable=False)

    # The status which the tree has been set to.
    status = db.Column(db.String(64), nullable=False)

    # A string describing why the status has changed.
    reason = db.Column(db.Text, nullable=False)

    # A set of tags (strings) which are attached to this log entry.
    # The field is a JSON-encoded list.
    _tags = db.Column("tags", db.Text, nullable=False)

    def __init__(self, tags: Optional[list[str]] = None, **kwargs):
        if tags is not None:
            kwargs["_tags"] = json.dumps(tags)
        super(Log, self).__init__(**kwargs)

    @sqlalchemy.ext.hybrid.hybrid_property
    def tags(self) -> list[str]:
        """Handle conversion of the `tags` column to a list."""
        return json.loads(self._tags)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "reason": self.reason,
            "status": self.status,
            "tags": self.tags,
            "tree": self.tree,
            "when": self.when.isoformat(),
            "who": self.who,
        }


class StatusChange(Base):
    """A change of status which applies to trees."""

    # The user who changed the tree status.
    who = db.Column(db.Text, nullable=False)

    # A string describing the reason the tree's status was changed.
    reason = db.Column(db.Text, nullable=False)

    # The timestamp the status was changed.
    when = db.Column(db.DateTime(timezone=True), nullable=False, index=True)

    # The status the trees were changed to.
    status = db.Column(db.String(64), nullable=False)

    # A back references to a `StatusChangeTree` list.
    trees: list["StatusChangeTree"] = relationship(
        "StatusChangeTree", back_populates="stack"
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "reason": self.reason,
            "status": self.status,
            "trees": [tree.to_dict() for tree in self.trees],
            "when": self.when.isoformat(),
            "who": self.who,
        }


class StatusChangeTree(Base):
    """A tree (ie a "stack") of status changes."""

    # The StatusChange that corresponds to this tree.
    stack_id = db.Column(db.Integer, db.ForeignKey(StatusChange.id), index=True)

    # The name of the tree this StatusChange applies to.
    tree = db.Column(db.String(32), nullable=False, index=True)

    # A JSON encoded string containing the previous state of the tree before
    # applying this change.
    last_state = db.Column(db.Text, nullable=False)

    # A backreference to the `StatusChange` model.
    stack: "StatusChange" = relationship("StatusChange", back_populates="trees")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "last_state": load_last_state(self.last_state),
            "tree": self.tree,
        }
