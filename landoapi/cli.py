# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import logging
import os
import subprocess
import sys
from typing import Optional

import click
import connexion
import requests
from flask.cli import FlaskGroup

from landoapi.models.configuration import (
    ConfigurationKey,
    ConfigurationVariable,
    VariableType,
)
from landoapi.models.treestatus import (
    Log,
    Tree,
    TreeCategory,
    TreeStatus,
)
from landoapi.systems import Subsystem

LINT_PATHS = ("setup.py", "tasks.py", "landoapi", "migrations", "tests")


def get_subsystems(exclude: Optional[list[Subsystem]] = None) -> list[Subsystem]:
    """Get subsystems from the app, excluding those specified in the given parameter.

    Args:
        exclude (list of Subsystem): Subsystems to exclude.

    Returns: list of Subsystem
    """
    from landoapi.app import SUBSYSTEMS

    exclusions = exclude or []
    return [s for s in SUBSYSTEMS if s not in exclusions]


def create_lando_api_app() -> connexion.App:
    from landoapi.app import construct_app, load_config

    config = load_config()
    app = construct_app(config, spec=config["API_SPEC"])
    for system in get_subsystems():
        system.init_app(app.app)

    return app.app


@click.group(cls=FlaskGroup, create_app=create_lando_api_app)
def cli():
    """Lando API cli."""


@cli.command(context_settings={"ignore_unknown_options": True})
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

    from landoapi.workers.landing_worker import LandingWorker

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


@cli.command(context_settings={"ignore_unknown_options": True})
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
def ruff():
    """Run ruff on lint paths."""
    for lint_path in LINT_PATHS:
        subprocess.call(
            ("ruff", "check", "--fix", "--target-version", "py39", lint_path)
        )


@cli.command(with_appcontext=False, context_settings={"ignore_unknown_options": True})
@click.argument("pytest_arguments", nargs=-1, type=click.UNPROCESSED)
def test(pytest_arguments):
    """Run the tests."""
    os.execvp("pytest", ("pytest",) + pytest_arguments)


def get_category_for_tree(tree: str) -> TreeCategory:
    """Return the `TreeCategory` for a tree given its name."""
    if tree.startswith("try"):
        return TreeCategory.TRY

    if tree.startswith("comm-"):
        return TreeCategory.COMM_REPOS

    if tree in {"autoland", "mozilla-central"}:
        return TreeCategory.DEVELOPMENT

    if tree in {"mozilla-beta", "mozilla-esr115", "mozilla-release"}:
        return TreeCategory.RELEASE_STABILIZATION

    return TreeCategory.OTHER


def ensure_status_correct(status: str) -> TreeStatus:
    """Paper over some of bad data in the "status" field.

    The set of values present as `status` in the existing Treestatus is:
        {'added', 'approval require', 'approval required', 'closed', 'motd', 'open'}
    """
    try:
        return TreeStatus(status)
    except ValueError:
        if status == "approval require":
            return TreeStatus.APPROVAL_REQUIRED

    return TreeStatus.OPEN


@cli.command("import-treestatus")
def import_treestatus_data():
    """Import Treestatus data into the database.

    NOTE: this command is used as a one-time only import of the existing
    Treestatus data. It should be removed after changes are landed.
    See bug 1894984.
    """
    from landoapi.storage import db_subsystem

    db_subsystem.ensure_ready()

    from landoapi.storage import db

    trees = requests.get("https://treestatus.mozilla-releng.net/trees")
    trees_data = trees.json()
    tree_logs = {}

    # Create all new trees.
    for tree in trees_data["result"].keys():
        print(f"Creating tree {tree}.")
        new_tree = Tree(
            tree=tree,
            status=TreeStatus.OPEN,
            reason="",
            message_of_the_day="",
            category=get_category_for_tree(tree),
        )
        db.session.add(new_tree)

        print(f"Saving logs for {tree}.")
        logs = requests.get(
            f"https://treestatus.mozilla-releng.net/trees/{tree}/logs_all"
        ).json()
        tree_logs[tree] = logs

    db.session.flush()
    print("Flushing.")

    # Create log entries for each update in the trees file
    for tree, logs in tree_logs.items():
        print(f"Importing logs for {tree}.")
        for log_entry in reversed(logs["result"]):
            log = Log(
                tree=log_entry["tree"],
                changed_by=log_entry["who"],
                status=ensure_status_correct(log_entry["status"]),
                reason=log_entry["reason"],
                tags=log_entry["tags"],
                created_at=log_entry["when"],
                updated_at=log_entry["when"],
            )
            db.session.add(log)

        # Commit log entries for this tree.
        print(f"Created log entries for {tree}.")

    db.session.commit()
    print("Finished importing Treestatus data.")


if __name__ == "__main__":
    cli()
