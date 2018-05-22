# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import json
import logging
import logging.config
import os
import re
import sys

import click
import connexion
from connexion.resolver import RestyResolver

import landoapi.models  # noqa, makes sure alembic knows about the models.
from landoapi.cache import cache
from landoapi.dockerflow import dockerflow
from landoapi.hooks import initialize_hooks
from landoapi.logging import MozLogFormatter
from landoapi.sentry import sentry
from landoapi.storage import alembic, db

logger = logging.getLogger(__name__)


def create_app(version_path):
    """Construct an application instance."""
    initialize_logging()

    app = connexion.App(__name__, specification_dir='spec/')

    swagger_ui_enabled = os.environ.get('ENV', None) == 'localdev'
    app.add_api(
        'swagger.yml',
        resolver=RestyResolver('landoapi.api'),
        swagger_ui=swagger_ui_enabled
    )

    # Get the Flask app being wrapped by the Connexion app.
    flask_app = app.app

    keys_before_setup = set(flask_app.config.keys())

    configure_app(flask_app, version_path)

    log_app_config(flask_app, keys_before_setup)

    flask_app.register_blueprint(dockerflow)

    # Initialize database
    db.init_app(flask_app)

    # Intialize the alembic extension
    alembic.init_app(flask_app)

    initialize_caching(flask_app)
    initialize_hooks(flask_app)

    return app


def configure_app(flask_app, version_path):
    flask_app.config['ENVIRONMENT'] = os.environ.get('ENV', None)

    # Application version metadata
    flask_app.config['VERSION_PATH'] = version_path
    version_info = json.load(open(version_path))
    logger.info('application version', extra=version_info)

    # Phabricator.
    flask_app.config['PHABRICATOR_URL'] = os.getenv('PHABRICATOR_URL')
    flask_app.config['PHABRICATOR_UNPRIVILEGED_API_KEY'] = (
        os.environ.get('PHABRICATOR_UNPRIVILEGED_API_KEY')
    )
    if re.match(
        r'^api-.{28}$', flask_app.config['PHABRICATOR_UNPRIVILEGED_API_KEY']
    ) is None:
        logger.error(
            'PHABRICATOR_UNPRIVILEGED_API_KEY has the wrong format, '
            'it must begin with "api-" and be 32 characters long.'
        )
        sys.exit(1)

    # Sentry
    this_app_version = version_info['version']
    initialize_sentry(flask_app, this_app_version)

    # Database configuration
    flask_app.config['SQLALCHEMY_DATABASE_URI'] = (
        os.environ.get('DATABASE_URL')
    )
    flask_app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    flask_app.config['ALEMBIC'] = {'script_location': '/migrations/'}

    flask_app.config['PATCH_BUCKET_NAME'] = os.getenv('PATCH_BUCKET_NAME')

    # Set the pingback url
    flask_app.config['PINGBACK_URL'] = '{host_url}/landings/update'.format(
        host_url=os.getenv('PINGBACK_HOST_URL')
    )
    flask_app.config['PINGBACK_ENABLED'] = (
        os.environ.get('PINGBACK_ENABLED', 'n')
    )
    for transplant_config in [
        'TRANSPLANT_URL', 'TRANSPLANT_USERNAME', 'TRANSPLANT_PASSWORD',
        'TRANSPLANT_API_KEY'
    ]:
        flask_app.config[transplant_config] = os.environ.get(transplant_config)

    # Protect against enabling pingback without proper security. If
    # we're allowing pingbacks but the api key is None or empty abort:
    if (
        flask_app.config['PINGBACK_ENABLED'] == 'y' and
        not flask_app.config['TRANSPLANT_API_KEY']
    ):
        logger.error('PINGBACK_ENABLED="y" but TRANSPLANT_API_KEY is unset.')
        sys.exit(1)

    # AWS credentials should be only provided if needed in development
    flask_app.config['AWS_ACCESS_KEY'] = os.getenv('AWS_ACCESS_KEY', None)
    flask_app.config['AWS_SECRET_KEY'] = os.getenv('AWS_SECRET_KEY', None)

    flask_app.config['CSP_REPORTING_URL'] = os.getenv('CSP_REPORTING_URL')

    # OIDC Configuration:
    # OIDC_IDENTIFIER should be the custom api identifier defined in auth0.
    flask_app.config['OIDC_IDENTIFIER'] = os.environ['OIDC_IDENTIFIER']
    # OIDC_DOMAIN should be the domain assigned to the auth0 orgnaization.
    flask_app.config['OIDC_DOMAIN'] = os.environ['OIDC_DOMAIN']
    # ODIC_JWKS_URL should be the url to the set of JSON Web Keys used by
    # auth0 to sign access_tokens.
    flask_app.config['OIDC_JWKS_URL'] = (
        'https://{oidc_domain}/.well-known/jwks.json'.format(
            oidc_domain=flask_app.config['OIDC_DOMAIN']
        )
    )


