# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging

from connexion import problem, ProblemException
from flask import current_app, g
from sqlalchemy.dialects.postgresql import array

from landoapi import auth
from landoapi.decorators import require_phabricator_api_key
from landoapi.landings import lazy_project_search, lazy_user_search
from landoapi.models.transplant import Transplant
from landoapi.phabricator import PhabricatorClient
from landoapi.repos import get_repos_for_env
from landoapi.reviews import get_collated_reviewers
from landoapi.revisions import gather_involved_phids
from landoapi.stacks import (
    build_stack_graph,
    calculate_landable_subgraphs,
    get_landable_repos_for_revision_data,
    request_extended_revision_data,
)
from landoapi.transplants import (
    check_landing_blockers,
    check_landing_warnings,
)
from landoapi.validation import revision_id_to_int

logger = logging.getLogger(__name__)


def _unmarshal_transplant_request(data):
    try:
        path = [
            (revision_id_to_int(item['revision_id']), item['diff_id'])
            for item in data['landing_path']
        ]
    except ValueError:
        raise ProblemException(
            400,
            'Landing Path Malformed',
            'The provided landing_path was malformed.',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400'
        )

    if not path:
        raise ProblemException(
            400,
            'Landing Path Required',
            'A non empty landing_path is required.',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400'
        )

    return path


def _choose_middle_revision_from_path(path):
    if not path:
        raise ValueError('path must not be empty')

    # For even length we want to choose the greater index
    # of the two middle items, so doing floor division by 2
    # on the length, rather than max index, will give us the
    # desired index.
    return path[len(path) // 2][0]


def _find_stack_from_landing_path(phab, landing_path):
    a_revision_id = _choose_middle_revision_from_path(landing_path)
    revision = phab.call_conduit(
        'differential.revision.search',
        constraints={'ids': [a_revision_id]},
    )
    revision = phab.single(revision, 'data', none_when_empty=True)
    if revision is None:
        raise ProblemException(
            404,
            'Stack Not Found',
            'The stack does not exist or you lack permission to see it.',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404'
        )  # yapf: disable

    # TODO: This assumes that all revisions and related objects in the stack
    # have uniform view permissions for the requesting user. Some revisions
    # being restricted could cause this to fail.
    return build_stack_graph(phab, phab.expect(revision, 'phid'))


def _convert_path_id_to_phid(path, stack_data):
    mapping = {
        PhabricatorClient.expect(r, 'id'): PhabricatorClient.expect(r, 'phid')
        for r in stack_data.revisions.values()
    }
    try:
        return [(mapping[r], d) for r, d in path]
    except IndexError:
        ProblemException(
            400,
            'Landing Path Invalid',
            'The provided landing_path is not valid.',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400'
        )


@auth.require_auth0(scopes=('lando', 'profile', 'email'), userinfo=True)
@require_phabricator_api_key(optional=True)
def dryrun(data):
    phab = g.phabricator
    landing_path = _unmarshal_transplant_request(data)

    nodes, edges = _find_stack_from_landing_path(phab, landing_path)
    stack_data = request_extended_revision_data(phab, [phid for phid in nodes])
    landing_path = _convert_path_id_to_phid(landing_path, stack_data)

    supported_repos = get_repos_for_env(current_app.config.get('ENVIRONMENT'))
    landable_repos = get_landable_repos_for_revision_data(
        stack_data, supported_repos
    )
    landable, blocked = calculate_landable_subgraphs(
        stack_data, edges, landable_repos
    )

    assessment = check_landing_blockers(
        g.auth0_user,
        landing_path,
        stack_data,
        landable,
        landable_repos,
    )
    if assessment.blocker is not None:
        return assessment.to_dict()

    # We have now verified that landable_path is valid and is indeed
    # landable (in the sense that it is a landable_subgraph, with no
    # revisions being blocked). Make this clear by using a different
    # value, and assume it going forward.
    valid_path = landing_path

    # Now that we know this is a valid path we can convert it into a list
    # of (revision, diff) tuples.
    to_land = [stack_data.revisions[r_phid] for r_phid, _ in valid_path]
    to_land = [
        (
            r,
            stack_data.diffs[PhabricatorClient.expect(r, 'fields', 'diffPHID')]
        ) for r in to_land
    ]

    # To be a landable path the entire path must have the same
    # repository, so we can get away with checking only one.
    repo = stack_data.repositories[to_land[0][0]['fields']['repositoryPHID']]
    landing_repo = landable_repos[repo['phid']]

    involved_phids = set()
    for revision, _ in to_land:
        involved_phids.update(gather_involved_phids(revision))

    involved_phids = list(involved_phids)
    users = lazy_user_search(phab, involved_phids)()
    projects = lazy_project_search(phab, involved_phids)()
    reviewers = {
        revision['phid']: get_collated_reviewers(revision)
        for revision, _ in to_land
    }

    assessment = check_landing_warnings(
        g.auth0_user, to_land, repo, landing_repo, reviewers, users, projects
    )
    return assessment.to_dict()


@require_phabricator_api_key(optional=True)
def get_list(stack_revision_id):
    """Return a list of Transplant objects"""
    revision_id = revision_id_to_int(stack_revision_id)

    phab = g.phabricator
    revision = phab.call_conduit(
        'differential.revision.search',
        constraints={'ids': [revision_id]},
    )
    revision = phab.single(revision, 'data', none_when_empty=True)
    if revision is None:
        return problem(
            404,
            'Revision not found',
            'The revision does not exist or you lack permission to see it.',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404'
        )

    # TODO: This assumes that all revisions and related objects in the stack
    # have uniform view permissions for the requesting user. Some revisions
    # being restricted could cause this to fail.
    nodes, edges = build_stack_graph(phab, phab.expect(revision, 'phid'))
    revision_phids = list(nodes)
    revs = phab.call_conduit(
        'differential.revision.search',
        constraints={'phids': revision_phids},
        limit=len(revision_phids),
    )
    revision_ids = [
        str(phab.expect(r, 'id')) for r in phab.expect(revs, 'data')
    ]
    transplants = Transplant.query.filter(
        Transplant.revision_to_diff_id.has_any(array(revision_ids))
    ).all()
    return [t.serialize() for t in transplants], 200
