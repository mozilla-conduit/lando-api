# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import os
from unittest.mock import MagicMock

import pytest

from landoapi import patches
from landoapi.mocks.canned_responses.auth0 import CANNED_USERINFO
from landoapi.models.transplant import Transplant, TransplantStatus
from landoapi.phabricator import ReviewerStatus, RevisionStatus
from landoapi.repos import Repo, SCM_LEVEL_3
from landoapi.reviews import get_collated_reviewers
from landoapi.tasks import admin_remove_phab_project
from landoapi.transplant_client import TransplantClient
from landoapi.transplants import (
    RevisionWarning,
    TransplantAssessment,
    warning_not_accepted,
    warning_previously_landed,
    warning_reviews_not_current,
    warning_revision_secure,
)


def test_dryrun_no_warnings_or_blockers(client, db, phabdouble, auth0_mock):
    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=phabdouble.repo())
    phabdouble.reviewer(r1, phabdouble.user(username="reviewer"))
    phabdouble.reviewer(r1, phabdouble.project("reviewer2"))

    response = client.post(
        "/transplants/dryrun",
        json={
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]}
            ]
        },
        headers=auth0_mock.mock_headers,
    )

    assert 200 == response.status_code
    assert "application/json" == response.content_type
    expected_json = {"confirmation_token": None, "warnings": [], "blocker": None}
    assert response.json == expected_json


def test_dryrun_invalid_path_blocks(client, db, phabdouble, auth0_mock):
    d1 = phabdouble.diff()
    d2 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=phabdouble.repo())
    r2 = phabdouble.revision(
        diff=d2, repo=phabdouble.repo(name="not-mozilla-central"), depends_on=[r1]
    )
    phabdouble.reviewer(r1, phabdouble.user(username="reviewer"))
    phabdouble.reviewer(r1, phabdouble.project("reviewer2"))

    response = client.post(
        "/transplants/dryrun",
        json={
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]},
                {"revision_id": "D{}".format(r2["id"]), "diff_id": d2["id"]},
            ]
        },
        headers=auth0_mock.mock_headers,
    )

    assert 200 == response.status_code
    assert "application/json" == response.content_type
    assert response.json["blocker"] is not None


def test_dryrun_in_progress_transplant_blocks(client, db, phabdouble, auth0_mock):
    repo = phabdouble.repo()

    # Structure:
    # *     merge
    # |\
    # | *   r2
    # *     r1
    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=repo)

    d2 = phabdouble.diff()
    r2 = phabdouble.revision(diff=d2, repo=repo)

    # merge
    phabdouble.revision(diff=phabdouble.diff(), repo=repo, depends_on=[r1, r2])

    # Create am in progress transplant on r2, which should
    # block attempts to land r1.
    _create_transplant(
        db,
        request_id=1,
        landing_path=[(r1["id"], d1["id"])],
        status=TransplantStatus.submitted,
    )

    phabdouble.reviewer(r1, phabdouble.user(username="reviewer"))
    phabdouble.reviewer(r1, phabdouble.project("reviewer2"))

    response = client.post(
        "/transplants/dryrun",
        json={
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]}
            ]
        },
        headers=auth0_mock.mock_headers,
    )

    assert 200 == response.status_code
    assert "application/json" == response.content_type
    assert response.json["blocker"] == (
        "A landing for revisions in this stack is already in progress."
    )


def test_dryrun_reviewers_warns(client, db, phabdouble, auth0_mock):
    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=phabdouble.repo())
    phabdouble.reviewer(
        r1, phabdouble.user(username="reviewer"), status=ReviewerStatus.REJECTED
    )

    response = client.post(
        "/transplants/dryrun",
        json={
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]}
            ]
        },
        headers=auth0_mock.mock_headers,
    )

    assert 200 == response.status_code
    assert "application/json" == response.content_type
    assert response.json["warnings"]
    assert response.json["warnings"][0]["id"] == 0
    assert response.json["confirmation_token"] is not None


