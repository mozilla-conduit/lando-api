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
    access_token, and flask.g.access_token_payload contains the decoded jwt
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
        g.access_token_payload = payload
        return f(*args, **kwargs)

    return wrapped


def get_auth0_userinfo(access_token):
    """Return userinfo data from auth0."""
    url = 'https://{oidc_domain}/userinfo'.format(
        oidc_domain=current_app.config['OIDC_DOMAIN']
    )
    return requests.get(
        url, headers={'Authorization': 'Bearer {}'.format(access_token)}
    )


def require_auth0_userinfo(f):
    """Decorator which verifies Auth0 access_token and fetches userinfo.

    Using this decorator implies require_access_token and everything
    that comes along with it.

    The provided access_token verified by require_access_token will
    then be used to request userinfo from auth0. This request must
    succeed and the returned userinfo will be used to construct
    an A0User object, which is accessed using flask.g.auth0_user.
    """

    @functools.wraps(f)
    def wrapped(*args, **kwargs):
        """Fetches userinfo before calling provided function.

        This wrapped function assumes it is wrapped by
        `require_access_token`.
        """

        try:
            resp = get_auth0_userinfo(g.access_token)
        except requests.exceptions.Timeout:
            raise ProblemException(
                500,
                'Auth0 Timeout',
                'Authentication server timed out, try again later',
                type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500' # noqa
            )  # yapf: disable
        except requests.exceptions.ConnectionError:
            raise ProblemException(
                500,
                'Auth0 Connection Problem',
                'Can\'t connect to authentication server, try again later',
                type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500' # noqa
            )  # yapf: disable
        except requests.exceptions.HTTPError:
            raise ProblemException(
                500,
                'Auth0 Response Error',
                'Authentication server response was invalid, try again later',
                type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500' # noqa
            )  # yapf: disable
        except requests.exceptions.RequestException:
            raise ProblemException(
                500,
                'Auth0 Error',
                'Problem communicating with Auth0, try again later',
                type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500' # noqa
            )  # yapf: disable

        if resp.status_code == 429:
            # TODO: We should be caching the userinfo to avoid hitting the
            # rate limit here. It might be important to hash the token for
            # the cache key rather than using it directly, look into this.
            raise ProblemException(
                429,
                'Auth0 Rate Limit',
                'Authentication rate limit hit, please wait before retrying',
                type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/429' # noqa
            )  # yapf: disable

        if resp.status_code == 401:
            raise ProblemException(
                401,
                'Auth0 Userinfo Unauthorized',
                'Unauthorized to access userinfo, check openid scope',
                type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/401' # noqa
            )  # yapf: disable

        if resp.status_code != 200:
            raise ProblemException(
                403,
                'Authorization Failure',
                'You do not have permission to access this resource',
                type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/403' # noqa
            )  # yapf: disable

        try:
            parsed_userinfo = resp.json()
        except ValueError:
            raise ProblemException(
                500,
                'Auth0 Response Error',
                'Authentication server response was invalid, try again later',
                type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500' # noqa
            )  # yapf: disable

        g.auth0_user = A0User(g.access_token, parsed_userinfo)
        return f(*args, **kwargs)

    return require_access_token(wrapped)


class A0User:
    """Represents a Mozilla auth0 user.

    It is assumed that the access_token provided to __init__ has
    already been verified properly.
    """
    _GROUPS_CLAIM_KEY = 'https://sso.mozilla.com/claim/groups'

    def __init__(self, access_token, userinfo):
        self.access_token = access_token

        # We should discourage touching userinfo directly
        # outside of this class to keep information about
        # its structure contained, hopefully making it
        # easier to react to changes.
        self._userinfo = userinfo
        self._groups = None

    @property
    def groups(self):
        if self._groups is None:
            groups = self._userinfo.get(self._GROUPS_CLAIM_KEY, [])
            groups = [groups] if isinstance(groups, str) else groups
            self._groups = set(groups)

        return self._groups

    def is_in_groups(self, *args):
        """Return True if the user is in all provided groups."""
        return set(args).issubset(self.groups)

    def can_land_changes(self):
        """Return True if the user has permissions to land."""
        return self.is_in_groups('active_scm_level_3')