def initialize_caching(flask_app):
    """Initialize cache objects from environment.

    Args:
        flask_app: A Flask() instance.
    """
    host = os.environ.get('CACHE_REDIS_HOST')

    if not host:
        # Default to not caching for testing.
        logger.warning('Cache initialized in null mode, caching disabled.')
        cache_config = {
            'CACHE_TYPE': 'null',
            'CACHE_NO_NULL_WARNING': True,
        }
    else:
        cache_config = {
            'CACHE_TYPE': 'redis',
            'CACHE_REDIS_HOST': host,
        }
        env_keys = (
            'CACHE_REDIS_PORT', 'CACHE_REDIS_PASSWORD', 'CACHE_REDIS_DB',
        )
        for k in env_keys:
            v = os.environ.get(k)
            if v is not None:
                cache_config[k] = v

    cache.init_app(flask_app, config=cache_config)


def initialize_sentry(flask_app, release):
    """Initialize Sentry application monitoring.

    See https://docs.sentry.io/clients/python/advanced/#client-arguments for
    details about what this function's arguments mean to Sentry.

    Args:
        flask_app: A Flask() instance.
        release: A string representing this application release number (such as
            a git sha).  Will be used as the Sentry "release" identifier. See
            the Sentry client configuration docs for details.
    """
    sentry_dsn = os.environ.get('SENTRY_DSN', None)
    logger.info('sentry status', extra={'enabled': bool(sentry_dsn)})
    sentry.init_app(flask_app, dsn=sentry_dsn)

    # Set these attributes directly because their keyword arguments can't be
    # passed into Sentry.__init__() or make_client().
    sentry.client.release = release
    sentry.client.environment = flask_app.config['ENVIRONMENT']
    sentry.client.processors = (
        'raven.processors.SanitizePasswordsProcessor',
        'raven.processors.RemoveStackLocalsProcessor',
    )


def initialize_logging():
    """Initialize application-wide logging."""
    level = os.environ.get('LOG_LEVEL', 'INFO')
    logging.config.dictConfig(
        {
            'version': 1,
            'formatters': {
                'mozlog': {
                    '()': MozLogFormatter,
                    'mozlog_logger': 'lando-api',
                },
            },
            'handlers': {
                'console': {
                    'class': 'logging.StreamHandler',
                    'formatter': 'mozlog',
                },
                'null': {
                    'class': 'logging.NullHandler',
                }
            },
            'loggers': {
                'landoapi': {
                    'level': level,
                    'handlers': ['console'],
                },
                'request.summary': {
                    'level': level,
                    'handlers': ['console'],
                },
                'flask': {
                    'handlers': ['null'],
                },
                'werkzeug': {
                    'level': 'ERROR',
                    'handlers': ['console'],
                },
            },
            'root': {
                'handlers': ['null'],
            },
            'disable_existing_loggers': True,
        }
    )
    logger.info('logging configured', extra={'LOG_LEVEL': level})


def log_app_config(flask_app, keys_before_setup):
    """Logs a sanitized version of the app configuration."""
    keys_to_sanitize = {
        'DATABASE_URL',
        'CACHE_REDIS_PASSWORD',
        'SQLALCHEMY_DATABASE_URI',
        'TRANSPLANT_USERNAME',
        'TRANSPLANT_PASSWORD',
        'TRANSPLANT_API_KEY',
        'AWS_ACCESS_KEY',
        'AWS_SECRET_KEY',
        'PHABRICATOR_UNPRIVILEGED_API_KEY',
    }

    keys_after_setup = set(flask_app.config.keys())
    keys_to_log = keys_after_setup.difference(keys_before_setup)

    safe_keys = keys_to_log.difference(keys_to_sanitize)
    settings = {k: flask_app.config[k] for k in safe_keys}

    sensitive_keys = keys_to_log.intersection(keys_to_sanitize)
    cleaned_settings = dict((k, '********') for k in sensitive_keys)
    settings.update(cleaned_settings)

    logger.info('app configured', extra={'configuration': settings})


@click.command()
@click.option('--debug', envvar='DEBUG', is_flag=True)
@click.option('--port', envvar='PORT', default=8888)
@click.option(
    '--version-path', envvar='VERSION_PATH', default='/app/version.json'
)
def development_server(debug, port, version_path):
    """Run the development server.

    This server should not be used for production deployments. Instead
    the application should be served by an external webserver as a wsgi
    app.
    """
    app = create_app(version_path)
    app.run(debug=debug, port=port, host='0.0.0.0')
