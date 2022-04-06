# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import os

from invoke import Collection, run, task

# The 'pty' setting is nice, as it provides colour output, but it doesn't work
# on Windows.
USE_PTY = os.name != "nt"


@task(
    help={
        "testargs": "Arguments to pass to the test suite (default: '')",
        "keep": "Do not remove the test container after running",
    }
)
def test(ctx, testargs="", keep=False):
    """Run the test suite."""
    ctx.config.keep_containers = keep  # Stashed for our cleanup tasks
    run(
        "docker-compose run {rm} lando-api test {args}".format(
            args=testargs, rm=("" if keep else " --rm")
        ),
        pty=USE_PTY,
        echo=True,
    )


@task(name="flake8")
def lint_flake8(ctx):
    """Run flake8."""
    run("docker-compose run --rm lando-api lint", pty=USE_PTY, echo=True)


@task(name="black")
def lint_black(ctx):
    """Run black."""
    run("docker-compose run --rm lando-api format", pty=USE_PTY, echo=True)


@task(default=True, name="all", post=[lint_flake8, lint_black])
def lint_all(ctx):
    """Lint project sourcecode."""
    pass


@task()
def format(ctx):
    """Format project sourcecode. (WARNING: rewrites files!)"""
    run("docker-compose run --rm lando-api format --in-place", echo=True)


@task(name="add-migration")
def add_migration(ctx, msg):
    """Call Alembic to create a migration revision"""
    ctx.run("docker-compose run --rm lando-api db revision '%s'" % msg)


@task(name="setup-db")
def setup_db(ctx):
    """Setup the Lando database by upgrading to latest migration file."""
    ctx.run("docker-compose run --rm lando-api db upgrade")


@task
def upgrade(ctx):
    """Call Alembic to run all available migration upgrades."""
    ctx.run("docker-compose run --rm lando-api db upgrade")


namespace = Collection(
    Collection("lint", lint_all, lint_flake8, lint_black),
    add_migration,
    format,
    setup_db,
    test,
    upgrade,
)
