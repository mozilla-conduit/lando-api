# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import datetime
from typing import Optional
from unittest import mock

import pytest
from connexion import ProblemException
from pydantic import BaseModel

from landoapi.api.treestatus import (
    CombinedTree,
    get_combined_tree,
    get_tree,
)
from landoapi.treestatus import (
    is_open,
)


class IncreasingDatetime:
    """Return an object that returns datetimes with increasing times."""

    def __init__(self, initial_time: datetime.datetime = datetime.datetime.min):
        self.current_datetime = initial_time

    def __call__(self, *args, **kwargs) -> datetime.datetime:
        increased_datetime = self.current_datetime + datetime.timedelta(minutes=10)
        self.current_datetime = increased_datetime
        return increased_datetime


class TreeData(BaseModel):
    category: str
    log_id: Optional[int]
    message_of_the_day: str
    reason: str
    status: str
    tags: list[str]
    tree: str


class LogEntry(BaseModel):
    id: int
    reason: str
    status: str
    tags: list[str]
    tree: str
    when: datetime.datetime
    who: str


class LastState(BaseModel):
    log_id: Optional[int]
    reason: str
    status: str
    tags: list[str]
    current_log_id: Optional[int]
    current_reason: str
    current_status: str
    current_tags: list[str]


class TreesEntry(BaseModel):
    id: int
    last_state: LastState
    tree: str


class StackEntry(BaseModel):
    id: Optional[int]
    reason: str
    status: str
    trees: list[TreesEntry]
    when: datetime.datetime
    who: str


def test_is_open_assumes_true_on_unknown_tree(db):
    assert is_open(
        "tree-doesn't-exist"
    ), "`is_open` should return `True` for unknown tree."


def test_is_open_for_open_tree(new_treestatus_tree):
    new_treestatus_tree(tree="mozilla-central", status="open")
    assert is_open("mozilla-central"), "`is_open` should return `True` for opened tree."


def test_is_open_for_closed_tree(new_treestatus_tree):
    new_treestatus_tree(tree="mozilla-central", status="closed")
    assert not is_open(
        "mozilla-central"
    ), "`is_open` should return `False` for closed tree."


def test_is_open_for_approval_required_tree(new_treestatus_tree):
    new_treestatus_tree(tree="mozilla-central", status="approval required")
    assert is_open(
        "mozilla-central"
    ), "`is_open` should return `True` for approval required tree."


def test_get_combined_tree(new_treestatus_tree):
    tree = new_treestatus_tree(
        motd="message",
        reason="reason",
        status="status",
        tree="mozilla-central",
    )

    assert get_combined_tree(tree) == CombinedTree(
        category="other",
        log_id=None,
        message_of_the_day="message",
        model=tree,
        reason="reason",
        status="status",
        tags=[],
        tree="mozilla-central",
    ), "Combined tree does not match expected."


def test_get_tree_exists(db, new_treestatus_tree):
    tree = new_treestatus_tree(
        tree="mozilla-central", status="open", reason="reason", motd="message"
    )
    response, status = get_tree("mozilla-central")
    assert "result" in response, "Response should be contained in the `result` key."
    assert status == 200, "Response status code should be 200."

    tree_response = TreeData(**response["result"])
    assert (
        tree_response.tree == tree.tree
    ), "Returned `tree` should be `mozilla-central`."
    assert (
        tree_response.message_of_the_day == tree.message_of_the_day
    ), "Returned `message_of_the_day` should be `message`."
    assert tree_response.reason == tree.reason, "Returned `reason` should be `reason`."
    assert tree_response.status == tree.status, "Returned `status` should be `open`."


def test_get_tree_missing(db):
    # `ProblemException` should be raised when a missing tree is passed.
    with pytest.raises(ProblemException):
        get_tree("missingtree")


def test_api_get_trees2(db, client, new_treestatus_tree):
    """API test for `GET /trees2`."""
    response = client.get("/treestatus/trees2")
    assert (
        response.status_code == 200
    ), "`GET /trees2` should return 200 even when no trees are found."
    assert "result" in response.json, "Response should contain `result` key."
    assert response.json["result"] == [], "Result from Treestatus should be empty."

    new_treestatus_tree(tree="mozilla-central")
    response = client.get("/treestatus/trees2")
    assert (
        response.status_code == 200
    ), "`GET /trees2` should return 200 when trees are found."
    result = response.json.get("result")
    assert result is not None, "Response should contain `result` key."
    assert len(result) == 1, "Result from Treestatus should contain one tree"
    assert TreeData(**result[0]), "Response should match expected tree format."


