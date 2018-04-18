# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import pytest

from landoapi.phabricator import (
    collate_reviewer_attachments,
    PhabricatorCommunicationException,
    result_list_to_phid_dict,
    RevisionStatus,
)


@pytest.mark.parametrize(
    'v', [
        'bogus',
        'unknown',
        'prefix_accepted',
        'accepted_suffix',
        'accepte',
        'abandonedaccepted',
        'closed',
    ]
)
def test_revision_status_uknown_values(v):
    assert RevisionStatus.from_status(v) is RevisionStatus.UNEXPECTED_STATUS


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


@pytest.mark.parametrize(
    'result_list, key',
    [
        (
            [{}],
            'phid',
        ),
        (
            [{'notphid': 1}, {'notphid': 1}],
            'phid',
        ),
        (
            [{'phidnot': 1}, {'phidnot': 1}],
            'phid',
        ),
        (
            [{'phid': 1}, {'notphid': 1}],
            'phid',
        ),
        (
            [{'phid': 1}, {'phid': 2}],
            'otherphid',
        ),
    ]
)  # yapf: disable
def test_result_list_to_phid_dict_missing_key_raises(result_list, key):
    with pytest.raises(PhabricatorCommunicationException):
        result_list_to_phid_dict(result_list, phid_key=key)


@pytest.mark.parametrize(
    'result_list, key',
    [
        ([{'phid': 1}, {'phid': 2}], 'phid'),
        ([{'phid': 1, 'other': ['a', 'b']}, {'phid': 2, 'other': []}], 'phid'),
        ([], 'phid'),
        ([{'phid': 1, 'data': 'stuff'}], 'phid')
    ]
)  # yapf: disable
def test_result_list_to_phid_dict(result_list, key):
    result = result_list_to_phid_dict(result_list, phid_key=key)

    for i in result_list:
        assert i[key] in result
        assert i is result[i[key]]


def test_result_list_to_phid_dict_duplicate_phids_raises():
    with pytest.raises(PhabricatorCommunicationException):
        result_list_to_phid_dict(
            [
                {
                    'phid': 'PHID-DREV-1',
                    'data': [1]
                },
                {
                    'phid': 'PHID-DREV-1',
                    'data': [2]
                },
            ]
        )
