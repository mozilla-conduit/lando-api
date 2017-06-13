# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Transplant API
See the OpenAPI Specification for this API in the spec/swagger.yml file.
"""
from connexion import problem
from flask import request
from landoapi.models.landing import (
    Landing,
    LandingNotCreatedException,
    LandingNotFoundException,
    RevisionNotFoundException,
)


def land(data, api_key=None):
    """ API endpoint at /revisions/{id}/transplants to land revision. """
    # get revision_id from body
    revision_id = data['revision_id']
    try:
        landing = Landing.create(revision_id, api_key)
    except RevisionNotFoundException:
        # We could not find a matching revision.
        return problem(
            404,
            'Revision not found',
            'The requested revision does not exist',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404'
        )
    except LandingNotCreatedException:
        # We could not find a matching revision.
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
    try:
        landing = Landing.get(landing_id)
    except LandingNotFoundException:
        return problem(
            404,
            'Landing not found',
            'The requested Landing does not exist',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404'
        )

    return landing.serialize(), 200
