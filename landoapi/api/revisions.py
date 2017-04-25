# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
from connexion import problem


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
