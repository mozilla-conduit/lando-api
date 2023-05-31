# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import functools
import hashlib
import logging
import os
from collections.abc import Iterable
from typing import (
    Callable,
    Optional,
)

import requests
from connexion import ProblemException, request
from flask import current_app, g
from jose import jwt

from landoapi.cache import cache
from landoapi.mocks.auth import MockAuth0
from landoapi.systems import Subsystem

logger = logging.getLogger(__name__)

ALGORITHMS = ["RS256"]
mock_auth0 = MockAuth0()


def get_auth_token() -> str:
    auth = request.headers.get("Authorization")
    if auth is None:
        raise ProblemException(
            401,
            "Authorization Header Required",
            "Authorization header is required and was not provided",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/401",
        )

    if not auth:
        raise ProblemException(
            401,
            "Authorization Header Invalid",
            "Authorization header must not be empty",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/401",
        )

    parts = auth.split()
    n_parts = len(parts)
    if parts[0].lower() != "bearer":
        raise ProblemException(
            401,
            "Authorization Header Invalid",
            "Authorization header must begin with Bearer",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/401",
        )

    if n_parts == 1:
        raise ProblemException(
            401,
            "Authorization Header Invalid",
            "Token not found in Authorization header",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/401",
        )

    if n_parts > 2:
        raise ProblemException(
            401,
            "Authorization Header Invalid",
            "Authorization header must be a Bearer token",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/401",
        )

    assert n_parts == 2
    return parts[1]


def get_rsa_key(jwks: dict, token: str) -> Optional[dict[str, str]]:
    """Return the rsa key from jwks for the provided token.

    `None` is returned if the key is not found.
    """
    unverified_header = jwt.get_unverified_header(token)
    for key in jwks["keys"]:
        if key["kid"] == unverified_header["kid"]:
            return {i: key[i] for i in ("kty", "kid", "use", "n", "e")}


def jwks_cache_key(url: str) -> str:
    return "auth0_jwks_{}".format(hashlib.sha256(url.encode("utf-8")).hexdigest())


def get_jwks() -> dict:
    """Return the auth0 jwks."""
    jwks_url = "https://{oidc_domain}/.well-known/jwks.json".format(
        oidc_domain=current_app.config["OIDC_DOMAIN"]
    )
    cache_key = jwks_cache_key(jwks_url)

    jwks = None
    with cache.suppress_failure():
        jwks = cache.get(cache_key)

    if jwks is not None:
        return jwks

    try:
        jwks_response = requests.get(jwks_url)
    except requests.exceptions.Timeout:
        raise ProblemException(
            500,
            "Auth0 Timeout",
            "Authentication server timed out, try again later",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500",
        )
    except requests.exceptions.ConnectionError:
        raise ProblemException(
            500,
            "Auth0 Connection Problem",
            "Can't connect to authentication server, try again later",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500",
        )
    except requests.exceptions.HTTPError:
        raise ProblemException(
            500,
            "Auth0 Response Error",
            "Authentication server response was invalid, try again later",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500",
        )
    except requests.exceptions.RequestException:
        raise ProblemException(
            500,
            "Auth0 Error",
            "Problem communicating with Auth0, try again later",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500",
        )

    try:
        jwks = jwks_response.json()
    except ValueError:
        logger.error("Auth0 jwks response was not valid json")
        raise ProblemException(
            500,
            "Auth0 Response Error",
            "Authentication server response was invalid, try again later",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500",
        )

    with cache.suppress_failure():
        cache.set(cache_key, jwks, timeout=60)

    return jwks


def userinfo_cache_key(access_token: str, user_sub: str) -> str:
    return "auth0_userinfo_{user_sub}_{token_hash}".format(
        user_sub=user_sub,
        token_hash=hashlib.sha256(access_token.encode("utf-8")).hexdigest(),
    )


def get_userinfo_url() -> str:
    return "https://{}/userinfo".format(current_app.config["OIDC_DOMAIN"])


def fetch_auth0_userinfo(access_token: str) -> requests.Response:
    """Return userinfo response from auth0 endpoint."""
    return requests.get(
        get_userinfo_url(), headers={"Authorization": "Bearer {}".format(access_token)}
    )


