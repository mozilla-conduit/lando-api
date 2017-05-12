# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import os
import subprocess
import sys

from connexion import problem
from flask import request


def search():
    pass


def get(id):
    # We could not find a matching revision.
    return problem(
        404,
        'Revision not found',
        'The requested revision does not exist',
        type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404'
    )


REPOSITORY_HOME = os.environ.get('REPOSITORY_HOME', None)


def post():
    """Land a revision from Phabricator"""
    if not REPOSITORY_HOME:
        return problem(
            500,
            'Not configured',
            'This method requires REPOSITORY_HOME env to return a string',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500'
        )

    # get phabricator revision id
    data = request.form
    if not data.get('id'):
        return  problem(
            400,
            'No data provided',
            'Phabricator Revision id is required',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400'
        )

    # get repository from phabricator
    repository_name = os.environ.get('STUB_REPOSITORY', None)
    if not repository_name:
        return problem(
            500,
            'Not configured',
            'This method requires STUB_REPOSITORY env to return a string',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500'
        )
    path = '%s%s' % (REPOSITORY_HOME, repository_name)
    env = os.environ.copy()

    # pull from the origin
    env[b'PYTHONPATH'] = (':'.join(sys.path)).encode('utf-8')
    p = subprocess.Popen('hg pull',
                         cwd=path,
                         env=env,
                         stderr=subprocess.PIPE,
                         stdout=subprocess.PIPE,
                         universal_newlines=True,
                         shell=True,
                         )
    try:
        outs, errs = p.communicate(timeout=15)
    except TimeoutExpired:
        p.kill()
        outs, errs = p.communicate()

    if errs:
        pass
        # return problem(
        #     500,
        #     'Pull failed',
        #     errs,
        #     type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500'
        # )

    # create the commit from the diff
    message = 'Hello World. Revision %s' % data['id']
    p = subprocess.Popen('hg commit -m "%s"' % message,
                         cwd=path,
                         env=env,
                         stderr=subprocess.PIPE,
                         stdout=subprocess.PIPE,
                         universal_newlines=True,
                         shell=True,
                         )
    try:
        outs, errs = p.communicate(timeout=2)
    except TimeoutExpired:
        p.kill()
        outs, errs = p.communicate()

    if errs:
        return problem(
            500,
            'Commit failed',
            errs,
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500'
        )

    return 'YAY'

