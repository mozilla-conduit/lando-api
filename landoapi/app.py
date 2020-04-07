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
    for env_var, default in [
        # AWS credentials should be only provided if needed in development
        ("AWS_ACCESS_KEY", None),
        ("AWS_SECRET_KEY", None),
        ("CACHE_REDIS_DB", None),
        ("CACHE_REDIS_HOST", None),
        ("CACHE_REDIS_PASSWORD", None),
        ("CACHE_REDIS_PORT", 6379),
        ("CELERY_BROKER_URL", None),
        ("CSP_REPORTING_URL", None),
        ("LANDO_UI_URL", None),
        ("LOG_LEVEL", "INFO"),
        ("MAIL_FROM", "mozphab-prod@mozilla.com"),
        ("MAIL_PASSWORD", None),
        ("MAIL_PORT", None),
        ("MAIL_RECIPIENT_WHITELIST", None),
        ("MAIL_SERVER", None),
        ("MAIL_USERNAME", None),
        ("OIDC_DOMAIN", None),
        ("OIDC_IDENTIFIER", None),
        ("PATCH_BUCKET_NAME", None),
        ("PINGBACK_ENABLED", "n"),
        ("PHABRICATOR_ADMIN_API_KEY", None),
        ("PHABRICATOR_UNPRIVILEGED_API_KEY", None),
        ("PHABRICATOR_URL", None),
        ("REPO_CLONES_PATH", "/repos"),
        ("REPOS_TO_LAND", None),
        ("SENTRY_DSN", None),
        ("TRANSPLANT_PASSWORD", None),
        ("TRANSPLANT_API_KEY", None),
        ("TRANSPLANT_URL", None),
        ("TRANSPLANT_USERNAME", None),
        ("TREESTATUS_URL", "https://treestatus.mozilla-releng.net"),
    ]:
        config[env_var] = os.getenv(env_var, default)

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
