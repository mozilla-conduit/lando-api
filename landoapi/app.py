# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging
import logging.config
import os

import connexion
from connexion.resolver import RestyResolver

import landoapi.models  # noqa, makes sure alembic knows about the models.

from landoapi.auth import auth0_subsystem
from landoapi.cache import cache_subsystem
from landoapi.celery import celery_subsystem
from landoapi.dockerflow import dockerflow
from landoapi.hooks import initialize_hooks
from landoapi.logging import logging_subsystem
from landoapi.patches import patches_s3_subsystem
from landoapi.phabricator import phabricator_subsystem
from landoapi.repos import repo_clone_subsystem
from landoapi.sentry import sentry_subsystem
from landoapi.smtp import smtp_subsystem
from landoapi.storage import db_subsystem
from landoapi.transplant_client import transplant_subsystem
from landoapi.treestatus import treestatus_subsystem
from landoapi.ui import lando_ui_subsystem
from landoapi.version import version

logger = logging.getLogger(__name__)

SUBSYSTEMS = [
    # Logging & sentry first so that other systems log properly.
    logging_subsystem,
    sentry_subsystem,
    auth0_subsystem,
    cache_subsystem,
    celery_subsystem,
    db_subsystem,
    lando_ui_subsystem,
    patches_s3_subsystem,
    phabricator_subsystem,
    smtp_subsystem,
    transplant_subsystem,
    treestatus_subsystem,
    repo_clone_subsystem,
]


def load_config():
    """Return configuration pulled from the environment."""
    config = {
        "ALEMBIC": {"script_location": "/migrations/"},
        "DISABLE_CELERY": bool(os.getenv("DISABLE_CELERY")),
        "ENVIRONMENT": os.getenv("ENV"),
        "MAIL_SUPPRESS_SEND": bool(os.getenv("MAIL_SUPPRESS_SEND")),
        "MAIL_USE_SSL": bool(os.getenv("MAIL_USE_SSL")),
        "MAIL_USE_TLS": bool(os.getenv("MAIL_USE_TLS")),
        "PINGBACK_URL": "{host_url}/landings/update".format(
            host_url=os.getenv("PINGBACK_HOST_URL")
        ),
        "SQLALCHEMY_DATABASE_URI": os.getenv("DATABASE_URL"),
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "VERSION": version(),
    }

    config_keys = (
        "AWS_ACCESS_KEY",
        "AWS_SECRET_KEY",
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
        "PATCH_BUCKET_NAME",
        "PINGBACK_ENABLED",
        "PHABRICATOR_ADMIN_API_KEY",
        "PHABRICATOR_UNPRIVILEGED_API_KEY",
        "PHABRICATOR_URL",
        "REPO_CLONES_PATH",
        "REPOS_TO_LAND",
        "SENTRY_DSN",
        "TRANSPLANT_PASSWORD",
        "TRANSPLANT_API_KEY",
        "TRANSPLANT_URL",
        "TRANSPLANT_USERNAME",
        "TREESTATUS_URL",
    )

    defaults = {
        "CACHE_REDIS_PORT": 6379,
        "LOG_LEVEL": "INFO",
        "MAIL_FROM": "mozphab-prod@mozilla.com",
        "PINGBACK_ENABLED": "n",
        "REPO_CLONES_PATH": "/repos",
        "TREESTATUS_URL": "https://treestatus.mozilla-releng.net",
    }

    for key in config_keys:
        config[key] = os.getenv(key, defaults.get(key))

    return config


def construct_app(config):
    app = connexion.App(__name__, specification_dir="spec/")

    app.add_api(
        "swagger.yml",
        resolver=RestyResolver("landoapi.api"),
        options=dict(swagger_ui=False),
    )
    flask_app = app.app
    flask_app.config.update(config)
    flask_app.register_blueprint(dockerflow)
    initialize_hooks(flask_app)

    return app
