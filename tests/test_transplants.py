# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from landoapi.mocks.canned_responses.auth0 import CANNED_USERINFO
from landoapi.models.transplant import Transplant
from landoapi.models.landing_job import LandingJob, LandingJobStatus
from landoapi.models.revisions import Revision
from landoapi.phabricator import ReviewerStatus, PhabricatorRevisionStatus
from landoapi.repos import Repo, SCM_CONDUIT, DONTBUILD
from landoapi.reviews import get_collated_reviewers
from landoapi.tasks import admin_remove_phab_project
from landoapi.transplants import (
    RevisionWarning,
    TransplantAssessment,
    warning_not_accepted,
    warning_previously_landed,
    warning_reviews_not_current,
    warning_revision_secure,
    warning_wip_commit_message,
)


def _create_landing_job(
    db,
    *,
    landing_path=((1, 1),),
    revisions=None,
    requester_email="tuser@example.com",
    repository_name="mozilla-central",
    repository_url="http://hg.test",
    status=None,
):
    job = LandingJob(
        revision_to_diff_id={str(r_id): d_id for r_id, d_id in landing_path},
        revision_order=[str(r_id) for r_id, _ in landing_path],
        requester_email=requester_email,
        repository_name=repository_name,
        repository_url=repository_url,
        status=status,
    )
    db.session.add(job)
    db.session.commit()
    return job


def test_dryrun_no_warnings_or_blockers(
    client, db, phabdouble, auth0_mock, release_management_project
):
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


def test_dryrun_invalid_path_blocks(
    client, db, phabdouble, auth0_mock, release_management_project
):
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


