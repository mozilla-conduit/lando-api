# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import pytest


@pytest.fixture(autouse=True)
def preamble(app, monkeypatch):
    # All API acceptance tests need the 'app' fixture to function.

    # Mock a valid API token.
    monkeypatch.setattr(
        "landoapi.decorators.PhabricatorClient.verify_api_token",
        lambda *args, **kwargs: True,
    )


@pytest.fixture
def authed_headers(auth0_mock):
    """Return a set of Auth0 and Phabricator auth'd headers."""
    headers = auth0_mock.mock_headers.copy()
    headers.append(("X-Phabricator-API-Key", "custom-key"))
    return headers


def monogram(revision):
    """Returns the monogram for a Phabricator API revision object.

    For example, a revision with ID 567 returns "D567".
    """
    return f"D{revision['id']}"


def test_request_sec_approval(
    client, authed_headers, db, phabdouble, secure_project, sec_approval_project
):
    revision = phabdouble.revision(projects=[secure_project])
    response = client.post(
        "/requestSecApproval",
        json={"revision_id": monogram(revision), "sanitized_message": "obscure"},
        headers=authed_headers,
    )

    assert response.status_code == 200


def test_public_revisions_cannot_be_submitted_for_sec_approval(
    client, authed_headers, phabdouble
):
    public_project = phabdouble.project("public")
    revision = phabdouble.revision(projects=[public_project])
    response = client.post(
        "/requestSecApproval",
        json={"revision_id": monogram(revision), "sanitized_message": "oops"},
        headers=authed_headers,
    )

    assert response.status_code == 400


def test_empty_commit_message_is_an_error(
    client, authed_headers, phabdouble, secure_project, sec_approval_project
):
    revision = phabdouble.revision(projects=[secure_project])
    response = client.post(
        "/requestSecApproval",
        json={"revision_id": monogram(revision), "sanitized_message": ""},
        headers=authed_headers,
    )

    assert response.status_code == 400
