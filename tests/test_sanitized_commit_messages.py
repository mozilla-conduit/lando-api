# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import pytest
from landoapi import patches
from landoapi.models import SecApprovalRequest
from landoapi.phabricator import PhabricatorClient
from landoapi.revisions import find_title_and_summary_for_landing
from landoapi.secapproval import (
    CommentParseError,
    make_secure_commit_message_review_comment,
)
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
    """Return a set of Auth0 and Phabricator auth'd headers."""
    headers = auth0_mock.mock_headers.copy()
    headers.append(("X-Phabricator-API-Key", "custom-key"))
    return headers


def monogram(revision):
    """Returns the monogram for a Phabricator API revision object.

    For example, a revision with ID 567 returns "D567".
    """
    return f"D{revision['id']}"


def test_integrated_update_sec_approval_commit_message(
    client, authed_headers, phabdouble, secure_project, sec_approval_project
):
    _, revision = _setup_inprogress_sec_approval_request(
        "", "original insecure title", phabdouble, secure_project
    )

    response = client.post(
        "/requestSecApproval",
        json={"revision_id": monogram(revision), "sanitized_message": "obscure"},
        headers=authed_headers,
    )

    assert response == 200


def test_integrated_empty_commit_message_is_an_error(
    client, authed_headers, phabdouble, secure_project, sec_approval_project
):
    revision = phabdouble.revision(projects=[secure_project])
    response = client.post(
        "/requestSecApproval",
        json={"revision_id": monogram(revision), "sanitized_message": ""},
        headers=authed_headers,
    )

    assert response.status_code == 400


def test_integrated_secure_stack_has_alternate_commit_message(
    client, phabdouble, mock_repo_config, secure_project, authed_headers, monkeypatch
):
    sanitized_title = "my secure commit title"
    revision_title = "my insecure revision title"

    # Build a revision with an active sec-approval request.
    diff, secure_revision = _setup_inprogress_sec_approval_request(
        sanitized_title, revision_title, phabdouble, secure_project
    )

    # Request the revision from Lando. It should have our new title and summary.
    response = client.get("/stacks/D{}".format(secure_revision["id"]))
    assert response == 200

    revision = PhabricatorClient.single(response.json, "revisions")
    assert revision["security"]["is_secure"]
    assert revision["security"]["has_secure_commit_message"]
    assert revision["title"] == sanitized_title
    assert revision["summary"] == ""


def test_integrated_secure_stack_without_sec_approval_does_not_use_secure_message(
    client, phabdouble, mock_repo_config, secure_project
):
    # Build a plain old secure revision, no sec-approval requests made.
    secure_revision = phabdouble.revision(
        repo=phabdouble.repo(), projects=[secure_project]
    )

    response = client.get("/stacks/D{}".format(secure_revision["id"]))
    assert response == 200

    revision = PhabricatorClient.single(response.json, "revisions")
    assert revision["security"]["is_secure"]
    assert not revision["security"]["has_secure_commit_message"]


def test_integrated_sec_approval_transplant_uses_alternate_message(
    app,
    client,
    phabdouble,
    transfactory,
    s3,
    auth0_mock,
    secure_project,
    monkeypatch,
    authed_headers,
):
    sanitized_title = "my secure commit title"
    revision_title = "my insecure revision title"

    # Build a revision with an active sec-approval request.
    diff, secure_revision = _setup_inprogress_sec_approval_request(
        sanitized_title, revision_title, phabdouble, secure_project
    )

    # Get our list of warnings so we can get the confirmation token, acknowledge them,
    # and land the request.
    response = client.post(
        "/transplants/dryrun",
        json={
            "landing_path": [
                {"revision_id": monogram(secure_revision), "diff_id": diff["id"]}
            ]
        },
        headers=auth0_mock.mock_headers,
    )

    assert response == 200
    confirmation_token = response.json["confirmation_token"]

    transfactory.mock_successful_response()

    # Request landing of the patch using our alternate commit message.
    response = client.post(
        "/transplants",
        json={
            "landing_path": [
                {"revision_id": monogram(secure_revision), "diff_id": diff["id"]}
            ],
            "confirmation_token": confirmation_token,
        },
        headers=auth0_mock.mock_headers,
    )
    assert response == 202

    # Check the transplanted patch for our alternate commit message.
    patch = s3.Object(
        app.config["PATCH_BUCKET_NAME"], patches.name(secure_revision["id"], diff["id"])
    )

    for line in patch.get()["Body"].read().decode().splitlines():
        if not line.startswith("#"):
            title = line
            break
    else:
        pytest.fail("Could not find commit message title in patch body")

    assert title == sanitized_title


