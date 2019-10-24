# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging
import urllib.parse

import kombu
from connexion import problem, ProblemException
from flask import current_app, g

from landoapi import auth
from landoapi.commit_message import format_commit_message
from landoapi.decorators import require_phabricator_api_key
from landoapi.hgexports import build_patch_for_revision
from landoapi.models.transplant import Transplant, TransplantStatus
from landoapi.patches import upload
from landoapi.phabricator import PhabricatorClient, ReviewerStatus
from landoapi.projects import (
    CHECKIN_PROJ_SLUG,
    get_checkin_project_phid,
    get_sec_approval_project_phid,
    get_secure_project_phid,
    project_search,
)
from landoapi.repos import get_repos_for_env
from landoapi.reviews import get_collated_reviewers, reviewer_identity
from landoapi.revisions import (
    gather_involved_phids,
    get_bugzilla_bug,
    select_diff_author,
)
from landoapi.stacks import (
    build_stack_graph,
    calculate_landable_subgraphs,
    get_landable_repos_for_revision_data,
    request_extended_revision_data,
)
from landoapi.storage import db
from landoapi.tasks import admin_remove_phab_project
from landoapi.transplants import (
    check_landing_blockers,
    check_landing_warnings,
    DEFAULT_OTHER_BLOCKER_CHECKS,
    TransplantAssessment,
)
from landoapi.transplant_client import TransplantClient, TransplantError
from landoapi.users import user_search
from landoapi.validation import revision_id_to_int

logger = logging.getLogger(__name__)


def _unmarshal_transplant_request(data):
    try:
        path = [
            (revision_id_to_int(item["revision_id"]), int(item["diff_id"]))
            for item in data["landing_path"]
        ]
    except (ValueError, TypeError):
        raise ProblemException(
            400,
            "Landing Path Malformed",
            "The provided landing_path was malformed.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
        )

    if not path:
        raise ProblemException(
            400,
            "Landing Path Required",
            "A non empty landing_path is required.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
        )

    # Confirmation token is optional. Convert usage of an empty
    # string to None as well to make using the API easier.
    confirmation_token = data.get("confirmation_token") or None

    return path, confirmation_token