def test_api_get_logs(db, client, auth0_mock):
    """API test for `GET /trees/{tree}/logs`."""

    def patch_tree(body):
        """Convenience closure to patch the tree."""
        client.patch("/treestatus/trees", headers=auth0_mock.mock_headers, json=body)

    # Create a new tree.
    client.put(
        "/treestatus/trees/tree",
        headers=auth0_mock.mock_headers,
        json={
            "category": "other",
            "status": "closed",
            "message_of_the_day": "",
            "tree": "tree",
            "reason": "",
        },
    )
    # Update status.
    patch_tree(
        {
            "reason": "first open",
            "status": "open",
            "tags": [],
            "trees": ["tree"],
        }
    )
    # Update status again.
    patch_tree(
        {
            "reason": "first close",
            "status": "closed",
            "tags": ["sometag1"],
            "trees": ["tree"],
        }
    )
    patch_tree(
        {
            "reason": "second open",
            "status": "open",
            "tags": [],
            "trees": ["tree"],
        }
    )
    # Update status again.
    patch_tree(
        {
            "reason": "second close",
            "status": "closed",
            "tags": ["sometag1"],
            "trees": ["tree"],
        }
    )
    patch_tree(
        {
            "reason": "third open",
            "status": "open",
            "tags": [],
            "trees": ["tree"],
        }
    )
    # Update status again.
    patch_tree(
        {
            "reason": "third close",
            "status": "closed",
            "tags": ["sometag1"],
            "trees": ["tree"],
        }
    )
    patch_tree(
        {
            "reason": "fourth open",
            "status": "open",
            "tags": [],
            "trees": ["tree"],
        }
    )
    # Update status again.
    patch_tree(
        {
            "reason": "fourth close",
            "status": "closed",
            "tags": ["sometag1"],
            "trees": ["tree"],
        }
    )

    # Check the most recent logs are returned.
    response = client.get(
        "/treestatus/trees/tree/logs",
        headers=auth0_mock.mock_headers,
        json={
            "status": "closed",
            "message_of_the_day": "",
            "tree": "tree",
            "reason": "",
        },
    )
    assert response.status_code == 200, "Requesting all logs should return `200`."
    result = response.json.get("result")
    assert result is not None, "Response JSON should contain `result` key."
    assert len(result) == 5, "`logs` endpoint should only return latest logs."
    expected_keys = [
        {
            "id": 8,
            "reason": "fourth close",
            "status": "closed",
            "tags": ["sometag1"],
        },
        {
            "id": 7,
            "reason": "fourth open",
            "status": "open",
            "tags": [],
        },
        {
            "id": 6,
            "reason": "third close",
            "status": "closed",
            "tags": ["sometag1"],
        },
        {
            "id": 5,
            "reason": "third open",
            "status": "open",
            "tags": [],
        },
        {
            "id": 4,
            "reason": "second close",
            "status": "closed",
            "tags": ["sometag1"],
        },
    ]

    for tree, expected in zip(result, expected_keys):
        tree_data = LogEntry(**tree)
        assert tree_data.id == expected["id"], "ID should match expected."
        assert tree_data.reason == expected["reason"], "Reason should match expected."
        assert tree_data.status == expected["status"], "Status should match expected."
        assert sorted(tree_data.tags) == sorted(
            expected["tags"]
        ), "Tags should match expected."

    # Check all results are returned from `logs_all`.
    response = client.get(
        "/treestatus/trees/tree/logs_all",
        headers=auth0_mock.mock_headers,
        json={
            "status": "closed",
            "message_of_the_day": "",
            "tree": "tree",
            "reason": "",
        },
    )
    assert response.status_code == 200, "Requesting all logs should return `200`."
    result = response.json.get("result")
    assert result is not None, "Response JSON should contain `result` key."
    expected_keys = [
        {
            "id": 8,
            "reason": "fourth close",
            "status": "closed",
            "tags": ["sometag1"],
        },
        {
            "id": 7,
            "reason": "fourth open",
            "status": "open",
            "tags": [],
        },
        {
            "id": 6,
            "reason": "third close",
            "status": "closed",
            "tags": ["sometag1"],
        },
        {
            "id": 5,
            "reason": "third open",
            "status": "open",
            "tags": [],
        },
        {
            "id": 4,
            "reason": "second close",
            "status": "closed",
            "tags": ["sometag1"],
        },
        {
            "id": 3,
            "reason": "second open",
            "status": "open",
            "tags": [],
        },
        {
            "id": 2,
            "reason": "first close",
            "status": "closed",
            "tags": ["sometag1"],
        },
        {
            "id": 1,
            "reason": "first open",
            "status": "open",
            "tags": [],
        },
    ]
    for tree, expected in zip(result, expected_keys):
        tree_data = LogEntry(**tree)
        assert tree_data.id == expected["id"], "ID should match expected."
        assert tree_data.reason == expected["reason"], "Reason should match expected."
        assert tree_data.status == expected["status"], "Status should match expected."
        assert sorted(tree_data.tags) == sorted(
            expected["tags"]
        ), "Tags should match expected."


def test_api_delete_trees_unknown(db, client, auth0_mock):
    """API test for `DELETE /trees/{tree}` with an unknown tree."""
    response = client.delete(
        "/treestatus/trees/unknowntree", headers=auth0_mock.mock_headers
    )
    assert (
        response.status_code == 404
    ), "Deleting an unknown tree should return a `404`."
    assert response.json == {
        "detail": "The tree does not exist.",
        "status": 404,
        "title": "No tree unknowntree found.",
        "type": "https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404",
    }, "Response JSON for unknown tree should match expected value."


