# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import copy
import time

import pytest
import requests
import requests_mock
from connexion import ProblemException
from connexion.lifecycle import ConnexionResponse
from jose import jwt

from landoapi.auth import (
    get_auth0_userinfo,
    require_access_token,
    require_auth0_userinfo,
)

from tests.canned_responses.auth0 import CANNED_USERINFO_1


TEST_KEY_PUB = {
    'kid': 'testkey',
    'kty': 'RSA',
    'use': 'sig',
    'alg': 'RS256',
    'n': 'xL-0dixTADArU_CbrrtBziH9seX_ipQaYMRyvzIWTgH5cAhlReSCP5zOBbjESLthi-R325hXn7EHNC9lT0KxDhWW3nocb7WnDc-X8cLpZqV6ZvFV_zAMP9E6ncxGrzPYim07tKS7QeBvevuBk996Q0PgzrMgIqtmzur-nOanqVWVq5beRscZkKWSqF6QsQ7QmksT_3bCrxjrjvggymuzjKwyYkFGRrN_eVFTgbjt4v7BoldzQI_j72HzN6Sndp8g0W2g0Yqon-d-BW6q55F2BiSKKhzGxqhLhs88uQwcDR7tckYTpD2CTNbTC7X2msDwRQuxVawirk_gpiJKaPRN5JpeJY-Ag452l_dllXahSnMR4sHs-NAU1k4Qo2UugqWt93HcbBpoecwKzMnZEZS4P0tcAW2Ng3ECHVOOQ1L1SfVEJYZTaIJkKTnJy43vT81zqPwIMfaO9aRD7zu3GuR8p8maSy3Hu5vHkQH8MTx_NSdtg92-xCT7X-nZV6dzaU0ihYoTwbprGsl9e9dSA3OgFxk-Re_RNR2S5jJ3PH7NJgpgwPly9TEzZkUSSZ4oO-eQJ5CCMxRnd7H6EjOQVwxfprbxY_GuQXsFx3WP_TGUlL2CO1P8Eq5V30ytu4CfZBy7xtVknQsV8c3Xiu7Y0Wuyo57Yds01p6gMszOYGxAk9t8',  # noqa
    'e': 'AQAB',
}  # yapf: disable