def get_auth0_userinfo(access_token: str, user_sub: str) -> dict:
    """Return userinfo data from auth0."""
    cache_key = userinfo_cache_key(access_token, user_sub)

    userinfo = None
    with cache.suppress_failure():
        userinfo = cache.get(cache_key)

    if userinfo is not None:
        return userinfo

    try:
        resp = fetch_auth0_userinfo(access_token)
    except requests.exceptions.Timeout:
        raise ProblemException(
            500,
            "Auth0 Timeout",
            "Authentication server timed out, try again later",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500",
        )
    except requests.exceptions.ConnectionError:
        raise ProblemException(
            500,
            "Auth0 Connection Problem",
            "Can't connect to authentication server, try again later",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500",
        )
    except requests.exceptions.HTTPError:
        raise ProblemException(
            500,
            "Auth0 Response Error",
            "Authentication server response was invalid, try again later",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500",
        )
    except requests.exceptions.RequestException:
        raise ProblemException(
            500,
            "Auth0 Error",
            "Problem communicating with Auth0, try again later",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500",
        )

    if resp.status_code == 429:
        # We should hopefully never hit this in production, so log an error
        # to make sure we investigate.
        logger.error("Auth0 Rate limit hit when requesting userinfo")
        raise ProblemException(
            429,
            "Auth0 Rate Limit",
            "Authentication rate limit hit, please wait before retrying",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/429",
        )

    if resp.status_code == 401:
        raise ProblemException(
            401,
            "Auth0 Userinfo Unauthorized",
            "Unauthorized to access userinfo, check openid scope",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/401",
        )

    if resp.status_code != 200:
        raise ProblemException(
            403,
            "Authorization Failure",
            "You do not have permission to access this resource",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/403",
        )

    try:
        userinfo = resp.json()
    except ValueError:
        logger.error("Auth0 userinfo response was not valid json")
        raise ProblemException(
            500,
            "Auth0 Response Error",
            "Authentication server response was invalid, try again later",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500",
        )

    with cache.suppress_failure():
        cache.set(cache_key, userinfo, timeout=60)

    return userinfo


class A0User:
    """Represents a Mozilla auth0 user.

    It is assumed that the access_token provided to __init__ has
    already been verified properly.
    """

    _GROUPS_CLAIM_KEY = "https://sso.mozilla.com/claim/groups"

    def __init__(self, access_token: str, userinfo: dict):
        self.access_token = access_token

        # We should discourage touching userinfo directly
        # outside of this class to keep information about
        # its structure contained, hopefully making it
        # easier to react to changes.
        self._userinfo = userinfo
        self._groups = None
        self._email = None

    @property
    def groups(self) -> Optional[set[str]]:
        if self._groups is None:
            groups = self._userinfo.get(self._GROUPS_CLAIM_KEY, [])
            groups = [groups] if isinstance(groups, str) else groups
            self._groups = set(groups)

        return self._groups

    @property
    def email(self) -> Optional[str]:
        """The Mozilla LDAP email address of the Auth0 user.

        Returns a Mozilla LDAP address or None if the userinfo has no email set
        or if the email is not verified.
        """
        if self._email is None:
            email = self._userinfo.get("email")
            if email and self._userinfo.get("email_verified"):
                self._email = email

        return self._email

    def is_in_groups(self, *args: str) -> bool:
        """Return True if the user is in all provided groups."""
        if not self.groups:
            return False

        return set(args).issubset(self.groups)


