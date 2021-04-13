# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import datetime
import logging

from sqlalchemy import or_, and_

from landoapi.models.base import Base
from landoapi.storage import db

logger = logging.getLogger(__name__)


class RepoNotice(Base):
    """A scheduled notice that is associated with a repository."""

    # This currently matches the keys in `landoapi.repos.REPO_CONFIG`.
    # In the future, a `Repo` model should be created to house repos.
    repo_identifier = db.Column(db.String(254), nullable=False)
    start_date = db.Column(db.DateTime(timezone=True), nullable=True)
    end_date = db.Column(db.DateTime(timezone=True), nullable=True)
    message = db.Column(db.Text(), default="")
    is_archived = db.Column(db.Boolean, default=False)

    # When set to `True`, results in a landing warning.
    is_warning = db.Column(db.Boolean, default=False)

    @classmethod
    def get_active_repo_notices(cls, repo_short_name):
        now = datetime.datetime.now()
        notices = (
            cls.query.filter(
                and_(cls.repo_identifier == repo_short_name, cls.is_archived == False)
            )
            .filter(
                or_(
                    and_(cls.start_date <= now, cls.end_date >= now),
                    and_(cls.start_date <= now, cls.end_date == None),
                    and_(cls.start_date == None, cls.end_date >= now),
                    and_(cls.start_date == None, cls.end_date == None),
                )
            )
            .order_by(cls.updated_at.desc())
        )
        return [n.serialize() for n in notices.all()]

    def serialize(self):
        data = super().serialize()
        data.update(
            {
                "repo_identifier": self.repo_identifier,
                "start_date": self.start_date.astimezone(
                    datetime.timezone.utc
                ).isoformat()
                if self.start_date
                else None,
                "end_date": self.end_date.astimezone(datetime.timezone.utc).isoformat()
                if self.end_date
                else None,
                "message": self.message,
                "is_archived": self.is_archived,
                "is_warning": self.is_warning,
            }
        )
        return data