def test_api_delete_trees_known(db, client, auth0_mock, new_treestatus_tree):
    """API test for `DELETE /trees/{tree}` with a known tree."""
    new_treestatus_tree(tree="mozilla-central")

    # Delete the tree.
    response = client.delete(
        "/treestatus/trees/mozilla-central", headers=auth0_mock.mock_headers
    )
    assert (
        response.status_code == 200
    ), "Deleting an unknown tree should return a `200`."
    assert (
        response.json == "mozilla-central"
    ), "API should return the tree name on successful delete."

    # Check that tree is deleted.
    response = client.get("/trees/mozilla-central")
    assert response.status_code == 404, "Tree should be Not Found after delete."


def test_api_put_trees_name_mismatch(db, client, auth0_mock):
    """API test for `PUT /trees/{tree}` when body and URL name do not match."""
    # Tree name in URL doesn't match body.
    response = client.put(
        "/treestatus/trees/wrongname",
        headers=auth0_mock.mock_headers,
        json={
            "category": "other",
            "status": "closed",
            "message_of_the_day": "",
            "tree": "tree",
            "reason": "",
        },
    )
    assert (
        response.status_code == 400
    ), "Mismatch of tree name in URL and body should error."


def test_api_put_trees(db, client, auth0_mock):
    """API test for `PUT /trees/{tree}`."""
    # Tree can be added as expected.
    response = client.put(
        "/treestatus/trees/tree",
        headers=auth0_mock.mock_headers,
        json={
            "category": "other",
            "status": "open",
            "message_of_the_day": "",
            "tree": "tree",
            "reason": "",
        },
    )
    assert (
        response.status_code == 200
    ), "Response code should be 200 when new tree is created."
    assert response.json["tree"] == "tree", "Tree name should match expected."
    assert response.json["status"] == "open", "Tree status should match expected."

    # Tree can be retrieved from the API after being added.
    response = client.get("/treestatus/trees/tree")
    assert (
        response.status_code == 200
    ), "Retrieving tree after addition should return 200 status code."
    result = response.json.get("result")
    assert result is not None, "Response should contain a `result` key."
    tree_data = TreeData(**result)
    assert (
        tree_data.status == "open"
    ), "Status should be retrievable after tree creation."

    # Attempt to add a duplicate tree.
    response = client.put(
        "/treestatus/trees/tree",
        headers=auth0_mock.mock_headers,
        json={
            "category": "other",
            "status": "closed",
            "message_of_the_day": "",
            "tree": "tree",
            "reason": "",
        },
    )
    assert (
        response.status_code == 400
    ), "Response code should be 400 when duplicate tree is created."
    assert response.json == {
        "detail": "Tree already exists.",
        "status": 400,
        "title": "Tree tree already exists.",
        "type": "https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
    }, "Response format should match expected."


def test_api_get_trees_single_not_found(db, client):
    """API test for `GET /trees/{tree}` with an unknown tree."""
    response = client.get("/treestatus/trees/unknowntree")
    assert (
        response.status_code == 404
    ), "Response code for unknown tree should be `404`."
    assert response.json == {
        "detail": "The tree does not exist.",
        "status": 404,
        "title": "No tree unknowntree found.",
        "type": "https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404",
    }, "Response JSON for missing result should match expected value."


def test_api_get_trees_single_exists(db, client, new_treestatus_tree):
    """API test for `GET /trees/{tree}` with a known tree."""
    new_treestatus_tree(tree="mozilla-central")

    response = client.get("/treestatus/trees/mozilla-central")
    assert (
        response.status_code == 200
    ), "Response code when a tree is found should be `200`."
    result = response.json.get("result")
    assert result is not None, "Response JSON should contain `result` key."
    get_data = TreeData(**result)
    assert get_data.tree == "mozilla-central", "Tree name should match expected"


def test_api_patch_trees_unknown_tree(db, client, auth0_mock, new_treestatus_tree):
    """API test for `PATCH /trees` with unknown tree name."""
    new_treestatus_tree(tree="mozilla-central")
    new_treestatus_tree(tree="autoland")

    # Pass a tree that doesn't exist.
    response = client.patch(
        "/treestatus/trees",
        headers=auth0_mock.mock_headers,
        json={"trees": ["badtree"]},
    )
    assert response.status_code == 404, "Passing a missing tree should return `404`."


def test_api_patch_trees_tags_required(db, client, auth0_mock, new_treestatus_tree):
    """API test for `PATCH /trees` with missing tags when closing."""
    new_treestatus_tree(tree="mozilla-central")
    new_treestatus_tree(tree="autoland")

    # Tags are required when closing a tree.
    response = client.patch(
        "/treestatus/trees",
        headers=auth0_mock.mock_headers,
        json={"status": "closed", "trees": ["autoland", "mozilla-central"]},
    )
    assert (
        response.status_code == 400
    ), "Closing a tree without tags should return `400`."
    assert response.json == {
        "detail": "Tags are required when closing a tree.",
        "status": 400,
        "title": "Tags are required when closing a tree.",
        "type": "https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
    }, "Error response should match expected."


