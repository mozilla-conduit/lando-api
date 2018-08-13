# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Landing API
See the OpenAPI Specification for this API in the spec/swagger.yml file.
"""
import logging
import urllib.parse

from connexion import problem
from flask import current_app, g, jsonify, request
from sqlalchemy.orm.exc import NoResultFound

from landoapi import auth
from landoapi.commit_message import format_commit_message
from landoapi.decorators import lazy, require_phabricator_api_key
from landoapi.hgexportbuilder import build_patch_for_revision
from landoapi.landings import (
    check_landing_conditions,
    LandingAssessment,
    LandingInProgress,
    lazy_get_diff,
    lazy_get_diff_author,
    lazy_get_landing_repo,
    lazy_get_latest_diff,
    lazy_get_open_parents,
    lazy_get_repository,
    lazy_get_reviewers,
    lazy_get_reviewers_extra_state,
    lazy_get_revision,
    lazy_get_revision_status,
    lazy_reviewers_search,
)
from landoapi.models.transplant import Transplant, TransplantStatus
from landoapi.patches import upload
from landoapi.phabricator import ReviewerStatus
from landoapi.reviews import reviewer_identity
from landoapi.revisions import get_bugzilla_bug
from landoapi.storage import db
from landoapi.transplant_client import TransplantClient, TransplantError
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
    phab = g.phabricator

    get_revision = lazy_get_revision(phab, revision_id)
    get_latest_diff = lazy_get_latest_diff(phab, get_revision)
    get_diff = lazy_get_diff(phab, diff_id, get_latest_diff)
    get_diff_author = lazy_get_diff_author(get_diff)
    get_latest_landed = lazy(Transplant.legacy_latest_landed)(revision_id)
    get_repository = lazy_get_repository(phab, get_revision)
    get_landing_repo = lazy_get_landing_repo(
        get_repository, current_app.config.get('ENVIRONMENT')
    )
    get_open_parents = lazy_get_open_parents(phab, get_revision)
    get_reviewers = lazy_get_reviewers(get_revision)
    get_reviewer_info = lazy_reviewers_search(phab, get_reviewers)
    get_reviewers_extra_state = lazy_get_reviewers_extra_state(
        get_reviewers, get_diff
    )
    get_revision_status = lazy_get_revision_status(get_revision)
    assessment = check_landing_conditions(
        g.auth0_user,
        revision_id,
        diff_id,
        get_revision,
        get_latest_diff,
        get_latest_landed,
        get_repository,
        get_landing_repo,
        get_diff,
        get_diff_author,
        get_open_parents,
        get_reviewers,
        get_reviewer_info,
        get_reviewers_extra_state,
        get_revision_status,
    )
    return jsonify(assessment.to_dict())


@auth.require_auth0(scopes=('lando', 'profile', 'email'), userinfo=True)
@require_phabricator_api_key(optional=True)
def post(data):
    """API endpoint at POST /landings to land revision."""
    logger.info(
        'landing requested by user',
        extra={
            'path': request.path,
            'method': request.method,
            'data': data,
        }
    )

    revision_id, diff_id = unmarshal_landing_request(data)
    confirmation_token = data.get('confirmation_token') or None

    phab = g.phabricator

    get_revision = lazy_get_revision(phab, revision_id)
    get_latest_diff = lazy_get_latest_diff(phab, get_revision)
    get_diff = lazy_get_diff(phab, diff_id, get_latest_diff)
    get_diff_author = lazy_get_diff_author(get_diff)
    get_latest_landed = lazy(Transplant.legacy_latest_landed)(revision_id)
    get_repository = lazy_get_repository(phab, get_revision)
    get_landing_repo = lazy_get_landing_repo(
        get_repository, current_app.config.get('ENVIRONMENT')
    )
    get_open_parents = lazy_get_open_parents(phab, get_revision)
    get_reviewers = lazy_get_reviewers(get_revision)
    get_reviewer_info = lazy_reviewers_search(phab, get_reviewers)
    get_reviewers_extra_state = lazy_get_reviewers_extra_state(
        get_reviewers, get_diff
    )
    get_revision_status = lazy_get_revision_status(get_revision)
    assessment = check_landing_conditions(
        g.auth0_user,
        revision_id,
        diff_id,
        get_revision,
        get_latest_diff,
        get_latest_landed,
        get_repository,
        get_landing_repo,
        get_diff,
        get_diff_author,
        get_open_parents,
        get_reviewers,
        get_reviewer_info,
        get_reviewers_extra_state,
        get_revision_status,
        short_circuit=True,
    )
    assessment.raise_if_blocked_or_unacknowledged(confirmation_token)
    if assessment.warnings:
        # Log any warnings that were acknowledged, for auditing.
        logger.info(
            'Landing with acknowledged warnings is being requested',
            extra={
                'revision_id': revision_id,
                'warnings': [w.serialize() for w in assessment.warnings],
            }
        )

    # These are guaranteed to return proper data since we're
    # running after checking_landing_conditions().
    revision = get_revision()
    landing_repo = get_landing_repo()
    author_name, author_email = get_diff_author()

    # Collect the usernames of reviewers who have accepted.
    reviewers = get_reviewers()
    users, projects = get_reviewer_info()
    accepted_reviewers = [
        reviewer_identity(phid, users, projects).identifier
        for phid, r in reviewers.items()
        if r['status'] is ReviewerStatus.ACCEPTED
    ]

    # Seconds since Unix Epoch, UTC.
    date_modified = phab.expect(revision, 'fields', 'dateModified')

    title = phab.expect(revision, 'fields', 'title')
    summary = phab.expect(revision, 'fields', 'summary')
    bug_id = get_bugzilla_bug(revision)
    human_revision_id = 'D{}'.format(revision_id)
    revision_url = urllib.parse.urljoin(
        current_app.config['PHABRICATOR_URL'], human_revision_id
    )
    commit_message = format_commit_message(
        title, bug_id, accepted_reviewers, summary, revision_url
    )

    # Construct the patch that will be sent to transplant.
    raw_diff = phab.call_conduit('differential.getrawdiff', diffID=diff_id)
    patch = build_patch_for_revision(
        raw_diff, author_name, author_email, commit_message[1], date_modified
    )

    # Upload the patch to S3
    patch_url = upload(
        revision_id,
        diff_id,
        patch,
        current_app.config['PATCH_BUCKET_NAME'],
        aws_access_key=current_app.config['AWS_ACCESS_KEY'],
        aws_secret_key=current_app.config['AWS_SECRET_KEY'],
    )

    trans = TransplantClient(
        current_app.config['TRANSPLANT_URL'],
        current_app.config['TRANSPLANT_USERNAME'],
        current_app.config['TRANSPLANT_PASSWORD'],
    )

    submitted_assessment = LandingAssessment(
        blockers=[
            LandingInProgress(
                'This revision was submitted for landing by another user at '
                'the same time.'
            )
        ]
    )
    ldap_username = g.auth0_user.email

    try:
        # WARNING: Entering critical section, do not add additional
        # code unless absolutely necessary. Acquires a lock on the
        # transplants table which gives exclusive write access and
        # prevents readers who are entering this critical section.
        # See https://www.postgresql.org/docs/9.3/static/explicit-locking.html
        # for more details on the specifics of the lock mode.
        with db.session.begin_nested():
            db.session.execute(
                'LOCK TABLE transplants IN SHARE ROW EXCLUSIVE MODE;'
            )
            if Transplant.is_revision_submitted(revision_id):
                submitted_assessment.raise_if_blocked_or_unacknowledged(None)

            transplant_request_id = trans.land(
                revision_id=revision_id,
                ldap_username=ldap_username,
                patch_urls=[patch_url],
                tree=landing_repo.tree,
                pingback=current_app.config['PINGBACK_URL'],
                push_bookmark=landing_repo.push_bookmark
            )
            transplant = Transplant(
                request_id=transplant_request_id,
                revision_to_diff_id={str(revision_id): diff_id},
                revision_order=[str(revision_id)],
                requester_email=ldap_username,
                tree=landing_repo.tree,
                repository_url=landing_repo.url,
                status=TransplantStatus.submitted
            )
            db.session.add(transplant)
    except TransplantError as exc:
        logger.info(
            'error creating transplant',
            extra={'revision': revision_id},
            exc_info=exc
        )
        return problem(
            502,
            'Landing not created',
            'The requested revision does exist, but landing failed.'
            'Please retry your request at a later time.',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/502'
        )

    # Transaction succeeded, commit the session.
    db.session.commit()

    logger.info(
        'transplant created',
        extra={
            'revision_id': revision_id,
            'transplant_id': transplant.id,
        }
    )
    return {'id': transplant.id}, 202


@require_phabricator_api_key(optional=True)
def get_list(revision_id):
    """API endpoint at GET /landings to return a list of Landing objects."""
    # Verify that the client is permitted to see the associated revision.
    revision_id = revision_id_to_int(revision_id)
    revision = g.phabricator.call_conduit(
        'differential.revision.search',
        constraints={'ids': [revision_id]},
    )
    revision = g.phabricator.expect(revision, 'data')
    revision = g.phabricator.single(revision, none_when_empty=True)
    if not revision:
        return problem(
            404,
            'Revision not found',
            'The revision does not exist or you lack permission to see it.',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404'
        )

    transplants = Transplant.query.filter(
        Transplant.revision_to_diff_id.has_key(str(revision_id))  # noqa
    ).all()
    return [t.legacy_serialize() for t in transplants], 200


@require_phabricator_api_key(optional=True)
def get(landing_id):
    """API endpoint at /landings/{landing_id} to return stored Landing.

    Note, at the time of writing this isn't in use by Lando UI, and most
    likely won't be in the near future. It is mainly used by the Lando
    API test suite.
    """
    transplant = Transplant.query.get(landing_id)

    # Only allow single revision transplants from this legacy endpoint.
    if transplant and len(transplant.revision_order) == 1:
        # Verify that the client has permission to see the associated revision.
        revision_id = int(transplant.revision_order[0])
        revision = g.phabricator.call_conduit(
            'differential.revision.search',
            constraints={'ids': [revision_id]},
        )
        revision = g.phabricator.expect(revision, 'data')
        revision = g.phabricator.single(revision, none_when_empty=True)
        if revision:
            return transplant.legacy_serialize(), 200

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
        transplant = Transplant.query.filter_by(request_id=data['request_id'])
        transplant = transplant.one()

        transplant.update_from_transplant(
            data['landed'],
            error=data.get('error_msg', ''),
            result=data.get('result', '')
        )
        db.session.commit()
    except NoResultFound:
        return problem(
            404,
            'Landing not found',
            'The requested Landing does not exist',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404'
        )

    return {}, 200
