# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import flask
import pytest

from connexion.lifecycle import ConnexionResponse

from landoapi.decorators import require_phabricator_api_key, lazy
from landoapi.phabricator_client import PhabricatorClient


def noop(*args, **kwargs):
    return ConnexionResponse(status_code=200)


@pytest.mark.parametrize(
    'optional,valid_key,status', [
        (False, None, 401),
        (False, False, 403),
        (False, True, 200),
        (True, None, 200),
        (True, False, 403),
        (True, True, 200)
    ]
)  # yapf: disable
def test_require_phabricator_api_key(
    monkeypatch, app, optional, valid_key, status
):
    headers = []
    if valid_key is not None:
        headers.append(('X-Phabricator-API-Key', 'custom-key'))
        monkeypatch.setattr(
            'landoapi.decorators.PhabricatorClient.verify_api_key',
            lambda *args, **kwargs: valid_key
        )

    with app.test_request_context('/', headers=headers):
        resp = require_phabricator_api_key(optional=optional)(noop)()
        if status == 200:
            assert isinstance(flask.g.phabricator, PhabricatorClient)
        if valid_key:
            assert flask.g.phabricator.api_key == 'custom-key'

    assert resp.status_code == status


def test_lazy_single_evaluation():
    evaluated = {
        'count': 0,
    }

    @lazy
    def counter():
        evaluated['count'] += 1
        return 'value'

    count = counter()

    assert evaluated['count'] == 0
    assert count() == 'value'
    assert evaluated['count'] == 1

    # accessing the value shouldn't call counter() again.
    assert count() == 'value'
    assert evaluated['count'] == 1


def test_lazy_recursive_calls():
    evaluated = {
        'count_a': 0,
        'count_b': 0,
        'count_c': 0,
    }

    @lazy
    def counter_a(basic, value_we_need, *, another_we_need=None):
        evaluated['count_a'] += 1
        return basic, value_we_need, another_we_need

    @lazy
    def counter_b():
        evaluated['count_b'] += 1
        return "FROM B"

    @lazy
    def counter_c():
        evaluated['count_c'] += 1
        return "FROM C"

    count_b = counter_b()
    count_c = counter_c()

    count_a = counter_a("HELLO", count_b, another_we_need=count_c)

    assert evaluated['count_a'] == 0
    assert count_a() == ("HELLO", "FROM B", "FROM C")
    assert evaluated['count_a'] == 1
    assert evaluated['count_b'] == 1
    assert evaluated['count_c'] == 1

    # accessing the value shouldn't call counter() again.
    assert count_a() == ("HELLO", "FROM B", "FROM C")
    assert evaluated['count_a'] == 1
    assert evaluated['count_b'] == 1
    assert evaluated['count_c'] == 1

    # non lazy arguments aren't called.
    assert counter_a(
        "HELLO", "FROM", another_we_need="BASIC"
    )() == ("HELLO", "FROM", "BASIC")
