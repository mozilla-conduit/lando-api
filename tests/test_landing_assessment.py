# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import pytest

from landoapi.landings import LandingAssessment, LandingProblem
from landoapi.mocks.canned_responses.auth0 import CANNED_USERINFO
from landoapi.models.landing import Landing, LandingStatus


class MockProblem(LandingProblem):
    id = 'M0CK'


def test_no_warnings_or_blockers(client, db, phabfactory, auth0_mock):
    phabfactory.revision('D23')
    response = client.post(
        '/landings/dryrun',
        json=dict(revision_id='D23', diff_id=1),
        headers=auth0_mock.mock_headers,
    )

    assert 200 == response.status_code
    assert 'application/json' == response.content_type
    expected_json = {
        'confirmation_token': None,
        'warnings': [],
        'blockers': [],
    }
    assert response.json == expected_json


def test_assess_invalid_id_format_returns_error(client, auth0_mock):
    response = client.post(
        '/landings/dryrun',
        json=dict(revision_id='a', diff_id=1),
        headers=auth0_mock.mock_headers,
    )
    assert response.status_code == 400


def test_no_auth0_headers_returns_error(client):
    response = client.post(
        '/landings/dryrun',
        json=dict(revision_id='D1', diff_id=1),
        content_type='application/json',
    )
    assert response.status_code == 401


def test_construct_assessment_dict_no_warnings_or_blockers():
    assessment = LandingAssessment([], [])
    expected_dict = {
        'confirmation_token': None,
        'warnings': [],
        'blockers': [],
    }

    assert assessment.to_dict() == expected_dict


def test_construct_assessment_dict_only_warnings():
    warnings = [MockProblem('oops')]
    blockers = []
    assessment = LandingAssessment(warnings, blockers)
    result = assessment.to_dict()
    assert result['confirmation_token'] is not None
    assert result['warnings'][0]['message'] == 'oops'
    assert not result['blockers']


def test_construct_assessment_dict_only_blockers():
    warnings = []
    blockers = [MockProblem('oops')]
    assessment = LandingAssessment(warnings, blockers)
    result = assessment.to_dict()
    assert result['confirmation_token'] is None
    assert result['blockers'][0]['message'] == 'oops'
    assert not result['warnings']


def test_token_for_no_issues_is_none():
    assert LandingAssessment.hash_warning_list([]) is None


def test_token_with_warnings_is_not_none():
    assert LandingAssessment.hash_warning_list(
        [{
            'id': 'W0',
            'message': 'oops'
        }]
    )


def test_hash_with_different_list_order_is_equal():
    a = LandingAssessment.hash_warning_list(
        [
            {
                'id': 'W1',
                'message': 'oops 1'
            },
            {
                'id': 'W2',
                'message': 'oops 2'
            },
            {
                'id': 'W3',
                'message': 'oops 3'
            },
        ]
    )
    b = LandingAssessment.hash_warning_list(
        [
            {
                'id': 'W3',
                'message': 'oops 3'
            },
            {
                'id': 'W2',
                'message': 'oops 2'
            },
            {
                'id': 'W1',
                'message': 'oops 1'
            },
        ]
    )
    assert a == b


def test_hash_with_same_id_different_warning_details_are_different():
    a = LandingAssessment.hash_warning_list(
        [{
            'id': 'W0',
            'message': 'revision 5 problem'
        }]
    )
    b = LandingAssessment.hash_warning_list(
        [{
            'id': 'W0',
            'message': 'revision 8 problem'
        }]
    )
    assert a != b


def test_hash_with_duplicate_ids_are_not_stripped():
    a = LandingAssessment.hash_warning_list(
        [
            {
                'id': 'W0',
                'message': 'same'
            },
            {
                'id': 'W0',
                'message': 'same'
            },
        ]
    )
    b = LandingAssessment.hash_warning_list([{'id': 'W0', 'message': 'same'}])
    assert a != b


def test_hash_of_empty_list_is_None():
    assert LandingAssessment.hash_warning_list([]) is None


def test_hash_object_throws_error():
    with pytest.raises(KeyError):
        LandingAssessment.hash_warning_list([{'id': object()}])