def test_integrated_sec_approval_problem_halts_landing(
    app,
    client,
    phabdouble,
    transfactory,
    s3,
    auth0_mock,
    secure_project,
    monkeypatch,
    authed_headers,
):
    sanitized_title = "my secure commit title"
    revision_title = "my insecure revision title"
    mangled_request_comment = "boom!"

    # Build a revision with an active sec-approval request.
    diff, secure_revision = _setup_inprogress_sec_approval_request(
        sanitized_title,
        revision_title,
        phabdouble,
        secure_project,
        sec_approval_comment_body=mangled_request_comment,
    )

    # Get our list of warnings so we can get the confirmation token, acknowledge them,
    # and land the request.
    response = client.post(
        "/transplants/dryrun",
        json={
            "landing_path": [
                {"revision_id": monogram(secure_revision), "diff_id": diff["id"]}
            ]
        },
        headers=auth0_mock.mock_headers,
    )

    assert response == 200
    confirmation_token = response.json["confirmation_token"]

    transfactory.mock_successful_response()

    # Request landing of the patch using our alternate commit message.
    with pytest.raises(CommentParseError):
        client.post(
            "/transplants",
            json={
                "landing_path": [
                    {"revision_id": monogram(secure_revision), "diff_id": diff["id"]}
                ],
                "confirmation_token": confirmation_token,
            },
            headers=auth0_mock.mock_headers,
        )


def test_find_title_and_summary_for_landing_of_public_revision(phabdouble):
    revision_title = "original insecure title"

    revision = phabdouble.revision(
        repo=phabdouble.repo(), projects=[], title=revision_title
    )
    revision = phabdouble.api_object_for(revision)

    commit_description = find_title_and_summary_for_landing(
        phabdouble.get_phabricator_client(), revision, False
    )

    assert commit_description.title == revision_title
    assert not commit_description.sanitized


def test_find_title_and_summary_for_landing_of_secure_revision_without_sec_approval(
    phabdouble, secure_project
):
    revision_title = "original insecure title"

    # Build a plain old secure revision, no sec-approval requests made.
    revision = phabdouble.revision(
        repo=phabdouble.repo(), projects=[secure_project], title=revision_title
    )
    revision = phabdouble.api_object_for(revision)

    commit_description = find_title_and_summary_for_landing(
        phabdouble.get_phabricator_client(), revision, True
    )

    assert commit_description.title == revision_title
    assert not commit_description.sanitized


def test_find_title_and_summary_for_landing_of_request_without_a_santized_message(
    monkeypatch, authed_headers, phabdouble, secure_project
):
    revision_title = "original insecure title"

    # Build a revision with an active sec-approval request.
    _, revision = _setup_inprogress_sec_approval_request(
        "",
        revision_title,
        phabdouble,
        secure_project,
        include_secure_commit_message=False,
    )
    revision = phabdouble.api_object_for(revision)

    commit_description = find_title_and_summary_for_landing(
        phabdouble.get_phabricator_client(), revision, True
    )

    assert commit_description.title == revision_title
    assert not commit_description.sanitized


def test_find_title_and_summary_for_landing_of_secure_rev_with_sec_approval(
    monkeypatch, authed_headers, phabdouble, secure_project
):
    sanitized_title = "my secure commit title"
    revision_title = "original insecure title"

    # Build a revision with an active sec-approval request.
    _, revision = _setup_inprogress_sec_approval_request(
        sanitized_title, revision_title, phabdouble, secure_project
    )
    revision = phabdouble.api_object_for(revision)

    commit_description = find_title_and_summary_for_landing(
        phabdouble.get_phabricator_client(), revision, True
    )

    assert commit_description.title == sanitized_title
    assert commit_description.sanitized


def _setup_inprogress_sec_approval_request(
    sanitized_commit_message,
    revision_title,
    phabdouble,
    secure_project,
    include_secure_commit_message=True,
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

    if include_secure_commit_message:
        # Add the two sec-approval request transactions to Phabricator. This also links
        # the sec-approval request comment to the secure revision.
        comment_txn = phabdouble.api_object_for(
            phabdouble.transaction("comment", secure_revision, comments=[mock_comment])
        )
        review_txn = phabdouble.api_object_for(
            phabdouble.transaction("reviewers.add", secure_revision)
        )
        alt_message_candidate_transactions = [comment_txn, review_txn]
    else:
        # Behave as if the user submitted only the security review request form
        # answers without a sanitized commit message.
        alt_message_candidate_transactions = []

    # Prime the database with our sec-approval request, as if we had made an earlier
    # request via the API.
    new_request = SecApprovalRequest.build(
        phabdouble.api_object_for(secure_revision), alt_message_candidate_transactions
    )
    db.session.add(new_request)
    db.session.commit()

    return diff, secure_revision