def test_api_patch_trees_remember_required_args(
    db, client, auth0_mock, new_treestatus_tree
):
    """API test for `PATCH /trees` required args with `remember`."""
    new_treestatus_tree(tree="mozilla-central")
    new_treestatus_tree(tree="autoland")

    # Remember == True requires status.
    response = client.patch(
        "/treestatus/trees",
        headers=auth0_mock.mock_headers,
        json={
            "remember": True,
            "reason": "somereason",
            "tags": ["sometag1", "sometag2"],
            "trees": ["autoland", "mozilla-central"],
        },
    )
    assert (
        response.status_code == 400
    ), "Invalid arguments with `'remember': true` should return `400`."
    assert response.json == {
        "detail": "Must specify status, reason and tags to remember the change.",
        "status": 400,
        "title": "Must specify status, reason and tags to remember the change.",
        "type": "https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
    }, "Error response should match expected."

    # Remember == True requires reason.
    response = client.patch(
        "/treestatus/trees",
        headers=auth0_mock.mock_headers,
        json={
            "remember": True,
            "status": "open",
            "tags": ["sometag1", "sometag2"],
            "trees": ["autoland", "mozilla-central"],
        },
    )
    assert (
        response.status_code == 400
    ), "Missing `reason` with `'remember': true` should return `400`."
    assert response.json == {
        "detail": "Must specify status, reason and tags to remember the change.",
        "status": 400,
        "title": "Must specify status, reason and tags to remember the change.",
        "type": "https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
    }, "Error response should match expected."

    # Remember == True requires tags.
    response = client.patch(
        "/treestatus/trees",
        headers=auth0_mock.mock_headers,
        json={
            "remember": True,
            "reason": "somereason",
            "status": "open",
            "trees": ["autoland", "mozilla-central"],
        },
    )
    assert (
        response.status_code == 400
    ), "Missing `tags` with `'remember': true` should return `400`."
    assert response.json == {
        "detail": "Must specify status, reason and tags to remember the change.",
        "status": 400,
        "title": "Must specify status, reason and tags to remember the change.",
        "type": "https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
    }, "Error response should match expected."


def test_api_patch_trees_success_remember(db, client, auth0_mock, new_treestatus_tree):
    """API test for `PATCH /trees` success with `remember: true`."""
    tree_names = ["autoland", "mozilla-central"]
    for tree in tree_names:
        new_treestatus_tree(tree=tree)

    response = client.patch(
        "/treestatus/trees",
        headers=auth0_mock.mock_headers,
        json={
            "remember": True,
            "reason": "somereason",
            "status": "closed",
            "tags": ["sometag1", "sometag2"],
            "trees": tree_names,
        },
    )
    assert (
        response.status_code == 200
    ), "Successful updating of tree statuses should return `200`."

    # Ensure the statuses were both updated as expected.
    response = client.get("/treestatus/trees")
    result = response.json.get("result")
    assert result is not None, "Response should contain a `result` key."

    assert all(tree in result for tree in tree_names), "Both trees should be returned."

    for tree, info in result.items():
        tree_data = TreeData(**info)

        assert tree_data.status == "closed", "Tree status should be set to closed."
        assert tree_data.reason == "somereason", "Tree reason should be set."

    response = client.get("/treestatus/stack")
    assert response.status_code == 200

    result = response.json.get("result")
    assert result is not None, "Response should contain a `result` key."
    assert (
        len(result) == 1
    ), "Setting `remember: true` should have created a stack entry."

    stack_entry = StackEntry(**result[0])
    assert (
        stack_entry.reason == "somereason"
    ), "Stack entry reason should match expected."
    assert stack_entry.status == "closed", "Stack entry status should match expected."

    for tree in stack_entry.trees:
        assert tree.last_state.current_reason == "somereason"
        assert tree.last_state.current_status == "closed"
        assert tree.last_state.reason == ""
        assert tree.last_state.status == ""


def test_api_patch_trees_success_no_remember(
    db, client, auth0_mock, new_treestatus_tree
):
    """API test for `PATCH /trees` success with `remember: false`."""
    new_treestatus_tree(tree="mozilla-central")
    new_treestatus_tree(tree="autoland")

    response = client.patch(
        "/treestatus/trees",
        headers=auth0_mock.mock_headers,
        json={
            "reason": "somereason",
            "status": "closed",
            "tags": ["sometag1", "sometag2"],
            "trees": ["autoland", "mozilla-central"],
        },
    )
    assert (
        response.status_code == 200
    ), "Successful updating of tree statuses should return `200`."

    # Ensure the statuses were both updated as expected.
    response = client.get("/treestatus/trees")
    result = response.json.get("result")
    assert result is not None, "Response should contain a result key."
    assert len(result) == 2, "Two trees should be returned."
    for tree in result.values():
        tree_data = TreeData(**tree)

        assert tree_data.reason == "somereason", "Status should be updated on the tree."
        assert tree_data.status == "closed", "Status should be updated on the tree."

    response = client.get("/treestatus/stack")
    assert response.status_code == 200
    assert (
        response.json["result"] == []
    ), "Status should not have been added to the stack."


