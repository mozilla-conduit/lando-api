# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import functools
import logging
import os

import requests
from connexion import (
    ProblemException,
    request,
)
from flask import current_app, g
from jose import jwt

from landoapi.mocks.auth import MockAuth0

logger = logging.getLogger(__name__)

ALGORITHMS = ["RS256"]
mock_auth0 = MockAuth0()


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


def get_auth0_userinfo(access_token):
    """Return userinfo data from auth0."""
    url = 'https://{oidc_domain}/userinfo'.format(
        oidc_domain=current_app.config['OIDC_DOMAIN']
    )
    return requests.get(
        url, headers={'Authorization': 'Bearer {}'.format(access_token)}
    )


class A0User:
    """Represents a Mozilla auth0 user.

    It is assumed that the access_token provided to __init__ has
    already been verified properly.

    Clients requesting landing must require that the Mozilla LDAP login
    method is used to take advantage of the high security of the LDAP login.

    # TODO: Verify that the access token was generated via LDAP login.
    # TODO: Verify that the access token has the 'openid', 'profile',
    # 'email', and 'lando' scopes set.
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
        self._email = None

    @property
    def groups(self):
        if self._groups is None:
            groups = self._userinfo.get(self._GROUPS_CLAIM_KEY, [])
            groups = [groups] if isinstance(groups, str) else groups
            self._groups = set(groups)

        return self._groups

    @property
    def email(self):
        """The Mozilla LDAP email address of the Auth0 user.

        Returns a Mozilla LDAP address or None if the userinfo has no email set
        or if the email is not verified.
        """
        if self._email is None:
            email = self._userinfo.get('email')
            if email and self._userinfo.get('email_verified'):
                self._email = email

        return self._email

    def is_in_groups(self, *args):
        """Return True if the user is in all provided groups."""
        return set(args).issubset(self.groups)

    def can_land_changes(self):
        """Return True if the user has permissions to land."""
        return self.is_in_groups('active_scm_level_3')


def _mock_parsed_userinfo_claims(userinfo):
    """ Partially mocks Auth0 userinfo by only injecting ldap claims

    Modifies the userinfo in place with either valid or invalid ldap claims
    for landing based on the configured option in docker-compose.yml.
    If not configured for claim injection, no changes are made to the userinfo.
    """
    a0_mock_option = os.getenv('LOCALDEV_MOCK_AUTH0_USER')
    if a0_mock_option == 'inject_valid':
        userinfo['https://sso.mozilla.com/claim/groups'] = [
            'active_scm_level_3',
            'all_scm_level_3',
        ]
    elif a0_mock_option == 'inject_invalid':
        userinfo['https://sso.mozilla.com/claim/groups'] = [
            'invalid_group',
        ]


class require_auth0:
    """Decorator which requires an Auth0 access_token with the provided scopes.

    Using this decorator on a connexion handler will require an oidc
    access_token be sent as a bearer token in the `Authorization` header
    of the request. If the header is not provided or is invalid an HTTP 401
    response will be sent.

    Scopes provided in the `scopes` argument, as an iterable, will be checked
    for presence in the access_token. If any of the provided scopes are
    missing an HTTP 401 response will be sent.

    Decorated functions may assume the Authorization header is present
    containing a Bearer token, flask.g.access_token contains the verified
    access_token, and flask.g.access_token_payload contains the decoded jwt
    payload.

    Optionally, if `userinfo` is set to `True` the verified access_token will
    be used to request userinfo from auth0. This request must succeed and the
    returned userinfo will be used to construct an A0User object, which is
    accessed using flask.g.auth0_user.
    """

    def __init__(self, scopes=None, userinfo=False):
        assert scopes is not None, (
            '`scopes` must be provided. If this endpoint truly does not '
            'require any scopes, explicilty pass an empty tuple `()`'
        )
        self.userinfo = userinfo
        self.scopes = scopes

    def _require_scopes(self, f):
        @functools.wraps(f)
        def wrapped(*args, **kwargs):
            token_scopes = set(g.access_token_payload.get('scope', '').split())
            if [scope for scope in self.scopes if scope not in token_scopes]:
                raise ProblemException(
                    401,
                    'Missing Scopes',
                    'Token is missing required scopes for this action',
                    type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/401' # noqa
                )  # yapf: disable

            return f(*args, **kwargs)

        return wrapped

    def _require_userinfo(self, f):
        """Decorator which fetches userinfo using an Auth0 access_token.

        This decorator assumes that any caller of the wrapped function has
        already verified the Auth0 access_token and it is present at
        `g.access_token`.
        """

        @functools.wraps(f)
        def wrapped(*args, **kwargs):
            # See docker-compose.yml for details on auth0 mock options.
            a0_mock_option = os.getenv('LOCALDEV_MOCK_AUTH0_USER')
            if os.getenv('ENV') == 'localdev' and a0_mock_option == 'default':
                g.auth0_user = A0User(g.access_token, mock_auth0.userinfo)
                return f(*args, **kwargs)

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
                    'Authentication server response was invalid, try again '
                    'later',
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
                    'Authentication rate limit hit, please wait before '
                    'retrying',
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
                    'Authentication server response was invalid, try again '
                    'later',
                    type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500' # noqa
                )  # yapf: disable

            if os.getenv('ENV') == 'localdev':
                _mock_parsed_userinfo_claims(parsed_userinfo)

            g.auth0_user = A0User(g.access_token, parsed_userinfo)
            return f(*args, **kwargs)

        return wrapped

    def _require_access_token(self, f):
        """Decorator which verifies Auth0 access_token."""

        @functools.wraps(f)
        def wrapped(*args, **kwargs):
            # See docker-compose.yml for details on auth0 mock options.
            a0_mock_option = os.getenv('LOCALDEV_MOCK_AUTH0_USER')
            if os.getenv('ENV') == 'localdev' and a0_mock_option == 'default':
                g.access_token = mock_auth0.access_token
                g.access_token_payload = mock_auth0.access_token_payload
                return f(*args, **kwargs)

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
                    'Appropriate key for Authorization header could not be '
                    'found',
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

    def __call__(self, f):
        if self.userinfo:
            f = self._require_userinfo(f)

        if self.scopes:
            f = self._require_scopes(f)

        return self._require_access_token(f)
