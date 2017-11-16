# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Revision API
See the OpenAPI Specification for this API in the spec/swagger.yml file.
"""
from connexion import problem
from flask import g

from landoapi.decorators import require_phabricator_api_key
from landoapi.utils import format_commit_message
from landoapi.validation import revision_id_to_int


@require_phabricator_api_key(optional=True)
def get(revision_id):
    """Gets revision from Phabricator.

    Returns None or revision.
    """
    phab = g.phabricator
    revision_id = revision_id_to_int(revision_id)
    revision = phab.get_revision(id=revision_id)

    if not revision:
        # We could not find a matching revision.
        return problem(
            404,
            'Revision not found',
            'The requested revision does not exist',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404'
        )

    return _format_revision(
        phab, revision, include_diff=True, include_parents=True
    ), 200


def _format_revision(
    phab,
    revision,
    include_diff=False,
    include_parents=False,
    last_author=None,
    last_repo=None
):
    """Formats a revision given by Phabricator to match Lando's spec.

    See the swagger.yml spec for the Revision definition.

    Args:
        phab: The PhabricatorClient to use to make additional requests.
        revision: The initial revision to format.
        include_diff: A flag to choose whether to include the information for
            the revision's most recent diff.
        include_parents: A flag to choose whether this method will recursively
            load parent revisions and format them as well.
        last_author: A hash of the author who created the revision. This is
            mainly used by this method itself when recursively loading parent
            revisions so as to prevent excess requests for what is often the
            same author on each parent revision.
        last_repo: A hash of the repo that this revision belongs to. This is
            mainly used by this method itself when recursively loading parent
            revisions so as to prevent excess requests for what is often the
            same repo on each parent revision.
    Returns:
        A hash of the formatted revision information.
    """
    bug_id = _extract_bug_id(revision)
    revision_id = int(revision['id'])
    reviewers = _build_reviewers(phab, revision_id)
    commit_message = format_commit_message(
        revision['title'], bug_id,
        [r['username'] for r in reviewers if r['username']]
    )
    diff = _build_diff(phab, revision) if include_diff else None
    author = _build_author(phab, revision, last_author)
    repo = _build_repo(phab, revision, last_repo)

    # This recursively loads the parent of a revision, and the parents of
    # that parent, and so on, ultimately creating a linked-list type structure
    # that connects the dependent revisions.
    parent_revisions = []
    if include_parents:
        parent_phids = revision['auxiliary']['phabricator:depends-on']
        for parent_phid in parent_phids:
            parent_revision_data = phab.get_revision(phid=parent_phid)
            if parent_revision_data:
                parent_revisions.append(
                    _format_revision(
                        phab,
                        parent_revision_data,
                        include_diff=False,
                        include_parents=True,
                        last_author=author,
                        last_repo=repo
                    )
                )

    return {
        'id': 'D{}'.format(revision_id),
        'phid': revision['phid'],
        'bug_id': bug_id,
        'title': revision['title'],
        'url': revision['uri'],
        'date_created': int(revision['dateCreated']),
        'date_modified': int(revision['dateModified']),
        'status': int(revision['status']),
        'status_name': revision['statusName'],
        'summary': revision['summary'],
        'test_plan': revision['testPlan'],
        'commit_message_preview': commit_message,
        'diff': diff,
        'author': author,
        'repo': repo,
        'reviewers': reviewers,
        'parent_revisions': parent_revisions,
    }


def _build_diff(phab, revision):
    """Helper method to build the repo json for a revision response.

    Args:
        phab: The PhabricatorClient to use to make additional requests.
        revision: The revision to get the most recent diff from.
    """
    if revision['activeDiffPHID']:
        raw_diff = phab.get_diff(phid=revision['activeDiffPHID'])
        diff = {
            'id': int(raw_diff['id']),
            'revision_id': 'D{}'.format(raw_diff['revisionID']),
            'date_created': int(raw_diff['dateCreated']),
            'date_modified': int(raw_diff['dateModified']),
            'vcs_base_revision': raw_diff['sourceControlBaseRevision'],
            'authors': None
        }

        if raw_diff['properties'] and raw_diff['properties']['local:commits']:
            commit_authors = []
            commits = list(raw_diff['properties']['local:commits'].values())
            commits.sort(key=lambda c: c['local'], reverse=True)
            for commit in commits:
                commit_authors.append(
                    {
                        'name': commit['author'],
                        'email': commit['authorEmail']
                    }
                )
            diff['authors'] = commit_authors
        return diff
    else:
        return None


def _build_author(phab, revision, last_author):
    """Helper method to build the author json for a revision response.

    Args:
        phab: The PhabricatorClient to use to make additional requests.
        revision: The revision to get the most recent diff from.
        last_author: The author of a child revision that will be checked,
            if it has the same phid, then it will be used instead of making
            additional requests to Phabricator.
    """
    if last_author and revision['authorPHID'] == last_author['phid']:
        return last_author

    raw_author = phab.get_user(revision['authorPHID'])
    return {
        'phid': raw_author['phid'],
        'username': raw_author['userName'],
        'real_name': raw_author['realName'],
        'url': raw_author['uri'],
        'image_url': raw_author['image'],
    }


def _build_reviewers(phab, revision_id):
    """Helper method to build the reviewers list for a revision response.

    Calls `phab.get_reviewers` to request reviewers and corresponding users
    data from Phabricator. If user is not found for the reviewer's PHID, an
    empty string is set as a value of username and real_name keys.

    Args:
        phab: The PhabricatorClient to make additional requests.
        revision_id: The id of the revision in Phabricator.

    Returns:
        List of the reviewers data sorted by the phid
    """
    reviewers_data = phab.get_reviewers(revision_id)
    reviewers = [
        {
            'phid': phid,
            # fields key is empty if user info not found for reviewer
            'username': r['fields']['username'] if r.get('fields') else '',
            'status': r['status'],
            'real_name': r['fields']['realName'] if r.get('fields') else '',
            'is_blocking': r['isBlocking']
        } for phid, r in reviewers_data.items()
    ]
    return sorted(reviewers, key=lambda r: r['phid'])


def _build_repo(phab, revision, last_repo):
    """Helper method to build the repo json for a revision response.

    Args:
        phab: The PhabricatorClient to use to make additional requests.
        revision: The revision to get the most recent diff from.
        last_repo: The repo of a child revision that will be checked,
            if it has the same phid, then it will be used instead of making
            additional requests to Phabricator.
    """
    if revision['repositoryPHID']:
        if last_repo and revision['repositoryPHID'] == last_repo['phid']:
            return last_repo

        raw_repo = phab.get_repo(revision['repositoryPHID'])
        return {
            'phid': raw_repo['phid'],
            'short_name': raw_repo['name'],
            'full_name': raw_repo['fullName'],
            'url': raw_repo['uri'],
        }

    return None


def _extract_bug_id(revision):
    """Helper method to extract the bug id from a Phabricator revision."""
    bug_id = revision['auxiliary'].get('bugzilla.bug-id', None)
    try:
        return int(bug_id)
    except (TypeError, ValueError):
        return None