TEST_KEY_PRIV = {
    'kid': 'testkey',
    'kty': 'RSA',
    'alg': 'RS256',
    'n': 'xL-0dixTADArU_CbrrtBziH9seX_ipQaYMRyvzIWTgH5cAhlReSCP5zOBbjESLthi-R325hXn7EHNC9lT0KxDhWW3nocb7WnDc-X8cLpZqV6ZvFV_zAMP9E6ncxGrzPYim07tKS7QeBvevuBk996Q0PgzrMgIqtmzur-nOanqVWVq5beRscZkKWSqF6QsQ7QmksT_3bCrxjrjvggymuzjKwyYkFGRrN_eVFTgbjt4v7BoldzQI_j72HzN6Sndp8g0W2g0Yqon-d-BW6q55F2BiSKKhzGxqhLhs88uQwcDR7tckYTpD2CTNbTC7X2msDwRQuxVawirk_gpiJKaPRN5JpeJY-Ag452l_dllXahSnMR4sHs-NAU1k4Qo2UugqWt93HcbBpoecwKzMnZEZS4P0tcAW2Ng3ECHVOOQ1L1SfVEJYZTaIJkKTnJy43vT81zqPwIMfaO9aRD7zu3GuR8p8maSy3Hu5vHkQH8MTx_NSdtg92-xCT7X-nZV6dzaU0ihYoTwbprGsl9e9dSA3OgFxk-Re_RNR2S5jJ3PH7NJgpgwPly9TEzZkUSSZ4oO-eQJ5CCMxRnd7H6EjOQVwxfprbxY_GuQXsFx3WP_TGUlL2CO1P8Eq5V30ytu4CfZBy7xtVknQsV8c3Xiu7Y0Wuyo57Yds01p6gMszOYGxAk9t8',  # noqa
    'e': 'AQAB',
    'd': 'F3hvBLHg7OLSKF9JkxyPixGO_Avd4iAszWJh9eD5vDCMGwtFWYMa7o-8G_6gm7SOvGtyyOVxfoFVxKnqwfvIt09oAf47KjBXT1R2YcbIpRAUe_dKNPj8XRiOj4hw3jGnIUxKlRAZrpAhfGBIYuWD5kZQqRfBO6GK0CBEY184nQCyrBeBSJwztoep6R_uztBfnihaqFz4eH7WiuWas8sJTjy0ffgfdAuxpz1GYvE2n5-YZc9c1lTT8hiTNQ4VVBdDiPg0-Qo7d2fcJrW--YTmuXDecougQs6Mw_Yw3jpNllscJEerzCnyQ0xVPM5mLqvZfcMZUokIUhcBS5BHpCGQsQEVUXQCV23AyrceRl6gYU2bvZB2Wk4jvC28sveFepu0rYZilylDCa_dO5l7L_ygmWy6e-T4lk42AQah_nWWn-FzmbvL0p0V0ju6xh-lw5kcBN3VFP5cGaUPvPQMUmgwNs1DOI03OhBd6AbhHilMTYURUVFHsYLEU9o6nnuvYnMSbQqyXCEUUxfWtR4hrWyYWZVDByOHWNb8esVV0Pgy3JGK-BEd5ChphBAlpcf_AVCnTUxn1qgj4mfWWOOIp1uyd9bA4JmRbbBhs9mxec0ALY59Bu-dwxnaVtt74f0vo6xeHSQOWqCwq9BgkVdToc40F9WXDtAdsnW2UBn_lv-4xDE',  # noqa
    'p': '4fMR5ypBeoB2ySbjwlQ_pcy7gOQ9Vz4LKxamOD24Irur1NVO7pvS9MIWIbMG1HFyGo2V1GQwSyif5hlKVnLcHgcAY2kt-5GGxZGXvqB0B9_6QK5DK8Ly41EGfG14Fcn0_wyTlSw7gU9JP-IPh1W4i7IR19dG207yu0PQJ1O6hjgISTMrOzmp22-Tdbb5m1E6HWv1qbX8zUW6U4uzA14bLcpkyooACp0WsC2kEJ3fvnK4P_SJg4B0QcSa_wAkkiAcrHAIfYhlBuR5UgdHLA5ZFrMWNPYH4FnHH75zNubRQxshj5xjndE6y8hpT9oIT8vzlRq6GHRb--3EOSkHuVBWDQ',  # noqa
    'q': '3upv461xjhfGrTKHoVmNleWhc5hTlsQ_214I01X3_Po-rVS7_SoCXcUpb-64b7RuDkvQJKOePRad9Id4cYEi-7vURq_dG7uJ-bhvuCDYAqBB5HsLKuZ38Uz1EPoui9ABZW-6mCf_8_Z3aLyDNWBGZz9UVilpbeUOEon60XdvTWdPLWGCq_kt_m7utNE2kMzs6RJIuWsKQ2wXLpofhN6tdbfF0M1o_g9BUNvO0rzPTZKZCpKrmM8XfMIdOeIHxEHpfDzgQKwCP117m8uog9rkqME26dKstVA5xxLcU1w0adfeotwcYXANfGG5KwvYs3K0LJ45KfccA9ocFzGtyXIRmw',  # noqa
    'dp': 'o5FGLZVOb3MeCsJHcP9yUAFk34rayRRWG2w7Ck3LxgEcBGgiyuMtFRiH0v95-0Lg-k3y4B1jRJV1I6q9QNXHeUlSQ6T5r7sK2G1sb4hSVv0Sec5tO_nVwS9_xYWtwABChnxBPmUV8qdF_KQW377zaNWQyzLBzbNaTqxpvH6FcfKQNQWAz1AQIZWlJzs9eO2VZ4UnAyOGjcdjemWQQujWPhDdZC4Al65epU11Dr5rIcCEl2_cOME95_p-xgkBcHMkrsQvsUiS8illljdEk6UTYzZj5hURYJ09ZEKHv3_aj3zNj9wD1VSI_srnSfIpwDKB9Dez7k4V5MucGFEWkVWR5Q',  # noqa
    'dq': 'YS49RznHBpZQ9BLSVEIxWob4gueGkXTPDfiJynBxI2WJS5FkPzNAQtcAgJ7G41P6otrkTATUqHcit4cTuA__S1WQbpyevUdeGHMSqWgQI9zvvQbzUGmXIqhVMmiPQD6XTTyPUWQmzpnFZvDAFtX4-2v9fW6iWtl_8A8dPJJgAJOoTfVzvTttlL2R7VxD-I6OPfHNqKAEom4OES_5y7g0UNykLapPOms2I2UgXnkXuw7ND3HvwzeNWsNZcHGcxy-g9ZuofClA9ZTwnXQE7C7Sfst1ACzrRERMXABZ8zGAXCBTHBbvfH8YMgB8dEq-10SLTeRQsX3cRcWhd28d_3NuPw',  # noqa
    'qi': 'iXoVkn5X2k577W1XV4VFz7mSXPRTmy7t3YpdPcU_0qQh8vP6JIAfS4nL6HRdXoZvFRNCmjJNT3pnZXXwmm6M2ZFPRLVDYi4KbZ2HaaXWN7SXBAnBCE6nlgY7IPnO6x2ksc_5UbE3ETLMM1Yy4FcZa3RuTRUjC7qFWkl-hd4e-gtRNajUcVjG2ZNcB2siSUxVa79HQAY59bqWMJnVQZnRdndLw2hm6UC9ZhrC9BDGdz6Fyiek1RPLGZX2ukyq9AXMu4ADyoTI0pTcAPWO1uOoxw7E9BOvQj07SIn77g6i-C3hXbdVfVfVrA57_pgS9Fk-QunTDaH8wVHEGB7FAIGPjA',  # noqa
}  # yapf: disable

