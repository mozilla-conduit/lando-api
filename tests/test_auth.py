# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import copy

import pytest
import requests
import requests_mock
from connexion import ProblemException
from connexion.lifecycle import ConnexionResponse
from flask import g

from landoapi.auth import (
    A0User,
    assert_scm_level_1,
    fetch_auth0_userinfo,
    require_auth0,
)
from landoapi.mocks.auth import TEST_KEY_PRIV, create_access_token
from landoapi.mocks.canned_responses.auth0 import CANNED_USERINFO


def noop(*args, **kwargs):
    return ConnexionResponse(status_code=200)


def test_require_access_token_missing(app):
    with app.test_request_context("/", headers=[]):
        with pytest.raises(ProblemException) as exc_info:
            require_auth0(scopes=())(noop)()

    assert exc_info.value.status == 401


@pytest.mark.parametrize(
    "headers,status",
    [
        ([("Authorization", "MALFORMED")], 401),
        ([("Authorization", "MALFORMED 12345")], 401),
        ([("Authorization", "BEARER 12345 12345")], 401),
        ([("Authorization", "")], 401),
        ([("Authorization", "Bearer bogus")], 400),
    ],
)
def test_require_access_token_malformed(jwks, app, headers, status):
    with app.test_request_context("/", headers=headers):
        with pytest.raises(ProblemException) as exc_info:
            require_auth0(scopes=())(noop)()

    assert exc_info.value.status == status


@pytest.mark.parametrize(
    "exc,status,title",
    [
        (requests.exceptions.ConnectTimeout, 500, "Auth0 Timeout"),
        (requests.exceptions.ReadTimeout, 500, "Auth0 Timeout"),
        (requests.exceptions.ProxyError, 500, "Auth0 Connection Problem"),
        (requests.exceptions.SSLError, 500, "Auth0 Connection Problem"),
        (requests.exceptions.HTTPError, 500, "Auth0 Response Error"),
        (requests.exceptions.RequestException, 500, "Auth0 Error"),
    ],
)
def test_require_auth0_userinfo_auth0_jwks_request_errors(app, exc, status, title):
    token = create_access_token()
    headers = [("Authorization", "Bearer {}".format(token))]
    with app.test_request_context("/", headers=headers):
        with requests_mock.mock() as m:
            m.get("/.well-known/jwks.json", exc=exc)

            with pytest.raises(ProblemException) as exc_info:
                require_auth0(scopes=(), userinfo=True)(noop)()

    assert exc_info.value.status == status
    assert exc_info.value.title == title


@pytest.mark.parametrize(
    "response_text,status,title",
    [
        ("NOT JSON", 500, "Auth0 Response Error"),
        ('{"missing_fields_in_json": "weird"}', 500, "Auth0 Response Error"),
    ],
)
def test_require_auth0_userinfo_auth0_jwks_invalid_response_error(
    app, response_text, status, title
):
    token = create_access_token()
    headers = [("Authorization", "Bearer {}".format(token))]
    with app.test_request_context("/", headers=headers):
        with requests_mock.mock() as m:
            m.get("/.well-known/jwks.json", text=response_text)

            with pytest.raises(ProblemException) as exc_info:
                require_auth0(scopes=(), userinfo=True)(noop)()

    assert exc_info.value.status == status
    assert exc_info.value.title == title


@pytest.mark.parametrize(
    "response_text,status,title", [("NOT JSON", 500, "Auth0 Response Error")]
)
def test_require_auth0_userinfo_auth0_userinfo_invalid_response_error(
    jwks, app, response_text, status, title
):
    token = create_access_token()
    headers = [("Authorization", "Bearer {}".format(token))]
    with app.test_request_context("/", headers=headers):
        with requests_mock.mock() as m:
            m.get("/userinfo", text=response_text)

            with pytest.raises(ProblemException) as exc_info:
                require_auth0(scopes=(), userinfo=True)(noop)()

    assert exc_info.value.status == status
    assert exc_info.value.title == title


def test_require_access_token_no_kid_match(jwks, app):
    key = copy.deepcopy(TEST_KEY_PRIV)
    key["kid"] = "BOGUSKID"
    token = create_access_token(key=key)
    headers = [("Authorization", "Bearer {}".format(token))]

    with app.test_request_context("/", headers=headers):
        with pytest.raises(ProblemException) as exc_info:
            require_auth0(scopes=())(noop)()

    assert exc_info.value.status == 400
    assert exc_info.value.title == "Authorization Header Invalid"
    assert exc_info.value.detail == (
        "Appropriate key for Authorization header could not be found"
    )


@pytest.mark.parametrize(
    "token_kwargs,status,title",
    [
        ({"exp": 1}, 401, "Token Expired"),
        ({"iss": "bogus issuer"}, 401, "Invalid Claims"),
        ({"aud": "bogus audience"}, 401, "Invalid Claims"),
    ],
)
def test_require_access_token_invalid(jwks, app, token_kwargs, status, title):
    token = create_access_token(**token_kwargs)
    headers = [("Authorization", "Bearer {}".format(token))]

    with app.test_request_context("/", headers=headers):
        with pytest.raises(ProblemException) as exc_info:
            require_auth0(scopes=())(noop)()

    assert exc_info.value.status == status
    assert exc_info.value.title == title


