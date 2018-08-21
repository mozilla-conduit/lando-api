# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import pytest

from landoapi.models.transplant import Transplant, TransplantStatus
from landoapi.phabricator import ReviewerStatus, RevisionStatus
from landoapi.reviews import get_collated_reviewers
from landoapi.transplants import (
    warning_not_accepted,
    warning_previously_landed,
    warning_reviews_not_current,
)


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


def test_get_transplants_for_entire_stack(db, client, phabdouble):
    d1a = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1a, repo=phabdouble.repo())
    d1b = phabdouble.diff(revision=r1)

    d2 = phabdouble.diff()
    r2 = phabdouble.revision(diff=d2, repo=phabdouble.repo(), depends_on=[r1])

    d3 = phabdouble.diff()
    r3 = phabdouble.revision(diff=d3, repo=phabdouble.repo(), depends_on=[r1])

    d_not_in_stack = phabdouble.diff()
    r_not_in_stack = phabdouble.revision(
        diff=d_not_in_stack, repo=phabdouble.repo()
    )

    t1 = _create_transplant(
        db,
        request_id=1,
        landing_path=[(r1['id'], d1a['id'])],
        status=TransplantStatus.failed
    )
    t2 = _create_transplant(
        db,
        request_id=2,
        landing_path=[(r1['id'], d1b['id'])],
        status=TransplantStatus.landed
    )
    t3 = _create_transplant(
        db,
        request_id=3,
        landing_path=[(r2['id'], d2['id'])],
        status=TransplantStatus.submitted
    )
    t4 = _create_transplant(
        db,
        request_id=4,
        landing_path=[(r3['id'], d3['id'])],
        status=TransplantStatus.landed,
    )

    t_not_in_stack = _create_transplant(
        db,
        request_id=5,
        landing_path=[(r_not_in_stack['id'], d_not_in_stack['id'])],
        status=TransplantStatus.landed
    )

    response = client.get(
        '/transplants?stack_revision_id=D{}'.format(r2['id'])
    )
    assert response.status_code == 200
    assert len(response.json) == 4

    tmap = {i['id']: i for i in response.json}
    assert t_not_in_stack.id not in tmap
    assert all(t.id in tmap for t in (t1, t2, t3, t4))


def test_get_transplant_from_middle_revision(db, client, phabdouble):
    d1 = phabdouble.diff()
    r1 = phabdouble.revision(diff=d1, repo=phabdouble.repo())

    d2 = phabdouble.diff()
    r2 = phabdouble.revision(diff=d2, repo=phabdouble.repo(), depends_on=[r1])

    d3 = phabdouble.diff()
    r3 = phabdouble.revision(diff=d3, repo=phabdouble.repo(), depends_on=[r1])

    t = _create_transplant(
        db,
        request_id=1,
        landing_path=[
            (r1['id'], d1['id']), (r2['id'], d2['id']), (r3['id'], d3['id'])
        ],
        status=TransplantStatus.failed
    )

    response = client.get(
        '/transplants?stack_revision_id=D{}'.format(r2['id'])
    )
    assert response.status_code == 200
    assert len(response.json) == 1
    assert response.json[0]['id'] == t.id


def test_warning_previously_landed_no_landings(db, phabdouble):
    phab = phabdouble.get_phabricator_client()
    d = phabdouble.diff()
    r = phabdouble.revision(diff=d)

    revision = phab.call_conduit(
        'differential.revision.search',
        constraints={'phids': [r['phid']]},
        attachments={
            'reviewers': True,
            'reviewers-extra': True,
        }
    )['data'][0]
    diff = phab.call_conduit(
        'differential.diff.search',
        constraints={'phids': [d['phid']]},
        attachments={'commits': True}
    )['data'][0]
    assert warning_previously_landed(revision=revision, diff=diff) is None


def test_warning_previously_landed_failed_landing(db, phabdouble):
    phab = phabdouble.get_phabricator_client()
    d = phabdouble.diff()
    r = phabdouble.revision(diff=d)

    _create_transplant(
        db,
        request_id=1,
        landing_path=[(r['id'], d['id'])],
        status=TransplantStatus.failed
    )

    revision = phab.call_conduit(
        'differential.revision.search',
        constraints={'phids': [r['phid']]},
        attachments={
            'reviewers': True,
            'reviewers-extra': True,
        }
    )['data'][0]
    diff = phab.call_conduit(
        'differential.diff.search',
        constraints={'phids': [d['phid']]},
        attachments={'commits': True}
    )['data'][0]
    assert warning_previously_landed(revision=revision, diff=diff) is None


