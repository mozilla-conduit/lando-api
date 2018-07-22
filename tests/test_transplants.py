# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from landoapi.phabricator import ReviewerStatus


def test_dryrun_no_warnings_or_blockers(client, db, phabdouble, auth0_mock):
    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=phabdouble.repo())
    phabdouble.reviewer(r1, phabdouble.user(username='reviewer'))
    phabdouble.reviewer(r1, phabdouble.project('reviewer2'))

    response = client.post(
        '/transplants/dryrun',
        json={
            'landing_path': [
                {
                    'revision_id': 'D{}'.format(r1['id']),
                    'diff_id': d1['id'],
                },
            ]
        },
        headers=auth0_mock.mock_headers,
    )

    assert 200 == response.status_code
    assert 'application/json' == response.content_type
    expected_json = {
        'confirmation_token': None,
        'warnings': [],
        'blocker': None,
    }
    assert response.json == expected_json


def test_dryrun_invalid_path_blocks(client, db, phabdouble, auth0_mock):
    d1 = phabdouble.diff()
    d2 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=phabdouble.repo())
    r2 = phabdouble.revision(
        diff=d2,
        repo=phabdouble.repo(name='not-mozilla-central'),
        depends_on=[r1]
    )
    phabdouble.reviewer(r1, phabdouble.user(username='reviewer'))
    phabdouble.reviewer(r1, phabdouble.project('reviewer2'))

    response = client.post(
        '/transplants/dryrun',
        json={
            'landing_path': [
                {
                    'revision_id': 'D{}'.format(r1['id']),
                    'diff_id': d1['id'],
                },
                {
                    'revision_id': 'D{}'.format(r2['id']),
                    'diff_id': d2['id'],
                },
            ]
        },
        headers=auth0_mock.mock_headers,
    )

    assert 200 == response.status_code
    assert 'application/json' == response.content_type
    assert response.json['blocker'] is not None


def test_dryrun_reviewers_warns(client, db, phabdouble, auth0_mock):
    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=phabdouble.repo())
    phabdouble.reviewer(
        r1,
        phabdouble.user(username='reviewer'),
        status=ReviewerStatus.REJECTED
    )

    response = client.post(
        '/transplants/dryrun',
        json={
            'landing_path': [
                {
                    'revision_id': 'D{}'.format(r1['id']),
                    'diff_id': d1['id'],
                },
            ]
        },
        headers=auth0_mock.mock_headers,
    )

    assert 200 == response.status_code
    assert 'application/json' == response.content_type
    assert response.json['warnings']
    assert response.json['warnings'][0]['id'] == 0
