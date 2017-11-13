# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import functools

from connexion import (
    problem,
    request,
)
from flask import g

from landoapi.phabricator_client import PhabricatorClient


class require_phabricator_api_key:
    """Decorator which requires and verifies the phabricator API Key.

    Using this decorator on a connexion handler will require a phabricator
    api key be sent in the `X-Phabricator-API-Key` header of the request. If
    the header is not provided an HTTP 401 response will be sent.

    The provided API key will be verified to be valid, if it is not an
    HTTP 403 response will be sent.

    If the optional parameter is True and no API key is provided, a default key
    will be used. If an API key is provided it will still be verified.

    Decorated functions may assume X-Phabricator-API-Key header is present,
    contains a valid phabricator API key and flask.g.phabricator is a
    PhabricatorClient using this API Key.
    """

    def __init__(self, optional=False):
        self.optional = optional

    def __call__(self, f):
        @functools.wraps(f)
        def wrapped(*args, **kwargs):
            api_key = request.headers.get('X-Phabricator-API-Key')

            if api_key is None and not self.optional:
                return problem(
                    401,
                    'X-Phabricator-API-Key Required',
                    ('Phabricator api key not provided in '
                     'X-Phabricator-API-Key header'),
                    type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/401' # noqa: E501
                )  # yapf: disable

            g.phabricator = PhabricatorClient(api_key=api_key)
            if api_key is not None and not g.phabricator.verify_api_key():
                return problem(
                    403,
                    'X-Phabricator-API-Key Invalid',
                    'Phabricator api key is not valid',
                    type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/403' # noqa: E501
                )  # yapf: disable

            return f(*args, **kwargs)

        return wrapped
