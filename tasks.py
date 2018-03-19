# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import json
import os

from invoke import Collection, run, task

DOCKER_IMAGE_NAME = os.getenv('DOCKERHUB_REPO', 'mozilla/landoapi')
# The 'pty' setting is nice, as it provides colour output, but it doesn't work
# on Windows.
USE_PTY = os.name != 'nt'


@task(
    help={
        'testargs': 'Arguments to pass to the test suite (default: \'\')',
        'keep': 'Do not remove the test container after running',
    },
)
def test(ctx, testargs='', keep=False):
    """Run the test suite."""
    ctx.config.keep_containers = keep  # Stashed for our cleanup tasks
    run(
        'docker-compose run {rm} lando-api pytest {args}'.format(
            args=testargs, rm=('' if keep else ' --rm')
        ),
        pty=USE_PTY,
        echo=True
    )


@task(name='flake8')
def lint_flake8(ctx):
    """Run flake8."""
    run('docker-compose run --rm py3-linter flake8 .', pty=USE_PTY, echo=True)


@task(name='yapf')
def lint_yapf(ctx):
    """Run yapf."""
    run(
        'docker-compose run --rm py3-linter yapf --diff --recursive ./',
        pty=USE_PTY,
        echo=True
    )


@task(default=True, name='all', post=[lint_flake8, lint_yapf])
def lint_all(ctx):
    """Lint project sourcecode."""
    pass


@task()
def format(ctx):
    """Format project sourcecode. (WARNING: rewrites files!)"""
    run(
        'docker-compose run --rm py3-linter yapf --in-place --recursive ./',
        echo=True
    )


@task
def version(ctx):
    """Print Dockerflow version information in JSON format."""
    version = {
        'commit': os.getenv('CIRCLE_SHA1', None),
        'version': os.getenv('CIRCLE_SHA1', None),
        'source': 'https://github.com/mozilla-conduit/lando-api',
        'build': os.getenv('CIRCLE_BUILD_URL', None)
    }
    print(json.dumps(version))


@task
def build(ctx):
    """Build the production docker image."""
    ctx.run(
        'docker build --pull -t {image_name} '
        '-f ./docker/Dockerfile-prod .'.format(image_name=DOCKER_IMAGE_NAME)
    )


@task(name='imageid')
def imageid(ctx):
    """Print the built docker image ID."""
    ctx.run(
        "docker inspect -f '{format}' {image_name}".
        format(image_name=DOCKER_IMAGE_NAME, format='{{.Id}}')
    )


@task(name='add-migration')
def add_migration(ctx, msg):
    """Call Alembic to create a migration revision"""
    ctx.run(
        "docker-compose run --rm lando-api lando-cli db revision '%s'" % msg
    )


@task(name='init')
def init(ctx):
    """Run Lando API first run init."""
    ctx.run("docker-compose run --rm lando-api lando-cli init")


@task
def upgrade(ctx):
    """Call Alembic to run all available migration upgrades."""
    ctx.run("docker-compose run --rm lando-api lando-cli db upgrade")


namespace = Collection(
    Collection(
        'lint',
        lint_all,
        lint_flake8,
        lint_yapf,
    ), add_migration, build, format, imageid, init, test, upgrade, version
)