@pytest.mark.parametrize(
    "userinfo,status,blocker",
    [
        (
            CANNED_USERINFO["NO_CUSTOM_CLAIMS"],
            200,
            "You have insufficient permissions to land. Level 3 "
            "Commit Access is required. See the FAQ for help.",
        ),
        (CANNED_USERINFO["EXPIRED_L3"], 200, "Your Level 3 Commit Access has expired."),
        (
            CANNED_USERINFO["UNVERIFIED_EMAIL"],
            200,
            "You do not have a Mozilla verified email address.",
        ),
    ],
)
def test_integrated_dryrun_blocks_for_bad_userinfo(
    client, db, auth0_mock, phabdouble, userinfo, status, blocker
):
    auth0_mock.userinfo = userinfo
    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=phabdouble.repo())

    response = client.post(
        "/transplants/dryrun",
        json={
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]}
            ]
        },
        headers=auth0_mock.mock_headers,
        content_type="application/json",
    )

    assert response.status_code == status
    assert response.json["blocker"] == blocker


def test_get_transplants_for_entire_stack(db, client, phabdouble):
    d1a = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1a, repo=phabdouble.repo())
    d1b = phabdouble.diff(revision=r1)

    d2 = phabdouble.diff()
    r2 = phabdouble.revision(diff=d2, repo=phabdouble.repo(), depends_on=[r1])

    d3 = phabdouble.diff()
    r3 = phabdouble.revision(diff=d3, repo=phabdouble.repo(), depends_on=[r1])

    d_not_in_stack = phabdouble.diff()
    r_not_in_stack = phabdouble.revision(diff=d_not_in_stack, repo=phabdouble.repo())

    t1 = _create_transplant(
        db,
        request_id=1,
        landing_path=[(r1["id"], d1a["id"])],
        status=TransplantStatus.failed,
    )
    t2 = _create_transplant(
        db,
        request_id=2,
        landing_path=[(r1["id"], d1b["id"])],
        status=TransplantStatus.landed,
    )
    t3 = _create_transplant(
        db,
        request_id=3,
        landing_path=[(r2["id"], d2["id"])],
        status=TransplantStatus.submitted,
    )
    t4 = _create_transplant(
        db,
        request_id=4,
        landing_path=[(r3["id"], d3["id"])],
        status=TransplantStatus.landed,
    )

    t_not_in_stack = _create_transplant(
        db,
        request_id=5,
        landing_path=[(r_not_in_stack["id"], d_not_in_stack["id"])],
        status=TransplantStatus.landed,
    )

    response = client.get("/transplants?stack_revision_id=D{}".format(r2["id"]))
    assert response.status_code == 200
    assert len(response.json) == 4

    tmap = {i["id"]: i for i in response.json}
    assert t_not_in_stack.id not in tmap
    assert all(t.id in tmap for t in (t1, t2, t3, t4))


def test_get_transplant_from_middle_revision(db, client, phabdouble):
    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=phabdouble.repo())

    d2 = phabdouble.diff()
    r2 = phabdouble.revision(diff=d2, repo=phabdouble.repo(), depends_on=[r1])

    d3 = phabdouble.diff()
    r3 = phabdouble.revision(diff=d3, repo=phabdouble.repo(), depends_on=[r1])

    t = _create_transplant(
        db,
        request_id=1,
        landing_path=[(r1["id"], d1["id"]), (r2["id"], d2["id"]), (r3["id"], d3["id"])],
        status=TransplantStatus.failed,
    )

    response = client.get("/transplants?stack_revision_id=D{}".format(r2["id"]))
    assert response.status_code == 200
    assert len(response.json) == 1
    assert response.json[0]["id"] == t.id


def test_get_transplant_not_authorized_to_view_revision(db, client, phabdouble):
    # Create a transplant pointing at a revision that will not
    # be returned by phabricator.
    _create_transplant(
        db, request_id=1, landing_path=[(1, 1)], status=TransplantStatus.submitted
    )
    response = client.get("/transplants?stack_revision_id=D1")
    assert response.status_code == 404


