# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import logging
import urllib.parse
from datetime import datetime

import kombu
from connexion import ProblemException, problem
from flask import current_app, g

from landoapi import auth
from landoapi.commit_message import format_commit_message
from landoapi.decorators import require_phabricator_api_key
from landoapi.models.landing_job import (
    LandingJob,
    LandingJobStatus,
    add_revisions_to_job,
)
from landoapi.models.revisions import Revision
from landoapi.phabricator import PhabricatorClient
from landoapi.projects import (
    CHECKIN_PROJ_SLUG,
    get_checkin_project_phid,
    get_data_policy_review_phid,
    get_release_managers,
    get_sec_approval_project_phid,
    get_secure_project_phid,
    project_search,
)
from landoapi.repos import (
    get_repos_for_env,
)
from landoapi.reviews import (
    approvals_for_commit_message,
    get_approved_by_ids,
    get_collated_reviewers,
    reviewers_for_commit_message,
)
from landoapi.revisions import (
    find_title_and_summary_for_landing,
    gather_involved_phids,
    get_bugzilla_bug,
    revision_is_secure,
    select_diff_author,
)
from landoapi.stacks import (
    RevisionStack,
    build_stack_graph,
    request_extended_revision_data,
)
from landoapi.storage import db
from landoapi.tasks import admin_remove_phab_project
from landoapi.transplants import (
    LandingAssessmentState,
    TransplantAssessment,
    assess_transplant_request,
)
from landoapi.users import user_search
from landoapi.validation import (
    parse_landing_path,
    revision_id_to_int,
)

logger = logging.getLogger(__name__)


def _parse_transplant_request(data: dict) -> dict:
    """Extract confirmation token, flags, and the landing path from provided data.

    Args
        data (dict): A dictionary representing the transplant request.

    Returns:
        dict: A dictionary containing the landing path, confirmation token and flags.
    """
    landing_path = parse_landing_path(data["landing_path"])

    if not landing_path:
        raise ProblemException(
            400,
            "Landing Path Required",
            "A non empty landing_path is required.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
        )

    flags = data.get("flags", [])

    # Confirmation token is optional. Convert usage of an empty
    # string to None as well to make using the API easier.
    confirmation_token = data.get("confirmation_token") or None

    return {
        "landing_path": landing_path,
        "confirmation_token": confirmation_token,
        "flags": flags,
    }


