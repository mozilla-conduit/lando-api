# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import pytest

from landoapi.phabricator import ReviewerStatus

pytestmark = pytest.mark.usefixtures('docker_env_vars')


def test_get_revision(client, phabdouble):
    revision = phabdouble.revision(repo=phabdouble.repo())
    response = client.get('/revisions/D{}'.format(revision['id']))
    assert response.status_code == 200
    assert response.content_type == 'application/json'
    assert response.json['id'] == 'D{}'.format(revision['id'])


def test_get_revision_with_active_diff(client, phabdouble):
    diff1 = phabdouble.diff()
    revision = phabdouble.revision(diff=diff1, repo=phabdouble.repo())
    diff2 = phabdouble.diff(revision=revision)

    assert diff1['id'] != diff2['id']

    response = client.get('/revisions/D1')
    assert response.json['diff']['id'] == diff2['id']
    assert response.json['latest_diff_id'] == diff2['id']

    response = client.get('/revisions/D1?diff_id={}'.format(diff1['id']))
    assert response.status_code == 200
    assert response.json['diff']['id'] == diff1['id']
    assert response.json['latest_diff_id'] == diff2['id']


def test_get_revision_with_foreign_diff(client, phabdouble):
    repo = phabdouble.repo()
    d1 = phabdouble.diff()
    phabdouble.revision(diff=d1, repo=repo)

    d2 = phabdouble.diff()
    r2 = phabdouble.revision(diff=d2, repo=repo)

    response = client.get(
        '/revisions/D{}?diff_id={}'.format(r2['id'], d1['id'])
    )
    assert response.status_code == 400


def test_get_revision_with_nonexisting_diff(client, phabdouble):
    diff = phabdouble.diff()
    revision = phabdouble.revision(diff=diff, repo=phabdouble.repo())

    bogus_diff_id = 900
    assert bogus_diff_id != diff['id']

    response = client.get(
        '/revisions/D{}?diff_id={}'.format(revision['id'], bogus_diff_id)
    )
    assert response.status_code == 404


def test_get_revision_returns_404(client, phabdouble):
    response = client.get('/revisions/D9000')
    assert response.status_code == 404
    assert response.content_type == 'application/problem+json'
    assert response.json['title'] == 'Revision not found'


def test_revision_id_format(client, phabdouble):
    revision = phabdouble.revision(repo=phabdouble.repo())
    response = client.get('/revisions/{}'.format(revision['id']))
    assert response.status_code == 400
    assert response.json['title'] == 'Bad Request'
    response = client.get('/revisions/d{}'.format(revision['id']))
    assert response.status_code == 400


def test_get_revision_no_reviewers(client, phabdouble):
    revision = phabdouble.revision(repo=phabdouble.repo())
    response = client.get('/revisions/D{}'.format(revision['id']))
    assert response.status_code == 200
    assert response.json['reviewers'] == []


def test_get_revision_multiple_reviewers(client, phabdouble):
    revision = phabdouble.revision(repo=phabdouble.repo())
    u1 = phabdouble.user(username='reviewer1')
    u2 = phabdouble.user(username='reviewer2')
    p1 = phabdouble.project('test-project')
    phabdouble.reviewer(revision, u1)
    phabdouble.reviewer(
        revision, u2, status=ReviewerStatus.REJECTED, isBlocking=False
    )
    phabdouble.reviewer(
        revision, p1, status=ReviewerStatus.BLOCKING, isBlocking=True
    )

    response = client.get('/revisions/D1')
    assert response.status_code == 200

    reviewers = response.json['reviewers']
    assert len(reviewers) == 3
    for reviewer in reviewers:
        if reviewer['phid'] == u1['phid']:
            assert reviewer == {
                'phid': u1['phid'],
                'status': 'accepted',
                'identifier': u1['userName'],
                'full_name': u1['realName'],
                'for_other_diff': False,
                'blocking_landing': False,
            }
        elif reviewer['phid'] == u2['phid']:
            assert reviewer == {
                'phid': u2['phid'],
                'status': 'rejected',
                'identifier': u2['userName'],
                'full_name': u2['realName'],
                'for_other_diff': False,
                'blocking_landing': True,
            }
        else:
            assert reviewer == {
                'phid': p1['phid'],
                'status': 'blocking',
                'identifier': p1['name'],
                'full_name': p1['name'],
                'for_other_diff': False,
                'blocking_landing': True,
            }