def test_warning_previously_landed_no_landings(db, phabdouble):
    phab = phabdouble.get_phabricator_client()
    d = phabdouble.diff()
    r = phabdouble.revision(diff=d)

    revision = phab.call_conduit(
        "differential.revision.search",
        constraints={"phids": [r["phid"]]},
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )["data"][0]
    diff = phab.call_conduit(
        "differential.diff.search",
        constraints={"phids": [d["phid"]]},
        attachments={"commits": True},
    )["data"][0]
    assert warning_previously_landed(revision=revision, diff=diff) is None


def test_warning_previously_landed_failed_landing(db, phabdouble):
    phab = phabdouble.get_phabricator_client()
    d = phabdouble.diff()
    r = phabdouble.revision(diff=d)

    _create_transplant(
        db,
        request_id=1,
        landing_path=[(r["id"], d["id"])],
        status=TransplantStatus.failed,
    )

    revision = phab.call_conduit(
        "differential.revision.search",
        constraints={"phids": [r["phid"]]},
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )["data"][0]
    diff = phab.call_conduit(
        "differential.diff.search",
        constraints={"phids": [d["phid"]]},
        attachments={"commits": True},
    )["data"][0]
    assert warning_previously_landed(revision=revision, diff=diff) is None


def test_warning_previously_landed_landed_landing(db, phabdouble):
    phab = phabdouble.get_phabricator_client()
    d = phabdouble.diff()
    r = phabdouble.revision(diff=d)

    _create_transplant(
        db,
        request_id=1,
        landing_path=[(r["id"], d["id"])],
        status=TransplantStatus.landed,
    )

    revision = phab.call_conduit(
        "differential.revision.search",
        constraints={"phids": [r["phid"]]},
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )["data"][0]
    diff = phab.call_conduit(
        "differential.diff.search",
        constraints={"phids": [d["phid"]]},
        attachments={"commits": True},
    )["data"][0]
    assert warning_previously_landed(revision=revision, diff=diff) is not None


def test_warning_revision_secure_project_none(phabdouble):
    phab = phabdouble.get_phabricator_client()
    r = phabdouble.revision(diff=phabdouble.diff())

    revision = phab.call_conduit(
        "differential.revision.search",
        constraints={"phids": [r["phid"]]},
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )["data"][0]
    assert warning_revision_secure(revision=revision, secure_project_phid=None) is None


def test_warning_revision_secure_is_secure(phabdouble, secure_project):
    phab = phabdouble.get_phabricator_client()
    r = phabdouble.revision(diff=phabdouble.diff(), projects=[secure_project])

    revision = phab.call_conduit(
        "differential.revision.search",
        constraints={"phids": [r["phid"]]},
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )["data"][0]
    assert (
        warning_revision_secure(
            revision=revision, secure_project_phid=secure_project["phid"]
        )
        is not None
    )


def test_warning_revision_secure_is_not_secure(phabdouble, secure_project):
    phab = phabdouble.get_phabricator_client()
    not_secure_project = phabdouble.project("not_secure_project")
    r = phabdouble.revision(diff=phabdouble.diff(), projects=[not_secure_project])

    revision = phab.call_conduit(
        "differential.revision.search",
        constraints={"phids": [r["phid"]]},
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )["data"][0]
    assert (
        warning_revision_secure(
            revision=revision, secure_project_phid=secure_project["phid"]
        )
        is None
    )


@pytest.mark.parametrize(
    "status", [s for s in RevisionStatus if s is not RevisionStatus.ACCEPTED]
)
def test_warning_not_accepted_warns_on_other_status(phabdouble, status):
    phab = phabdouble.get_phabricator_client()
    r = phabdouble.revision(status=status)

    revision = phab.call_conduit(
        "differential.revision.search",
        constraints={"phids": [r["phid"]]},
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )["data"][0]
    assert warning_not_accepted(revision=revision) is not None


def test_warning_not_accepted_no_warning_when_accepted(phabdouble):
    phab = phabdouble.get_phabricator_client()
    r = phabdouble.revision(status=RevisionStatus.ACCEPTED)

    revision = phab.call_conduit(
        "differential.revision.search",
        constraints={"phids": [r["phid"]]},
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )["data"][0]
    assert warning_not_accepted(revision=revision) is None


