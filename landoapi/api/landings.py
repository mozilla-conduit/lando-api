# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Landing API
See the OpenAPI Specification for this API in the spec/swagger.yml file.
"""
import hmac
import logging

from connexion import problem
from flask import current_app, g, jsonify, request
from sqlalchemy.orm.exc import NoResultFound

from landoapi import auth
from landoapi.decorators import lazy, require_phabricator_api_key
from landoapi.landings import check_landing_conditions
from landoapi.models.landing import (
    InactiveDiffException,
    Landing,
    LandingNotCreatedException,
    OverrideDiffException,
)
from landoapi.models.patch import (
    DiffNotFoundException, DiffNotInRevisionException
)
from landoapi.validation import revision_id_to_int

logger = logging.getLogger(__name__)


def unmarshal_landing_request(data):
    return (
        revision_id_to_int(data['revision_id']), data['diff_id'],
        data.get('force_override_of_diff_id'),
    )


@auth.require_auth0(scopes=('lando', 'profile', 'email'), userinfo=True)
@require_phabricator_api_key(optional=True)
def dryrun(data):
    """API endpoint at /landings/dryrun.

    Returns a LandingAssessment for the given Revision ID.
    """
    revision_id, diff_id, override_diff_id = unmarshal_landing_request(data)
    get_revision = lazy(g.phabricator.get_revision)(revision_id)
    assessment = check_landing_conditions(
        g.auth0_user, revision_id, diff_id, g.phabricator, get_revision
    )
    return jsonify(assessment.to_dict())


@auth.require_auth0(scopes=('lando', 'profile', 'email'), userinfo=True)
@require_phabricator_api_key(optional=True)
def post(data):
    """API endpoint at POST /landings to land revision."""
    logger.info(
        {
            'path': request.path,
            'method': request.method,
            'data': data,
            'msg': 'landing requested by user'
        }, 'landing.invoke'
    )

    revision_id, diff_id, override_diff_id = unmarshal_landing_request(data)
    get_revision = lazy(g.phabricator.get_revision)(revision_id)
    assessment = check_landing_conditions(
        g.auth0_user,
        revision_id,
        diff_id,
        g.phabricator,
        get_revision,
        short_circuit=True
    )
    assessment.raise_if_blocked_or_unacknowledged(None)

    # This is guaranteed to return an actual revision since we're
    # running it after checking_landing_conditions().
    revision = get_revision()

    try:
        landing = Landing.create(
            revision,
            diff_id,
            g.auth0_user.email,
            g.phabricator,
            override_diff_id=override_diff_id
        )
    except DiffNotFoundException:
        # We could not find a matching diff
        logger.info(
            {
                'diff': diff_id,
                'msg': 'diff not found'
            }, 'landing.failure'
        )
        return problem(
            404,
            'Diff not found',
            'The requested diff does not exist',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404'
        )
    except InactiveDiffException as exc:
        # Attempt to land an inactive diff
        logger.info(
            {
                'revision': revision_id,
                'diff_id': exc.diff_id,
                'active_diff_id': exc.active_diff_id,
                'msg': 'Requested to land an inactive diff'
            }, 'landing.failure'
        )
        return problem(
            409,
            'Inactive Diff',
            'The requested diff is not the active one for this revision.',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/409'
        )
    except OverrideDiffException as exc:
        # Wrong diff chosen to override.
        logger.info(
            {
                'revision': revision_id,
                'diff_id': exc.diff_id,
                'active_diff_id': exc.active_diff_id,
                'override_diff_id': exc.override_diff_id,
                'msg': 'Requested override_diff_id is not the active one'
            }, 'landing.failure'
        )
        return problem(
            409,
            'Overriding inactive diff',
            'The diff to override is not the active one for this revision.',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/409'
        )
    except LandingNotCreatedException as exc:
        logger.info(
            {
                'revision': revision_id,
                'exc': exc,
                'msg': 'error creating landing',
            }, 'landing.error'
        )
        return problem(
            502,
            'Landing not created',
            'The requested revision does exist, but landing failed.'
            'Please retry your request at a later time.',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/502'
        )
    except DiffNotInRevisionException:
        # Diff's revisionID field does not equal revision_id
        logger.info(
            {
                'revision': revision_id,
                'diff_id': diff_id,
                'msg': 'Diff not it revision.',
            }, 'landing.error'
        )
        return problem(
            400,
            'Diff not related to the revision',
            'The requested diff is not related to the requested revision.',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400'
        )

    return {'id': landing.id}, 202


@require_phabricator_api_key(optional=True)
def get_list(revision_id):
    """API endpoint at GET /landings to return a list of Landing objects."""
    # Verify that the client is permitted to see the associated revision.
    revision_id = revision_id_to_int(revision_id)
    revision = g.phabricator.get_revision(id=revision_id)
    if not revision:
        return problem(
            404,
            'Revision not found',
            'The revision does not exist or you lack permission to see it.',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404'
        )

    landings = Landing.query.filter_by(revision_id=revision_id).all()
    return [l.serialize() for l in landings], 200


@require_phabricator_api_key(optional=True)
def get(landing_id):
    """API endpoint at /landings/{landing_id} to return stored Landing."""
    landing = Landing.query.get(landing_id)

    if landing:
        # Verify that the client has permission to see the associated revision.
        revision = g.phabricator.get_revision(id=landing.revision_id)
        if revision:
            return landing.serialize(), 200

    return problem(
        404,
        'Landing not found',
        'The landing does not exist or you lack permission to see it.',
        type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404'
    )


def update(data):
    """Update landing on pingback from Transplant.

    API-Key header is required to authenticate Transplant API

    data contains following fields:
        request_id: integer (required)
            id of the landing request in Transplant
        landed: boolean (required)
            true when operation was successful
        tree: string
            tree name as per treestatus
        rev: string
            matching phabricator revision identifier
        destination: string
            full url of destination repo
        trysyntax: string
            change will be pushed to try or empty string
        error_msg: string
            error message if landed == false
            empty string if landed == true
        result: string
            revision (sha) of push if landed == true
            empty string if landed == false
    """
    if current_app.config['PINGBACK_ENABLED'] != 'y':
        logger.warning(
            {
                'data': data,
                'remote_addr': request.remote_addr,
                'msg': 'Attempt to access a disabled pingback',
            }, 'pingback.warning'
        )
        return _not_authorized_problem()

    passed_key = request.headers.get('API-Key', '')
    required_key = current_app.config['TRANSPLANT_API_KEY']
    if not hmac.compare_digest(passed_key, required_key):
        logger.warning(
            {
                'data': data,
                'remote_addr': request.remote_addr,
                'msg': 'Wrong API Key',
            }, 'pingback.error'
        )
        return _not_authorized_problem()

    try:
        landing = Landing.query.filter_by(request_id=data['request_id']).one()
    except NoResultFound:
        return problem(
            404,
            'Landing not found',
            'The requested Landing does not exist',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404'
        )

    landing.update_from_transplant(
        data['landed'],
        error=data.get('error_msg', ''),
        result=data.get('result', '')
    )
    landing.save()
    return {}, 200


def _not_authorized_problem():
    return problem(
        403,
        'Not Authorized',
        'You\'re not authorized to proceed.',
        type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/403'
    )
