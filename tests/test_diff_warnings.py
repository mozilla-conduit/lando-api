# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import pytest

from landoapi.models.revisions import (
    DiffWarning,
    DiffWarningGroup,
    DiffWarningStatus,
)


@pytest.fixture
def phab_header(phabdouble):
    user = phabdouble.user(username="test")
    return {"X-Phabricator-API-Key": user["apiKey"]}


@pytest.fixture
def diff_warning_data():
    return {"message": "this is a test warning"}


def test_diff_warning_create_bad_request(db, client, auth0_mock):
    """Ensure a request that is missing required data returns an error."""
    response = client.post(
        "/diff_warnings",
        json={},
    )
    assert response.status_code == 400


def test_diff_warning_create_bad_request_no_message(db, client, phab_header):
    """Ensure a request with incorrect data returns an error."""
    response = client.post(
        "/diff_warnings",
        json={"revision_id": 1, "diff_id": 1, "group": "LINT", "data": {}},
        headers=phab_header,
    )
    assert response.status_code == 400


def test_diff_warning_create(db, client, diff_warning_data, phab_header):
    """Ensure that a warning is created correctly according to provided parameters."""
    response = client.post(
        "/diff_warnings",
        json={
            "revision_id": 1,
            "diff_id": 1,
            "group": "LINT",
            "data": diff_warning_data,
        },
        headers=phab_header,
    )
    assert response.status_code == 201
    assert "id" in response.json

    pk = response.json["id"]
    warning = DiffWarning.query.get(pk)
    assert warning.group == DiffWarningGroup.LINT
    assert warning.revision_id == 1
    assert warning.diff_id == 1
    assert warning.status == DiffWarningStatus.ACTIVE
    assert warning.data == diff_warning_data


def test_diff_warning_delete(db, client, diff_warning_data, phab_header):
    """Ensure that a DELETE request will archive a warning."""
    response = client.post(
        "/diff_warnings",
        json={
            "revision_id": 1,
            "diff_id": 1,
            "group": "LINT",
            "data": diff_warning_data,
        },
        headers=phab_header,
    )
    assert response.status_code == 201
    pk = response.json["id"]
    warning = DiffWarning.query.get(pk)
    assert warning.status == DiffWarningStatus.ACTIVE

    response = client.delete(
        f"/diff_warnings/{pk}",
        headers=phab_header,
    )

    assert response.status_code == 200

    warning = DiffWarning.query.get(pk)
    assert warning.status == DiffWarningStatus.ARCHIVED


def test_diff_warning_get(db, client, diff_warning_data, phab_header):
    """Ensure that the API returns a properly serialized list of warnings."""
    response = client.post(
        "/diff_warnings",
        json={
            "revision_id": 1,
            "diff_id": 1,
            "group": "LINT",
            "data": diff_warning_data,
        },
        headers=phab_header,
    )
    assert response.status_code == 201

    response = client.post(
        "/diff_warnings",
        json={
            "revision_id": 1,
            "diff_id": 1,
            "group": "LINT",
            "data": diff_warning_data,
        },
        headers=phab_header,
    )
    assert response.status_code == 201

    # Create another diff warning in a different group.
    response = client.post(
        "/diff_warnings",
        json={
            "revision_id": 1,
            "diff_id": 1,
            "group": "GENERAL",
            "data": diff_warning_data,
        },
        headers=phab_header,
    )
    assert response.status_code == 201

    response = client.get(
        "/diff_warnings",
        query_string={"revision_id": 1, "diff_id": 1, "group": "LINT"},
        headers=phab_header,
    )
    assert response.status_code == 200
    assert response.json == [
        {
            "diff_id": 1,
            "group": "LINT",
            "id": 1,
            "revision_id": 1,
            "status": "ACTIVE",
            "data": diff_warning_data,
        },
        {
            "diff_id": 1,
            "group": "LINT",
            "id": 2,
            "revision_id": 1,
            "status": "ACTIVE",
            "data": diff_warning_data,
        },
    ]
