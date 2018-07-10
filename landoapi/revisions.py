# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging
from collections import Counter

from landoapi.phabricator import PhabricatorClient

logger = logging.getLogger(__name__)


def gather_involved_phids(revision):
    """Return the set of Phobject phids involved in a revision.

    At the time of writing Users and Projects are the type of Phobjects
    which may author or review a revision.
    """
    attachments = PhabricatorClient.expect(revision, 'attachments')

    entities = {PhabricatorClient.expect(revision, 'fields', 'authorPHID')}
    entities.update(
        {
            PhabricatorClient.expect(r, 'reviewerPHID')
            for r in
            PhabricatorClient.expect(attachments, 'reviewers', 'reviewers')
        }
    )
    entities.update(
        {
            PhabricatorClient.expect(r, 'reviewerPHID')
            for r in PhabricatorClient.
            expect(attachments, 'reviewers-extra', 'reviewers-extra')
        }
    )
    return entities


def serialize_author(phid, user_search_data):
    out = {
        'phid': phid,
        'username': None,
        'real_name': None,
    }
    author = user_search_data.get(phid)
    if author is not None:
        out['username'] = PhabricatorClient.expect(
            author, 'fields', 'username'
        )
        out['real_name'] = PhabricatorClient.expect(
            author, 'fields', 'realName'
        )

    return out


def serialize_diff(diff):
    author_name, author_email = select_diff_author(diff)
    fields = PhabricatorClient.expect(diff, 'fields')

    return {
        'id': PhabricatorClient.expect(diff, 'id'),
        'phid': PhabricatorClient.expect(diff, 'phid'),
        'date_created': PhabricatorClient.to_datetime(
            PhabricatorClient.expect(fields, 'dateCreated')
        ).isoformat(),
        'date_modified': PhabricatorClient.to_datetime(
            PhabricatorClient.expect(fields, 'dateModified')
        ).isoformat(),
        'author': {
            'name': author_name or '',
            'email': author_email or '',
        },
    }  # yapf: disable


def select_diff_author(diff):
    commits = PhabricatorClient.expect(
        diff, 'attachments', 'commits', 'commits'
    )
    if not commits:
        return None, None

    authors = [c.get('author', {}) for c in commits]
    authors = Counter((a.get('name'), a.get('email')) for a in authors)
    authors = authors.most_common(1)
    return authors[0][0] if authors else (None, None)


def get_bugzilla_bug(revision):
    bug = PhabricatorClient.expect(revision, 'fields').get('bugzilla.bug-id')
    return int(bug) if bug else None
