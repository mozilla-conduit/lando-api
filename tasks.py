# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import json
import os

from invoke import Collection, task, run

DOCKER_IMAGE_NAME = os.getenv('DOCKERHUB_REPO', 'lando-api')
project_root = os.path.dirname(__file__)

# Name used by docker-compose to create a test-only docker environment.
project_test_name = 'testlandoapi'


@task(name='remove-containers')
def remove_containers(ctx):
    """Remove all temporary containers created for testing."""
    if not ctx.config.get('keep_containers'):
        cmd = (
            'docker-compose'
            ' -f {project_root}/docker-compose.yml'
            ' -p {test_project_name}'
        ).format(
            project_root=project_root, test_project_name=project_test_name
        )

        ctx.run(cmd + ' stop', pty=True, echo=True)
        ctx.run(cmd + ' rm --force -v', pty=True, echo=True)


@task(
    help={
        'testargs': 'Arguments to pass to the test suite (default: \'\')',
        'keep': 'Do not remove the test container after running',
    },
    post=[remove_containers]
)
def test(ctx, testargs='', keep=False):
    """Run the test suite."""
    ctx.config.keep_containers = keep  # Stashed for our cleanup tasks
    run(
        'docker-compose'
        ' -f {project_root}/docker-compose.yml'
        ' -p {test_project_name}'
        ' run'
        '{rm}'
        ' lando-api'
        ' pytest {args}'
        ''.format(
            project_root=project_root,
            test_project_name=project_test_name,
            args=testargs,
            rm=('' if keep else ' --rm')
        ),
        pty=True,
        echo=True
    )


@task(name='flake8')
def lint_flake8(ctx):
    """Run flake8."""
    run(
        'docker-compose'
        ' -f {project_root}/docker-compose.yml'
        ' run'
        ' --rm'
        ' py3-linter'
        ' flake8 ./'
        ''.format(project_root=project_root),
        pty=True,
        echo=True
    )


@task(name='yapf')
def lint_yapf(ctx):
    """Run yapf."""
    run(
        'docker-compose'
        ' -f {project_root}/docker-compose.yml'
        ' run'
        ' --rm'
        ' py3-linter'
        ' yapf'
        ' --diff --recursive'
        ' ./'
        ''.format(project_root=project_root),
        pty=True,
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
        'docker-compose'
        ' -f {project_root}/docker-compose.yml'
        ' run'
        ' --rm'
        ' py3-linter'
        ' yapf'
        ' --in-place --recursive'
        ' ./'
        ''.format(project_root=project_root),
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


@task(name='build')
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


namespace = Collection(
    Collection(
        'lint',
        lint_all,
        lint_flake8,
        lint_yapf,
    ), build, format, imageid, remove_containers, test, version
)
