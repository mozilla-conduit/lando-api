# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import pytest
import requests
import requests_mock

from landoapi.treestatus import (
    TreeStatus,
    TreeStatusCommunicationException,
    TreeStatusError,
)


@pytest.mark.parametrize(
    "exc",
    [
        requests.ConnectionError,
        requests.Timeout,
        requests.ConnectTimeout,
        requests.TooManyRedirects,
    ],
)
def test_raise_communication_exception_on_request_exceptions(treestatus_url, exc):
    api = TreeStatus(url=treestatus_url)
    with requests_mock.mock() as m:
        m.get(treestatus_url + "/trees/autoland", exc=exc)

        with pytest.raises(TreeStatusCommunicationException):
            api.request("GET", "trees/autoland")

        assert m.called


def test_raise_communication_exception_on_invalid_json(treestatus_url):
    api = TreeStatus(url=treestatus_url)
    with requests_mock.mock() as m:
        m.get(treestatus_url + "/stacks/autoland", text="invalid } json {[[")

        with pytest.raises(TreeStatusCommunicationException):
            api.request("GET", "stacks/autoland")

        assert m.called


@pytest.mark.parametrize(
    "status, body",
    [
        (404, "[]"),
        (500, "{}"),
        (500, '{"detail": "detail", "instance": "instance"}'),
        (400, "{}"),
        (401, "{}"),
    ],
)
def test_raise_error_exception_on_error_response(treestatus_url, status, body):
    api = TreeStatus(url=treestatus_url)
    with requests_mock.mock() as m:
        m.get(treestatus_url + "/trees/autoland", status_code=status, text=body)

        with pytest.raises(TreeStatusError):
            api.request("GET", "trees/autoland")

        assert m.called


def test_raise_error_with_details_on_error_response(treestatus_url):
    api = TreeStatus(url=treestatus_url)
    error = {
        "detail": "No such tree",
        "instance": "about:blank",
        "status": 404,
        "title": "404 Not Found: No such tree",
        "type": "about:blank",
    }
    with requests_mock.mock() as m:
        m.get(
            treestatus_url + "/trees/autoland", status_code=error["status"], json=error
        )

        with pytest.raises(TreeStatusError) as exc_info:
            api.request("GET", "trees/autoland")

        assert m.called
        assert exc_info.value.detail == error["detail"]
        assert exc_info.value.title == error["title"]
        assert exc_info.value.type == error["type"]
        assert exc_info.value.instance == error["instance"]
        assert exc_info.value.status_code == error["status"]
        assert exc_info.value.response == error


def test_is_open_assumes_true_on_unkown_tree(treestatusdouble):
    ts = treestatusdouble.get_treestatus_client()
    assert ts.is_open("tree-doesn't-exist")


def test_is_open_for_open_tree(treestatusdouble):
    ts = treestatusdouble.get_treestatus_client()
    treestatusdouble.open_tree("mozilla-central")
    assert ts.is_open("mozilla-central")


def test_is_open_for_closed_tree(treestatusdouble):
    ts = treestatusdouble.get_treestatus_client()
    treestatusdouble.close_tree("mozilla-central")
    assert not ts.is_open("mozilla-central")


def test_is_open_for_approval_required_tree(treestatusdouble):
    ts = treestatusdouble.get_treestatus_client()
    treestatusdouble.set_tree("mozilla-central", status="approval required")
    assert not ts.is_open("mozilla-central")
