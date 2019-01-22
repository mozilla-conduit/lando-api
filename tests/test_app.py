# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
""" Tests for application setup and configuration code."""

import pytest

from landoapi.app import url_from_environ


@pytest.mark.parametrize("var_value", ["landoapi.test", "/somepath.html", ""])
def test_invalid_url_from_environ(monkeypatch, var_value):
    monkeypatch.setenv("LANDO_API_URL", var_value)

    with pytest.raises(ValueError, match="Error validating URL"):
        url_from_environ("LANDO_API_URL", die=False)


def test_valid_url_from_environ(monkeypatch):
    expected_urlstr = "https://landoapi.test"
    monkeypatch.setenv("LANDO_API_URL", expected_urlstr)
    urlstr = url_from_environ("LANDO_API_URL", die=False)
    assert urlstr == expected_urlstr


def test_varname_for_urlstr_missing_from_environ(monkeypatch):
    monkeypatch.delenv("LANDO_API_URL", raising=False)
    with pytest.raises(ValueError, match="Error validating URL"):
        url_from_environ("LANDO_API_URL", die=False)