TEST_JWKS = {
    'keys': [TEST_KEY_PUB],
}


@pytest.fixture
def jwks(monkeypatch):
    monkeypatch.setattr(
        'landoapi.auth.get_jwks', lambda *args, **kwargs: TEST_JWKS
    )


def create_access_token(
    iss=None, aud=None, sub=None, scope=None, iat=None, exp=None, key=None
):
    """Return a signed jwt access_token for testing."""
    headers = {}

    key = key or TEST_KEY_PRIV
    if 'kid' in key:
        headers['kid'] = key['kid']

    iss = iss or 'https://{oidc_domain}/'.format(
        oidc_domain='lando-api.auth0.test'
    )
    aud = aud or [
        'lando-api',
        'https://lando-api.auth0.test/userinfo',
    ]
    return jwt.encode(
        {
            'iss': iss,
            'aud': aud,
            'sub': sub or 'user@example.com',
            'scope': scope or 'all',
            'iat': iat or int(time.time()),
            'exp': exp or int(time.time()) + 30,
        },
        key,
        headers=headers,
        algorithm='RS256',
    )


def noop(*args, **kwargs):
    return ConnexionResponse(status_code=200)


def test_require_access_token_missing(app):
    with app.test_request_context('/', headers=[]):
        with pytest.raises(ProblemException) as exc_info:
            require_access_token(noop)()

    assert exc_info.value.status == 401


@pytest.mark.parametrize(
    'headers,status', [
        ([('Authorization', 'MALFORMED')], 401),
        ([('Authorization', 'MALFORMED 12345')], 401),
        ([('Authorization', 'BEARER 12345 12345')], 401),
        ([('Authorization', '')], 401),
        ([('Authorization', 'Bearer bogus')], 400),
    ]
)
def test_require_access_token_malformed(jwks, app, headers, status):
    with app.test_request_context('/', headers=headers):
        with pytest.raises(ProblemException) as exc_info:
            require_access_token(noop)()

    assert exc_info.value.status == status


def test_require_access_token_no_kid_match(jwks, app):
    key = copy.deepcopy(TEST_KEY_PRIV)
    key['kid'] = 'BOGUSKID'
    token = create_access_token(key=key)
    headers = [('Authorization', 'Bearer {}'.format(token))]

    with app.test_request_context('/', headers=headers):
        with pytest.raises(ProblemException) as exc_info:
            require_access_token(noop)()

    assert exc_info.value.status == 400
    assert exc_info.value.title == 'Authorization Header Invalid'
    assert exc_info.value.detail == (
        'Appropriate key for Authorization header could not be found'
    )


