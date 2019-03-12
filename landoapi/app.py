# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import json
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
from landoapi.sentry import sentry_subsystem
from landoapi.storage import db_subsystem
from landoapi.transplant_client import transplant_subsystem
from landoapi.ui import lando_ui_subsystem

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
    transplant_subsystem,
]


def load_config():
    """Return configuration pulled from the environment."""
    config = {
        "ALEMBIC": {"script_location": "/migrations/"},
        "DISABLE_CELERY": bool(os.getenv("DISABLE_CELERY")),
        "ENVIRONMENT": os.getenv("ENV"),
        "PINGBACK_URL": "{host_url}/landings/update".format(
            host_url=os.getenv("PINGBACK_HOST_URL")
        ),
        "SQLALCHEMY_DATABASE_URI": os.getenv("DATABASE_URL"),
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "VERSION": {
            "source": "https://github.com/mozilla-conduit/lando-api",
            "version": "0.0.0",
            "commit": "",
            "build": "dev",
        },
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
        ("MAIL_PORT", None),
        ("MAIL_RECIPIENT_WHITELIST", None),
        ("MAIL_SERVER", None),
        ("MAIL_SUPPRESS_SEND", None),
        ("OIDC_DOMAIN", None),
        ("OIDC_IDENTIFIER", None),
        ("PATCH_BUCKET_NAME", None),
        ("PINGBACK_ENABLED", "n"),
        ("PHABRICATOR_UNPRIVILEGED_API_KEY", None),
        ("PHABRICATOR_URL", None),
        ("SENTRY_DSN", None),
        ("TRANSPLANT_PASSWORD", None),
        ("TRANSPLANT_API_KEY", None),
        ("TRANSPLANT_URL", None),
        ("TRANSPLANT_USERNAME", None),
        ("VERSION_PATH", "/app/version.json"),
    ]:
        config[env_var] = os.getenv(env_var, default)

    # Read the version information.
    if config.get("VERSION_PATH") is not None:
        try:
            with open(config["VERSION_PATH"]) as f:
                config["VERSION"] = json.load(f)
        except (IOError, ValueError):
            logger.warning(
                "VERSION_PATH ({}) could not be loaded, assuming dev".format(
                    config.get("VERSION_PATH")
                )
            )

    return config


def construct_app(config, testing=False):
    app = connexion.App(__name__, specification_dir="spec/")

    swagger_ui_enabled = config.get("ENVIRONMENT", None) == "localdev"
    app.add_api(
        "swagger.yml",
        resolver=RestyResolver("landoapi.api"),
        swagger_ui=swagger_ui_enabled,
    )
    flask_app = app.app
    flask_app.config.update(config)
    flask_app.register_blueprint(dockerflow)
    initialize_hooks(flask_app)

    return app
