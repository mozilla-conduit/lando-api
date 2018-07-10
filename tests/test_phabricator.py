# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import pytest

from landoapi.phabricator import (
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
