# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Transplant API
See the OpenAPI Specification for this API in the spec/swagger.yml file.
"""
import logging
from connexion import problem
from flask import request
from sqlalchemy.orm.exc import NoResultFound
from landoapi.models.landing import (
    Landing, LandingNotCreatedException, RevisionNotFoundException,
    TRANSPLANT_JOB_FAILED, TRANSPLANT_JOB_LANDED
)

logger = logging.getLogger(__name__)


def land(data, api_key=None):
    """ API endpoint at /revisions/{id}/transplants to land revision. """
    # get revision_id from body
    revision_id = data['revision_id']
    diff_id = data['diff_id']
    logger.info(
        {
            'path': request.path,
            'method': request.method,
            'data': data,
            'msg': 'landing requested by user'
        }, 'landing.invoke'
    )
    try:
        landing = Landing.create(revision_id, api_key, diff_id)
    except RevisionNotFoundException:
        # We could not find a matching revision.
        logger.info(
            {
                'revision': revision_id,
                'msg': 'revision not found'
            }, 'landing.failure'
        )
        return problem(
            404,
            'Revision not found',
            'The requested revision does not exist',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404'
        )
    except LandingNotCreatedException as exc:
        # We could not find a matching revision.
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


def get_list(revision_id=None, status=None):
    """ API endpoint at /landings to return all Landing objects related to a
    Revision or of specific status.
    """
    kwargs = {}
    if revision_id:
        kwargs['revision_id'] = revision_id

    if status:
        kwargs['status'] = status

    landings = Landing.query.filter_by(**kwargs).all()
    return list(map(lambda l: l.serialize(), landings)), 200


def get(landing_id):
    """ API endpoint at /landings/{landing_id} to return stored Landing.
    """
    landing = Landing.query.get(landing_id)
    if not landing:
        return problem(
            404,
            'Landing not found',
            'The requested Landing does not exist',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404'
        )

    return landing.serialize(), 200


def update(landing_id, data):
    """Update landing on pingback from Transplant.

    data contains following fields:
    request_id: integer
        id of the landing request in Transplant
    tree: string
        tree name as per treestatus
    rev: string
        matching phabricator revision identifier
    destination: string
        full url of destination repo
    trysyntax: string
        change will be pushed to try or empty string
    landed: boolean;
        true when operation was successful
    error_msg: string
        error message if landed == false
        empty string if landed == true
    result: string
        revision (sha) of push if landed == true
        empty string if landed == false
    """
    try:
        landing = Landing.query.filter_by(
            id=landing_id, request_id=data['request_id']
        ).one()
    except NoResultFound:
        return problem(
            404,
            'Landing not found',
            'The requested Landing does not exist',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404'
        )

    landing.error = data.get('error_msg', '')
    landing.result = data.get('result', '')
    landing.status = TRANSPLANT_JOB_LANDED if data['landed'
                                                  ] else TRANSPLANT_JOB_FAILED
    landing.save()
    return {}, 202