@pytest.mark.parametrize("token_kwargs", [{}])
def test_require_access_token_valid(jwks, app, token_kwargs):
    token = create_access_token(**token_kwargs)
    headers = [("Authorization", "Bearer {}".format(token))]
    with app.test_request_context("/", headers=headers):
        resp = require_auth0(scopes=())(noop)()

    assert resp.status_code == 200


def test_fetch_auth0_userinfo(app):
    with app.app_context():
        with requests_mock.mock() as m:
            m.get("/userinfo", status_code=200, json=CANNED_USERINFO["STANDARD"])
            resp = fetch_auth0_userinfo(create_access_token())

    assert resp.status_code == 200


def test_userinfo_cache(app):
    with app.app_context():
        with requests_mock.mock() as m:
            m.get("/userinfo", status_code=200, json=CANNED_USERINFO["STANDARD"])
            resp = fetch_auth0_userinfo(create_access_token())

    assert resp.status_code == 200


def test_require_auth0_userinfo_expired_token(jwks, app):
    # Make sure requiring userinfo also validates the token first.
    expired_token = create_access_token(exp=1)
    headers = [("Authorization", "Bearer {}".format(expired_token))]
    with app.test_request_context("/", headers=headers):
        with pytest.raises(ProblemException) as exc_info:
            require_auth0(scopes=(), userinfo=True)(noop)()

    assert exc_info.value.status == 401
    assert exc_info.value.title == "Token Expired"


@pytest.mark.parametrize(
    "exc,status,title",
    [
        (requests.exceptions.ConnectTimeout, 500, "Auth0 Timeout"),
        (requests.exceptions.ReadTimeout, 500, "Auth0 Timeout"),
        (requests.exceptions.ProxyError, 500, "Auth0 Connection Problem"),
        (requests.exceptions.SSLError, 500, "Auth0 Connection Problem"),
        (requests.exceptions.HTTPError, 500, "Auth0 Response Error"),
        (requests.exceptions.RequestException, 500, "Auth0 Error"),
    ],
)
def test_require_auth0_userinfo_auth0_userinfo_request_errors(
    jwks, app, exc, status, title
):
    token = create_access_token()
    headers = [("Authorization", "Bearer {}".format(token))]
    with app.test_request_context("/", headers=headers):
        with requests_mock.mock() as m:
            m.get("/userinfo", exc=exc)

            with pytest.raises(ProblemException) as exc_info:
                require_auth0(scopes=(), userinfo=True)(noop)()

    assert exc_info.value.status == status
    assert exc_info.value.title == title


@pytest.mark.parametrize(
    "a0status,a0kwargs,status,title",
    [
        (429, {"text": "Too Many Requests"}, 429, "Auth0 Rate Limit"),
        (401, {"text": "Unauthorized"}, 401, "Auth0 Userinfo Unauthorized"),
        (200, {"text": "NOT JSON"}, 500, "Auth0 Response Error"),
    ],
)
def test_require_auth0_userinfo_auth0_failures(
    jwks, app, a0status, a0kwargs, status, title
):
    token = create_access_token()
    headers = [("Authorization", "Bearer {}".format(token))]
    with app.test_request_context("/", headers=headers):
        with requests_mock.mock() as m:
            m.get("/userinfo", status_code=a0status, **a0kwargs)

            with pytest.raises(ProblemException) as exc_info:
                require_auth0(scopes=(), userinfo=True)(noop)()

    assert exc_info.value.status == status
    assert exc_info.value.title == title


def test_require_auth0_userinfo_succeeded(jwks, app):
    token = create_access_token()
    headers = [("Authorization", "Bearer {}".format(token))]
    with app.test_request_context("/", headers=headers):
        with requests_mock.mock() as m:
            m.get("/userinfo", status_code=200, json=CANNED_USERINFO["STANDARD"])
            resp = require_auth0(scopes=(), userinfo=True)(noop)()

        assert isinstance(g.auth0_user, A0User)

    assert resp.status_code == 200


@pytest.mark.parametrize(
    "userinfo,groups,result",
    [
        (CANNED_USERINFO["STANDARD"], ("bogus",), False),
        (CANNED_USERINFO["STANDARD"], ("active_scm_level_1", "bogus"), False),
        (CANNED_USERINFO["STANDARD"], ("active_scm_level_1",), True),
        (CANNED_USERINFO["STANDARD"], ("active_scm_level_1", "all_scm_level_1"), True),
        (CANNED_USERINFO["NO_CUSTOM_CLAIMS"], ("active_scm_level_1",), False),
        (CANNED_USERINFO["NO_CUSTOM_CLAIMS"], ("active_scm_level_1", "bogus"), False),
        (CANNED_USERINFO["SINGLE_GROUP"], ("all_scm_level_1",), True),
        (CANNED_USERINFO["SINGLE_GROUP"], ("active_scm_level_1",), False),
        (
            CANNED_USERINFO["SINGLE_GROUP"],
            ("active_scm_level_1", "all_scm_level_1"),
            False,
        ),
        (CANNED_USERINFO["STRING_GROUP"], ("all_scm_level_1",), True),
        (CANNED_USERINFO["STRING_GROUP"], ("active_scm_level_1",), False),
        (
            CANNED_USERINFO["STRING_GROUP"],
            ("active_scm_level_1", "all_scm_level_1"),
            False,
        ),
        (CANNED_USERINFO["STANDARD"], (), True),
    ],
)
def test_user_is_in_groups(userinfo, groups, result):
    token = create_access_token()
    user = A0User(token, userinfo)
    assert user.is_in_groups(*groups) == result


