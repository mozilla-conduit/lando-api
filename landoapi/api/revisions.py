# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Revision API
See the OpenAPI Specification for this API in the spec/swagger.yml file.
"""
import logging
import urllib.parse
from datetime import datetime, timezone

from connexion import problem
from flask import current_app, g

from landoapi.commit_message import format_commit_message
from landoapi.decorators import require_phabricator_api_key
from landoapi.landings import (
    lazy_get_reviewers,
    lazy_user_search,
)
from landoapi.phabricator import (
    PhabricatorClient,
    ReviewerStatus,
)
from landoapi.reviews import calculate_review_extra_state
from landoapi.validation import revision_id_to_int

logger = logging.getLogger(__name__)


@require_phabricator_api_key(optional=True)
def get(revision_id, diff_id=None):
    """Gets revision from Phabricator.

    Args:
        revision_id: (string) ID of the revision in 'D{number}' format
        diff_id: (integer) Id of the diff to return with the revision. By
            default the active diff will be returned.
    """
    revision_id = revision_id_to_int(revision_id)

    phab = g.phabricator
    revision = phab.call_conduit(
        'differential.revision.search',
        constraints={'ids': [revision_id]},
        attachments={
            'reviewers': True,
            'reviewers-extra': True,
        }
    )
    revision = phab.single(revision, 'data', none_when_empty=True)
    if revision is None:
        return problem(
            404,
            'Revision not found',
            'The requested revision does not exist',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404'
        )

    latest_diff = phab.single(
        phab.call_conduit(
            'differential.diff.search',
            constraints={
                'phids': [phab.expect(revision, 'fields', 'diffPHID')]
            },
        ), 'data'
    )
    latest_diff_id = phab.expect(latest_diff, 'id')
    if diff_id is not None and diff_id != latest_diff_id:
        diff = phab.single(
            phab.call_conduit(
                'differential.diff.search', constraints={'ids': [diff_id]}
            ),
            'data',
            none_when_empty=True
        )
    else:
        diff = latest_diff

    if diff is None:
        return problem(
            404,
            'Diff not found',
            'The requested diff does not exist',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404'
        )

    revision_phid = phab.expect(revision, 'phid')
    if phab.expect(diff, 'fields', 'revisionPHID') != revision_phid:
        return problem(
            400,
            'Diff not related to the revision',
            'The requested diff is not related to the requested revision.',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400'
        )

    # TODO: remove when commit author information is available in
    # the 'commits' attachment of 'differential.revision.search'.
    diff_id = phab.expect(diff, 'id')
    querydiffs_diff = phab.call_conduit(
        'differential.querydiffs', ids=[diff_id]
    )
    querydiffs_diff = phab.expect(querydiffs_diff, str(diff_id))

    author_phid = phab.expect(revision, 'fields', 'authorPHID')

    # Immediately execute the lazy functions.
    reviewers = lazy_get_reviewers(revision)()
    users = lazy_user_search(phab, list(reviewers.keys()) + [author_phid])()

    accepted_reviewers = [
        phab.expect(users, phid, 'fields', 'username')
        for phid, r in reviewers.items()
        if r['status'] is ReviewerStatus.ACCEPTED
    ]

    title = phab.expect(revision, 'fields', 'title')
    summary = phab.expect(revision, 'fields', 'summary')
    bug_id = phab.expect(revision, 'fields').get('bugzilla.bug-id')
    bug_id = int(bug_id) if bug_id and not isinstance(bug_id, int) else None
    human_revision_id = 'D{}'.format(revision_id)
    revision_url = urllib.parse.urljoin(
        current_app.config['PHABRICATOR_URL'], human_revision_id
    )
    commit_message_title, commit_message = format_commit_message(
        title, bug_id, accepted_reviewers, summary, revision_url
    )

    reviewers_response = _render_reviewers_response(
        reviewers, users, phab.expect(diff, 'phid')
    )
    author_response = _render_author_response(author_phid, users)
    diff_response = _render_diff_response(querydiffs_diff)

    return {
        'id': human_revision_id,
        'phid': phab.expect(revision, 'phid'),
        'bug_id': bug_id,
        'title': title,
        'url': revision_url,
        'date_created': _epoch_to_isoformat_time(
            phab.expect(revision, 'fields', 'dateCreated')
        ),
        'date_modified': _epoch_to_isoformat_time(
            phab.expect(revision, 'fields', 'dateModified')
        ),
        'summary': summary,
        'commit_message_title': commit_message_title,
        'commit_message': commit_message,
        'diff': diff_response,
        'latest_diff_id': latest_diff_id,
        'author': author_response,
        'reviewers': reviewers_response,
    }, 200  # yapf: disable


def _render_reviewers_response(
    collated_reviewers, user_search_data, diff_phid
):
    reviewers = []

    for phid, r in collated_reviewers.items():
        user_fields = user_search_data.get(phid, {}).get('fields', {})
        state = calculate_review_extra_state(
            diff_phid, r['status'], r['diffPHID'], r['voidedPHID']
        )
        reviewers.append(
            {
                'phid': phid,
                'status': r['status'].value,
                'for_other_diff': state['for_other_diff'],
                'blocking_landing': state['blocking_landing'],
                'username': user_fields.get('username', ''),
                'real_name': user_fields.get('realName', ''),
                # Deprecated, remove after lando UI stops use.
                'is_blocking': False,
            }
        )

    return reviewers


def _render_author_response(phid, user_search_data):
    author = user_search_data.get(phid, {})
    return {
        'phid': PhabricatorClient.expect(author, 'phid'),
        'username': PhabricatorClient.expect(author, 'fields', 'username'),
        'real_name': PhabricatorClient.expect(author, 'fields', 'realName'),
    }


def _render_diff_response(querydiffs_data):
    return {
        'id': int(PhabricatorClient.expect(querydiffs_data, 'id')),
        'date_created': _epoch_to_isoformat_time(
            PhabricatorClient.expect(querydiffs_data, 'dateCreated')
        ),
        'date_modified': _epoch_to_isoformat_time(
            PhabricatorClient.expect(querydiffs_data, 'dateModified')
        ),
        'author': {
            'name': querydiffs_data.get('authorName', ''),
            'email': querydiffs_data.get('authorEmail', ''),
        },
    }  # yapf: disable


def _epoch_to_isoformat_time(seconds):
    """Converts epoch seconds to an ISO formatted UTC time string."""
    return datetime.fromtimestamp(int(seconds), timezone.utc).isoformat()
