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
    """Types that will be used to determine what to parse string values into."""

    BOOL = "BOOL"
    INT = "INT"
    STR = "STR"


class ConfigurationVariable(Base):
    """An arbitrary key-value table store that can be used to configure the system.
    """

    key = db.Column(db.String, unique=True)
    raw_value = db.Column(db.String(254), default="")
    variable_type = db.Column(db.Enum(VariableType), default=VariableType.STR)

    @property
    def value(self):
        """The parsed value of `raw_value` based on `variable_type`.

        Returns:
            If `variable_type` is set to `VariableType.BOOL`, then `raw_value` is
            checked against a list of "truthy" values and a boolean is returned. If it
            is set to `VariableType.INT`, then `raw_value` is converted to an integer
            before being returned. Otherwise, if it is set to `VariableType.STR`,
            `raw_value` is returned as the original string.

        Raises:
            `ValueError`: If `variable_type` is set to `INT`, but `raw_value` is not a
            string representing an integer.
        """
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
        """Fetch a variable using `key`, return `default` if it does not exist.

        Returns: The parsed value of the configuration variable, of type `str`, `int`,
            or `bool`.
        """
        record = cls.query.filter(cls.key == key).one_or_none()
        return record.value if record else default

    @classmethod
    def set(cls, key, variable_type, raw_value):
        """Set a variable `key` of type `variable_type` and value `raw_value`.

        Returns:
            ConfigurationVariable: The configuration variable that was created and/or
                set.

        NOTE: This method will create the variable with the provided `key` if it does
        not exist.
        """
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
