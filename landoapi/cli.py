# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging
import os
import sys

import click
from flask.cli import FlaskGroup

from landoapi import (
    patches,
)
from landoapi.models.configuration import (
    ConfigurationVariable,
    ConfigurationKey,
    VariableType,
)


LINT_PATHS = ("setup.py", "tasks.py", "landoapi", "migrations", "tests")


def get_subsystems(exclude=None):
    """Get subsystems from the app, excluding those specified in the given parameter.

    Args:
        exclude (list of Subsystem): Subsystems to exclude.

    Returns: list of Subsystem
    """
    from landoapi.app import SUBSYSTEMS

    exclusions = exclude or []
    return [s for s in SUBSYSTEMS if s not in exclusions]


def create_lando_api_app(info):
    from landoapi.app import construct_app, load_config

    config = load_config()
    app = construct_app(config)
    for system in get_subsystems():
        system.init_app(app.app)

    return app.app


@click.group(cls=FlaskGroup, create_app=create_lando_api_app)
def cli():
    """Lando API cli."""


@cli.command()
@click.option("--init-s3", is_flag=True)
def init(init_s3):
    """Initialize Lando API (Create the DB, etc.)"""
    # Create the database and set the alembic version to
    # head revision.
    from landoapi.storage import alembic, db

    db.create_all()
    alembic.stamp("head")

    # Create a fake S3 bucket, ie for moto.
    if init_s3:
        s3 = patches.create_s3(
            aws_access_key=os.environ["AWS_ACCESS_KEY"],
            aws_secret_key=os.environ["AWS_SECRET_KEY"],
            endpoint_url=os.environ["S3_ENDPOINT_URL"],
        )
        s3.create_bucket(Bucket=os.environ["PATCH_BUCKET_NAME"])


@cli.command(context_settings=dict(ignore_unknown_options=True))
@click.argument("celery_arguments", nargs=-1, type=click.UNPROCESSED)
def worker(celery_arguments):
    """Initialize a Celery worker for this app."""
    from landoapi.app import repo_clone_subsystem

    for system in get_subsystems(exclude=[repo_clone_subsystem]):
        system.ensure_ready()

    from landoapi.celery import celery

    celery.worker_main((sys.argv[0],) + celery_arguments)


@cli.command(name="landing-worker")
def landing_worker():
    from landoapi.app import auth0_subsystem, lando_ui_subsystem

    exclusions = [auth0_subsystem, lando_ui_subsystem]
    for system in get_subsystems(exclude=exclusions):
        system.ensure_ready()

    from landoapi.landing_worker import LandingWorker

    worker = LandingWorker()
    worker.start()


@cli.command(name="run-pre-deploy-sequence")
def run_pre_deploy_sequence():
    """Runs the sequence of commands required before a deployment."""
    from landoapi.storage import db_subsystem

    db_subsystem.ensure_ready()
    ConfigurationVariable.set(
        ConfigurationKey.API_IN_MAINTENANCE, VariableType.BOOL, "1"
    )
    ConfigurationVariable.set(
        ConfigurationKey.LANDING_WORKER_PAUSED, VariableType.BOOL, "1"
    )


@cli.command(name="run-post-deploy-sequence")
def run_post_deploy_sequence():
    """Runs the sequence of commands required after a deployment."""
    from landoapi.storage import db_subsystem

    db_subsystem.ensure_ready()
    ConfigurationVariable.set(
        ConfigurationKey.API_IN_MAINTENANCE, VariableType.BOOL, "0"
    )
    ConfigurationVariable.set(
        ConfigurationKey.LANDING_WORKER_PAUSED, VariableType.BOOL, "0"
    )


@cli.command(context_settings=dict(ignore_unknown_options=True))
@click.argument("celery_arguments", nargs=-1, type=click.UNPROCESSED)
def celery(celery_arguments):
    """Run the celery base command for this app."""
    from landoapi.app import repo_clone_subsystem

    for system in get_subsystems(exclude=[repo_clone_subsystem]):
        system.ensure_ready()

    from landoapi.celery import celery

    celery.start([sys.argv[0]] + list(celery_arguments))


@cli.command()
def uwsgi():
    """Run the service in production mode with uwsgi."""
    from landoapi.app import repo_clone_subsystem

    for system in get_subsystems(exclude=[repo_clone_subsystem]):
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
