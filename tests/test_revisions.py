# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import pytest
from unittest.mock import MagicMock

from landoapi.phabricator import RevisionStatus, ReviewerStatus
from landoapi.repos import get_repos_for_env

from landoapi.revisions import (
    check_author_planned_changes,
    check_diff_author_is_known,
    check_relman_approval,
    revision_is_secure,
    revision_needs_testing_tag,
)

pytestmark = pytest.mark.usefixtures("docker_env_vars")


def test_check_diff_author_is_known_with_author(phabdouble):
    # Adds author information by default.
    d = phabdouble.diff()
    phabdouble.revision(diff=d, repo=phabdouble.repo())
    diff = phabdouble.api_object_for(d, attachments={"commits": True})

    assert check_diff_author_is_known(diff=diff) is None


def test_check_diff_author_is_known_with_unknown_author(phabdouble):
    # No commits for no author data.
    d = phabdouble.diff(commits=[])
    phabdouble.revision(diff=d, repo=phabdouble.repo())
    diff = phabdouble.api_object_for(d, attachments={"commits": True})

    assert check_diff_author_is_known(diff=diff) is not None


@pytest.mark.parametrize(
    "status", [s for s in RevisionStatus if s is not RevisionStatus.CHANGES_PLANNED]
)
def test_check_author_planned_changes_changes_not_planned(phabdouble, status):
    revision = phabdouble.api_object_for(
        phabdouble.revision(status=status),
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )
    assert check_author_planned_changes(revision=revision) is None


def test_check_author_planned_changes_changes_planned(phabdouble):
    revision = phabdouble.api_object_for(
        phabdouble.revision(status=RevisionStatus.CHANGES_PLANNED),
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )
    assert check_author_planned_changes(revision=revision) is not None


def test_secure_api_flag_on_public_revision_is_false(client, phabdouble):
    public_project = phabdouble.project("public")
    revision = phabdouble.revision(projects=[public_project])

    response = client.get("/stacks/D{}".format(revision["id"]))

    assert response.status_code == 200
    response_revision = response.json["revisions"].pop()
    assert not response_revision["is_secure"]


def test_secure_api_flag_on_secure_revision_is_true(
    db, client, phabdouble, secure_project
):
    revision = phabdouble.revision(projects=[secure_project])

    response = client.get("/stacks/D{}".format(revision["id"]))

    assert response.status_code == 200
    response_revision = response.json["revisions"].pop()
    assert response_revision["is_secure"]


def test_public_revision_is_not_secure(phabdouble, secure_project):
    public_project = phabdouble.project("public")
    revision = phabdouble.api_object_for(
        phabdouble.revision(projects=[public_project]),
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )
    assert not revision_is_secure(revision, secure_project["phid"])


def test_secure_revision_is_secure(phabdouble, secure_project):
    revision = phabdouble.api_object_for(
        phabdouble.revision(projects=[secure_project]),
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )
    assert revision_is_secure(revision, secure_project["phid"])


def test_relman_approval_missing(phabdouble):
    """A repo with an approval required needs relman as reviewer"""
    relman_group = phabdouble.project("release-managers")
    repo = phabdouble.repo(name="uplift-target")
    repos = get_repos_for_env("localdev")
    assert repos["uplift-target"].approval_required is True

    revision = phabdouble.revision(repo=repo)
    phab_revision = phabdouble.api_object_for(
        revision,
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )

    check = check_relman_approval(relman_group["phid"], repos)
    assert (
        check(revision=phab_revision, repo=phabdouble.api_object_for(repo))
        == "The release-managers group was not requested for review"
    )


@pytest.mark.parametrize("status", list(ReviewerStatus))
def test_relman_approval_status(status, phabdouble):
    """Check only an approval from relman allows landing"""
    relman_group = phabdouble.project("release-managers")
    repo = phabdouble.repo(name="uplift-target")
    repos = get_repos_for_env("localdev")
    assert repos["uplift-target"].approval_required is True

    # Add relman as reviewer with specified status
    revision = phabdouble.revision(repo=repo)
    phabdouble.reviewer(revision, relman_group, status=status)

    # Add a some extra reviewers
    for i in range(3):
        phabdouble.reviewer(revision, phabdouble.user(username=f"reviewer-{i}"))

    phab_revision = phabdouble.api_object_for(
        revision,
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )

    check = check_relman_approval(relman_group["phid"], repos)
    output = check(revision=phab_revision, repo=phabdouble.api_object_for(repo))
    if status == ReviewerStatus.ACCEPTED:
        assert output is None
    else:
        assert (
            output
            == "The release-managers group did not accept that stack: you need to wait for a group approval from release-managers, or request a new review."  # noqa
        )


def test_revision_does_not_need_testing_tag(phabdouble, monkeypatch):
    testing_tag_projects = [{"phid": "testing-tag-phid"}]
    testing_policy_project = {"phid": "testing-policy-phid"}
    repo = phabdouble.repo(projects=[testing_policy_project])
    revision = phabdouble.revision(projects=testing_tag_projects, repo=repo)
    mock_get_phabricator_repo = MagicMock()
    mock_get_phabricator_repo.return_value = repo
    monkeypatch.setattr(
        "landoapi.revisions.get_phabricator_repo", mock_get_phabricator_repo
    )
    assert not revision_needs_testing_tag(
        revision, ["testing-tag-phid"], "testing-policy-phid"
    )


def test_revision_needs_testing_tag(phabdouble, monkeypatch):
    testing_policy_project = {"phid": "testing-policy-phid"}
    repo = phabdouble.repo(projects=[testing_policy_project])
    revision = phabdouble.revision(projects=[], repo=repo)
    mock_get_phabricator_repo = MagicMock()
    mock_get_phabricator_repo.return_value = repo
    monkeypatch.setattr(
        "landoapi.revisions.get_phabricator_repo", mock_get_phabricator_repo
    )
    assert revision_needs_testing_tag(
        revision, ["testing-tag-phid"], "testing-policy-phid"
    )


def test_repo_does_not_have_testing_policy(phabdouble, monkeypatch):
    repo = phabdouble.repo(projects=[])
    revision = phabdouble.revision(projects=[], repo=repo)
    mock_get_phabricator_repo = MagicMock()
    mock_get_phabricator_repo.return_value = repo
    monkeypatch.setattr(
        "landoapi.revisions.get_phabricator_repo", mock_get_phabricator_repo
    )
    assert not revision_needs_testing_tag(
        revision, ["testing-tag-phid"], "testing-policy-phid"
    )
