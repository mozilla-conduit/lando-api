# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging

from typing import Union

from flask_caching import Cache
from flask_caching.backends.rediscache import RedisCache
from redis import RedisError

from landoapi.redis import SuppressRedisFailure
from landoapi.systems import Subsystem

# 60s * 60m * 24h
DEFAULT_CACHE_KEY_TIMEOUT_SECONDS = 60 * 60 * 24

logger = logging.getLogger(__name__)
cache = Cache()
cache.suppress_failure = SuppressRedisFailure


class CacheSubsystem(Subsystem):
    name = "cache"

    def init_app(self, app):
        super().init_app(app)

        host = self.flask_app.config.get("CACHE_REDIS_HOST")
        if not host:
            # Default to not caching for testing.
            logger.warning("Cache initialized in null mode, caching disabled.")
            cache_config = {"CACHE_TYPE": "null", "CACHE_NO_NULL_WARNING": True}
        else:
            cache_config = {"CACHE_TYPE": "redis", "CACHE_REDIS_HOST": host}
            config_keys = ("CACHE_REDIS_PORT", "CACHE_REDIS_PASSWORD", "CACHE_REDIS_DB")
            for k in config_keys:
                v = self.flask_app.config.get(k)
                if v is not None:
                    cache_config[k] = v

        cache.init_app(self.flask_app, config=cache_config)

    def healthy(self) -> Union[bool, str]:
        if not isinstance(cache.cache, RedisCache):
            return "Cache is not configured to use redis"

        # Dirty, but if this breaks in the future we can instead
        # create our own redis-py client with its own connection
        # pool.
        redis = cache.cache._read_clients

        try:
            redis.ping()
        except RedisError as exc:
            return "RedisError: {!s}".format(exc)

        return True


cache_subsystem = CacheSubsystem()