def test_dryrun_in_progress_transplant_blocks(
    client, db, phabdouble, auth0_mock, release_management_project
):
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
    _create_landing_job(
        db,
        landing_path=[(r1["id"], d1["id"])],
        status=LandingJobStatus.SUBMITTED,
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


def test_dryrun_reviewers_warns(
    client, db, phabdouble, auth0_mock, release_management_project
):
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


def test_dryrun_codefreeze_warn(
    client,
    db,
    phabdouble,
    auth0_mock,
    codefreeze_datetime,
    monkeypatch,
    request_mocker,
    release_management_project,
):
    product_details = "https://product-details.mozilla.org/1.0/firefox_versions.json"
    request_mocker.register_uri(
        "GET",
        product_details,
        json={
            "NEXT_SOFTFREEZE_DATE": "two_days_ago",
            "NEXT_MERGE_DATE": "tomorrow",
        },
    )
    monkeypatch.setattr("landoapi.transplants.datetime", codefreeze_datetime())
    mc_repo = Repo(
        tree="mozilla-conduit",
        url="https://hg.test/mozilla-conduit",
        access_group=SCM_CONDUIT,
        commit_flags=[DONTBUILD],
        product_details_url=product_details,
    )
    mc_mock = MagicMock()
    mc_mock.return_value = {"mozilla-central": mc_repo}
    monkeypatch.setattr("landoapi.transplants.get_repos_for_env", mc_mock)

    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=phabdouble.repo())
    phabdouble.reviewer(
        r1, phabdouble.user(username="reviewer"), status=ReviewerStatus.ACCEPTED
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

    assert response.status_code == 200
    assert response.content_type == "application/json"
    assert response.json[
        "warnings"
    ], "warnings should not be empty for a repo under code freeze"
    assert (
        response.json["warnings"][0]["id"] == 8
    ), "the warning ID should match the ID for warning_code_freeze"
    assert response.json["confirmation_token"] is not None


def test_dryrun_outside_codefreeze(
    client,
    db,
    phabdouble,
    auth0_mock,
    codefreeze_datetime,
    monkeypatch,
    request_mocker,
    release_management_project,
):
    product_details = "https://product-details.mozilla.org/1.0/firefox_versions.json"
    request_mocker.register_uri(
        "GET",
        product_details,
        json={
            "NEXT_SOFTFREEZE_DATE": "four_weeks_from_today",
            "NEXT_MERGE_DATE": "five_weeks_from_today",
        },
    )
    monkeypatch.setattr("landoapi.transplants.datetime", codefreeze_datetime())
    mc_repo = Repo(
        tree="mozilla-conduit",
        url="https://hg.test/mozilla-conduit",
        access_group=SCM_CONDUIT,
        commit_flags=[DONTBUILD],
        product_details_url=product_details,
    )
    mc_mock = MagicMock()
    mc_mock.return_value = {"mozilla-central": mc_repo}
    monkeypatch.setattr("landoapi.transplants.get_repos_for_env", mc_mock)

    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=phabdouble.repo())
    phabdouble.reviewer(
        r1, phabdouble.user(username="reviewer"), status=ReviewerStatus.ACCEPTED
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

    assert response.status_code == 200
    assert response.content_type == "application/json"
    assert not response.json["warnings"]


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
    client,
    db,
    auth0_mock,
    phabdouble,
    userinfo,
    status,
    blocker,
    release_management_project,
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

    t1 = _create_landing_job(
        db,
        landing_path=[(r1["id"], d1a["id"])],
        status=LandingJobStatus.FAILED,
    )
    t2 = _create_landing_job(
        db,
        landing_path=[(r1["id"], d1b["id"])],
        status=LandingJobStatus.LANDED,
    )
    t3 = _create_landing_job(
        db,
        landing_path=[(r2["id"], d2["id"])],
        status=LandingJobStatus.SUBMITTED,
    )
    t4 = _create_landing_job(
        db,
        landing_path=[(r3["id"], d3["id"])],
        status=LandingJobStatus.LANDED,
    )

    t_not_in_stack = _create_landing_job(
        db,
        landing_path=[(r_not_in_stack["id"], d_not_in_stack["id"])],
        status=LandingJobStatus.LANDED,
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

    t = _create_landing_job(
        db,
        landing_path=[(r1["id"], d1["id"]), (r2["id"], d2["id"]), (r3["id"], d3["id"])],
        status=LandingJobStatus.FAILED,
    )

    response = client.get("/transplants?stack_revision_id=D{}".format(r2["id"]))
    assert response.status_code == 200
    assert len(response.json) == 1
    assert response.json[0]["id"] == t.id


def test_get_transplant_not_authorized_to_view_revision(db, client, phabdouble):
    # Create a transplant pointing at a revision that will not
    # be returned by phabricator.
    _create_landing_job(db, landing_path=[(1, 1)], status=LandingJobStatus.SUBMITTED)
    response = client.get("/transplants?stack_revision_id=D1")
    assert response.status_code == 404


def test_warning_previously_landed_no_landings(db, phabdouble):
    d = phabdouble.diff()
    r = phabdouble.revision(diff=d)
    revision = phabdouble.api_object_for(
        r, attachments={"reviewers": True, "reviewers-extra": True, "projects": True}
    )
    diff = phabdouble.api_object_for(d, attachments={"commits": True})
    assert warning_previously_landed(revision=revision, diff=diff) is None


def test_warning_previously_landed_failed_landing(db, phabdouble):
    d = phabdouble.diff()
    r = phabdouble.revision(diff=d)

    _create_landing_job(
        db,
        landing_path=[(r["id"], d["id"])],
        status=LandingJobStatus.FAILED,
    )

    revision = phabdouble.api_object_for(
        r, attachments={"reviewers": True, "reviewers-extra": True, "projects": True}
    )
    diff = phabdouble.api_object_for(d, attachments={"commits": True})

    assert warning_previously_landed(revision=revision, diff=diff) is None


def test_warning_previously_landed_landed_landing(db, phabdouble):
    d = phabdouble.diff()
    r = phabdouble.revision(diff=d)

    _create_landing_job(
        db,
        landing_path=[(r["id"], d["id"])],
        status=LandingJobStatus.LANDED,
    )

    revision = phabdouble.api_object_for(
        r, attachments={"reviewers": True, "reviewers-extra": True, "projects": True}
    )
    diff = phabdouble.api_object_for(d, attachments={"commits": True})

    assert warning_previously_landed(revision=revision, diff=diff) is not None


def test_warning_revision_secure_project_none(phabdouble):
    revision = phabdouble.api_object_for(
        phabdouble.revision(),
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )

    assert warning_revision_secure(revision=revision, secure_project_phid=None) is None


def test_warning_revision_secure_is_secure(phabdouble, secure_project):
    revision = phabdouble.api_object_for(
        phabdouble.revision(projects=[secure_project]),
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )

    assert (
        warning_revision_secure(
            revision=revision, secure_project_phid=secure_project["phid"]
        )
        is not None
    )


def test_warning_revision_secure_is_not_secure(phabdouble, secure_project):
    not_secure_project = phabdouble.project("not_secure_project")
    revision = phabdouble.api_object_for(
        phabdouble.revision(projects=[not_secure_project]),
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )

    assert (
        warning_revision_secure(
            revision=revision, secure_project_phid=secure_project["phid"]
        )
        is None
    )


@pytest.mark.parametrize(
    "status",
    [
        s
        for s in PhabricatorRevisionStatus
        if s is not PhabricatorRevisionStatus.ACCEPTED
    ],
)
def test_warning_not_accepted_warns_on_other_status(phabdouble, status):
    revision = phabdouble.api_object_for(
        phabdouble.revision(status=status),
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )

    assert warning_not_accepted(revision=revision) is not None


def test_warning_not_accepted_no_warning_when_accepted(phabdouble):
    revision = phabdouble.api_object_for(
        phabdouble.revision(status=PhabricatorRevisionStatus.ACCEPTED),
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )

    assert warning_not_accepted(revision=revision) is None


def test_warning_reviews_not_current_warns_on_unreviewed_diff(phabdouble):
    d_reviewed = phabdouble.diff()
    r = phabdouble.revision(diff=d_reviewed)
    phabdouble.reviewer(
        r,
        phabdouble.user(username="reviewer"),
        on_diff=d_reviewed,
        status=ReviewerStatus.ACCEPTED,
    )
    d_new = phabdouble.diff(revision=r)
    revision = phabdouble.api_object_for(
        r, attachments={"reviewers": True, "reviewers-extra": True, "projects": True}
    )
    reviewers = get_collated_reviewers(revision)
    diff = phabdouble.api_object_for(d_new, attachments={"commits": True})

    assert (
        warning_reviews_not_current(revision=revision, diff=diff, reviewers=reviewers)
        is not None
    )


def test_warning_reviews_not_current_warns_on_unreviewed_revision(phabdouble):
    d = phabdouble.diff()
    r = phabdouble.revision(diff=d)
    # Don't create any reviewers.

    revision = phabdouble.api_object_for(
        r, attachments={"reviewers": True, "reviewers-extra": True, "projects": True}
    )
    reviewers = get_collated_reviewers(revision)
    diff = phabdouble.api_object_for(d, attachments={"commits": True})

    assert (
        warning_reviews_not_current(revision=revision, diff=diff, reviewers=reviewers)
        is not None
    )


def test_warning_reviews_not_current_no_warning_on_accepted_diff(phabdouble):
    d = phabdouble.diff()
    r = phabdouble.revision(diff=d)
    phabdouble.reviewer(
        r,
        phabdouble.user(username="reviewer"),
        on_diff=d,
        status=ReviewerStatus.ACCEPTED,
    )

    revision = phabdouble.api_object_for(
        r, attachments={"reviewers": True, "reviewers-extra": True, "projects": True}
    )
    reviewers = get_collated_reviewers(revision)
    diff = phabdouble.api_object_for(d, attachments={"commits": True})

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
    db,
    client,
    phabdouble,
    auth0_mock,
    release_management_project,
    register_codefreeze_uri,
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
    job_id = response.json["id"]

    # Ensure DB access isn't using uncommitted data.
    db.session.close()

    # Get LandingJob object by its id
    job = LandingJob.query.get(job_id)
    assert job.id == job_id
    assert job.revision_to_diff_id == {
        str(r1["id"]): d1["id"],
        str(r2["id"]): d2["id"],
        str(r3["id"]): d3["id"],
    }
    assert job.revision_order == [str(r1["id"]), str(r2["id"]), str(r3["id"])]
    assert job.status == LandingJobStatus.SUBMITTED


def test_integrated_transplant_with_flags(
    db, client, phabdouble, auth0_mock, monkeypatch, release_management_project
):
    repo = phabdouble.repo(name="mozilla-new")
    user = phabdouble.user(username="reviewer")

    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=repo)
    phabdouble.reviewer(r1, user)

    test_flags = ["VALIDFLAG1", "VALIDFLAG2"]

    mock_format_commit_message = MagicMock()
    mock_format_commit_message.return_value = "Mock formatted commit message."
    monkeypatch.setattr(
        "landoapi.api.transplants.format_commit_message", mock_format_commit_message
    )
    response = client.post(
        "/transplants",
        json={
            "flags": test_flags,
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]}
            ],
        },
        headers=auth0_mock.mock_headers,
    )
    assert response.status_code == 202
    assert response.content_type == "application/json"
    assert mock_format_commit_message.call_count == 1
    assert test_flags in mock_format_commit_message.call_args[0]


