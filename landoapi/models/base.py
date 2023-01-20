# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import re

from sqlalchemy.ext.declarative import declared_attr

from landoapi.storage import db


# Regex to parse various forms of capitalizations/camel case into snake case.
table_name_re = re.compile("((?<=[a-z0-9])[A-Z]|(?!^)[A-Z](?=[a-z]))")


class Base(db.Model):
    """An abstract base model that provides common methods and columns."""

    __abstract__ = True

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=db.func.now()
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=db.func.now(),
        onupdate=db.func.now(),
    )

    @declared_attr
    def __tablename__(self) -> str:
        """Return a snake-case version of the class name as the table name.

        To override __tablename__, define this attribute as needed on your
        model.
        """
        return table_name_re.sub(r"_\1", self.__name__).lower()

    def __repr__(self) -> str:
        """Return a human-readable representation of the instance.

        For example, `<Transplant: 1235>`.
        """
        return f"<{self.__class__.__name__}: {self.id}>"
