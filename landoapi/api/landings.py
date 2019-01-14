# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Landing API
See the OpenAPI Specification for this API in the spec/swagger.yml file.
"""
import logging

from connexion import problem
from sqlalchemy.orm.exc import NoResultFound

from landoapi import auth
from landoapi.models.transplant import Transplant
from landoapi.notifications import notify_user_of_landing_failure
from landoapi.storage import db

logger = logging.getLogger(__name__)


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
        transplant = Transplant.query.filter_by(request_id=data["request_id"])
        transplant = transplant.one()

        transplant.update_from_transplant(
            data["landed"],
            error=data.get("error_msg", ""),
            result=data.get("result", ""),
        )
        db.session.commit()
    except NoResultFound:
        return problem(
            404,
            "Landing not found",
            "The requested Landing does not exist",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404",
        )

    if not data["landed"]:
        notify_user_of_landing_failure(data["request_id"], data["error_msg"])
    return {}, 200
