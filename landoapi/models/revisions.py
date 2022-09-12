# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""
This module provides the definitions for revisions and custom revision/diff warnings.
"""

from __future__ import annotations

from typing import Any

import enum
import logging

import networkx as nx
from sqlalchemy.dialects.postgresql.json import JSONB

from landoapi.hgexports import build_patch_for_revision
from landoapi.models.base import Base
from landoapi.phabricator import call_conduit
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


# Association table with custom "index" column to guarantee sorting of revisions.
# The diff_id column is used as a transaction record of the diff_id at landing time.
revision_landing_job = db.Table(
    "revision_landing_job",
    db.Column("landing_job_id", db.ForeignKey("landing_job.id")),
    db.Column("revision_id", db.ForeignKey("revision.id")),
    db.Column("index", db.Integer),
    db.Column("diff_id", db.Integer, nullable=True),
)


@enum.unique
class RevisionStatus(enum.Enum):
    # New means this revision was just created.
    NEW = "NEW"

    # Stale means something changed upstream and we need to re-check this revision.
    STALE = "STALE"

    # Waiting means it can be picked up by the revision worker.
    WAITING = "WAITING"

    # Picked up means a revision worker has picked this up. This signals to other
    # workers to not pick up this particular revision. This is really just an
    # "in between" state.
    PICKED_UP = "PICKED_UP"

    # Checking means it is currently running through various checks.
    CHECKING = "CHECKING"

    # Problem means something went wrong in some of the checks.
    PROBLEM = "PROBLEM"

    # Ready means revision worker is finished and this revision can be queued to land.
    READY = "READY"

    # Below four statuses describe the landing state.
    QUEUED = "QUEUED"  # LandingJob has been submitted
    LANDING = "LANDING"  # LandingWorker is processing job
    LANDED = "LANDED"  # LandingWorker is finished processing job
    FAILED = "FAILED"  # LandingWorker could not land job

    @classmethod
    @property
    def LANDING_STATES(cls):
        """States where the revision is in process of landing."""
        return (cls.QUEUED, cls.LANDING, cls.LANDED)

    @classmethod
    @property
    def NON_READY_STATES(cls):
        return (cls.NEW, cls.STALE, cls.WAITING, cls.CHECKING)


class Revision(Base):
    """
    A representation of a revision in the database referencing a Phabricator revision.
    """

    # revision_id and diff_id map to Phabricator IDs (integers).
    revision_id = db.Column(db.Integer, nullable=False, unique=True)

    # diff_id is that of the latest diff on the revision at landing request time. It
    # does not track all diffs.
    diff_id = db.Column(db.Integer, nullable=False)

    # The actual patch.
    patch_bytes = db.Column(db.LargeBinary, nullable=False, default=b"")
    patch_locked = db.Column(db.Boolean, nullable=False, default=False)

    # Patch metadata, such as author, timestamp, etc...
    patch_data = db.Column(JSONB, nullable=False, default=dict)

    landing_jobs = db.relationship(
        "LandingJob", secondary=revision_landing_job, back_populates="revisions"
    )

    status = db.Column(
        db.Enum(RevisionStatus), nullable=False, default=RevisionStatus.NEW
    )

    # short name and callsign
    repo_name = db.Column(db.String(254), nullable=False, default="")
    repo_callsign = db.Column(db.String(254), nullable=False, default="")

    data = db.Column(JSONB, nullable=False, default=dict)

    stack_graph = db.Column(JSONB, nullable=False, default=dict)

    def __repr__(self):
        """Return a human-readable representation of the instance."""
        return (
            f"<{self.__class__.__name__}: {self.id} "
            f"[D{self.revision_id}-{self.diff_id}] "
            f"[{self.status.value if self.status else ''}]>"
        )

    @classmethod
    def get_from_revision_id(cls, revision_id: int) -> "Revision":
        """Return a Revision object from a given ID."""
        return cls.query.filter(Revision.revision_id == revision_id).one()

    def set_patch(self, raw_diff: bytes, patch_data: dict[str, str], final=False):
        """Given a raw_diff and patch data, build the patch and store it."""
        if self.patch_locked:
            raise ValueError("Patch can not be modified.")

        self.patch_data = patch_data
        patch = build_patch_for_revision(raw_diff, **self.patch_data)
        self.patch_bytes = patch.encode("utf-8")
        if final:
            self.patch_locked = True
            db.session.commit()

    def set_temporary_patch(self) -> str:
        """
        Fetch the most up to date patch to be pre-processed.

        Fill in placeholder patch data if it is not available.
        """
        raw_diff = call_conduit("differential.getrawdiff", diffID=self.diff_id)
        patch_data = {
            "author_name": "",
            "author_email": "",
            "commit_message": "This is an automated commit message.",
            "timestamp": 0,
        }
        self.set_patch(raw_diff, patch_data, final=False)

    @property
    def stack(self):
        stack_graph = {
            Revision.get_from_revision_id(source): [
                Revision.get_from_revision_id(dest) for dest in dests
            ]
            for source, dests in self.stack_graph.items()
        }

        return nx.DiGraph(stack_graph).reverse()

    @property
    def successor(self):
        """Return a successor if there is only one, otherwise return None."""
        successors = self.stack.successors(self)
        if len(successors) == 1:
            return list(successors)[0]

    @property
    def predecessor(self):
        """Return a predecessor if there is only one, otherwise return None."""
        predecessors = list(self.stack.predecessors(self))
        if len(predecessors) == 1:
            return predecessors[0]

    @property
    def successors(self):
        """Return the current revision and all successors."""
        successors = nx.nodes(nx.dfs_tree(self.stack, self))
        return list(successors.keys())

    @property
    def predecessors(self):
        """Return all predecessors without current revision."""
        predecessors = list(nx.nodes(nx.dfs_tree(self.stack.reverse(), self)).keys())
        predecessors.reverse()
        return [
            predecessor
            for predecessor in predecessors
            if not predecessor.status == RevisionStatus.LANDED and predecessor != self
        ]

    @property
    def linear_stack(self):
        """Return a list of all successors and predecessors if linear.

        Stop at the first predecessor with multiple predecessors.
        Stop at the first successor with multiple successors.
        """
        stack = []

        predecessors = list(self.stack.predecessors(self))
        while predecessors:
            if len(predecessors) > 1:
                break
            predecessor = predecessors[0]
            stack.insert(0, predecessor)
            predecessors = list(self.stack.predecessors(predecessor))

        stack.append(self)

        successors = list(self.stack.successors(self))
        while successors:
            if len(successors) > 1:
                break
            successor = successors[0]
            stack.append(successor)
            successors = list(self.stack.successors(successor))

        return stack

    def change_triggered(self, changes):
        """Check if any of the changes should trigger a status change."""
        keys = ("repo_name", "repo_callsign", "diff_id", "stack_graph")
        for key in keys:
            old = getattr(self, key, None)
            new = changes.get(key, None)
            if type(old) == type(new) and type(old) == dict:
                if old != new:
                    logger.info(f"Change detected in {self} ({key}) {old} vs {new}")
                    return True
            elif str(old) != str(new):
                logger.info(f"Change detected in {self} ({key}) {old} vs {new}")
                return True
        return False

    def fail(self):
        """Clear relevant fields on revision when a landing job fails."""
        self.status = RevisionStatus.FAILED
        db.session.commit()

    def land(self):
        """Clear relevant fields on revision when a landing job fails."""
        self.status = RevisionStatus.LANDED
        db.session.commit()

    def ready(self):
        """Clear relevant fields on revision when a landing job fails."""
        self.status = RevisionStatus.READY
        db.session.commit()

    def update_data(self, **params):
        logger.info(f"Updating revision {self} data with {params}")
        if self.data:
            data = self.data.copy()
        else:
            data = {}
        data.update(params)
        self.data = data

    def serialize(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "revision_id": self.revision_id,
            "diff_id": self.diff_id,
            "repo_name": self.repo_name,
            "status": self.status.value,
            "data": self.data,
        }


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