@pytest.mark.parametrize(
    'token_kwargs,status,title', [
        ({
            'exp': 1
        }, 401, 'Token Expired'),
        ({
            'iss': 'bogus issuer'
        }, 401, 'Invalid Claims'),
        ({
            'aud': 'bogus audience'
        }, 401, 'Invalid Claims'),
    ]
)
def test_require_access_token_invalid(jwks, app, token_kwargs, status, title):
    token = create_access_token(**token_kwargs)
    headers = [('Authorization', 'Bearer {}'.format(token))]

    with app.test_request_context('/', headers=headers):
        with pytest.raises(ProblemException) as exc_info:
            require_access_token(noop)()

    assert exc_info.value.status == status
    assert exc_info.value.title == title


@pytest.mark.parametrize('token_kwargs', [
    {},
])
def test_require_access_token_valid(
    jwks,
    app,
    token_kwargs,
):
    token = create_access_token(**token_kwargs)
    headers = [('Authorization', 'Bearer {}'.format(token))]
    with app.test_request_context('/', headers=headers):
        resp = require_access_token(noop)()

    assert resp.status_code == 200


def test_get_auth0_userinfo(app):
    with app.app_context():
        with requests_mock.mock() as m:
            m.get('/userinfo', status_code=200, json=CANNED_USERINFO_1)
            resp = get_auth0_userinfo(create_access_token())

    assert resp.status_code == 200


def test_require_auth0_userinfo_expired_token(jwks, app):
    # Make sure requiring userinfo also validates the token first.
    expired_token = create_access_token(exp=1)
    headers = [('Authorization', 'Bearer {}'.format(expired_token))]
    with app.test_request_context('/', headers=headers):
        with pytest.raises(ProblemException) as exc_info:
            require_auth0_userinfo(noop)()

    assert exc_info.value.status == 401
    assert exc_info.value.title == 'Token Expired'


@pytest.mark.parametrize(
    'exc,status,title', [
        (requests.exceptions.ConnectTimeout, 500, 'Auth0 Timeout'),
        (requests.exceptions.ReadTimeout, 500, 'Auth0 Timeout'),
        (requests.exceptions.ProxyError, 500, 'Auth0 Connection Problem'),
        (requests.exceptions.SSLError, 500, 'Auth0 Connection Problem'),
        (requests.exceptions.HTTPError, 500, 'Auth0 Response Error'),
        (requests.exceptions.RequestException, 500, 'Auth0 Error'),
    ]
)
def test_require_auth0_userinfo_auth0_request_errors(
    jwks, app, exc, status, title
):
    token = create_access_token()
    headers = [('Authorization', 'Bearer {}'.format(token))]
    with app.test_request_context('/', headers=headers):
        with requests_mock.mock() as m:
            m.get('/userinfo', exc=exc)

            with pytest.raises(ProblemException) as exc_info:
                require_auth0_userinfo(noop)()

    assert exc_info.value.status == status
    assert exc_info.value.title == title


@pytest.mark.parametrize(
    'a0status,a0kwargs,status,title', [
        (429, {'text': 'Too Many Requests'}, 429, 'Auth0 Rate Limit'),
        (401, {'text': 'Unauthorized'}, 401, 'Auth0 Userinfo Unauthorized'),
        (200, {'text': 'NOT JSON'}, 500, 'Auth0 Response Error'),
    ]
)  # yapf: disable
def test_require_auth0_userinfo_auth0_failures(
    jwks, app, a0status, a0kwargs, status, title
):
    token = create_access_token()
    headers = [('Authorization', 'Bearer {}'.format(token))]
    with app.test_request_context('/', headers=headers):
        with requests_mock.mock() as m:
            m.get('/userinfo', status_code=a0status, **a0kwargs)

            with pytest.raises(ProblemException) as exc_info:
                require_auth0_userinfo(noop)()

    assert exc_info.value.status == status
    assert exc_info.value.title == title


def test_require_auth0_userinfo_succeeded(jwks, app):
    token = create_access_token()
    headers = [('Authorization', 'Bearer {}'.format(token))]
    with app.test_request_context('/', headers=headers):
        with requests_mock.mock() as m:
            m.get('/userinfo', status_code=200, json=CANNED_USERINFO_1)

            resp = require_auth0_userinfo(noop)()

    assert resp.status_code == 200