def test_warning_reviews_not_current_warns_on_unreviewed_diff(phabdouble):
    phab = phabdouble.get_phabricator_client()
    d_reviewed = phabdouble.diff()
    r = phabdouble.revision(diff=d_reviewed)
    phabdouble.reviewer(
        r,
        phabdouble.user(username="reviewer"),
        on_diff=d_reviewed,
        status=ReviewerStatus.ACCEPTED,
    )
    d_new = phabdouble.diff(revision=r)

    revision = phab.call_conduit(
        "differential.revision.search",
        constraints={"phids": [r["phid"]]},
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )["data"][0]
    reviewers = get_collated_reviewers(revision)

    diff = phab.call_conduit(
        "differential.diff.search",
        constraints={"phids": [d_new["phid"]]},
        attachments={"commits": True},
    )["data"][0]

    assert (
        warning_reviews_not_current(revision=revision, diff=diff, reviewers=reviewers)
        is not None
    )


def test_warning_reviews_not_current_warns_on_unreviewed_revision(phabdouble):
    phab = phabdouble.get_phabricator_client()
    d = phabdouble.diff()
    r = phabdouble.revision(diff=d)
    # Don't create any reviewers.

    revision = phab.call_conduit(
        "differential.revision.search",
        constraints={"phids": [r["phid"]]},
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )["data"][0]
    reviewers = get_collated_reviewers(revision)

    diff = phab.call_conduit(
        "differential.diff.search",
        constraints={"phids": [d["phid"]]},
        attachments={"commits": True},
    )["data"][0]

    assert (
        warning_reviews_not_current(revision=revision, diff=diff, reviewers=reviewers)
        is not None
    )


def test_warning_reviews_not_current_no_warning_on_accepted_diff(phabdouble):
    phab = phabdouble.get_phabricator_client()
    d = phabdouble.diff()
    r = phabdouble.revision(diff=d)
    phabdouble.reviewer(
        r,
        phabdouble.user(username="reviewer"),
        on_diff=d,
        status=ReviewerStatus.ACCEPTED,
    )

    revision = phab.call_conduit(
        "differential.revision.search",
        constraints={"phids": [r["phid"]]},
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )["data"][0]
    reviewers = get_collated_reviewers(revision)

    diff = phab.call_conduit(
        "differential.diff.search",
        constraints={"phids": [d["phid"]]},
        attachments={"commits": True},
    )["data"][0]

    assert (
        warning_reviews_not_current(revision=revision, diff=diff, reviewers=reviewers)
        is None
    )


def test_confirmation_token_warning_order():
    warnings_a = [
        RevisionWarning(0, "W0", 123, "Details123"),
        RevisionWarning(0, "W0", 124, "Details124"),
        RevisionWarning(1, "W1", 123, "Details123"),
        RevisionWarning(3, "W3", 13, "Details3"),
        RevisionWarning(1000, "W1000", 13, "Details3"),
    ]
    warnings_b = [
        warnings_a[3],
        warnings_a[1],
        warnings_a[0],
        warnings_a[4],
        warnings_a[2],
    ]

    assert all(
        TransplantAssessment.confirmation_token(warnings_a)
        == TransplantAssessment.confirmation_token(w)
        for w in (warnings_b, reversed(warnings_a), reversed(warnings_b))
    )


