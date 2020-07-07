# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging

from connexion import ProblemException
from flask import g

from landoapi import auth
from landoapi.models.landing_job import LandingJob, LandingJobStatus, LandingJobAction
from landoapi.storage import db

logger = logging.getLogger(__name__)


@auth.require_auth0(scopes=("lando", "profile", "email"), userinfo=True)
def put(landing_job_id, data):
    """Update a landing job.

    Checks whether the logged in user is allowed to modify the landing job that is
    passed, does some basic validation on the data passed, and updates the landing job
    instance accordingly.

    Args:
        landing_job_id (int): The unique ID of the LandingJob object.
        data (dict): A dictionary containing the cleaned data payload from the request.

    Raises:
        ProblemException: If a LandingJob object corresponding to the landing_job_id
            is not found, if a user is not authorized to access said LandingJob object,
            if an invalid status is provided, or if a LandingJob object can not be
            updated (for example, when trying to cancel a job that is already in
            progress).
    """
    landing_job = LandingJob.query.with_for_update().get(landing_job_id)

    if not landing_job:
        raise ProblemException(
            404,
            "Landing job not found",
            f"A landing job with ID {landing_job_id} was not found.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404",
        )

    ldap_username = g.auth0_user.email
    if landing_job.requester_email != ldap_username:
        raise ProblemException(
            403,
            "Unauthorized",
            f"User not authorized to update landing job {landing_job_id}",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/403",
        )

    if data["status"] == LandingJobStatus.CANCELLED.value:
        if landing_job.status == LandingJobStatus.SUBMITTED:
            landing_job.transition_status(LandingJobAction.CANCEL)
            db.session.commit()
            return {"id": landing_job.id}, 200
        else:
            raise ProblemException(
                400,
                "Landing job could not be cancelled.",
                f"Landing job status ({landing_job.status}) does not allow cancelling.",
                type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
            )
    else:
        raise ProblemException(
            400,
            "Invalid status provided",
            f"The provided status {data['status']} is not allowed.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
        )