def test_integrated_transplant_with_invalid_flags(
    db, client, phabdouble, auth0_mock, monkeypatch, release_management_project
):
    repo = phabdouble.repo(name="mozilla-new")
    user = phabdouble.user(username="reviewer")

    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=repo)
    phabdouble.reviewer(r1, user)

    test_flags = ["VALIDFLAG1", "INVALIDFLAG"]
    response = client.post(
        "/transplants",
        json={
            "flags": test_flags,
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]}
            ],
        },
        headers=auth0_mock.mock_headers,
    )
    assert response.status_code == 400


def test_integrated_transplant_legacy_repo_checkin_project_removed(
    db,
    client,
    phabdouble,
    transfactory,
    auth0_mock,
    checkin_project,
    monkeypatch,
    release_management_project,
    register_codefreeze_uri,
):
    repo = phabdouble.repo(name="mozilla-central")
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


def test_integrated_transplant_repo_checkin_project_removed(
    db,
    client,
    phabdouble,
    auth0_mock,
    checkin_project,
    monkeypatch,
    release_management_project,
):
    repo = phabdouble.repo(name="mozilla-new")
    user = phabdouble.user(username="reviewer")

    d = phabdouble.diff()
    r = phabdouble.revision(diff=d, repo=repo, projects=[checkin_project])
    phabdouble.reviewer(r, user)

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
    call_kwargs = mock_remove.apply_async.call_args[1]
    assert call_kwargs["args"] == (r["phid"], checkin_project["phid"])


