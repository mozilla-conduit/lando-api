# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Landing API
See the OpenAPI Specification for this API in the spec/swagger.yml file.
"""
import logging

from connexion import problem
from flask import current_app, g, jsonify, request
from sqlalchemy.orm.exc import NoResultFound

from landoapi import auth
from landoapi.decorators import lazy, require_phabricator_api_key
from landoapi.landings import (
    check_landing_conditions,
    lazy_get_landing_repo,
    lazy_get_repository,
    lazy_get_revision,
    lazy_latest_diff_id,
)
from landoapi.models.landing import (
    Landing,
    LandingNotCreatedException,
)
from landoapi.models.patch import DiffNotFoundException
from landoapi.storage import db
from landoapi.validation import revision_id_to_int

logger = logging.getLogger(__name__)


def unmarshal_landing_request(data):
    return (revision_id_to_int(data['revision_id']), data['diff_id'])


@auth.require_auth0(scopes=('lando', 'profile', 'email'), userinfo=True)
@require_phabricator_api_key(optional=True)
def dryrun(data):
    """API endpoint at /landings/dryrun.

    Returns a LandingAssessment for the given Revision ID.
    """
    revision_id, diff_id = unmarshal_landing_request(data)
    get_revision = lazy_get_revision(g.phabricator, revision_id)
    get_latest_diff_id = lazy_latest_diff_id(g.phabricator, get_revision)
    get_latest_landed = lazy(Landing.latest_landed)(revision_id)
    get_repository = lazy_get_repository(g.phabricator, get_revision)
    get_landing_repo = lazy_get_landing_repo(
        g.phabricator, get_repository, current_app.config.get('ENVIRONMENT')
    )
    assessment = check_landing_conditions(
        g.auth0_user, revision_id, diff_id, g.phabricator, get_revision,
        get_latest_diff_id, get_latest_landed, get_repository, get_landing_repo
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

    revision_id, diff_id = unmarshal_landing_request(data)
    get_revision = lazy_get_revision(g.phabricator, revision_id)
    get_latest_diff_id = lazy_latest_diff_id(g.phabricator, get_revision)
    get_latest_landed = lazy(Landing.latest_landed)(revision_id)
    get_repository = lazy_get_repository(g.phabricator, get_revision)
    get_landing_repo = lazy_get_landing_repo(
        g.phabricator, get_repository, current_app.config.get('ENVIRONMENT')
    )
    assessment = check_landing_conditions(
        g.auth0_user,
        revision_id,
        diff_id,
        g.phabricator,
        get_revision,
        get_latest_diff_id,
        get_latest_landed,
        get_repository,
        get_landing_repo,
        short_circuit=True
    )
    assessment.raise_if_blocked_or_unacknowledged(None)

    # This is guaranteed to return an actual revision since we're
    # running it after checking_landing_conditions().
    revision = get_revision()

    try:
        landing = Landing.create(
            revision, diff_id, g.auth0_user.email, g.phabricator,
            get_latest_diff_id(), get_landing_repo()
        )
    except DiffNotFoundException:
        # If we get here something has gone quite wrong with phabricator.
        # Before this point we should have verified that the provided diff
        # id was a diff associated with the revision, so failing to find
        # the raw diff itself is puzzling.
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

    return {'id': landing.id}, 202


@require_phabricator_api_key(optional=True)
def get_list(revision_id):
    """API endpoint at GET /landings to return a list of Landing objects."""
    # Verify that the client is permitted to see the associated revision.
    revision_id = revision_id_to_int(revision_id)
    if not g.phabricator.call_conduit('differential.query', ids=[revision_id]):
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
        if g.phabricator.call_conduit(
            'differential.query', ids=[landing.revision_id]
        ):
            return landing.serialize(), 200

    return problem(
        404,
        'Landing not found',
        'The landing does not exist or you lack permission to see it.',
        type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404'
    )


@auth.require_transplant_authentication
def update(data):
    """Update landing on pingback from Transplant.

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
    db.session.commit()
    return {}, 200