def test_api_get_trees(db, client, new_treestatus_tree):
    """API test for `GET /trees`."""
    response = client.get("/treestatus/trees")
    assert (
        response.status_code == 200
    ), "`GET /trees` should return 200 even when no trees are found."
    assert "result" in response.json, "Response should contain `result` key."
    assert response.json["result"] == {}, "Result from Treestatus should be empty."

    new_treestatus_tree(tree="mozilla-central")
    response = client.get("/treestatus/trees")
    assert (
        response.status_code == 200
    ), "`GET /trees` should return 200 when trees are found."
    assert "result" in response.json, "Response should contain `result` key."
    assert response.json["result"] == {
        "mozilla-central": {
            "category": "other",
            "log_id": None,
            "message_of_the_day": "",
            "reason": "",
            "status": "",
            "tags": [],
            "tree": "mozilla-central",
        }
    }, "Result from Treestatus should contain one tree."


@mock.patch("landoapi.api.treestatus._now")
def test_api_delete_stack2_restore(
    _now_mock, db, client, new_treestatus_tree, auth0_mock
):
    """API test for `DELETE /stack2/restore/{id}`."""
    # Mock the current time to be a steadily increasing value.
    _now_mock.side_effect = IncreasingDatetime()

    new_treestatus_tree(tree="mozilla-central")
    new_treestatus_tree(tree="autoland")

    response = client.patch(
        "/treestatus/trees",
        headers=auth0_mock.mock_headers,
        json={
            "remember": True,
            "reason": "some reason for opening",
            "status": "open",
            "tags": ["sometag1", "sometag2"],
            "trees": ["autoland", "mozilla-central"],
        },
    )
    assert response.status_code == 200, "Response code should be 200."

    response = client.patch(
        "/treestatus/trees",
        headers=auth0_mock.mock_headers,
        json={
            "remember": True,
            "reason": "some reason to close",
            "status": "closed",
            "tags": ["closingtag1", "closingtag2"],
            "trees": ["autoland", "mozilla-central"],
        },
    )

    response = client.get("/treestatus/stack")
    assert "result" in response.json, "Response should contain a `result` key."
    assert response.json["result"] == [
        {
            "id": 2,
            "reason": "some reason to close",
            "status": "closed",
            "trees": [
                {
                    "id": 3,
                    "last_state": {
                        "current_log_id": 3,
                        "current_reason": "some reason to close",
                        "current_status": "closed",
                        "current_tags": ["closingtag1", "closingtag2"],
                        "log_id": 1,
                        "reason": "some reason for opening",
                        "status": "open",
                        "tags": ["sometag1", "sometag2"],
                    },
                    "tree": "mozilla-central",
                },
                {
                    "id": 4,
                    "last_state": {
                        "current_log_id": 4,
                        "current_reason": "some reason to close",
                        "current_status": "closed",
                        "current_tags": ["closingtag1", "closingtag2"],
                        "log_id": 2,
                        "reason": "some reason for opening",
                        "status": "open",
                        "tags": ["sometag1", "sometag2"],
                    },
                    "tree": "autoland",
                },
            ],
            "when": "0001-01-01T01:00:00+00:00",
            "who": "ad|Example-LDAP|testuser",
        },
        {
            "id": 1,
            "reason": "some reason for opening",
            "status": "open",
            "trees": [
                {
                    "id": 1,
                    "last_state": {
                        "current_log_id": 1,
                        "current_reason": "some reason for opening",
                        "current_status": "open",
                        "current_tags": ["sometag1", "sometag2"],
                        "log_id": None,
                        "reason": "",
                        "status": "",
                        "tags": [],
                    },
                    "tree": "mozilla-central",
                },
                {
                    "id": 2,
                    "last_state": {
                        "current_log_id": 2,
                        "current_reason": "some reason for opening",
                        "current_status": "open",
                        "current_tags": ["sometag1", "sometag2"],
                        "log_id": None,
                        "reason": "",
                        "status": "",
                        "tags": [],
                    },
                    "tree": "autoland",
                },
            ],
            "when": "0001-01-01T00:30:00+00:00",
            "who": "ad|Example-LDAP|testuser",
        },
    ], "Current stack should contain changes."

    response = client.delete(
        "/treestatus/stack2/restore/2", headers=auth0_mock.mock_headers
    )
    assert response.status_code == 200

    response = client.get("/treestatus/stack")
    assert "result" in response.json, "Response should contain a `result` key."
    assert response.json["result"] == [
        {
            "id": 1,
            "reason": "some reason for opening",
            "status": "open",
            "trees": [
                {
                    "id": 1,
                    "last_state": {
                        "current_log_id": 1,
                        "current_reason": "some reason for opening",
                        "current_status": "open",
                        "current_tags": ["sometag1", "sometag2"],
                        "log_id": None,
                        "reason": "",
                        "status": "",
                        "tags": [],
                    },
                    "tree": "mozilla-central",
                },
                {
                    "id": 2,
                    "last_state": {
                        "current_log_id": 2,
                        "current_reason": "some reason for opening",
                        "current_status": "open",
                        "current_tags": ["sometag1", "sometag2"],
                        "log_id": None,
                        "reason": "",
                        "status": "",
                        "tags": [],
                    },
                    "tree": "autoland",
                },
            ],
            "when": "0001-01-01T00:30:00+00:00",
            "who": "ad|Example-LDAP|testuser",
        },
    ], "Current stack should restore previous stack state."

    # Check current tree state.
    response = client.get("/treestatus/trees/autoland")
    assert response.status_code == 200
    assert response.json["result"] == {
        "category": "other",
        "log_id": 6,
        "message_of_the_day": "",
        "reason": "some reason for opening",
        "status": "open",
        "tags": ["sometag1", "sometag2"],
        "tree": "autoland",
    }, "Tree status should be reset to previous."