def test_integrated_transplant_without_auth0_permissions(
    client, auth0_mock, phabdouble, db, release_management_project
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


def test_transplant_wrong_landing_path_format(db, client, auth0_mock):
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
    db, client, phabdouble, auth0_mock, release_management_project
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
    db, client, phabdouble, auth0_mock, release_management_project
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
    db, client, phabdouble, auth0_mock, release_management_project
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
    db, client, phabdouble, auth0_mock, release_management_project
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


def test_integrated_transplant_sec_approval_group_is_excluded_from_reviewers_list(
    app,
    db,
    client,
    phabdouble,
    auth0_mock,
    transfactory,
    sec_approval_project,
    release_management_project,
    register_codefreeze_uri,
):
    repo = phabdouble.repo()
    user = phabdouble.user(username="normal_reviewer")

    diff = phabdouble.diff()
    revision = phabdouble.revision(diff=diff, repo=repo)
    phabdouble.reviewer(revision, user)
    phabdouble.reviewer(revision, sec_approval_project)

    transfactory.mock_successful_response()

    response = client.post(
        "/transplants",
        json={
            "landing_path": [
                {"revision_id": "D{}".format(revision["id"]), "diff_id": diff["id"]}
            ]
        },
        headers=auth0_mock.mock_headers,
    )
    assert response == 202

    # Check the transplanted patch for our alternate commit message.
    patch_text = Revision.get_from_revision_id(revision["id"]).patch_bytes.decode(
        "utf-8"
    )
    assert sec_approval_project["name"] not in patch_text


def test_warning_wip_commit_message(phabdouble):
    revision = phabdouble.api_object_for(
        phabdouble.revision(
            title="WIP: Bug 123: test something r?reviewer",
            status=PhabricatorRevisionStatus.ACCEPTED,
        ),
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )

    assert warning_wip_commit_message(revision=revision) is not None


def test_display_branch_head():
    assert Transplant(revision_order=["1", "2"]).head_revision == "D2"


def test_codefreeze_datetime_mock(codefreeze_datetime):
    dt = codefreeze_datetime()
    assert dt.now(tz=timezone.utc) == datetime(2000, 1, 5, 0, 0, 0, tzinfo=timezone.utc)
    assert dt.strptime("tomorrow -0800", fmt="") == datetime(2000, 1, 6, 0, 0, 0)


def test_unresolved_comment_warn(
    client,
    db,
    phabdouble,
    auth0_mock,
    release_management_project,
):
    """Ensure a warning is generated when a revision has unresolved comments.

    This test sets up a revision and adds a resolved comment and dummy
    transaction. Sending a request should not generate a warning at this
    stage.

    Adding an unresolved comment and making the request again should
    generate a warning.
    """
    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=phabdouble.repo())
    phabdouble.reviewer(r1, phabdouble.user(username="reviewer"))
    phabdouble.transaction(
        transaction_type="inline",
        object=r1,
        comments=["this is done"],
        fields={"isDone": True},
    )
    # get_inline_comments should filter out unrelated transaction types.
    phabdouble.transaction("dummy", r1)

    response = client.post(
        "/transplants/dryrun",
        json={
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]}
            ]
        },
        headers=auth0_mock.mock_headers,
    )

    assert response.status_code == 200
    assert response.content_type == "application/json"
    assert not response.json[
        "warnings"
    ], "warnings should be empty for a revision without unresolved comments"

    phabdouble.transaction(
        transaction_type="inline",
        object=r1,
        comments=["this is not done"],
        fields={"isDone": False},
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

    assert response.status_code == 200
    assert response.content_type == "application/json"
    assert response.json[
        "warnings"
    ], "warnings should not be empty for a revision with unresolved comments"
    assert (
        response.json["warnings"][0]["id"] == 9
    ), "the warning ID should match the ID for warning_unresolved_comments"


def test_unresolved_comment_stack(
    client,
    db,
    phabdouble,
    auth0_mock,
    release_management_project,
):
    """
    Ensure a warning is generated when a revision in the stack has unresolved comments.

    This test sets up a stack and adds a transaction to each revision, including
    unresolved comments and a dummy transaction.
    """
    repo = phabdouble.repo()
    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=repo)
    phabdouble.reviewer(r1, phabdouble.user(username="reviewer"))

    d2 = phabdouble.diff()
    r2 = phabdouble.revision(diff=d2, repo=repo, depends_on=[r1])
    phabdouble.reviewer(r2, phabdouble.user(username="reviewer"))

    d3 = phabdouble.diff()
    r3 = phabdouble.revision(diff=d3, repo=repo, depends_on=[r2])
    phabdouble.reviewer(r3, phabdouble.user(username="reviewer"))

    phabdouble.transaction(
        transaction_type="inline",
        object=r1,
        comments=["this is not done"],
        fields={"isDone": False},
    )

    phabdouble.transaction(
        transaction_type="inline",
        object=r2,
        comments=["this is not done"],
        fields={"isDone": False},
    )

    phabdouble.transaction(
        transaction_type="inline",
        object=r3,
        comments=["this is done"],
        fields={"isDone": True},
    )

    # get_inline_comments should filter out unrelated transaction types.
    phabdouble.transaction("dummy", r3)

    response = client.post(
        "/transplants/dryrun",
        json={
            "landing_path": [
                {"revision_id": "D{}".format(r1["id"]), "diff_id": d1["id"]},
                {"revision_id": "D{}".format(r2["id"]), "diff_id": d2["id"]},
                {"revision_id": "D{}".format(r3["id"]), "diff_id": d3["id"]},
            ]
        },
        headers=auth0_mock.mock_headers,
    )

    assert response.status_code == 200
    assert response.content_type == "application/json"
    assert response.json[
        "warnings"
    ], "warnings should not be empty for a stack with unresolved comments"
    assert (
        response.json["warnings"][0]["id"] == 9
    ), "the warning ID should match the ID for warning_unresolved_comments"
