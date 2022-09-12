# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import pytest

from landoapi.phabricator import PhabricatorCommunicationException
from landoapi.projects import project_search
from landoapi.reviews import (
    approvals_for_commit_message,
    collate_reviewer_attachments,
    get_collated_reviewers,
    reviewers_for_commit_message,
)
from landoapi.users import user_search


def test_collate_reviewer_attachments_malformed_raises():
    with pytest.raises(PhabricatorCommunicationException):
        collate_reviewer_attachments([{"bogus": 1}], [{"bogus": 2}])


def test_collate_reviewer_attachments_mismatched_length_raises(phabdouble):
    revision = phabdouble.revision()
    user = phabdouble.user(username="reviewer")
    phabdouble.reviewer(revision, user)

    attachments = phabdouble.call_conduit(
        "differential.revision.search",
        constraints={"ids": [revision["id"]]},
        attachments={"reviewers": True, "reviewers-extra": True},
    )["data"][0]["attachments"]

    with pytest.raises(PhabricatorCommunicationException):
        collate_reviewer_attachments(attachments["reviewers"]["reviewers"], [])

    with pytest.raises(PhabricatorCommunicationException):
        collate_reviewer_attachments(
            [], attachments["reviewers-extra"]["reviewers-extra"]
        )


@pytest.mark.parametrize("n_reviewers", [0, 1, 2, 10, 100])
def test_collate_reviewer_attachments_n_reviewers(phabdouble, n_reviewers):
    revision = phabdouble.revision()
    users = [
        phabdouble.user(username="reviewer{}".format(i)) for i in range(n_reviewers)
    ]
    reviewers = [phabdouble.reviewer(revision, user) for user in users]

    attachments = phabdouble.call_conduit(
        "differential.revision.search",
        constraints={"ids": [revision["id"]]},
        attachments={"reviewers": True, "reviewers-extra": True},
    )["data"][0]["attachments"]

    collated = collate_reviewer_attachments(
        attachments["reviewers"]["reviewers"],
        attachments["reviewers-extra"]["reviewers-extra"],
    )
    assert len(collated) == len(reviewers)
    assert all(user["phid"] in collated for user in users)
    if n_reviewers == 0:
        assert collated == {}
    else:
        attachment_keys = set(
            attachments["reviewers-extra"]["reviewers-extra"][0]
        ) | set(attachments["reviewers"]["reviewers"][0])
        assert attachment_keys == set(collated[users[0]["phid"]].keys())


def test_sec_approval_is_filtered_from_commit_message_reviewer_list(
    phabdouble,
    secure_project,
    sec_approval_project,
):
    revision = phabdouble.revision(projects=[secure_project])
    user = phabdouble.user(username="normal_reviewer")
    phabdouble.reviewer(revision, user)
    phabdouble.reviewer(revision, sec_approval_project)

    revision = phabdouble.api_object_for(
        revision, attachments={"reviewers": True, "reviewers-extra": True}
    )
    reviewers = get_collated_reviewers(revision)

    involved_phids = reviewers.keys()
    phab = phabdouble.get_phabricator_client()
    users = user_search(phab, involved_phids)
    projects = project_search(phab, involved_phids)

    filtered_reviewers = reviewers_for_commit_message(
        reviewers, users, projects, sec_approval_project["phid"]
    )
    assert user["userName"] in filtered_reviewers
    assert sec_approval_project["name"] not in filtered_reviewers


def test_approvals_for_commit_message(
    phabdouble,
    sec_approval_project,
    release_management_project,
):
    revision = phabdouble.revision()
    user = phabdouble.user(username="normal_reviewer")
    phabdouble.reviewer(revision, user)
    phabdouble.reviewer(revision, release_management_project)

    revision = phabdouble.api_object_for(
        revision, attachments={"reviewers": True, "reviewers-extra": True}
    )
    reviewers = get_collated_reviewers(revision)

    involved_phids = reviewers.keys()
    phab = phabdouble.get_phabricator_client()
    users = user_search(phab, involved_phids)
    projects = project_search(phab, involved_phids)

    accepted_reviewers = reviewers_for_commit_message(
        reviewers, users, projects, sec_approval_project["phid"]
    )

    relman_phids = {user["phid"]}

    accepted_reviewers, approval_reviewers = approvals_for_commit_message(
        reviewers,
        users,
        projects,
        relman_phids,
        accepted_reviewers,
    )

    assert (
        user["userName"] in approval_reviewers
    ), "RelMan review should be recognized as approval."
    assert (
        user["userName"] not in accepted_reviewers
    ), "RelMan review should be filtered from regular reviewers."
    assert (
        release_management_project["name"] not in accepted_reviewers
    ), "`release-managers` project should be filtered from `accepted_reviewers`."