@mock.patch("landoapi.api.treestatus._now")
def test_api_delete_stack2_discard(
    _now_mock, db, client, new_treestatus_tree, auth0_mock
):
    """API test for `DELETE /stack2/discard/{id}`."""
    # Mock the current time to be a steadily increasing value.
    _now_mock.side_effect = IncreasingDatetime()

    new_treestatus_tree(tree="mozilla-central")
    new_treestatus_tree(tree="autoland")

    response = client.patch(
        "/treestatus/trees",
        headers=auth0_mock.mock_headers,
        json={
            "remember": True,
            "reason": "some reason for opening",
            "status": "open",
            "tags": ["sometag1", "sometag2"],
            "trees": ["autoland", "mozilla-central"],
        },
    )
    assert response.status_code == 200

    response = client.patch(
        "/treestatus/trees",
        headers=auth0_mock.mock_headers,
        json={
            "remember": True,
            "reason": "some reason to close",
            "status": "closed",
            "tags": ["closingtag1", "closingtag2"],
            "trees": ["autoland", "mozilla-central"],
        },
    )

    response = client.get("/treestatus/stack")
    assert "result" in response.json, "Response should contain a `result` key."
    assert response.json["result"] == [
        {
            "id": 2,
            "reason": "some reason to close",
            "status": "closed",
            "trees": [
                {
                    "id": 3,
                    "last_state": {
                        "current_log_id": 3,
                        "current_reason": "some reason to close",
                        "current_status": "closed",
                        "current_tags": ["closingtag1", "closingtag2"],
                        "log_id": 1,
                        "reason": "some reason for opening",
                        "status": "open",
                        "tags": ["sometag1", "sometag2"],
                    },
                    "tree": "mozilla-central",
                },
                {
                    "id": 4,
                    "last_state": {
                        "current_log_id": 4,
                        "current_reason": "some reason to close",
                        "current_status": "closed",
                        "current_tags": ["closingtag1", "closingtag2"],
                        "log_id": 2,
                        "reason": "some reason for opening",
                        "status": "open",
                        "tags": ["sometag1", "sometag2"],
                    },
                    "tree": "autoland",
                },
            ],
            "when": "0001-01-01T01:00:00+00:00",
            "who": "ad|Example-LDAP|testuser",
        },
        {
            "id": 1,
            "reason": "some reason for opening",
            "status": "open",
            "trees": [
                {
                    "id": 1,
                    "last_state": {
                        "current_log_id": 1,
                        "current_reason": "some reason for opening",
                        "current_status": "open",
                        "current_tags": ["sometag1", "sometag2"],
                        "log_id": None,
                        "reason": "",
                        "status": "",
                        "tags": [],
                    },
                    "tree": "mozilla-central",
                },
                {
                    "id": 2,
                    "last_state": {
                        "current_log_id": 2,
                        "current_reason": "some reason for opening",
                        "current_status": "open",
                        "current_tags": ["sometag1", "sometag2"],
                        "log_id": None,
                        "reason": "",
                        "status": "",
                        "tags": [],
                    },
                    "tree": "autoland",
                },
            ],
            "when": "0001-01-01T00:30:00+00:00",
            "who": "ad|Example-LDAP|testuser",
        },
    ], "Current stack should contain changes."

    response = client.delete(
        "/treestatus/stack2/discard/2", headers=auth0_mock.mock_headers
    )
    assert response.status_code == 200

    response = client.get("/treestatus/stack")
    assert "result" in response.json, "Response should contain a `result` key."
    assert response.json["result"] == [
        {
            "id": 1,
            "reason": "some reason for opening",
            "status": "open",
            "trees": [
                {
                    "id": 1,
                    "last_state": {
                        "current_log_id": 1,
                        "current_reason": "some reason for opening",
                        "current_status": "open",
                        "current_tags": ["sometag1", "sometag2"],
                        "log_id": None,
                        "reason": "",
                        "status": "",
                        "tags": [],
                    },
                    "tree": "mozilla-central",
                },
                {
                    "id": 2,
                    "last_state": {
                        "current_log_id": 2,
                        "current_reason": "some reason for opening",
                        "current_status": "open",
                        "current_tags": ["sometag1", "sometag2"],
                        "log_id": None,
                        "reason": "",
                        "status": "",
                        "tags": [],
                    },
                    "tree": "autoland",
                },
            ],
            "when": "0001-01-01T00:30:00+00:00",
            "who": "ad|Example-LDAP|testuser",
        },
    ], "Current stack should contain updated changes after discard."

    response = client.get("/treestatus/trees/autoland")
    assert response.status_code == 200
    assert response.json["result"] == {
        "category": "other",
        "log_id": 4,
        "message_of_the_day": "",
        "reason": "some reason to close",
        "status": "closed",
        "tags": ["closingtag1", "closingtag2"],
        "tree": "autoland",
    }, "Tree status should be preserved."


