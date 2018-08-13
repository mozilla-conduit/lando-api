# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import enum
import logging

from landoapi.storage import db

logger = logging.getLogger(__name__)


@enum.unique
class LandingStatus(enum.Enum):
    """DEPRECATED"""
    # Default value - stays in database only if landing request was aborted.
    aborted = 'aborted'

    # Set from pingback
    submitted = 'submitted'
    landed = 'landed'
    failed = 'failed'


class Landing(db.Model):
    """DEPRECATED

    This model has been replaced by landoapi.models.transplant.Transplant
    and has been kept around as part of data migration. In the future when
    migration has been completed this may been cleaned up and dropped from
    the database with another migration.
    """
    __tablename__ = "landings"

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, unique=True)
    revision_id = db.Column(db.Integer)
    diff_id = db.Column(db.Integer)
    active_diff_id = db.Column(db.Integer)
    status = db.Column(
        db.Enum(LandingStatus), nullable=False, default=LandingStatus.aborted
    )
    error = db.Column(db.Text(), default='')
    result = db.Column(db.Text(), default='')
    requester_email = db.Column(db.String(254))
    tree = db.Column(db.String(128))
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=db.func.now()
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=db.func.now(),
        onupdate=db.func.now()
    )
