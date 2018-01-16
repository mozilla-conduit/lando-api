# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Revision API
See the OpenAPI Specification for this API in the spec/swagger.yml file.
"""
import logging

from connexion import problem, ProblemException
from flask import g

from landoapi.commit_message import format_commit_message
from landoapi.decorators import require_phabricator_api_key
from landoapi.models.patch import DiffNotInRevisionException, Patch
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

    try:
        return _format_revision(
            phab,
            revision,
            diff_id=diff_id,
            include_diff=True,
            include_parents=True
        ), 200
    except DiffNotInRevisionException:
        logger.info(
            {
                'revision': revision_id,
                'diff_id': diff_id,
                'msg': 'Diff not it revision.',
            }, 'revision.error'
        )
        return problem(
            400,
            'Diff not related to the revision',
            'The requested diff is not related to the requested revision.',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400'
        )


def _format_revision(
    phab,
    revision,
    diff_id=None,
    include_diff=False,
    include_parents=False,
    last_author=None,
    last_repo=None,
):
    """Formats a revision given by Phabricator to match Lando's spec.

    See the swagger.yml spec for the Revision definition.

    Args:
        phab: The PhabricatorClient to use to make additional requests.
        revision: The initial revision to format.
        diff_id: The id of one of this revision's diffs to include. If no id
            is given the most recent diff will be used.
        include_diff: A flag to choose whether to include the revision's diff.
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
        A dict of the formatted revision information.
    """
    bug_id = phab.extract_bug_id(revision)
    revision_id = int(revision['id'])
    reviewers = _build_reviewers(phab, revision_id)
    commit_message_title, commit_message = format_commit_message(
        revision['title'],
        bug_id,
        [r['username'] for r in reviewers if r.get('username')],
        revision['summary'],
        revision['uri'],
    )
    author = _build_author(phab, revision, last_author)
    repo = _build_repo(phab, revision, last_repo)

    diff = None
    latest_diff_id = None
    if include_diff:
        latest_diff_id = phab.diff_phid_to_id(phid=revision['activeDiffPHID'])
        diff = _build_diff(phab, revision, diff_id or latest_diff_id)

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
        'commit_message_title': commit_message_title,
        'commit_message': commit_message,
        'diff': diff,
        'latest_diff_id': latest_diff_id,
        'author': author,
        'repo': repo,
        'reviewers': reviewers,
        'parent_revisions': parent_revisions,
    }


def _build_diff(phab, revision, diff_id):
    """Helper method to build the repo json for a revision response.

    Args:
        phab: The PhabricatorClient to use to make additional requests.
        revision: The revision to get the most recent diff from.
        diff_id: (integer) Id of the diff to return with the revision.
    """
    phab_diff = phab.get_diff(id=diff_id)

    if phab_diff is None:
        raise ProblemException(
            404,
            'Diff not found',
            'The requested diff does not exist',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404'
        )  # yapf: disable

    if diff_id:
        Patch.validate_diff_assignment(diff_id, revision)

    diff = {
        'id': int(phab_diff['id']),
        'revision_id': 'D{}'.format(phab_diff['revisionID']),
        'date_created': int(phab_diff['dateCreated']),
        'date_modified': int(phab_diff['dateModified']),
        'vcs_base_revision': phab_diff['sourceControlBaseRevision'],
        'authors': None
    }

    if phab_diff['properties'] and phab_diff['properties']['local:commits']:
        commit_authors = []
        commits = list(phab_diff['properties']['local:commits'].values())
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
        List of the reviewers data for the revision
    """
    reviewers_list = phab.get_reviewers(revision_id)
    return [
        {
            'phid': r['reviewerPHID'],
            # fields key is empty if user info not found for reviewer
            'username': r['fields']['username'] if r.get('fields') else '',
            'status': r['status'],
            'real_name': r['fields']['realName'] if r.get('fields') else '',
            'is_blocking': r['isBlocking']
        } for r in reviewers_list
    ]


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
