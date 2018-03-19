# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import os

import click
from flask.cli import FlaskGroup


def create_lando_api_app(info):
    from landoapi.app import create_app
    version_path = os.getenv('VERSION_PATH', '/app/version.json')
    return create_app(version_path).app


@click.group(cls=FlaskGroup, create_app=create_lando_api_app)
def cli():
    """Lando API cli."""


@cli.command()
def init():
    """Initialize Lando API (Create the DB, etc.)"""
    # Create the database and set the alembic version to
    # head revision.
    from landoapi.storage import alembic, db
    db.create_all()
    alembic.stamp('head')


if __name__ == '__main__':
    cli()
