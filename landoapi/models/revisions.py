# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""
This module provides the definitions for custom revision/diff warnings.

The `DiffWarning` model provides a warning that is associated with a particular
Phabricator diff that is associated with a particular revision.
"""

from datetime import datetime
from pathlib import Path
import enum
import hashlib
import io
import json
import logging

from sqlalchemy.dialects.postgresql.json import JSONB

from landoapi.models.base import Base
from landoapi.storage import db

logger = logging.getLogger(__name__)


def calculate_patch_hash(patch: bytes) -> str:
    """Given a patch, calculate the sha1 hash and return the hex digest."""
    with io.BytesIO() as stream:
        stream.write(patch)
        return hashlib.sha1(stream.getvalue()).hexdigest()


@enum.unique
class DiffWarningStatus(enum.Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


@enum.unique
class DiffWarningGroup(enum.Enum):
    GENERAL = "GENERAL"
    LINT = "LINT"


@enum.unique
class RevisionStatus(enum.Enum):
    # New means this revision was just created.
    NEW = "NEW"

    # Stale means something changed upstream and we need to re-check this revision.
    STALE = "STALE"

    # Picked up means a revision worker has picked this up. This signals to other
    # workers to not pick up this particular revision. This is really just an
    # "in between" state.
    PICKED_UP = "PICKED_UP"

    # Ready for preprocessing means it can be picked up by the revision worker.
    READY_FOR_PREPROCESSING = "READY_FOR_PREPROCESSING"

    # Preprocessing means it is currently running through various checks.
    PREPROCESSING = "PREPROCESSING"

    # Problem means something went wrong in some of the checks.
    PROBLEM = "PROBLEM"

    # Ready means revision worker is finished and this revision can be queued to land.
    READY = "READY"

    # Below four statuses are describe the landing state.
    QUEUED = "QUEUED"
    LANDING = "LANDING"
    LANDED = "LANDED"
    FAILED = "FAILED"

    # Obsolete means this revision is not being picked up remotely any more.
    OBSOLETE = "OBSOLETE"

    @classmethod
    @property
    def LANDING_STATES(cls):
        return (cls.QUEUED, cls.LANDING, cls.LANDED)

    @classmethod
    @property
    def NON_READY_STATES(cls):
        return (cls.NEW, cls.STALE, cls.READY_FOR_PREPROCESSING, cls.PREPROCESSING)


class RevisionLandingJob(db.Model):
    landing_job_id = db.Column(db.ForeignKey("landing_job.id"), primary_key=True)
    revision_id = db.Column(db.ForeignKey("revision.id"), primary_key=True)
    index = db.Column(db.Integer, nullable=True)

    revision = db.relationship("Revision", back_populates="landing_jobs")
    landing_job = db.relationship("LandingJob", back_populates="revisions")


class Revision(Base):
    PATCH_DIRECTORY = Path("/patches")

    # revision_id and diff_id map to Phabricator IDs (integers).
    revision_id = db.Column(db.Integer, nullable=False, unique=True)
    diff_id = db.Column(db.Integer, nullable=False)

    # short name and callsign
    repo_name = db.Column(db.String(254), nullable=False, default="")
    repo_callsign = db.Column(db.String(254), nullable=False, default="")

    # If a landing is requested, this will be landed after it is in "READY" state.
    landing_requested = db.Column(db.Boolean, nullable=False, default=False)

    # Phabricator build target ID (PHID-HMBT-*).
    target = db.Column(db.String(254), nullable=False, default="")

    status = db.Column(
        db.Enum(RevisionStatus), nullable=False, default=RevisionStatus.NEW
    )

    patch_hash = db.Column(db.String(254), nullable=False, default="")
    data = db.Column(JSONB, nullable=False, default=dict)
    patch_data = db.Column(JSONB, nullable=False, default=dict)

    landing_jobs = db.relationship("RevisionLandingJob", back_populates="revision")

    predecessor_id = db.Column(db.Integer, db.ForeignKey("revision.id"), nullable=True)
    predecessor = db.relationship(
        "Revision", back_populates="successor", remote_side="Revision.id", uselist=False
    )
    successor = db.relationship("Revision", uselist=False)

    @classmethod
    def get_from_revision_id(cls, revision_id):
        return cls.query.filter(Revision.revision_id == revision_id).one()

    @property
    def stack_hashes(self):
        """Return a dictionary with diff and timestamp hashes.

        This property can be used to determine if something changed in the sequence of
        revisions.
        """
        # TODO: possibly add another a status hash, which hashes the sequence of
        # statuses. In that case, we can be more specific when detecting a change as
        # some revisions may have an updated timestamp but no meaningful change.
        stack = [r for r in (self.predecessors + self.successors)]
        diffs = " ".join([str(r.diff_id) for r in stack]).encode("utf-8")
        timestamps = " ".join([r.updated_at.isoformat() for r in stack]).encode("utf-8")
        diffs_hash = hashlib.sha1(diffs).hexdigest()
        timestamps_hash = hashlib.sha1(timestamps).hexdigest()
        return {"diffs": diffs_hash, "timestamps": timestamps_hash}

    @property
    def successors(self):
        """Return the current revision and all successors."""
        # TODO: rename this to "next sequence".
        successors = [self]
        if not self.successor:
            return successors

        revision = self
        while revision.successor:
            successors.append(revision.successor)
            revision = revision.successor
        return successors

    @property
    def predecessors(self):
        """Return all revisions that this revision depends on."""
        # TODO: rename this to "previous sequence".
        if not self.predecessor:
            return []

        predecessors = []
        revision = self
        while revision.predecessor:
            if revision.predecessor.status == RevisionStatus.LANDED:
                break
            predecessors.append(revision.predecessor)
            revision = revision.predecessor
        predecessors.reverse()
        return predecessors

    def get_patch(self):
        from landoapi.hgexports import build_patch_for_revision
        from landoapi.workers.revision_worker import call_conduit

        raw_diff = call_conduit("differential.getrawdiff", diffID=self.diff_id)
        patch_data = self.patch_data or {
            "author_name": "",
            "author_email": "",
            "commit_message": "This is an automated commit message.",
            "timestamp": int(datetime.now().timestamp()),
        }
        return build_patch_for_revision(raw_diff, **patch_data)

    def clear_patch_cache(self):
        if self.patch_cache_path.exists():
            self.patch_cache_path.unlink()
            return True
        return False

    @property
    def patch_cache_path(self):
        file_path = self.PATCH_DIRECTORY / f"{self.revision_id}_{self.diff_id}.diff"
        return file_path

    @property
    def patch(self):
        file_path = self.patch_cache_path
        if file_path.exists() and file_path.is_file():
            with file_path.open("r") as f:
                return f.read()
        patch = self.get_patch()
        with file_path.open("w") as f:
            f.write(patch)
        return patch

    def __repr__(self):
        """Return a human-readable representation of the instance."""
        return (
            f"<{self.__class__.__name__}: {self.id} "
            f"[D{self.revision_id}-{self.diff_id}]"
            f"[{self.status.value if self.status else ''}]>"
        )

    @classmethod
    def get_or_create(cls, revision_id, diff_id):
        """Fetches a revision if it exists, otherwise creates it."""
        lando_revision = cls.query.filter(
            cls.revision_id == revision_id, cls.diff_id == diff_id
        ).one_or_none()
        if not lando_revision:
            lando_revision = cls(
                revision_id=revision_id,
                diff_id=diff_id,
            )
            db.session.add(lando_revision)
            db.session.commit()
        return lando_revision

    def has_non_ready_revisions(self):
        return self.revisions.filter(Revision.status != RevisionStatus.READY).exists()

    def change_triggered(self, changes):
        """Check if any of the changes should trigger a status change."""
        keys = ("repo_name", "repo_callsign", "diff_id", "predecessor")
        data_keys = ("predecessor",)
        for key in keys:
            if key in data_keys:
                if self.data.get(key, None) != changes.get(key, None):
                    return True
            elif getattr(self, key, None) != changes.get(key, None):
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

    def update_data(self, **params):
        logger.info(f"Updating revision {self} data with {params}")
        if self.data:
            data = self.data.copy()
        else:
            data = {}
        data.update(params)
        self.data = data

    def store_patch_hash(self, patch):
        self.patch_hash = calculate_patch_hash(patch)
        db.session.commit()

    def verify_patch_hash(self, patch):
        patch_hash = calculate_patch_hash(patch)
        return self.patch_hash == patch_hash

    def serialize(self):
        return {
            "id": self.id,
            "revision_id": self.revision_id,
            "diff_id": self.diff_id,
            "repo_name": self.repo_name,
            "status": self.status.value,
            "data": self.data,
            "stack_hashes": json.dumps(self.stack_hashes),
        }


class DiffWarning(Base):
    """Represents a warning message associated with a particular diff and revision."""

    # A Phabricator revision and diff ID (NOTE: revision ID does not inlude a prefix.)
    revision_id = db.Column(db.Integer, nullable=False)
    diff_id = db.Column(db.Integer, nullable=False)

    # TODO: add foreign key to a Revision.

    # An arbitary dictionary of data that will be determined by the client.
    # It is up to the UI to interpret this data and show it to the user.
    data = db.Column(JSONB, nullable=False)

    # Whether the warning is active or archived. This is used in filters.
    status = db.Column(
        db.Enum(DiffWarningStatus), nullable=False, default=DiffWarningStatus.ACTIVE
    )

    # The "type" of warning. This is mainly to group warnings when querying the API.
    group = db.Column(db.Enum(DiffWarningGroup), nullable=False)

    # The code freeze dates generally correspond to PST work days.
    @property
    def code_freeze_offset(self) -> str:
        return "-0800"

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