@mock.patch("landoapi.api.treestatus._now")
def test_api_patch_stack(_now_mock, db, client, new_treestatus_tree, auth0_mock):
    """API test for `PATCH /stack/{id}`."""
    # Mock the current time to be a steadily increasing value.
    _now_mock.side_effect = IncreasingDatetime()

    new_treestatus_tree(tree="autoland")

    # Set the tree to open.
    response = client.patch(
        "/treestatus/trees",
        headers=auth0_mock.mock_headers,
        json={
            "remember": True,
            "reason": "some reason for opening",
            "status": "open",
            "tags": ["sometag1", "sometag2"],
            "trees": ["autoland"],
        },
    )
    assert response.status_code == 200

    # Set the tree to closed.
    response = client.patch(
        "/treestatus/trees",
        headers=auth0_mock.mock_headers,
        json={
            "remember": True,
            "reason": "the tree is closed.",
            "status": "closed",
            "tags": ["closed tree"],
            "trees": ["autoland"],
        },
    )
    assert response.status_code == 200

    # Get information about the stack.
    response = client.get("/treestatus/stack")
    assert response.status_code == 200
    assert response.json["result"] == [
        {
            "id": 2,
            "reason": "the tree is closed.",
            "status": "closed",
            "trees": [
                {
                    "id": 2,
                    "last_state": {
                        "current_log_id": 2,
                        "current_reason": "the tree is closed.",
                        "current_status": "closed",
                        "current_tags": ["closed tree"],
                        "log_id": 1,
                        "reason": "some reason for opening",
                        "status": "open",
                        "tags": ["sometag1", "sometag2"],
                    },
                    "tree": "autoland",
                }
            ],
            "when": "0001-01-01T00:40:00+00:00",
            "who": "ad|Example-LDAP|testuser",
        },
        {
            "id": 1,
            "reason": "some reason for opening",
            "status": "open",
            "trees": [
                {
                    "id": 1,
                    "last_state": {
                        "current_log_id": 1,
                        "current_reason": "some reason for opening",
                        "current_status": "open",
                        "current_tags": ["sometag1", "sometag2"],
                        "log_id": None,
                        "reason": "",
                        "status": "",
                        "tags": [],
                    },
                    "tree": "autoland",
                }
            ],
            "when": "0001-01-01T00:20:00+00:00",
            "who": "ad|Example-LDAP|testuser",
        },
    ]

    # Patch the stack.
    response = client.patch(
        "/treestatus/stack/1",
        headers=auth0_mock.mock_headers,
        json={"reason": "updated reason", "tags": ["updated tags"]},
    )
    assert response.status_code == 200, "Response should be `200` on successful update."

    # Check the stack has been updated.
    response = client.get("/treestatus/stack")
    assert response.status_code == 200
    assert response.json["result"] == [
        {
            "id": 2,
            "reason": "the tree is closed.",
            "status": "closed",
            "trees": [
                {
                    "id": 2,
                    "last_state": {
                        "current_log_id": 2,
                        "current_reason": "the tree is closed.",
                        "current_status": "closed",
                        "current_tags": ["closed tree"],
                        "log_id": 1,
                        "reason": "some reason for opening",
                        "status": "open",
                        "tags": ["sometag1", "sometag2"],
                    },
                    "tree": "autoland",
                }
            ],
            "when": "0001-01-01T00:40:00+00:00",
            "who": "ad|Example-LDAP|testuser",
        },
        {
            "id": 1,
            "reason": "updated reason",
            "status": "open",
            "trees": [
                {
                    "id": 1,
                    "last_state": {
                        "current_log_id": 1,
                        "current_reason": "updated reason",
                        "current_status": "open",
                        "current_tags": ["updated tags"],
                        "log_id": None,
                        "reason": "",
                        "status": "",
                        "tags": [],
                    },
                    "tree": "autoland",
                }
            ],
            "when": "0001-01-01T00:20:00+00:00",
            "who": "ad|Example-LDAP|testuser",
        },
    ], "Stack should be updated with new reason and tags."


