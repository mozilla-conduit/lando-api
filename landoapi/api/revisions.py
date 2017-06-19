# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Revision API
See the OpenAPI Specification for this API in the spec/swagger.yml file.
"""
from connexion import problem
from landoapi.phabricator_client import PhabricatorClient
from landoapi.transplant_client import TransplantClient


def get(revision_id, api_key=None):
    """ API endpoint at /revisions/{id} to get revision data. """
    phab = PhabricatorClient(api_key)
    revision = phab.get_revision(id=revision_id)

    if not revision:
        # We could not find a matching revision.
        return problem(
            404,
            'Revision not found',
            'The requested revision does not exist',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404'
        )

    return _format_revision(phab, revision, include_parents=True), 200


def land(revision_id, api_key=None):
    """ API endpoint at /revisions/{id}/transplants to land revision. """
    phab = PhabricatorClient(api_key)
    revision = phab.get_revision(id=revision_id)

    if not revision:
        # We could not find a matching revision.
        return problem(
            404,
            'Revision not found',
            'The requested revision does not exist',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404'
        )

    revision = _format_revision(phab, revision, include_parents=True)

    trans = TransplantClient()
    id = trans.land('ldap_username@example.com', revision)
    return {}, 202


def _format_revision(
    phab, revision, include_parents=False, last_author=None, last_repo=None
):
    """ Formats a revision given by Phabricator to match Lando's spec.

    See the swagger.yml spec for the Revision definition.

    Args:
        phab: The PhabricatorClient to use to make additional requests.
        revision: The initial revision to format.
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

    # Load the author if it isn't the same as the child revision's author.
    if last_author and revision['authorPHID'] == last_author['phid']:
        author = last_author
    else:
        raw_author = phab.get_user(revision['authorPHID'])
        author = {
            'phid': raw_author['phid'],
            'username': raw_author['userName'],
            'real_name': raw_author['realName'],
            'url': raw_author['uri'],
            'image_url': raw_author['image'],
        }

    # Load the repo if it isn't the same as the child revision's repo.
    if last_repo and revision['repositoryPHID'] == last_repo['phid']:
        repo = last_repo
    else:
        raw_repo = phab.get_repo(revision['repositoryPHID'])
        repo = {
            'phid': raw_repo['phid'],
            'short_name': raw_repo['name'],
            'full_name': raw_repo['fullName'],
            'url': raw_repo['uri'],
        }

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
                    _format_revision(phab, parent_revision_data, True)
                )

    bug_id = revision['auxiliary'].get('bugzilla.bug-id', None)
    try:
        bug_id = int(bug_id)
    except (TypeError, ValueError):
        bug_id = None

    return {
        'id': int(revision['id']),
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
        'author': author,
        'repo': repo,
        'parent_revisions': parent_revisions,
    }