@pytest.mark.parametrize(
    "userinfo,expected_email",
    [
        (CANNED_USERINFO["STANDARD"], "tuser@example.com"),
        (CANNED_USERINFO["NO_EMAIL"], None),
        (CANNED_USERINFO["UNVERIFIED_EMAIL"], None),
    ],
)
def test_user_email(userinfo, expected_email):
    token = create_access_token()
    user = A0User(token, userinfo)
    assert user.email == expected_email


@pytest.mark.parametrize(
    "scopes, token_kwargs,status,title",
    [
        (("profile", "lando"), {"scope": "profile"}, 401, "Missing Scopes"),
        (("profile", "lando"), {"scope": "lando"}, 401, "Missing Scopes"),
        (("profile", "lando"), {"scope": "lando bogus"}, 401, "Missing Scopes"),
        (("profile", "lando"), {"scope": "profile bogus"}, 401, "Missing Scopes"),
        (("profile", "lando"), {"scope": "Profile Lando"}, 401, "Missing Scopes"),
    ],
)
def test_require_scopes_invalid(jwks, app, scopes, token_kwargs, status, title):
    token = create_access_token(**token_kwargs)
    headers = [("Authorization", "Bearer {}".format(token))]

    with app.test_request_context("/", headers=headers):
        with pytest.raises(ProblemException) as exc_info:
            require_auth0(scopes=scopes)(noop)()

    assert exc_info.value.status == status
    assert exc_info.value.title == title


@pytest.mark.parametrize(
    "scopes, token_kwargs",
    [
        (("lando", "profile"), {"scope": "lando profile"}),
        (("lando", "profile"), {"scope": "profile lando"}),
        (("lando", "profile"), {"scope": "lando profile extrascope"}),
        (("lando", "profile"), {"scope": "extrascope lando profile"}),
        (("lando", "profile"), {"scope": "lando extrascope profile"}),
        (("lando", "profile"), {"scope": "extra1 lando extra2 profile extra3"}),
        ((), {"scope": "lando profile"}),
        (("lando",), {"scope": "lando profile"}),
        (("profile",), {"scope": "lando profile"}),
        (
            ("scope1", "scope2", "scope3", "scope4", "scope5", "scope6"),
            {"scope": "scope1 scope2 scope3 scope4 scope5 scope6"},
        ),
    ],
)
def test_require_access_scopes_valid(jwks, app, scopes, token_kwargs):
    token = create_access_token(**token_kwargs)
    headers = [("Authorization", "Bearer {}".format(token))]
    with app.test_request_context("/", headers=headers):
        resp = require_auth0(scopes=scopes)(noop)()

    assert resp.status_code == 200


def test_scm_level_1_enforce():
    """Test scm_level_1 enforcement and error handling."""
    token = create_access_token()

    # Test `all_scm_level_1` is missing.
    userinfo = CANNED_USERINFO["MISSING_L1"]
    user = A0User(token, userinfo)
    with pytest.raises(ProblemException) as exc_info:
        assert_scm_level_1(user)
    assert exc_info.value.status == 401, "Lack of level 1 permission should return 401."
    assert (
        exc_info.value.title == "`scm_level_1` access is required."
    ), "Lack of level 1 permissions should return appropriate error."

    # Test `expired_scm_level_1` is present.
    userinfo = CANNED_USERINFO["EXPIRED_L1"]
    user = A0User(token, userinfo)
    with pytest.raises(ProblemException) as exc_info:
        assert_scm_level_1(user)
    assert exc_info.value.status == 401, "Expired level 1 permission should return 401."
    assert (
        exc_info.value.title == "Your `scm_level_1` commit access has expired."
    ), "Expired level 1 permissions should return appropriate error."

    # Test `active_scm_level_1` is not present.
    userinfo = CANNED_USERINFO["MISSING_ACTIVE_L1"]
    user = A0User(token, userinfo)
    with pytest.raises(ProblemException) as exc_info:
        assert_scm_level_1(user)
    assert (
        exc_info.value.status == 401
    ), "Lack of active level 1 permission should return 401."
    assert (
        exc_info.value.title == "Your `scm_level_1` commit access has expired."
    ), "Lack of active level 1 permissions should return appropriate error."

    # Test happy path.
    userinfo = CANNED_USERINFO["STANDARD"]
    user = A0User(token, userinfo)
    assert assert_scm_level_1(user) is None
