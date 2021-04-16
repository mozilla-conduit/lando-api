# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import enum
import logging

from landoapi.models.base import Base
from landoapi.storage import db

logger = logging.getLogger(__name__)


@enum.unique
class VariableType(enum.Enum):
    BOOL = "BOOL"
    INT = "INT"
    STR = "STR"


class ConfigurationVariable(Base):
    key = db.Column(db.String, unique=True)
    raw_value = db.Column(db.String(254), default="")
    variable_type = db.Column(db.Enum(VariableType), default=VariableType.STR)

    @property
    def value(self):
        if self.variable_type == VariableType.BOOL:
            return self.raw_value.lower() in ("1", "true")
        elif self.variable_type == VariableType.INT:
            try:
                return int(self.raw_value)
            except ValueError:
                logger.error(f"Could not convert {self.raw_value} to an integer.")
        elif self.variable_type == VariableType.STR:
            return self.raw_value

    @classmethod
    def get(cls, key, default):
        record = cls.query.filter(cls.key == key).one_or_none()
        return record.value if record else default

    @classmethod
    def set(cls, key, variable_type, raw_value):
        record = cls.query.filter(cls.key == key).one_or_none()
        if record.variable_type == variable_type and record.raw_value == raw_value:
            logger.info(f"Configuration variable {key} is already set to {raw_value}.")
            return

        if not record:
            logger.info(f"Creating new configuration variable {key}.")
            record = cls()

        record.variable_type = variable_type
        record.raw_value = raw_value
        db.session.add(record)
        db.session.commit()
        logger.info(f"Configuration variable {key} set to {raw_value} ({record.value})")
        return record
