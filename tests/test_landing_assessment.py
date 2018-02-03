# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import pytest

from landoapi.api.landings import LandingAssessment


def test_no_warnings_or_problems(client, phabfactory, auth0_mock):
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
        'problems': [],
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


def test_construct_assessment_dict_no_warnings_or_problems():
    assessment = LandingAssessment([], [])
    expected_json = {
        'confirmation_token': None,
        'warnings': [],
        'problems': [],
    }

    assert assessment.to_dict() == expected_json


def test_construct_assessment_dict_only_warnings():
    warnings = [{'id': 'W0', 'message': 'oops'}]
    problems = []
    assessment = LandingAssessment(warnings, problems)
    result = assessment.to_dict()
    assert result['confirmation_token'] is not None
    assert result['warnings'] == warnings
    assert result['problems'] == problems


def test_construct_assessment_dict_only_problems():
    warnings = []
    problems = [{'id': 'E0', 'message': 'fark'}]
    assessment = LandingAssessment(warnings, problems)

    expected_json = {
        'confirmation_token': None,
        'warnings': warnings,
        'problems': problems,
    }

    assert assessment.to_dict() == expected_json


def test_token_for_no_issues_is_none():
    a = LandingAssessment(None, None)
    assert a.hash_warning_list() is None


def test_token_with_warnings_is_not_none():
    a = LandingAssessment([{'id': 'W0', 'message': 'oops'}], None)
    assert a.hash_warning_list()


def test_hash_with_different_list_order_is_equal():
    w1 = [
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
    w2 = [
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
    a = LandingAssessment(w1, [])
    b = LandingAssessment(w2, [])
    assert a.hash_warning_list() == b.hash_warning_list()


def test_hash_with_same_id_different_warning_details_are_different():
    a = LandingAssessment([{'id': 'W0', 'message': 'revision 5 problem'}], [])
    b = LandingAssessment([{'id': 'W0', 'message': 'revision 8 problem'}], [])
    assert a.hash_warning_list() != b.hash_warning_list()


def test_hash_with_duplicate_ids_are_stripped():
    w1 = [
        {
            'id': 'W0',
            'message': 'same'
        },
        {
            'id': 'W0',
            'message': 'same'
        },
    ]
    w2 = [{'id': 'W0', 'message': 'same'}]
    a = LandingAssessment(w1, [])
    b = LandingAssessment(w2, [])
    assert a.hash_warning_list() == b.hash_warning_list()


def test_hash_of_non_list_is_error():
    a = LandingAssessment('oops', [])
    with pytest.raises(TypeError):
        a.hash_warning_list()


def test_hash_of_empty_list_is_None():
    a = LandingAssessment([], [])
    assert a.hash_warning_list() is None


def test_hash_object_throws_error():
    a = LandingAssessment([{'id': object()}], None)
    with pytest.raises(TypeError):
        a.hash_warning_list()
