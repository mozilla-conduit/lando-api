# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging
import os
import sys

import click
from flask.cli import FlaskGroup


LINT_PATHS = ("setup.py", "tasks.py", "landoapi", "migrations", "tests")


def create_lando_api_app(info):
    from landoapi.app import construct_app, load_config, SUBSYSTEMS

    config = load_config()
    app = construct_app(config)
    for system in SUBSYSTEMS:
        system.init_app(app.app)

    return app.app


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
    alembic.stamp("head")


@cli.command(context_settings=dict(ignore_unknown_options=True))
@click.argument("celery_arguments", nargs=-1, type=click.UNPROCESSED)
def worker(celery_arguments):
    """Initialize a Celery worker for this app."""
    from landoapi.app import SUBSYSTEMS

    for system in SUBSYSTEMS:
        system.ensure_ready()

    from landoapi.celery import celery

    celery.worker_main((sys.argv[0],) + celery_arguments)


@cli.command(name="landing-worker")
def landing_worker():
    from landoapi.app import SUBSYSTEMS

    for system in SUBSYSTEMS:
        system.ensure_ready()

    from landoapi.landing_worker import LandingWorker

    worker = LandingWorker()
    worker.start()


@cli.command(context_settings=dict(ignore_unknown_options=True))
@click.argument("celery_arguments", nargs=-1, type=click.UNPROCESSED)
def celery(celery_arguments):
    """Run the celery base command for this app."""
    from landoapi.app import SUBSYSTEMS

    for system in SUBSYSTEMS:
        system.ensure_ready()

    from landoapi.celery import celery

    celery.start([sys.argv[0]] + list(celery_arguments))


@cli.command()
def uwsgi():
    """Run the service in production mode with uwsgi."""
    from landoapi.app import SUBSYSTEMS

    for system in SUBSYSTEMS:
        system.ensure_ready()

    logging.shutdown()
    os.execvp("uwsgi", ["uwsgi"])


@cli.command(name="format", with_appcontext=False)
@click.option("--in-place", "-i", is_flag=True)
def format_code(in_place):
    """Format python code"""
    cmd = ("black",)
    if not in_place:
        cmd = cmd + ("--diff",)
    os.execvp("black", cmd + LINT_PATHS)


@cli.command(with_appcontext=False)
def lint():
    """Lint python code with flake8"""
    os.execvp("flake8", ("flake8",) + LINT_PATHS)


@cli.command(with_appcontext=False, context_settings=dict(ignore_unknown_options=True))
@click.argument("pytest_arguments", nargs=-1, type=click.UNPROCESSED)
def test(pytest_arguments):
    """Run the tests."""
    os.execvp("pytest", ("pytest",) + pytest_arguments)


if __name__ == "__main__":
    cli()
