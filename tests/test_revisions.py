# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import pytest

from landoapi.phabricator import PhabricatorRevisionStatus, ReviewerStatus
from landoapi.repos import get_repos_for_env
from landoapi.revisions import (
    check_author_planned_changes,
    check_diff_author_is_known,
    check_revision_data_classification,
    check_uplift_approval,
    revision_is_secure,
    revision_needs_testing_tag,
)
from landoapi.stacks import (
    request_extended_revision_data,
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
    "status",
    [
        s
        for s in PhabricatorRevisionStatus
        if s is not PhabricatorRevisionStatus.CHANGES_PLANNED
    ],
)
def test_check_author_planned_changes_changes_not_planned(phabdouble, status):
    revision = phabdouble.api_object_for(
        phabdouble.revision(status=status),
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )
    assert check_author_planned_changes(revision=revision) is None


def test_check_author_planned_changes_changes_planned(phabdouble):
    revision = phabdouble.api_object_for(
        phabdouble.revision(status=PhabricatorRevisionStatus.CHANGES_PLANNED),
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )
    assert check_author_planned_changes(revision=revision) is not None


def test_secure_api_flag_on_public_revision_is_false(
    db,
    client,
    phabdouble,
    release_management_project,
    needs_data_classification_project,
    sec_approval_project,
):
    repo = phabdouble.repo(name="test-repo")
    public_project = phabdouble.project("public")
    revision = phabdouble.revision(projects=[public_project], repo=repo)

    response = client.get("/stacks/D{}".format(revision["id"]))

    assert response.status_code == 200
    response_revision = response.json["revisions"].pop()
    assert not response_revision["is_secure"]


def test_secure_api_flag_on_secure_revision_is_true(
    db,
    client,
    phabdouble,
    secure_project,
    release_management_project,
    needs_data_classification_project,
    sec_approval_project,
):
    repo = phabdouble.repo(name="test-repo")
    revision = phabdouble.revision(projects=[secure_project], repo=repo)

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


def test_relman_approval_missing(
    phabdouble, release_management_project, needs_data_classification_project
):
    """A repo with an approval required needs relman as reviewer"""
    repo = phabdouble.repo(name="uplift-target")
    repos = get_repos_for_env("localdev")
    assert repos["uplift-target"].approval_required is True

    revision = phabdouble.revision(repo=repo)
    phab_revision = phabdouble.api_object_for(
        revision,
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )

    phab_client = phabdouble.get_phabricator_client()
    stack_data = request_extended_revision_data(phab_client, [revision["phid"]])

    check = check_uplift_approval(
        release_management_project["phid"],
        repos,
        stack_data,
    )
    assert check(revision=phab_revision, repo=phabdouble.api_object_for(repo)) == (
        "The release-managers group did not accept the stack: "
        "you need to wait for a group approval from release-managers, "
        "or request a new review."
    )


@pytest.mark.parametrize("status", list(ReviewerStatus))
def test_relman_approval_status(
    status, phabdouble, release_management_project, needs_data_classification_project
):
    """Check only an approval from relman allows landing"""
    repo = phabdouble.repo(name="uplift-target")
    repos = get_repos_for_env("localdev")
    assert repos["uplift-target"].approval_required is True

    # Add relman as reviewer with specified status
    revision = phabdouble.revision(repo=repo, uplift="blah blah")
    phabdouble.reviewer(
        revision,
        release_management_project,
        status=status,
    )

    # Add a some extra reviewers
    for i in range(3):
        phabdouble.reviewer(revision, phabdouble.user(username=f"reviewer-{i}"))

    phab_revision = phabdouble.api_object_for(
        revision,
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )

    phab_client = phabdouble.get_phabricator_client()
    stack_data = request_extended_revision_data(phab_client, [revision["phid"]])

    check = check_uplift_approval(
        release_management_project["phid"],
        repos,
        stack_data,
    )
    output = check(revision=phab_revision, repo=phabdouble.api_object_for(repo))
    if status == ReviewerStatus.ACCEPTED:
        assert output is None
    else:
        assert output == (
            "The release-managers group did not accept the stack: you need to wait "
            "for a group approval from release-managers, or request a new review."
        )


def test_revision_does_not_need_testing_tag(phabdouble):
    testing_tag_projects = [{"phid": "testing-tag-phid"}]
    testing_policy_project = {"phid": "testing-policy-phid"}
    repo = phabdouble.repo(projects=[testing_policy_project])
    revision = phabdouble.revision(projects=testing_tag_projects, repo=repo)
    assert not revision_needs_testing_tag(
        revision, repo, ["testing-tag-phid"], "testing-policy-phid"
    )


def test_revision_needs_testing_tag(phabdouble):
    testing_policy_project = {"phid": "testing-policy-phid"}
    repo = phabdouble.repo(projects=[testing_policy_project])
    revision = phabdouble.revision(projects=[], repo=repo)
    assert revision_needs_testing_tag(
        revision, repo, ["testing-tag-phid"], "testing-policy-phid"
    )


def test_repo_does_not_have_testing_policy(phabdouble):
    repo = phabdouble.repo(projects=[])
    revision = phabdouble.revision(projects=[], repo=repo)
    assert not revision_needs_testing_tag(
        revision, repo, ["testing-tag-phid"], "testing-policy-phid"
    )


def test_revision_has_data_classification_tag(
    phabdouble, needs_data_classification_project
):
    repo = phabdouble.repo()
    revision = phabdouble.revision(
        repo=repo, projects=[needs_data_classification_project]
    )
    phab_revision = phabdouble.api_object_for(
        revision,
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )

    check = check_revision_data_classification(
        needs_data_classification_project["phid"]
    )

    assert check(revision=phab_revision, repo=phabdouble.api_object_for(repo)) == (
        "Revision makes changes to data collection and "
        "should have its data classification assessed before landing."
    ), "Revision with data classification project tag should be blocked from landing."

    revision = phabdouble.revision(repo=repo)
    phab_revision = phabdouble.api_object_for(
        revision,
        attachments={"reviewers": True, "reviewers-extra": True, "projects": True},
    )
    assert (
        check(revision=phab_revision, repo=phabdouble.api_object_for(repo)) is None
    ), "Revision with no data classification tag should not be blocked from landing."
