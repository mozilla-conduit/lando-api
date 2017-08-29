# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import json
import os

import click
import connexion
import logging

from connexion.resolver import RestyResolver
from raven.contrib.flask import Sentry

from landoapi.dockerflow import dockerflow
from landoapi.storage import alembic, db
from mozlogging import MozLogFormatter

logger = logging.getLogger(__name__)


def create_app(version_path):
    """Construct an application instance."""
    initialize_logging()

    app = connexion.App(__name__, specification_dir='spec/')
    app.add_api('swagger.yml', resolver=RestyResolver('landoapi.api'))

    # Get the Flask app being wrapped by the Connexion app.
    flask_app = app.app

    flask_app.config['VERSION_PATH'] = version_path
    log_config_change('VERSION_PATH', version_path)

    version_info = json.load(open(version_path))
    logger.info(version_info, 'app.version')

    this_app_version = version_info['version']
    initialize_sentry(flask_app, this_app_version)

    db_uri = flask_app.config.setdefault(
        'SQLALCHEMY_DATABASE_URI', os.environ.get('DATABASE_URL', 'sqlite://')
    )
    log_config_change('SQLALCHEMY_DATABASE_URI', db_uri)

    flask_app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    flask_app.config['ALEMBIC'] = {'script_location': '/migrations/'}

    flask_app.config['PATCH_BUCKET_NAME'] = os.getenv('PATCH_BUCKET_NAME')
    log_config_change(
        'PATCH_BUCKET_NAME', flask_app.config['PATCH_BUCKET_NAME']
    )
    flask_app.config['PINGBACK_HOST_URL'] = os.getenv('PINGBACK_HOST_URL')
    log_config_change(
        'PINGBACK_HOST_URL', flask_app.config['PINGBACK_HOST_URL']
    )

    # AWS credentials should be only provided if needed in development
    flask_app.config['AWS_ACCESS_KEY'] = os.getenv('AWS_ACCESS_KEY', None)
    flask_app.config['AWS_SECRET_KEY'] = os.getenv('AWS_SECRET_KEY', None)

    flask_app.register_blueprint(dockerflow)

    # Initialize database
    db.init_app(flask_app)

    # Intialize the alembic extension
    alembic.init_app(app.app)

    return app


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
    if sentry_dsn:
        log_config_change('SENTRY_DSN', sentry_dsn)
    else:
        log_config_change('SENTRY_DSN', 'none (sentry disabled)')

    # Do this after logging the DSN so if there is a DSN URL parsing error
    # the logs will record the configured value before the Sentry client
    # kills the app.
    sentry = Sentry(flask_app, dsn=sentry_dsn)

    # Set these attributes directly because their keyword arguments can't be
    # passed into Sentry.__init__() or make_client().
    sentry.client.release = release
    log_config_change('SENTRY_LOG_RELEASE_AS', release)

    environment = os.environ.get('ENV', None)
    sentry.client.environment = environment
    log_config_change('SENTRY_LOG_ENVIRONMENT_AS', environment)


def initialize_logging():
    """Initialize application-wide logging."""
    mozlog_handler = logging.StreamHandler()
    mozlog_handler.setFormatter(MozLogFormatter())

    # We need to configure the logger just for our application code.  This is
    # because the MozLogFormatter changes the signature of the standard
    # library logging functions.  Any code that tries to log a message assuming
    # the standard library's formatter is in place, such as the code in the
    # libraries we use, with throw an error if the MozLogFormatter tries to
    # handle the message.
    app_logger = logging.getLogger('landoapi')

    # Stop our specially-formatted log messages from bubbling up to any
    # Flask-installed loggers that may be present.  They will throw an exception
    # if they handle our messages.
    app_logger.propagate = False

    app_logger.addHandler(mozlog_handler)

    level = os.environ.get('LOG_LEVEL', 'INFO')
    app_logger.setLevel(level)

    log_config_change('LOG_LEVEL', level)


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


def log_config_change(setting_name, value):
    """Helper to log configuration changes.

    Args:
        setting_name: The setting being changed.
        value: The setting's new value.
    """
    logger.info({'setting': setting_name, 'value': value}, 'app.configure')
