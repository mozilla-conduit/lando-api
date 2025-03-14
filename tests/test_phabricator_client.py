# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Tests for the PhabricatorClient
"""

import pytest
import requests
import requests_mock

from landoapi.phabricator import PhabricatorAPIException
from tests.utils import phab_url

pytestmark = pytest.mark.usefixtures("docker_env_vars")


def test_ping_success(get_phab_client):
    phab = get_phab_client(api_key="api-key")
    with requests_mock.mock() as m:
        m.post(
            phab_url("conduit.ping"),
            status_code=200,
            json={"result": [], "error_code": None, "error_info": None},
        )
        phab.call_conduit("conduit.ping")
        assert m.called


def test_raise_exception_if_ping_encounters_connection_error(get_phab_client):
    phab = get_phab_client(api_key="api-key")
    with requests_mock.mock() as m:
        # Test with the generic ConnectionError, which is a superclass for
        # other connection error types.
        m.post(phab_url("conduit.ping"), exc=requests.ConnectionError)

        with pytest.raises(PhabricatorAPIException):
            phab.call_conduit("conduit.ping")
        assert m.called


def test_raise_exception_if_api_ping_times_out(get_phab_client):
    phab = get_phab_client(api_key="api-key")
    with requests_mock.mock() as m:
        # Test with the generic Timeout exception, which all other timeout
        # exceptions derive from.
        m.post(phab_url("conduit.ping"), exc=requests.Timeout)

        with pytest.raises(PhabricatorAPIException):
            phab.call_conduit("conduit.ping")
        assert m.called


def test_raise_exception_if_api_returns_error_json_response(get_phab_client):
    phab = get_phab_client(api_key="api-key")
    error_json = {
        "result": None,
        "error_code": "ERR-CONDUIT-CORE",
        "error_info": "BOOM",
    }

    with requests_mock.mock() as m:
        # Test with the generic Timeout exception, which all other timeout
        # exceptions derive from.
        m.post(phab_url("conduit.ping"), status_code=500, json=error_json)

        with pytest.raises(PhabricatorAPIException):
            phab.call_conduit("conduit.ping")
        assert m.called


def test_phabricator_exception(get_phab_client):
    """Ensures that the PhabricatorClient converts JSON errors from Phabricator
    into proper exceptions with the error_code and error_message in tact.
    """
    phab = get_phab_client(api_key="api-key")
    error = {
        "result": None,
        "error_code": "ERR-CONDUIT-CORE",
        "error_info": "The value for parameter 'blah' is not valid JSON.",
    }

    with requests_mock.mock() as m:
        m.post(phab_url("differential.query"), status_code=200, json=error)
        with pytest.raises(PhabricatorAPIException) as e_info:
            phab.call_conduit("differential.query", ids=["1"])[0]
        assert e_info.value.error_code == error["error_code"]
        assert e_info.value.error_info == error["error_info"]