def _mock_userinfo_claims(userinfo: dict):
    """Partially mocks Auth0 userinfo by only injecting ldap claims

    Modifies the userinfo in place with either valid or invalid ldap claims
    for landing based on the configured option in docker-compose.yml.
    If not configured for claim injection, no changes are made to the userinfo.
    """
    a0_mock_option = os.getenv("LOCALDEV_MOCK_AUTH0_USER")
    if a0_mock_option == "inject_valid":
        userinfo["https://sso.mozilla.com/claim/groups"] = [
            "active_scm_level_3",
            "all_scm_level_3",
            "active_scm_level_2",
            "all_scm_level_2",
            "active_scm_level_1",
            "all_scm_level_1",
        ]
    elif a0_mock_option == "inject_invalid":
        userinfo["https://sso.mozilla.com/claim/groups"] = ["invalid_group"]


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

    def __init__(self, scopes: Iterable[str], userinfo: bool = False):
        self.userinfo = userinfo
        self.scopes = scopes

    def _require_scopes(self, f: Callable) -> Callable:
        @functools.wraps(f)
        def wrapped(*args, **kwargs):
            token_scopes = set(g.access_token_payload.get("scope", "").split())
            if any(scope not in token_scopes for scope in self.scopes):
                raise ProblemException(
                    401,
                    "Missing Scopes",
                    "Token is missing required scopes for this action",
                    type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/401",
                )

            return f(*args, **kwargs)

        return wrapped

    def _require_userinfo(self, f: Callable) -> Callable:
        """Decorator which fetches userinfo using an Auth0 access_token.

        This decorator assumes that any caller of the wrapped function has
        already verified the Auth0 access_token and it is present at
        `g.access_token`.
        """

        @functools.wraps(f)
        def wrapped(*args, **kwargs):
            # See docker-compose.yml for details on auth0 mock options.
            a0_mock_option = os.getenv("LOCALDEV_MOCK_AUTH0_USER")
            if os.getenv("ENV") == "localdev" and a0_mock_option == "default":
                g.auth0_user = A0User(g.access_token, mock_auth0.userinfo)
                return f(*args, **kwargs)

            userinfo = get_auth0_userinfo(g.access_token, g.access_token_payload["sub"])

            if os.getenv("ENV") == "localdev":
                _mock_userinfo_claims(userinfo)

            g.auth0_user = A0User(g.access_token, userinfo)
            return f(*args, **kwargs)

        return wrapped

    def _require_access_token(self, f: Callable) -> Callable:
        """Decorator which verifies Auth0 access_token."""

        @functools.wraps(f)
        def wrapped(*args, **kwargs):
            # See docker-compose.yml for details on auth0 mock options.
            a0_mock_option = os.getenv("LOCALDEV_MOCK_AUTH0_USER")
            if os.getenv("ENV") == "localdev" and a0_mock_option == "default":
                g.access_token = mock_auth0.access_token
                g.access_token_payload = mock_auth0.access_token_payload
                return f(*args, **kwargs)

            token = get_auth_token()
            jwks = get_jwks()

            try:
                key = get_rsa_key(jwks, token)
            except KeyError:
                logger.error("Auth0 jwks response structure unexpected")
                raise ProblemException(
                    500,
                    "Auth0 Response Error",
                    "Authentication server response was invalid, try again later",
                    type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500",
                )
            except jwt.JWTError:
                raise ProblemException(
                    400,
                    "Invalid Authorization",
                    "Unable to parse Authorization token",
                    type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
                )

            if key is None:
                raise ProblemException(
                    400,
                    "Authorization Header Invalid",
                    "Appropriate key for Authorization header could not be found",
                    type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/401",
                )

            issuer = "https://{oidc_domain}/".format(
                oidc_domain=current_app.config["OIDC_DOMAIN"]
            )

            try:
                payload = jwt.decode(
                    token,
                    key,
                    algorithms=ALGORITHMS,
                    audience=current_app.config["OIDC_IDENTIFIER"],
                    issuer=issuer,
                )
            except jwt.ExpiredSignatureError:
                raise ProblemException(
                    401,
                    "Token Expired",
                    "Appropriate token is expired. Please log out and back in.",
                    type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/401",
                )
            except jwt.JWTClaimsError:
                raise ProblemException(
                    401,
                    "Invalid Claims",
                    "Invalid Authorization claims in token, please check "
                    "the audience and issuer",
                    type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/401",
                )
            except Exception:
                raise ProblemException(
                    400,
                    "Invalid Authorization",
                    "Unable to parse Authorization token",
                    type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/401",
                )

            # At this point the access_token has been validated and payload
            # contains the parsed token.
            g.access_token = token
            g.access_token_payload = payload
            return f(*args, **kwargs)

        return wrapped

    def __call__(self, f: Callable) -> Callable:
        if self.userinfo:
            f = self._require_userinfo(f)

        if self.scopes:
            f = self._require_scopes(f)

        return self._require_access_token(f)


def assert_scm_level_1(auth0_user: A0User):
    """Raise an appropriate `ProblemException` if the user is missing `scm_level_1`."""
    # Return appropriate error message if user does not have commit access.
    if not auth0_user.is_in_groups("all_scm_level_1"):
        raise ProblemException(
            401,
            "`scm_level_1` access is required.",
            "You do not have `scm_level_1` commit access.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404",
        )

    # Check that user has active_scm_level_1 and not `expired_scm_level_1`.
    if auth0_user.is_in_groups("expired_scm_level_1") or not auth0_user.is_in_groups(
        "active_scm_level_1"
    ):
        raise ProblemException(
            401,
            "Your `scm_level_1` commit access has expired.",
            "Your `scm_level_1` commit access has expired.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404",
        )


def enforce_scm_level_1(func):
    """Decorator to enforce `active_scm_level_1` membership with error messaging."""

    @functools.wraps(func)
    def wrap_api(*args, **kwargs):
        assert_scm_level_1(g.auth0_user)
        return func(*args, **kwargs)

    return wrap_api


class Auth0Subsystem(Subsystem):
    name = "auth0"

    def ready(self) -> bool | str:
        domain = self.flask_app.config.get("OIDC_DOMAIN")
        identifier = self.flask_app.config.get("OIDC_IDENTIFIER")

        # OIDC_DOMAIN should be the domain assigned to the auth0 organization.
        # Leaving this unset could cause an application security problem.  We
        # require it to be set.
        #
        # OIDC_IDENTIFIER should be the custom api identifier defined in auth0.
        # Leaving this unset could cause an application security problem.  We
        # require it to be set.
        if not domain:
            return "OIDC_DOMAIN isn't set."
        if not identifier:
            return "OIDC_IDENTIFIER isn't set."

        return True

    def healthy(self) -> bool | str:
        try:
            get_jwks()
        except ProblemException as exc:
            return "Exception when requesting jwks: {}".format(exc.detail)

        return True


auth0_subsystem = Auth0Subsystem()
