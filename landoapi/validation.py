# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import re

from connexion import ProblemException

REVISION_ID_RE = re.compile(r'^D(?P<id>[1-9][0-9]*)$')


def revision_id_to_int(revision_id):
    m = REVISION_ID_RE.match(revision_id)
    if m is None:
        raise ProblemException(
            400,
            'Bad Request',
            'Revision IDs must be of the form "D<integer>"',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400'  # noqa
        )  # yapf: disable

    return int(m.group('id'))