def _choose_middle_revision_from_path(path: list[tuple[int, int]]) -> int:
    if not path:
        raise ValueError("path must not be empty")

    # For even length we want to choose the greater index
    # of the two middle items, so doing floor division by 2
    # on the length, rather than max index, will give us the
    # desired index.
    return path[len(path) // 2][0]


def _find_stack_from_landing_path(
    phab: PhabricatorClient, landing_path: list[tuple[int, int]]
) -> tuple[set[str], set[tuple[str, str]]]:
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
    return build_stack_graph(revision)


@auth.require_auth0(scopes=("lando", "profile", "email"), userinfo=True)
@require_phabricator_api_key(optional=True)
def dryrun(phab: PhabricatorClient, data: dict):
    landing_path = _parse_transplant_request(data)["landing_path"]

    release_managers = get_release_managers(phab)
    if not release_managers:
        raise Exception("Could not find `#release-managers` project on Phabricator.")

    data_policy_review_phid = get_data_policy_review_phid(phab)
    if not data_policy_review_phid:
        raise Exception(
            "Could not find `#needs-data-classification` project on Phabricator."
        )

    supported_repos = get_repos_for_env(current_app.config.get("ENVIRONMENT"))

    relman_group_phid = phab.expect(release_managers, "phid")
    nodes, edges = _find_stack_from_landing_path(phab, landing_path)
    stack_data = request_extended_revision_data(phab, list(nodes))
    stack = RevisionStack(set(stack_data.revisions.keys()), edges)
    landing_assessment = LandingAssessmentState.from_landing_path(
        landing_path, stack_data, g.auth0_user
    )
    assessment, transplant_state = assess_transplant_request(
        phab,
        supported_repos,
        stack_data,
        stack,
        relman_group_phid,
        data_policy_review_phid,
        landing_assessment=landing_assessment,
    )
    return assessment.to_dict()


@auth.require_auth0(scopes=("lando", "profile", "email"), userinfo=True)
@require_phabricator_api_key(optional=True)
def post(phab: PhabricatorClient, data: dict):
    parsed_transplant_request = _parse_transplant_request(data)
    confirmation_token = parsed_transplant_request["confirmation_token"]
    flags = parsed_transplant_request["flags"]
    landing_path = parsed_transplant_request["landing_path"]

    logger.info(
        "transplant requested by user",
        extra={
            "has_confirmation_token": confirmation_token is not None,
            "landing_path": str(landing_path),
            "flags": flags,
        },
    )

    release_managers = get_release_managers(phab)
    if not release_managers:
        raise Exception("Could not find `#release-managers` project on Phabricator.")

    data_policy_review_phid = get_data_policy_review_phid(phab)
    if not data_policy_review_phid:
        raise Exception(
            "Could not find `#needs-data-classification` project on Phabricator."
        )

    relman_group_phid = phab.expect(release_managers, "phid")

    supported_repos = get_repos_for_env(current_app.config.get("ENVIRONMENT"))

    nodes, edges = _find_stack_from_landing_path(phab, landing_path)
    stack_data = request_extended_revision_data(phab, list(nodes))
    stack = RevisionStack(set(stack_data.revisions.keys()), edges)

    landing_assessment = LandingAssessmentState.from_landing_path(
        landing_path, stack_data, g.auth0_user
    )
    assessment, transplant_state = assess_transplant_request(
        phab,
        supported_repos,
        stack_data,
        stack,
        relman_group_phid,
        data_policy_review_phid,
        landing_assessment=landing_assessment,
    )
    to_land, landing_repo = (
        landing_assessment.to_land,
        landing_assessment.landing_repo,
    )

    assessment.raise_if_blocked_or_unacknowledged(confirmation_token)

    if not all((to_land, landing_repo, stack_data)):
        raise ValueError(
            "One or more values missing in access transplant request: "
            f"{to_land}, {landing_repo}, {stack_data}"
        )

    allowed_flags = [f[0] for f in landing_repo.commit_flags]
    invalid_flags = set(flags) - set(allowed_flags)
    if invalid_flags:
        raise ProblemException(
            400,
            "Invalid flags specified",
            f"Flags must be one or more of {allowed_flags}; "
            f"{invalid_flags} provided.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
        )

    if assessment.warnings:
        # Log any warnings that were acknowledged, for auditing.
        logger.info(
            "Transplant with acknowledged warnings is being requested",
            extra={
                "landing_path": str(landing_path),
                "warnings": [
                    {"i": w.i, "revision_id": w.revision_id, "details": w.details}
                    for w in assessment.warnings
                ],
            },
        )

    involved_phids = set()

    revisions = [r[0] for r in to_land]

    for revision in revisions:
        involved_phids.update(gather_involved_phids(revision))

    involved_phids = list(involved_phids)
    users = user_search(phab, involved_phids)
    projects = project_search(phab, involved_phids)

    secure_project_phid = get_secure_project_phid(phab)

    # Take note of any revisions that the checkin project tag must be
    # removed from.
    checkin_phid = get_checkin_project_phid(phab)
    checkin_revision_phids = [
        r["phid"]
        for r in revisions
        if checkin_phid in phab.expect(r, "attachments", "projects", "projectPHIDs")
    ]

    sec_approval_project_phid = get_sec_approval_project_phid(phab)
    relman_phids = {
        member["phid"]
        for member in release_managers["attachments"]["members"]["members"]
    }

    lando_revisions = []
    revision_reviewers = {}

    # Build the patches to land.
    for revision, diff in to_land:
        reviewers = get_collated_reviewers(revision)
        accepted_reviewers = reviewers_for_commit_message(
            reviewers, users, projects, sec_approval_project_phid
        )

        # Find RelMan reviews for rewriting to `a=<reviewer>`.
        if landing_repo.approval_required:
            accepted_reviewers, approval_reviewers = approvals_for_commit_message(
                reviewers, users, projects, relman_phids, accepted_reviewers
            )
        else:
            approval_reviewers = []

        secure = revision_is_secure(revision, secure_project_phid)
        commit_description = find_title_and_summary_for_landing(phab, revision, secure)

        commit_message = format_commit_message(
            commit_description.title,
            get_bugzilla_bug(revision),
            accepted_reviewers,
            approval_reviewers,
            commit_description.summary,
            urllib.parse.urljoin(
                current_app.config["PHABRICATOR_URL"], "D{}".format(revision["id"])
            ),
            flags,
        )[1]
        author_name, author_email = select_diff_author(diff)
        timestamp = int(datetime.now().timestamp())

        # Construct the patch that will be transplanted.
        revision_id = revision["id"]
        diff_id = diff["id"]

        lando_revision = Revision.get_from_revision_id(revision_id)
        if not lando_revision:
            lando_revision = Revision(revision_id=revision_id)
            db.session.add(lando_revision)

        lando_revision.diff_id = diff_id
        db.session.commit()

        revision_reviewers[lando_revision.id] = get_approved_by_ids(
            phab,
            PhabricatorClient.expect(revision, "attachments", "reviewers", "reviewers"),
        )

        patch_data = {
            "author_name": author_name,
            "author_email": author_email,
            "commit_message": commit_message,
            "timestamp": timestamp,
        }

        raw_diff = phab.call_conduit("differential.getrawdiff", diffID=diff["id"])
        lando_revision.set_patch(raw_diff, patch_data)
        db.session.commit()
        lando_revisions.append(lando_revision)

    ldap_username = g.auth0_user.email

    submitted_assessment = TransplantAssessment(
        blockers=[
            "This stack was submitted for landing by another user at the same time."
        ]
    )
    stack_ids = [revision.revision_id for revision in lando_revisions]
    with db.session.begin_nested():
        LandingJob.lock_table()
        if (
            LandingJob.revisions_query(stack_ids)
            .filter(
                LandingJob.status.in_(
                    [LandingJobStatus.SUBMITTED, LandingJobStatus.IN_PROGRESS]
                )
            )
            .count()
            != 0
        ):
            submitted_assessment.raise_if_blocked_or_unacknowledged(None)

        # Trigger a local transplant
        job = LandingJob(
            requester_email=ldap_username,
            repository_name=landing_repo.short_name,
            repository_url=landing_repo.url,
        )
    add_revisions_to_job(lando_revisions, job)
    logger.info(f"Setting {revision_reviewers} reviewer data on each revision.")
    for revision in lando_revisions:
        revision.data = {"approved_by": revision_reviewers[revision.id]}

    # Submit landing job.
    job.status = LandingJobStatus.SUBMITTED
    job.set_landed_revision_diffs()
    db.session.commit()

    logger.info(f"New landing job {job.id} created for {landing_repo.tree} repo.")

    # Asynchronously remove the checkin project from any of the landing
    # revisions that had it.
    for r_phid in checkin_revision_phids:
        try:
            admin_remove_phab_project.apply_async(
                args=(r_phid, checkin_phid),
                kwargs={"comment": f"#{CHECKIN_PROJ_SLUG} handled, landing queued."},
            )
        except kombu.exceptions.OperationalError:
            # Best effort is acceptable here, Transplant *is* going to land
            # these changes so it's better to return properly from the request.
            pass

    return {"id": job.id}, 202


@require_phabricator_api_key(optional=True)
def get_list(phab: PhabricatorClient, stack_revision_id: str):
    """Return a list of Transplant objects"""
    revision_id_int = revision_id_to_int(stack_revision_id)

    revision = phab.call_conduit(
        "differential.revision.search", constraints={"ids": [revision_id_int]}
    )
    revision = phab.single(revision, "data", none_when_empty=True)
    if revision is None:
        return problem(
            404,
            "Revision not found",
            "The revision does not exist or you lack permission to see it.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404",
        )
    nodes, edges = build_stack_graph(revision)
    revision_phids = list(nodes)
    revs = phab.call_conduit(
        "differential.revision.search",
        constraints={"phids": revision_phids},
        limit=len(revision_phids),
    )

    # Return both transplants and landing jobs, since for repos that were switched
    # both or either of these could be populated.

    rev_ids = [phab.expect(r, "id") for r in phab.expect(revs, "data")]

    landing_jobs = LandingJob.revisions_query(rev_ids).all()

    return [job.serialize() for job in landing_jobs], 200
