# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import functools
import logging

import requests
from connexion import (
    ProblemException,
    request,
)
from flask import current_app, g
from jose import jwt

logger = logging.getLogger(__name__)

ALGORITHMS = ["RS256"]


def get_auth_token():
    auth = request.headers.get('Authorization')
    if auth is None:
        raise ProblemException(
            401,
            'Authorization Header Required',
            'Authorization header is required and was not provided',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/401' # noqa
        )  # yapf: disable

    if not auth:
        raise ProblemException(
            401,
            'Authorization Header Invalid',
            'Authorization header must not be empty',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/401' # noqa
        )  # yapf: disable

    parts = auth.split()
    n_parts = len(parts)
    if parts[0].lower() != 'bearer':
        raise ProblemException(
            401,
            'Authorization Header Invalid',
            'Authorization header must begin with Bearer',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/401' # noqa
        )  # yapf: disable

    if n_parts == 1:
        raise ProblemException(
            401,
            'Authorization Header Invalid',
            'Token not found in Authorization header',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/401' # noqa
        )  # yapf: disable

    if n_parts > 2:
        raise ProblemException(
            401,
            'Authorization Header Invalid',
            'Authorization header must be a Bearer token',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/401' # noqa
        )  # yapf: disable

    assert n_parts == 2
    return parts[1]


def get_rsa_key(jwks, token):
    """Return the rsa key from jwks for the provided token.

    `None` is returned if the key is not found.
    """
    unverified_header = jwt.get_unverified_header(token)
    for key in jwks['keys']:
        if key['kid'] == unverified_header['kid']:
            return {i: key[i] for i in ('kty', 'kid', 'use', 'n', 'e')}


def get_jwks(url):
    """Return the jwks found at provided url."""
    return requests.get(url).json()


def require_access_token(f):
    """Decorator which verifies Auth0 access_token.

    Using this decorator on a connexion handler will require an oidc
    access_token be sent as a bearer token in the `Authorization` header
    of the request. If the header is not provided or is invalid an HTTP 401
    response will be sent.

    Decorated functions may assume the Authorization header is present
    containing a Bearer token, flask.g.access_token contains the verified
    access_token, and flask.g.current_user contains the decoded jwt
    payload.
    """

    @functools.wraps(f)
    def wrapped(*args, **kwargs):
        token = get_auth_token()
        jwks = get_jwks(current_app.config['OIDC_JWKS_URL'])

        try:
            key = get_rsa_key(jwks, token)
        except (jwt.JWTError, KeyError):
            raise ProblemException(
                400,
                'Invalid Authorization',
                'Unable to parse Authorization token',
                type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400' # noqa
            )  # yapf: disable

        if key is None:
            raise ProblemException(
                400,
                'Authorization Header Invalid',
                'Appropriate key for Authorization header could not be found',
                type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/401' # noqa
            )  # yapf: disable

        issuer = 'https://{oidc_domain}/'.format(
            oidc_domain=current_app.config['OIDC_DOMAIN']
        )

        try:
            payload = jwt.decode(
                token,
                key,
                algorithms=ALGORITHMS,
                audience=current_app.config['OIDC_IDENTIFIER'],
                issuer=issuer
            )
        except jwt.ExpiredSignatureError:
            raise ProblemException(
                401,
                'Token Expired',
                'Appropriate token is expired',
                type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/401' # noqa
            )  # yapf: disable
        except jwt.JWTClaimsError:
            raise ProblemException(
                401,
                'Invalid Claims',
                'Invalid Authorization claims in token, please check '
                'the audience and issuer',
                type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/401' # noqa
            )  # yapf: disable
        except Exception:
            raise ProblemException(
                400,
                'Invalid Authorization',
                'Unable to parse Authorization token',
                type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/401' # noqa
            )  # yapf: disable

        # At this point the access_token has been validated and payload
        # contains the parsed token.
        g.access_token = token
        g.current_user = payload
        return f(*args, **kwargs)

    return wrapped
