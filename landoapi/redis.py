# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging
from contextlib import suppress

from redis import RedisError

logger = logging.getLogger(__name__)


class SuppressRedisFailure(suppress):
    """Context manager to suppress redis communication failures."""

    def __init__(self):
        super().__init__(RedisError)

    def __exit__(self, exctype, excinst, exctb):
        ret = super().__exit__(exctype, excinst, exctb)
        if exctype is not None and ret:
            logger.warning(
                'suppressed redis exception',
                exc_info=(exctype, excinst, exctb),
            )

        return ret
