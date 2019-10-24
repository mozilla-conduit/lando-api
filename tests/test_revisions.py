# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import pytest

from landoapi.phabricator import RevisionStatus
from landoapi.revisions import (
    check_author_planned_changes,
    check_diff_author_is_known,
    revision_is_secure,
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


def test_secure_api_flag_on_secure_revision_is_true(client, phabdouble, secure_project):
    revision = phabdouble.revision(projects=[secure_project])

    response = client.get("/stacks/D{}".format(revision["id"]))

    assert response.status_code == 200
    response_revision = response.json["revisions"].pop()
    assert response_revision["is_secure"]


def test_sec_approval_group_is_excluded_from_reviewers_list(
    client, phabdouble, secure_project, sec_approval_project
):
    revision = phabdouble.revision(projects=[secure_project])

    user = phabdouble.user(username="normal_reviewer")
    phabdouble.reviewer(revision, user)
    phabdouble.reviewer(revision, sec_approval_project)

    response = client.get("/stacks/D{}".format(revision["id"]))
    assert response == 200

    response_revision = response.json["revisions"].pop()
    assert response_revision["is_secure"]
    assert sec_approval_project["name"] not in response_revision["commit_message_title"]


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
