# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from landoapi.models.revisions import Revision, RevisionStatus as RS
from landoapi.models.landing_job import LandingJob, LandingJobStatus as LJS


def get():
    """Return a redirect repsonse to the swagger specification."""
    return None, 302, {"Location": "/swagger.json"}


def get_stats():
    """Return some useful statistics about the Lando system."""
    data = {}
    data["landing_jobs"] = {
        "SUBMITTED": LandingJob.query.filter(
            LandingJob.status == LJS.SUBMITTED
        ).count(),
        "DEFERRED": LandingJob.query.filter(LandingJob.status == LJS.DEFERRED).count(),
        "FAILED": LandingJob.query.filter(LandingJob.status == LJS.FAILED).count(),
        "CANCELLED": LandingJob.query.filter(
            LandingJob.status == LJS.CANCELLED
        ).count(),
        "IN_PROGRESS": LandingJob.query.filter(
            LandingJob.status == LJS.IN_PROGRESS
        ).count(),
        "LANDED": LandingJob.query.filter(LandingJob.status == LJS.LANDED).count(),
    }

    data["revisions"] = {
        "NEW": Revision.query.filter(Revision.status == RS.NEW).count(),
        "STALE": Revision.query.filter(Revision.status == RS.STALE).count(),
        "PICKED_UP": Revision.query.filter(Revision.status == RS.PICKED_UP).count(),
        "READY_FOR_PREPROCESSING": Revision.query.filter(
            Revision.status == RS.READY_FOR_PREPROCESSING
        ).count(),
        "PREPROCESSING": Revision.query.filter(
            Revision.status == RS.PREPROCESSING
        ).count(),
        "PROBLEM": Revision.query.filter(Revision.status == RS.PROBLEM).count(),
        "READY": Revision.query.filter(Revision.status == RS.READY).count(),
        "QUEUED": Revision.query.filter(Revision.status == RS.QUEUED).count(),
        "LANDING": Revision.query.filter(Revision.status == RS.LANDING).count(),
        "LANDED": Revision.query.filter(Revision.status == RS.LANDED).count(),
        "FAILED": Revision.query.filter(Revision.status == RS.FAILED).count(),
    }

    return data, 200