@mock.patch("landoapi.api.treestatus._now")
def test_api_patch_log(_now_mock, client, new_treestatus_tree, auth0_mock):
    """API test for `PATCH /log/{id}`."""
    # Mock the current time to be a steadily increasing value.
    _now_mock.side_effect = IncreasingDatetime()

    new_treestatus_tree(tree="autoland")
    response = client.patch(
        "/treestatus/trees",
        headers=auth0_mock.mock_headers,
        json={
            "remember": True,
            "reason": "some reason for closing",
            "status": "closed",
            "tags": ["sometag1", "sometag2"],
            "trees": ["autoland"],
        },
    )
    assert response.status_code == 200

    response = client.get("/treestatus/trees/autoland/logs")

    log_id = response.json["result"][0]["id"]

    response = client.patch(
        f"/treestatus/log/{log_id}",
        headers=auth0_mock.mock_headers,
        json={"reason": "new log reason"},
    )
    assert (
        response.status_code == 200
    ), "Response code should be `200` on successful update."

    response = client.patch(
        f"/treestatus/log/{log_id}",
        headers=auth0_mock.mock_headers,
        json={"tags": ["new tag 1", "new tag 2"]},
    )
    assert (
        response.status_code == 200
    ), "Response code should be `200` on successful update."

    response = client.get("/treestatus/trees/autoland/logs")
    assert response.status_code == 200
    log_result = response.json["result"][0]
    assert (
        log_result["reason"] == "new log reason"
    ), "Fetching logs should show updated reason."
    assert log_result["tags"] == [
        "new tag 1",
        "new tag 2",
    ], "Fetching logs should show updated tags."

    response = client.get("/treestatus/stack")
    assert response.status_code == 200
    stack_tree = response.json["result"][0]["trees"][0]["last_state"]
    assert (
        stack_tree["current_reason"] == "new log reason"
    ), "Stack should show updated log reason."
    assert stack_tree["current_tags"] == [
        "new tag 1",
        "new tag 2",
    ], "Stack should show updated log tags."


@mock.patch("landoapi.api.treestatus._now")
def test_api_get_stack(_now_mock, db, client, new_treestatus_tree, auth0_mock):
    """API test for `GET /stack`."""
    # Mock the current time to be a steadily increasing value.
    _now_mock.side_effect = IncreasingDatetime()

    new_treestatus_tree(tree="mozilla-central")
    new_treestatus_tree(tree="autoland")

    response = client.patch(
        "/treestatus/trees",
        headers=auth0_mock.mock_headers,
        json={
            "remember": True,
            "reason": "some reason for opening",
            "status": "open",
            "tags": ["sometag1", "sometag2"],
            "trees": ["autoland", "mozilla-central"],
        },
    )
    assert response.status_code == 200

    response = client.patch(
        "/treestatus/trees",
        headers=auth0_mock.mock_headers,
        json={
            "remember": True,
            "reason": "some reason to close",
            "status": "closed",
            "tags": ["closingtag1", "closingtag2"],
            "trees": ["autoland", "mozilla-central"],
        },
    )

    response = client.get("/treestatus/stack")
    assert response.status_code == 200
    assert "result" in response.json, "Response should contain a `result` key."
    assert response.json["result"] == [
        {
            "id": 2,
            "reason": "some reason to close",
            "status": "closed",
            "trees": [
                {
                    "id": 3,
                    "last_state": {
                        "current_log_id": 3,
                        "current_reason": "some reason to close",
                        "current_status": "closed",
                        "current_tags": ["closingtag1", "closingtag2"],
                        "log_id": 1,
                        "reason": "some reason for opening",
                        "status": "open",
                        "tags": ["sometag1", "sometag2"],
                    },
                    "tree": "mozilla-central",
                },
                {
                    "id": 4,
                    "last_state": {
                        "current_log_id": 4,
                        "current_reason": "some reason to close",
                        "current_status": "closed",
                        "current_tags": ["closingtag1", "closingtag2"],
                        "log_id": 2,
                        "reason": "some reason for opening",
                        "status": "open",
                        "tags": ["sometag1", "sometag2"],
                    },
                    "tree": "autoland",
                },
            ],
            "when": "0001-01-01T01:00:00+00:00",
            "who": "ad|Example-LDAP|testuser",
        },
        {
            "id": 1,
            "reason": "some reason for opening",
            "status": "open",
            "trees": [
                {
                    "id": 1,
                    "last_state": {
                        "current_log_id": 1,
                        "current_reason": "some reason for opening",
                        "current_status": "open",
                        "current_tags": ["sometag1", "sometag2"],
                        "log_id": None,
                        "reason": "",
                        "status": "",
                        "tags": [],
                    },
                    "tree": "mozilla-central",
                },
                {
                    "id": 2,
                    "last_state": {
                        "current_log_id": 2,
                        "current_reason": "some reason for opening",
                        "current_status": "open",
                        "current_tags": ["sometag1", "sometag2"],
                        "log_id": None,
                        "reason": "",
                        "status": "",
                        "tags": [],
                    },
                    "tree": "autoland",
                },
            ],
            "when": "0001-01-01T00:30:00+00:00",
            "who": "ad|Example-LDAP|testuser",
        },
    ], "Current stack should contain changes."
