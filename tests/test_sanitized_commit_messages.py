# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import pytest
from landoapi import patches
from landoapi.phabricator import PhabricatorClient
from landoapi.revisions import find_title_and_summary_for_landing
from landoapi.secapproval import SECURE_COMMENT_TEMPLATE, CommentParseError


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


def test_integrated_request_sec_approval(
    client, authed_headers, db, phabdouble, secure_project, sec_approval_project
):
    revision = phabdouble.revision(projects=[secure_project])
    response = client.post(
        "/requestSecApproval",
        json={"revision_id": monogram(revision), "sanitized_message": "obscure"},
        headers=authed_headers,
    )

    assert response.status_code == 200


def test_integrated_public_revisions_cannot_be_submitted_for_sec_approval(
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
    db,
    client,
    phabdouble,
    mock_repo_config,
    secure_project,
    authed_headers,
    monkeypatch,
):
    sanitized_title = "my secure commit title"
    revision_title = "my insecure revision title"

    # Build a revision with an active sec-approval request.
    diff, secure_revision = _make_sec_approval_request(
        sanitized_title,
        revision_title,
        authed_headers,
        client,
        monkeypatch,
        phabdouble,
        secure_project,
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
    db, client, phabdouble, mock_repo_config, secure_project
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
    db,
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
    diff, secure_revision = _make_sec_approval_request(
        sanitized_title,
        revision_title,
        authed_headers,
        client,
        monkeypatch,
        phabdouble,
        secure_project,
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
    db,
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
    diff, secure_revision = _make_sec_approval_request(
        sanitized_title,
        revision_title,
        authed_headers,
        client,
        monkeypatch,
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
    db, phabdouble, secure_project
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


def test_find_title_and_summary_for_landing_of_secure_rev_with_sec_approval(
    db, client, monkeypatch, authed_headers, phabdouble, secure_project
):
    sanitized_title = "my secure commit title"
    revision_title = "original insecure title"

    # Build a revision with an active sec-approval request.
    _, revision = _make_sec_approval_request(
        sanitized_title,
        revision_title,
        authed_headers,
        client,
        monkeypatch,
        phabdouble,
        secure_project,
    )
    revision = phabdouble.api_object_for(revision)

    commit_description = find_title_and_summary_for_landing(
        phabdouble.get_phabricator_client(), revision, True
    )

    assert commit_description.title == sanitized_title
    assert commit_description.sanitized


def _make_sec_approval_request(
    sanitized_commit_message,
    revision_title,
    authed_headers,
    client,
    monkeypatch,
    phabdouble,
    secure_project,
    sec_approval_comment_body=None,
):
    diff = phabdouble.diff()

    # Build a specially formatted sec-approval request comment.
    if sec_approval_comment_body is None:
        sec_approval_comment_body = SECURE_COMMENT_TEMPLATE.format(
            message=sanitized_commit_message
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

    # PhabricatorDouble does not return valid transaction data after editing a
    # revision to ask for sec-approval. Instead of using the PhabricatorDouble fake
    # API call to get the transactions we want we'll use a traditional mock to get
    # them.
    def fake_send_message_for_review(revision_phid, message, phabclient):
        # Respond with the two transactions that should be generated by a successful
        # sec-approval request.
        return [comment_txn, review_txn]

    monkeypatch.setattr(
        "landoapi.api.secapproval.send_sanitized_commit_message_for_review",
        fake_send_message_for_review,
    )

    # Post the sec-approval request so that it gets saved into the database.
    response = client.post(
        "/requestSecApproval",
        json={
            "revision_id": monogram(secure_revision),
            "sanitized_message": sanitized_commit_message,
        },
        headers=authed_headers,
    )
    assert response == 200

    return diff, secure_revision
