# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging
import logging.config
import os
from typing import Any

import connexion
from connexion.resolver import RestyResolver

import landoapi.models  # noqa: F401
from landoapi.auth import auth0_subsystem
from landoapi.cache import cache_subsystem
from landoapi.celery import celery_subsystem
from landoapi.dockerflow import dockerflow
from landoapi.hooks import initialize_hooks
from landoapi.logging import logging_subsystem
from landoapi.phabricator import phabricator_subsystem
from landoapi.repos import repo_clone_subsystem
from landoapi.sentry import sentry_subsystem
from landoapi.smtp import smtp_subsystem
from landoapi.storage import db_subsystem
from landoapi.systems import Subsystem
from landoapi.ui import lando_ui_subsystem
from landoapi.version import version

logger = logging.getLogger(__name__)

# Subsystems shared across different services
SUBSYSTEMS: list[Subsystem] = [
    # Logging & sentry first so that other systems log properly.
    logging_subsystem,
    sentry_subsystem,
    auth0_subsystem,
    cache_subsystem,
    celery_subsystem,
    db_subsystem,
    lando_ui_subsystem,
    phabricator_subsystem,
    smtp_subsystem,
    repo_clone_subsystem,
]


def load_config() -> dict[str, Any]:
    """Return configuration pulled from the environment."""
    config = {
        "ALEMBIC": {"script_location": "/migrations/"},
        "DISABLE_CELERY": bool(os.getenv("DISABLE_CELERY")),
        "ENVIRONMENT": os.getenv("ENV"),
        "MAIL_SUPPRESS_SEND": bool(os.getenv("MAIL_SUPPRESS_SEND")),
        "MAIL_USE_SSL": bool(os.getenv("MAIL_USE_SSL")),
        "MAIL_USE_TLS": bool(os.getenv("MAIL_USE_TLS")),
        "SQLALCHEMY_DATABASE_URI": os.getenv("DATABASE_URL"),
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "VERSION": version(),
    }

    config_keys = (
        "BUGZILLA_API_KEY",
        "BUGZILLA_URL",
        "CACHE_REDIS_DB",
        "CACHE_REDIS_HOST",
        "CACHE_REDIS_PASSWORD",
        "CACHE_REDIS_PORT",
        "CELERY_BROKER_URL",
        "CSP_REPORTING_URL",
        "LANDO_UI_URL",
        "LOG_LEVEL",
        "MAIL_FROM",
        "MAIL_PASSWORD",
        "MAIL_PORT",
        "MAIL_RECIPIENT_WHITELIST",
        "MAIL_SERVER",
        "MAIL_USERNAME",
        "OIDC_DOMAIN",
        "OIDC_IDENTIFIER",
        "PHABRICATOR_ADMIN_API_KEY",
        "PHABRICATOR_UNPRIVILEGED_API_KEY",
        "PHABRICATOR_URL",
        "REPO_CLONES_PATH",
        "REPOS_TO_LAND",
        "SENTRY_DSN",
    )

    defaults = {
        "CACHE_REDIS_PORT": 6379,
        "LOG_LEVEL": "INFO",
        "MAIL_FROM": "mozphab-prod@mozilla.com",
        "REPO_CLONES_PATH": "/repos",
    }

    for key in config_keys:
        config[key] = os.getenv(key, defaults.get(key))

    return config


def construct_app(config: dict[str, Any]) -> connexion.App:
    app = connexion.App(__name__, specification_dir="spec/")

    app.add_api(
        "swagger.yml",
        resolver=RestyResolver("landoapi.api"),
        options={"swagger_ui": False},
    )
    flask_app = app.app
    flask_app.config.update(config)
    flask_app.register_blueprint(dockerflow)
    initialize_hooks(flask_app)

    return app