def _choose_middle_revision_from_path(path):
    if not path:
        raise ValueError("path must not be empty")

    # For even length we want to choose the greater index
    # of the two middle items, so doing floor division by 2
    # on the length, rather than max index, will give us the
    # desired index.
    return path[len(path) // 2][0]


def _find_stack_from_landing_path(phab, landing_path):
    a_revision_id = _choose_middle_revision_from_path(landing_path)
    revision = phab.call_conduit(
        "differential.revision.search", constraints={"ids": [a_revision_id]}
    )
    revision = phab.single(revision, "data", none_when_empty=True)
    if revision is None:
        raise ProblemException(
            404,
            "Stack Not Found",
            "The stack does not exist or you lack permission to see it.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404",
        )

    # TODO: This assumes that all revisions and related objects in the stack
    # have uniform view permissions for the requesting user. Some revisions
    # being restricted could cause this to fail.
    return build_stack_graph(phab, phab.expect(revision, "phid"))


def _convert_path_id_to_phid(path, stack_data):
    mapping = {
        PhabricatorClient.expect(r, "id"): PhabricatorClient.expect(r, "phid")
        for r in stack_data.revisions.values()
    }
    try:
        return [(mapping[r], d) for r, d in path]
    except IndexError:
        ProblemException(
            400,
            "Landing Path Invalid",
            "The provided landing_path is not valid.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
        )


def _assess_transplant_request(phab, landing_path):
    nodes, edges = _find_stack_from_landing_path(phab, landing_path)
    stack_data = request_extended_revision_data(phab, [phid for phid in nodes])
    landing_path = _convert_path_id_to_phid(landing_path, stack_data)

    supported_repos = get_repos_for_env(current_app.config.get("ENVIRONMENT"))
    landable_repos = get_landable_repos_for_revision_data(stack_data, supported_repos)
    landable, blocked = calculate_landable_subgraphs(
        stack_data, edges, landable_repos, other_checks=DEFAULT_OTHER_BLOCKER_CHECKS
    )

    assessment = check_landing_blockers(
        g.auth0_user, landing_path, stack_data, landable, landable_repos
    )
    if assessment.blocker is not None:
        return (assessment, None, None, None)

    # We have now verified that landable_path is valid and is indeed
    # landable (in the sense that it is a landable_subgraph, with no
    # revisions being blocked). Make this clear by using a different
    # value, and assume it going forward.
    valid_path = landing_path

    # Now that we know this is a valid path we can convert it into a list
    # of (revision, diff) tuples.
    to_land = [stack_data.revisions[r_phid] for r_phid, _ in valid_path]
    to_land = [
        (r, stack_data.diffs[PhabricatorClient.expect(r, "fields", "diffPHID")])
        for r in to_land
    ]

    # To be a landable path the entire path must have the same
    # repository, so we can get away with checking only one.
    repo = stack_data.repositories[to_land[0][0]["fields"]["repositoryPHID"]]
    landing_repo = landable_repos[repo["phid"]]

    involved_phids = set()
    for revision, _ in to_land:
        involved_phids.update(gather_involved_phids(revision))

    involved_phids = list(involved_phids)
    users = user_search(phab, involved_phids)
    projects = project_search(phab, involved_phids)
    reviewers = {
        revision["phid"]: get_collated_reviewers(revision) for revision, _ in to_land
    }

    assessment = check_landing_warnings(
        g.auth0_user,
        to_land,
        repo,
        landing_repo,
        reviewers,
        users,
        projects,
        get_secure_project_phid(phab),
    )
    return (assessment, to_land, landing_repo, stack_data)


@auth.require_auth0(scopes=("lando", "profile", "email"), userinfo=True)
@require_phabricator_api_key(optional=True)
def dryrun(data):
    phab = g.phabricator
    landing_path, _ = _unmarshal_transplant_request(data)
    assessment, *_ = _assess_transplant_request(phab, landing_path)
    return assessment.to_dict()


@auth.require_auth0(scopes=("lando", "profile", "email"), userinfo=True)
@require_phabricator_api_key(optional=True)
def post(data):
    phab = g.phabricator
    landing_path, confirmation_token = _unmarshal_transplant_request(data)
    logger.info(
        "transplant requested by user",
        extra={
            "has_confirmation_token": confirmation_token is not None,
            "landing_path": landing_path,
        },
    )
    assessment, to_land, landing_repo, stack_data = _assess_transplant_request(
        phab, landing_path
    )
    assessment.raise_if_blocked_or_unacknowledged(confirmation_token)
    assert to_land is not None
    assert landing_repo is not None
    assert stack_data is not None

    if assessment.warnings:
        # Log any warnings that were acknowledged, for auditing.
        logger.info(
            "Transplant with acknowledged warnings is being requested",
            extra={
                "landing_path": landing_path,
                "warnings": [
                    {"i": w.i, "revision_id": w.revision_id, "details": w.details}
                    for w in assessment.warnings
                ],
            },
        )

    involved_phids = set()
    for revision, _ in to_land:
        involved_phids.update(gather_involved_phids(revision))

    involved_phids = list(involved_phids)
    users = user_search(phab, involved_phids)
    projects = project_search(phab, involved_phids)

    # Take note of any revisions that the checkin project tag must be
    # removed from.
    checkin_phid = get_checkin_project_phid(phab)
    checkin_revision_phids = [
        r["phid"]
        for r, _ in to_land
        if checkin_phid in phab.expect(r, "attachments", "projects", "projectPHIDs")
    ]

    sec_approval_project_phid = get_sec_approval_project_phid(phab)

    # Build the patches to land.
    patch_urls = []
    for revision, diff in to_land:
        reviewers = get_collated_reviewers(revision)

        # The sec-approval group must not appear in the commit message reviewers list.
        # Bug 1590225
        if sec_approval_project_phid in reviewers:
            del reviewers[sec_approval_project_phid]

        accepted_reviewers = [
            reviewer_identity(phid, users, projects).identifier
            for phid, r in reviewers.items()
            if r["status"] is ReviewerStatus.ACCEPTED
        ]

        _, commit_message = format_commit_message(
            phab.expect(revision, "fields", "title"),
            get_bugzilla_bug(revision),
            accepted_reviewers,
            phab.expect(revision, "fields", "summary"),
            urllib.parse.urljoin(
                current_app.config["PHABRICATOR_URL"], "D{}".format(revision["id"])
            ),
        )
        author_name, author_email = select_diff_author(diff)
        date_modified = phab.expect(revision, "fields", "dateModified")

        # Construct the patch that will be sent to transplant.
        raw_diff = phab.call_conduit("differential.getrawdiff", diffID=diff["id"])
        patch = build_patch_for_revision(
            raw_diff, author_name, author_email, commit_message, date_modified
        )

        # Upload the patch to S3
        patch_url = upload(
            revision["id"],
            diff["id"],
            patch,
            current_app.config["PATCH_BUCKET_NAME"],
            aws_access_key=current_app.config["AWS_ACCESS_KEY"],
            aws_secret_key=current_app.config["AWS_SECRET_KEY"],
        )
        patch_urls.append(patch_url)

    trans = TransplantClient(
        current_app.config["TRANSPLANT_URL"],
        current_app.config["TRANSPLANT_USERNAME"],
        current_app.config["TRANSPLANT_PASSWORD"],
    )
    submitted_assessment = TransplantAssessment(
        blocker=(
            "This stack was submitted for landing by another user at the same time."
        )
    )
    ldap_username = g.auth0_user.email
    revision_to_diff_id = {str(r["id"]): d["id"] for r, d in to_land}
    revision_order = [str(r["id"]) for r, _ in to_land]
    stack_ids = [r["id"] for r in stack_data.revisions.values()]

    # We pass the revision id of the base of our landing path to
    # transplant in rev as it must be unique until the request
    # has been serviced. While this doesn't use Autoland Transplant
    # to enforce not requesting from the same stack again, Lando
    # ensures this itself.
    root_revision_id = to_land[0][0]["id"]

    try:
        # WARNING: Entering critical section, do not add additional
        # code unless absolutely necessary. Acquires a lock on the
        # transplants table which gives exclusive write access and
        # prevents readers who are entering this critical section.
        # See https://www.postgresql.org/docs/9.3/static/explicit-locking.html
        # for more details on the specifics of the lock mode.
        with db.session.begin_nested():
            db.session.execute("LOCK TABLE transplants IN SHARE ROW EXCLUSIVE MODE;")
            if (
                Transplant.revisions_query(stack_ids)
                .filter_by(status=TransplantStatus.submitted)
                .first()
                is not None
            ):
                submitted_assessment.raise_if_blocked_or_unacknowledged(None)

            transplant_request_id = trans.land(
                revision_id=root_revision_id,
                ldap_username=ldap_username,
                patch_urls=patch_urls,
                tree=landing_repo.tree,
                pingback=current_app.config["PINGBACK_URL"],
                push_bookmark=landing_repo.push_bookmark,
            )
            transplant = Transplant(
                request_id=transplant_request_id,
                revision_to_diff_id=revision_to_diff_id,
                revision_order=revision_order,
                requester_email=ldap_username,
                tree=landing_repo.tree,
                repository_url=landing_repo.url,
                status=TransplantStatus.submitted,
            )
            db.session.add(transplant)
    except TransplantError:
        logger.exception(
            "error creating transplant", extra={"landing_path": landing_path}
        )
        return problem(
            502,
            "Transplant not created",
            "The requested landing_path is valid, but transplant failed."
            "Please retry your request at a later time.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/502",
        )

    # Transaction succeeded, commit the session.
    db.session.commit()

    logger.info(
        "transplant created",
        extra={"landing_path": landing_path, "transplant_id": transplant.id},
    )

    # Asynchronously remove the checkin project from any of the landing
    # revisions that had it.
    for r_phid in checkin_revision_phids:
        try:
            admin_remove_phab_project.apply_async(
                args=(r_phid, checkin_phid),
                kwargs=dict(comment=f"#{CHECKIN_PROJ_SLUG} handled, landing queued."),
            )
        except kombu.exceptions.OperationalError:
            # Best effort is acceptable here, Transplant *is* going to land
            # these changes so it's better to return properly from the request.
            pass

    return {"id": transplant.id}, 202


@require_phabricator_api_key(optional=True)
def get_list(stack_revision_id):
    """Return a list of Transplant objects"""
    revision_id = revision_id_to_int(stack_revision_id)

    phab = g.phabricator
    revision = phab.call_conduit(
        "differential.revision.search", constraints={"ids": [revision_id]}
    )
    revision = phab.single(revision, "data", none_when_empty=True)
    if revision is None:
        return problem(
            404,
            "Revision not found",
            "The revision does not exist or you lack permission to see it.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404",
        )

    # TODO: This assumes that all revisions and related objects in the stack
    # have uniform view permissions for the requesting user. Some revisions
    # being restricted could cause this to fail.
    nodes, edges = build_stack_graph(phab, phab.expect(revision, "phid"))
    revision_phids = list(nodes)
    revs = phab.call_conduit(
        "differential.revision.search",
        constraints={"phids": revision_phids},
        limit=len(revision_phids),
    )

    transplants = Transplant.revisions_query(
        [phab.expect(r, "id") for r in phab.expect(revs, "data")]
    ).all()
    return [t.serialize() for t in transplants], 200
