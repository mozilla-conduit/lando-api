# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import pytest
from landoapi.models import SecApprovalRequest
from landoapi.secapproval import make_secure_commit_message_review_comment
from landoapi.storage import db


@pytest.fixture(autouse=True)
def preamble(app, db, monkeypatch):
    # All API acceptance tests need the 'app' fixture to function.

    # Mock a valid API token.
    monkeypatch.setattr(
        "landoapi.decorators.PhabricatorClient.verify_api_token",
        lambda *args, **kwargs: True,
    )


@pytest.fixture
def authed_headers(auth0_mock):
    """Return a set of Auth0 and Phabricator auth'd headers for use by the test client.
    """
    headers = auth0_mock.mock_headers.copy()
    headers.append(("X-Phabricator-API-Key", "custom-key"))
    return headers


def monogram(revision):
    """Returns the monogram for a Phabricator API revision object.

    For example, a revision with ID 567 returns "D567".
    """
    return f"D{revision['id']}"


def test_integrated_stack_reports_sec_approval_in_progress(
    client, authed_headers, phabdouble, secure_project, sec_approval_project
):
    revision = _setup_inprogress_sec_approval_request(
        "", "original insecure title", phabdouble, secure_project
    )

    # Sanity check to ensure the system thinks a review is already in progress.
    response = client.get(f"/stacks/{monogram(revision)}", headers=authed_headers)
    assert response == 200
    assert response.json["revisions"][0]["security"]["has_security_review"]


def test_integrated_request_sec_approval_for_revision(
    client, authed_headers, phabdouble, secure_project, sec_approval_project
):
    revision = phabdouble.revision(projects=[secure_project])
    response = client.post(
        "/requestSecApproval",
        json={"revision_id": monogram(revision), "form_content": "My form answers"},
        headers=authed_headers,
    )

    assert response == 200


def test_integrated_request_sec_approval_with_commit_message(
    client, authed_headers, phabdouble, secure_project, sec_approval_project
):
    revision = phabdouble.revision(projects=[secure_project])
    response = client.post(
        "/requestSecApproval",
        json={
            "revision_id": monogram(revision),
            "form_content": "my answers",
            "sanitized_message": "obscure",
        },
        headers=authed_headers,
    )

    assert response == 200


def test_integrated_public_revisions_cannot_be_submitted_for_sec_approval(
    client, authed_headers, phabdouble
):
    public_project = phabdouble.project("public")
    revision = phabdouble.revision(projects=[public_project])
    response = client.post(
        "/requestSecApproval",
        json={"revision_id": monogram(revision), "form_content": "oops"},
        headers=authed_headers,
    )

    assert response == 400
    assert response.json["title"] == "Operation only allowed for secure revisions"


def test_integrated_request_with_empty_fields_is_an_error(
    client, authed_headers, phabdouble, secure_project, sec_approval_project
):
    revision = phabdouble.revision(projects=[secure_project])
    response = client.post(
        "/requestSecApproval",
        json={
            "revision_id": monogram(revision),
            "form_content": "",
            "sanitized_message": "",
        },
        headers=authed_headers,
    )

    assert response == 400
    assert response.json["title"] == "Empty sec-approval request form"


def test_integrated_resending_sec_approval_form_is_not_allowed(
    client, authed_headers, phabdouble, secure_project, sec_approval_project
):
    revision = _setup_inprogress_sec_approval_request(
        "", "original insecure title", phabdouble, secure_project
    )

    response = client.post(
        "/requestSecApproval",
        json={"revision_id": monogram(revision), "form_content": "my answers"},
        headers=authed_headers,
    )

    assert response == 400
    assert response.json["title"] == "Sec-approval request already in progress"


def _setup_inprogress_sec_approval_request(
    sanitized_commit_message,
    revision_title,
    phabdouble,
    secure_project,
    sec_approval_comment_body=None,
):
    diff = phabdouble.diff()

    # Build a specially formatted sec-approval request comment.
    if sec_approval_comment_body is None:
        sec_approval_comment_body = make_secure_commit_message_review_comment(
            sanitized_commit_message
        )
    mock_comment = phabdouble.comment(sec_approval_comment_body)

    # Build a secure revision.
    secure_revision = phabdouble.revision(
        diff=diff,
        repo=phabdouble.repo(),
        projects=[secure_project],
        title=revision_title,
    )

    # Add the two sec-approval request transactions to Phabricator. This also links
    # the sec-approval request comment to the secure revision.
    comment_txn = phabdouble.api_object_for(
        phabdouble.transaction("comment", secure_revision, comments=[mock_comment])
    )
    review_txn = phabdouble.api_object_for(
        phabdouble.transaction("reviewers.add", secure_revision)
    )

    # Prime the database with our sec-approval request, as if we had made an earlier
    # request via the API.
    new_request = SecApprovalRequest.build(
        phabdouble.api_object_for(secure_revision), [comment_txn, review_txn]
    )
    db.session.add(new_request)
    db.session.commit()

    return secure_revision