def test_warning_previously_landed_landed_landing(db, phabdouble):
    phab = phabdouble.get_phabricator_client()
    d = phabdouble.diff()
    r = phabdouble.revision(diff=d)

    _create_transplant(
        db,
        request_id=1,
        landing_path=[(r['id'], d['id'])],
        status=TransplantStatus.landed
    )

    revision = phab.call_conduit(
        'differential.revision.search',
        constraints={'phids': [r['phid']]},
        attachments={
            'reviewers': True,
            'reviewers-extra': True,
        }
    )['data'][0]
    diff = phab.call_conduit(
        'differential.diff.search',
        constraints={'phids': [d['phid']]},
        attachments={'commits': True}
    )['data'][0]
    assert warning_previously_landed(revision=revision, diff=diff) is not None


@pytest.mark.parametrize(
    'status', [s for s in RevisionStatus if s is not RevisionStatus.ACCEPTED]
)
def test_warning_not_accepted_warns_on_other_status(phabdouble, status):
    phab = phabdouble.get_phabricator_client()
    r = phabdouble.revision(status=status)

    revision = phab.call_conduit(
        'differential.revision.search',
        constraints={'phids': [r['phid']]},
        attachments={
            'reviewers': True,
            'reviewers-extra': True,
        }
    )['data'][0]
    assert warning_not_accepted(revision=revision) is not None


def test_warning_not_accepted_no_warning_when_accepted(phabdouble):
    phab = phabdouble.get_phabricator_client()
    r = phabdouble.revision(status=RevisionStatus.ACCEPTED)

    revision = phab.call_conduit(
        'differential.revision.search',
        constraints={'phids': [r['phid']]},
        attachments={
            'reviewers': True,
            'reviewers-extra': True,
        }
    )['data'][0]
    assert warning_not_accepted(revision=revision) is None


def test_warning_reviews_not_current_warns_on_unreviewed_diff(phabdouble):
    phab = phabdouble.get_phabricator_client()
    d_reviewed = phabdouble.diff()
    r = phabdouble.revision(diff=d_reviewed)
    phabdouble.reviewer(
        r,
        phabdouble.user(username='reviewer'),
        on_diff=d_reviewed,
        status=ReviewerStatus.ACCEPTED
    )
    d_new = phabdouble.diff(revision=r)

    revision = phab.call_conduit(
        'differential.revision.search',
        constraints={'phids': [r['phid']]},
        attachments={
            'reviewers': True,
            'reviewers-extra': True,
        }
    )['data'][0]
    reviewers = get_collated_reviewers(revision)

    diff = phab.call_conduit(
        'differential.diff.search',
        constraints={'phids': [d_new['phid']]},
        attachments={'commits': True}
    )['data'][0]

    assert warning_reviews_not_current(
        revision=revision, diff=diff, reviewers=reviewers
    ) is not None


def test_warning_reviews_not_current_warns_on_unreviewed_revision(phabdouble):
    phab = phabdouble.get_phabricator_client()
    d = phabdouble.diff()
    r = phabdouble.revision(diff=d)
    # Don't create any reviewers.

    revision = phab.call_conduit(
        'differential.revision.search',
        constraints={'phids': [r['phid']]},
        attachments={
            'reviewers': True,
            'reviewers-extra': True,
        }
    )['data'][0]
    reviewers = get_collated_reviewers(revision)

    diff = phab.call_conduit(
        'differential.diff.search',
        constraints={'phids': [d['phid']]},
        attachments={'commits': True}
    )['data'][0]

    assert warning_reviews_not_current(
        revision=revision, diff=diff, reviewers=reviewers
    ) is not None


def test_warning_reviews_not_current_no_warning_on_accepted_diff(phabdouble):
    phab = phabdouble.get_phabricator_client()
    d = phabdouble.diff()
    r = phabdouble.revision(diff=d)
    phabdouble.reviewer(
        r,
        phabdouble.user(username='reviewer'),
        on_diff=d,
        status=ReviewerStatus.ACCEPTED
    )

    revision = phab.call_conduit(
        'differential.revision.search',
        constraints={'phids': [r['phid']]},
        attachments={
            'reviewers': True,
            'reviewers-extra': True,
        }
    )['data'][0]
    reviewers = get_collated_reviewers(revision)

    diff = phab.call_conduit(
        'differential.diff.search',
        constraints={'phids': [d['phid']]},
        attachments={'commits': True}
    )['data'][0]

    assert warning_reviews_not_current(
        revision=revision, diff=diff, reviewers=reviewers
    ) is None


def _create_transplant(
    db,
    *,
    request_id=1,
    landing_path=((1, 1), ),
    requester_email='tuser@example.com',
    tree='mozilla-central',
    repository_url='http://hg.test',
    status=TransplantStatus.submitted
):
    transplant = Transplant(
        request_id=request_id,
        revision_to_diff_id={
            str(r_id): d_id for r_id, d_id in landing_path
        },
        revision_order=[str(r_id) for r_id, _ in landing_path],
        requester_email=requester_email,
        tree=tree,
        repository_url=repository_url,
        status=status
    )  # yapf: disable
    db.session.add(transplant)
    db.session.commit()
    return transplant