def test_integrated_transplant_simple_stack_saves_data_in_db(
    db, client, phabdouble, transfactory, s3, auth0_mock
):
    repo = phabdouble.repo()
    user = phabdouble.user(username="reviewer")

    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=repo)
    phabdouble.reviewer(r1, user)

    d2 = phabdouble.diff()
    r2 = phabdouble.revision(diff=d2, repo=repo, depends_on=[r1])
    phabdouble.reviewer(r2, user)

    d3 = phabdouble.diff()
    r3 = phabdouble.revision(diff=d3, repo=repo, depends_on=[r2])
    phabdouble.reviewer(r3, user)

    transplant_request_id = 3
    transfactory.mock_successful_response(transplant_request_id)

    response = client.post(
        "/transplants",
        json={
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]},
                {"revision_id": "D{}".format(r2["id"]), "diff_id": d2["id"]},
                {"revision_id": "D{}".format(r3["id"]), "diff_id": d3["id"]},
            ]
        },
        headers=auth0_mock.mock_headers,
    )
    assert response.status_code == 202
    assert response.content_type == "application/json"
    assert "id" in response.json
    transplant_id = response.json["id"]

    # Ensure DB access isn't using uncommitted data.
    db.session.close()

    # Get Transplant object by its id
    transplant = Transplant.query.get(transplant_id)
    assert transplant.id == transplant_id
    assert transplant.revision_to_diff_id == {
        str(r1["id"]): d1["id"],
        str(r2["id"]): d2["id"],
        str(r3["id"]): d3["id"],
    }
    assert transplant.revision_order == [str(r1["id"]), str(r2["id"]), str(r3["id"])]
    assert transplant.status == TransplantStatus.submitted
    assert transplant.request_id == transplant_request_id


def test_integrated_transplant_checkin_project_removed(
    db, client, phabdouble, transfactory, s3, auth0_mock, checkin_project, monkeypatch
):
    repo = phabdouble.repo()
    user = phabdouble.user(username="reviewer")

    d = phabdouble.diff()
    r = phabdouble.revision(diff=d, repo=repo, projects=[checkin_project])
    phabdouble.reviewer(r, user)

    transfactory.mock_successful_response(3)

    mock_remove = MagicMock(admin_remove_phab_project)
    monkeypatch.setattr(
        "landoapi.api.transplants.admin_remove_phab_project", mock_remove
    )

    response = client.post(
        "/transplants",
        json={
            "landing_path": [{"revision_id": "D{}".format(r["id"]), "diff_id": d["id"]}]
        },
        headers=auth0_mock.mock_headers,
    )
    assert response.status_code == 202
    assert mock_remove.apply_async.called
    _, call_kwargs = mock_remove.apply_async.call_args
    assert call_kwargs["args"] == (r["phid"], checkin_project["phid"])


def test_integrated_transplant_without_auth0_permissions(
    client, auth0_mock, phabdouble, db
):
    auth0_mock.userinfo = CANNED_USERINFO["NO_CUSTOM_CLAIMS"]

    repo = phabdouble.repo(name="mozilla-central")
    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=repo)
    response = client.post(
        "/transplants",
        json={
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]}
            ]
        },
        headers=auth0_mock.mock_headers,
    )

    assert response.status_code == 400
    assert response.json["blocker"] == (
        "You have insufficient permissions to land. "
        "Level 3 Commit Access is required. See the FAQ for help."
    )


def test_integrated_push_bookmark_sent_when_supported_repo(
    db,
    client,
    phabdouble,
    monkeypatch,
    s3,
    auth0_mock,
    get_phab_client,
    mock_repo_config,
):
    # Mock the repo to have a push bookmark.
    mock_repo_config(
        {
            "test": {
                "mozilla-central": Repo(
                    "mozilla-central", SCM_LEVEL_3, "@", "http://hg.test"
                )
            }
        }
    )

    # Mock the phabricator response data
    repo = phabdouble.repo(name="mozilla-central")
    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=repo)
    phabdouble.reviewer(r1, phabdouble.user(username="reviewer"))
    patch_url = patches.url("landoapi.test.bucket", patches.name(r1["id"], d1["id"]))

    tsclient = MagicMock(spec=TransplantClient)
    tsclient().land.return_value = 1
    monkeypatch.setattr("landoapi.api.transplants.TransplantClient", tsclient)
    client.post(
        "/transplants",
        json={
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]}
            ]
        },
        headers=auth0_mock.mock_headers,
    )
    tsclient().land.assert_called_once_with(
        revision_id=r1["id"],
        ldap_username="tuser@example.com",
        patch_urls=[patch_url],
        tree="mozilla-central",
        pingback="{}/landings/update".format(os.getenv("PINGBACK_HOST_URL")),
        push_bookmark="@",
    )


