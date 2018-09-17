# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Revision API
See the OpenAPI Specification for this API in the spec/swagger.yml file.
"""
import logging
import urllib.parse

from connexion import problem
from flask import current_app, g

from landoapi.commit_message import format_commit_message
from landoapi.decorators import require_phabricator_api_key
from landoapi.landings import lazy_project_search, lazy_user_search
from landoapi.phabricator import PhabricatorClient, ReviewerStatus
from landoapi.reviews import (
    get_collated_reviewers,
    reviewer_identity,
    serialize_reviewers,
)
from landoapi.revisions import get_bugzilla_bug, serialize_author, serialize_diff

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
    revision_id = revision_id_to_int(revision_id)

    phab = g.phabricator
    revision = phab.call_conduit(
        "differential.revision.search",
        constraints={"ids": [revision_id]},
        attachments={"reviewers": True, "reviewers-extra": True},
    )
    revision = phab.single(revision, "data", none_when_empty=True)
    if revision is None:
        return problem(
            404,
            "Revision not found",
            "The requested revision does not exist",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404",
        )

    latest_diff = phab.single(
        phab.call_conduit(
            "differential.diff.search",
            constraints={"phids": [phab.expect(revision, "fields", "diffPHID")]},
            attachments={"commits": True},
        ),
        "data",
    )
    latest_diff_id = phab.expect(latest_diff, "id")
    if diff_id is not None and diff_id != latest_diff_id:
        diff = phab.single(
            phab.call_conduit(
                "differential.diff.search",
                constraints={"ids": [diff_id]},
                attachments={"commits": True},
            ),
            "data",
            none_when_empty=True,
        )
    else:
        diff = latest_diff

    if diff is None:
        return problem(
            404,
            "Diff not found",
            "The requested diff does not exist",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404",
        )

    revision_phid = phab.expect(revision, "phid")
    if phab.expect(diff, "fields", "revisionPHID") != revision_phid:
        return problem(
            400,
            "Diff not related to the revision",
            "The requested diff is not related to the requested revision.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
        )

    author_phid = phab.expect(revision, "fields", "authorPHID")
    reviewers = get_collated_reviewers(revision)

    # Immediately execute the lazy functions.
    users = lazy_user_search(phab, list(reviewers.keys()) + [author_phid])()
    projects = lazy_project_search(phab, list(reviewers.keys()))()

    accepted_reviewers = [
        reviewer_identity(phid, users, projects).identifier
        for phid, r in reviewers.items()
        if r["status"] is ReviewerStatus.ACCEPTED
    ]

    title = phab.expect(revision, "fields", "title")
    summary = phab.expect(revision, "fields", "summary")
    bug_id = get_bugzilla_bug(revision)
    human_revision_id = "D{}".format(revision_id)
    revision_url = urllib.parse.urljoin(
        current_app.config["PHABRICATOR_URL"], human_revision_id
    )
    commit_message_title, commit_message = format_commit_message(
        title, bug_id, accepted_reviewers, summary, revision_url
    )

    reviewers_response = serialize_reviewers(
        reviewers, users, projects, phab.expect(diff, "phid")
    )
    author_response = serialize_author(author_phid, users)
    diff_response = serialize_diff(diff)

    return (
        {
            "id": human_revision_id,
            "phid": phab.expect(revision, "phid"),
            "bug_id": bug_id,
            "title": title,
            "url": revision_url,
            "date_created": PhabricatorClient.to_datetime(
                phab.expect(revision, "fields", "dateCreated")
            ).isoformat(),
            "date_modified": PhabricatorClient.to_datetime(
                phab.expect(revision, "fields", "dateModified")
            ).isoformat(),
            "summary": summary,
            "commit_message_title": commit_message_title,
            "commit_message": commit_message,
            "diff": diff_response,
            "latest_diff_id": latest_diff_id,
            "author": author_response,
            "reviewers": reviewers_response,
        },
        200,
    )
