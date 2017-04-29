# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import os

import click
import connexion
from connexion.resolver import RestyResolver
from landoapi.dockerflow import dockerflow


def create_app(version_path):
    """Construct an application instance."""
    app = connexion.App(__name__, specification_dir='spec/')
    app.add_api('swagger.yml', resolver=RestyResolver('landoapi.api'))

    # Get the Flask app being wrapped by the Connexion app.
    flask_app = app.app
    flask_app.config['VERSION_PATH'] = version_path
    flask_app.register_blueprint(dockerflow)

    return app


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