@pytest.mark.parametrize(
    'userinfo,status,expected_blockers', [
        (
            CANNED_USERINFO['NO_CUSTOM_CLAIMS'], 200, [
                {
                    'id':
                    'E002',
                    'message':
                    'You have insufficient permissions to land. scm_level_3 '
                    'access is required.',
                },
            ]
        ),
        (
            CANNED_USERINFO['EXPIRED_L3'], 200, [
                {
                    'id': 'E002',
                    'message': 'Your scm_level_3 access has expired.',
                },
            ]
        ),
        (
            CANNED_USERINFO['UNVERIFIED_EMAIL'], 200, [
                {
                    'id': 'E001',
                    'message':
                    'You do not have a Mozilla verified email address.',
                },
            ]
        ),
    ]
)
def test_blockers_for_bad_userinfo(
    client, db, auth0_mock, phabfactory, userinfo, status, expected_blockers
):
    # Remove SCM level 3 claim from Mozilla claim groups
    auth0_mock.userinfo = userinfo
    phabfactory.revision()

    response = client.post(
        '/landings/dryrun',
        json=dict(revision_id='D1', diff_id=1),
        headers=auth0_mock.mock_headers,
        content_type='application/json',
    )

    assert response.status_code == status
    assert response.json['blockers'] == expected_blockers


def test_inactive_diff_warns(
    db, client, phabfactory, transfactory, auth0_mock
):
    phabfactory.diff(id=1)
    d2 = phabfactory.diff(id=2)
    phabfactory.revision(active_diff=d2, diffs=["1"])
    transfactory.mock_successful_response()
    response = client.post(
        '/landings/dryrun',
        json=dict(revision_id='D1', diff_id=1),
        headers=auth0_mock.mock_headers,
        content_type='application/json',
    )
    assert response.status_code == 200
    assert response.json['warnings'][0] == {
        'id': 'W001',
        'message': (
            'Diff 1 is not the latest diff for the revision. Diff 2 '
            'is now the latest, you might want to land it instead.'
        ),
    }  # yapf: disable


def test_previously_landed_warns(
    db, client, phabfactory, transfactory, auth0_mock
):
    db.session.add(
        Landing(
            request_id=1,
            revision_id=1,
            diff_id=1,
            active_diff_id=1,
            requester_email='tuser@example.com',
            tree='mozilla-central',
            status=LandingStatus.landed,
            result=('X' * 40)
        )
    )
    db.session.commit()

    diff = phabfactory.diff(id=1)
    phabfactory.revision(active_diff=diff)
    response = client.post(
        '/landings/dryrun',
        json=dict(revision_id='D1', diff_id=1),
        headers=auth0_mock.mock_headers,
        content_type='application/json',
    )
    assert response.status_code == 200
    assert response.json['warnings'][0] == {
        'id': 'W002',
        'message': (
            'This diff ({landed_diff_id}) has already landed as '
            'commit {commit_sha}. Unless this change has been backed '
            'out, new changes should use a new revision.'.format(
                landed_diff_id=1, commit_sha='X'*40
            )
        ),
    }  # yapf: disable


def test_previously_landed_but_landed_since_still_warns(
    db, client, phabfactory, transfactory, auth0_mock
):
    db.session.add(
        Landing(
            request_id=1,
            revision_id=1,
            diff_id=1,
            active_diff_id=1,
            requester_email='tuser@example.com',
            tree='mozilla-central',
            status=LandingStatus.landed,
            result=('X' * 40)
        )
    )
    db.session.commit()

    db.session.add(
        Landing(
            request_id=2,
            revision_id=1,
            diff_id=2,
            active_diff_id=2,
            requester_email='tuser@example.com',
            tree='mozilla-central',
            status=LandingStatus.failed,
            result=('X' * 40)
        )
    )
    db.session.commit()

    phabfactory.diff(id=1)
    diff = phabfactory.diff(id=2)
    phabfactory.revision(active_diff=diff, diffs=['1'])
    response = client.post(
        '/landings/dryrun',
        json=dict(revision_id='D1', diff_id=2),
        headers=auth0_mock.mock_headers,
        content_type='application/json',
    )
    assert response.status_code == 200
    assert response.json['warnings'][0] == {
        'id': 'W002',
        'message': (
            'Another diff ({landed_diff_id}) of this revision has already '
            'landed as commit {commit_sha}. Unless this change has been '
            'backed out, new changes should use a new revision.'.format(
                landed_diff_id=1, commit_sha='X'*40
            )
        ),
    }  # yapf: disable