@pytest.mark.parametrize(
    "mock_error_method",
    [
        "mock_http_error_response",
        "mock_connection_error_response",
        "mock_malformed_data_response",
    ],
)
def test_integrated_transplant_error_responds_with_502(
    app, db, client, phabdouble, transfactory, s3, auth0_mock, mock_error_method
):
    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=phabdouble.repo())
    phabdouble.reviewer(r1, phabdouble.user(username="reviewer"))
    getattr(transfactory, mock_error_method)()

    response = client.post(
        "/transplants",
        json={
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]}
            ]
        },
        headers=auth0_mock.mock_headers,
    )

    assert response.status_code == 502
    assert response.json["title"] == "Transplant not created"


def test_transplant_wrong_landing_path_format(client, auth0_mock):
    response = client.post(
        "/transplants",
        json={"landing_path": [{"revision_id": 1, "diff_id": 1}]},
        headers=auth0_mock.mock_headers,
    )
    assert response.status_code == 400

    response = client.post(
        "/transplants",
        json={"landing_path": [{"revision_id": "1", "diff_id": 1}]},
        headers=auth0_mock.mock_headers,
    )
    assert response.status_code == 400

    response = client.post(
        "/transplants",
        json={"landing_path": [{"revision_id": "D1"}]},
        headers=auth0_mock.mock_headers,
    )
    assert response.status_code == 400


def test_integrated_transplant_diff_not_in_revision(
    db, client, phabdouble, s3, auth0_mock
):
    repo = phabdouble.repo()
    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=repo)
    d2 = phabdouble.diff()
    phabdouble.revision(diff=d2, repo=repo)

    response = client.post(
        "/transplants",
        json={
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d2["id"]}
            ]
        },
        headers=auth0_mock.mock_headers,
    )
    assert response.status_code == 400
    assert response.json["blocker"] == "A requested diff is not the latest."


def test_transplant_nonexisting_revision_returns_404(
    db, client, phabdouble, auth0_mock
):
    response = client.post(
        "/transplants",
        json={"landing_path": [{"revision_id": "D1", "diff_id": 1}]},
        headers=auth0_mock.mock_headers,
    )
    assert response.status_code == 404
    assert response.content_type == "application/problem+json"
    assert response.json["title"] == "Stack Not Found"


def test_integrated_transplant_revision_with_no_repo(
    db, client, phabdouble, auth0_mock
):
    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1)

    response = client.post(
        "/transplants",
        json={
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]}
            ]
        },
        headers=auth0_mock.mock_headers,
    )
    assert response.status_code == 400
    assert response.json["title"] == "Landing is Blocked"
    assert response.json["blocker"] == (
        "The requested set of revisions are not landable."
    )


def test_integrated_transplant_revision_with_unmapped_repo(
    db, client, phabdouble, auth0_mock
):
    repo = phabdouble.repo(name="notsupported")
    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=repo)

    response = client.post(
        "/transplants",
        json={
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]}
            ]
        },
        headers=auth0_mock.mock_headers,
    )
    assert response.status_code == 400
    assert response.json["title"] == "Landing is Blocked"
    assert response.json["blocker"] == (
        "The requested set of revisions are not landable."
    )


def test_display_branch_head():
    assert Transplant(revision_order=["1", "2"]).head_revision == "D2"


def _create_transplant(
    db,
    *,
    request_id=1,
    landing_path=((1, 1),),
    requester_email="tuser@example.com",
    tree="mozilla-central",
    repository_url="http://hg.test",
    status=TransplantStatus.submitted
):
    transplant = Transplant(
        request_id=request_id,
        revision_to_diff_id={str(r_id): d_id for r_id, d_id in landing_path},
        revision_order=[str(r_id) for r_id, _ in landing_path],
        requester_email=requester_email,
        tree=tree,
        repository_url=repository_url,
        status=status,
    )
    db.session.add(transplant)
    db.session.commit()
    return transplant
