# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import pytest

from landoapi.phabricator import PhabricatorCommunicationException
from landoapi.reviews import collate_reviewer_attachments


def test_collate_reviewer_attachments_malformed_raises():
    with pytest.raises(PhabricatorCommunicationException):
        collate_reviewer_attachments([{'bogus': 1}], [{'bogus': 2}])


def test_collate_reviewer_attachments_mismatched_length_raises(phabdouble):
    revision = phabdouble.revision()
    user = phabdouble.user(username='reviewer')
    phabdouble.reviewer(revision, user)

    attachments = phabdouble.call_conduit(
        'differential.revision.search',
        constraints={'ids': [revision['id']]},
        attachments={
            'reviewers': True,
            'reviewers-extra': True,
        }
    )['data'][0]['attachments']

    with pytest.raises(PhabricatorCommunicationException):
        collate_reviewer_attachments(attachments['reviewers']['reviewers'], [])

    with pytest.raises(PhabricatorCommunicationException):
        collate_reviewer_attachments(
            [], attachments['reviewers-extra']['reviewers-extra']
        )


@pytest.mark.parametrize('n_reviewers', [0, 1, 2, 10, 100])
def test_collate_reviewer_attachments_n_reviewers(phabdouble, n_reviewers):
    revision = phabdouble.revision()
    users = [
        phabdouble.user(username='reviewer{}'.format(i))
        for i in range(n_reviewers)
    ]
    reviewers = [phabdouble.reviewer(revision, user) for user in users]

    attachments = phabdouble.call_conduit(
        'differential.revision.search',
        constraints={'ids': [revision['id']]},
        attachments={
            'reviewers': True,
            'reviewers-extra': True,
        }
    )['data'][0]['attachments']

    collated = collate_reviewer_attachments(
        attachments['reviewers']['reviewers'],
        attachments['reviewers-extra']['reviewers-extra']
    )
    assert len(collated) == len(reviewers)
    assert all(user['phid'] in collated for user in users)
    if n_reviewers == 0:
        assert collated == {}
    else:
        attachment_keys = (
            set(attachments['reviewers-extra']['reviewers-extra'][0]) |
            set(attachments['reviewers']['reviewers'][0])
        )
        assert attachment_keys == set(collated[users[0]['phid']].keys())
