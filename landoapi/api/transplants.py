# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
from datetime import datetime
import logging
import urllib.parse

import kombu
from connexion import problem, ProblemException
from flask import current_app, g

from landoapi import auth
from landoapi.commit_message import format_commit_message
from landoapi.decorators import require_phabricator_api_key
from landoapi.hgexports import build_patch_for_revision
from landoapi.models.landing_job import LandingJob, LandingJobStatus
from landoapi.models.revisions import Revision, RevisionStatus, RevisionLandingJob
from landoapi.phabricator import PhabricatorClient
from landoapi.projects import (
    CHECKIN_PROJ_SLUG,
    get_checkin_project_phid,
    get_sec_approval_project_phid,
    get_secure_project_phid,
    get_testing_tag_project_phids,
    get_testing_policy_phid,
    get_relman_group_phid,
    project_search,
)
from landoapi.repos import get_repos_for_env
from landoapi.reviews import (
    approvals_for_commit_message,
    get_collated_reviewers,
    reviewers_for_commit_message,
)
from landoapi.revisions import (
    gather_involved_phids,
    get_bugzilla_bug,
    select_diff_author,
    find_title_and_summary_for_landing,
    revision_is_secure,
)
from landoapi.stacks import (
    build_stack_graph,
    calculate_landable_subgraphs,
    get_landable_repos_for_revision_data,
    request_extended_revision_data,
)
from landoapi.storage import db, _lock_table_for
from landoapi.tasks import admin_remove_phab_project
from landoapi.transplants import (
    TransplantAssessment,
    check_landing_blockers,
    check_landing_warnings,
    convert_path_id_to_phid,
    get_blocker_checks,
)
from landoapi.uplift import (
    get_release_managers,
)
from landoapi.users import user_search
from landoapi.validation import (
    revision_id_to_int,
    parse_landing_path,
)

logger = logging.getLogger(__name__)


def _parse_transplant_request(data):
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
    return build_stack_graph(revision)


def _assess_transplant_request(phab, landing_path):
    nodes, edges = _find_stack_from_landing_path(phab, landing_path)
    stack_data = request_extended_revision_data(phab, [phid for phid in nodes])
    landing_path = convert_path_id_to_phid(landing_path, stack_data)

    supported_repos = get_repos_for_env(current_app.config.get("ENVIRONMENT"))
    landable_repos = get_landable_repos_for_revision_data(stack_data, supported_repos)

    other_checks = get_blocker_checks(
        repositories=supported_repos,
        relman_group_phid=get_relman_group_phid(phab),
        stack_data=stack_data,
    )

    landable, blocked = calculate_landable_subgraphs(
        stack_data, edges, landable_repos, other_checks=other_checks
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
        get_testing_tag_project_phids(phab),
        get_testing_policy_phid(phab),
    )
    return (assessment, to_land, landing_repo, stack_data)


@auth.require_auth0(scopes=("lando", "profile", "email"), userinfo=True)
@require_phabricator_api_key(optional=True)
def dryrun(data):
    phab = g.phabricator
    landing_path = _parse_transplant_request(data)["landing_path"]
    assessment, *_ = _assess_transplant_request(phab, landing_path)
    return assessment.to_dict()


@auth.require_auth0(scopes=("lando", "profile", "email"), userinfo=True)
@require_phabricator_api_key(optional=True)
def post(data):
    phab = g.phabricator

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
    assessment, to_land, landing_repo, stack_data = _assess_transplant_request(
        phab, landing_path
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
    release_managers = get_release_managers(phab)
    relman_phids = {
        member["phid"]
        for member in release_managers["attachments"]["members"]["members"]
    }

    lando_revisions = []
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

        patch_data = {
            "author_name": author_name,
            "author_email": author_email,
            "commit_message": commit_message,
            "timestamp": timestamp,
        }
        lando_revision = Revision.get_or_create(
            revision["id"],
            diff["id"],
        )
        if lando_revision.patch_data != patch_data:
            logger.info("Patch data stale, updating...")
            lando_revision.clear_patch_cache()
            lando_revision.patch_data = patch_data
        db.session.commit()

        # Construct the patch, and store the hash.
        raw_diff = phab.call_conduit("differential.getrawdiff", diffID=diff["id"])
        patch = build_patch_for_revision(raw_diff, **lando_revision.patch_data)
        lando_revision.store_patch_hash(patch.encode("utf-8"))
        lando_revisions.append(lando_revision)

    ldap_username = g.auth0_user.email
    stack_ids = [r["id"] for r in stack_data.revisions.values()]

    submitted_assessment = TransplantAssessment(
        blocker=(
            "This stack was submitted for landing by another user at the same time."
        )
    )

    with db.session.begin_nested():
        _lock_table_for(db.session, model=LandingJob)
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
            status=None,
            requester_email=ldap_username,
            repository_name=landing_repo.short_name,
            repository_url=landing_repo.url,
        )

        db.session.add(job)

    # Commit to get job ID.
    db.session.commit()

    for index, revision in enumerate(lando_revisions):
        # Iterate over all revisions and add the landing job + index.
        revision.status = RevisionStatus.QUEUED
        db.session.add(
            RevisionLandingJob(
                index=index, landing_job_id=job.id, revision_id=revision.id
            )
        )
        logger.debug(f"{revision} updated with {job} and index {index}.")
        db.session.commit()

    # Submit landing job.
    job.status = LandingJobStatus.SUBMITTED
    db.session.commit()

    logger.info(f"New landing job {job.id} created for {landing_repo.tree} repo")

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

    # Note, this response content is not being used anywhere.
    return {"id": job.id}, 202


@require_phabricator_api_key(optional=True)
def get_list(stack_revision_id):
    """Return a list of Transplant objects"""
    revision_id = revision_id_to_int(stack_revision_id)
    revision = Revision.query.filter(Revision.revision_id == revision_id).one_or_none()

    if revision is None:
        return problem(
            404,
            "Revision not found",
            "The revision does not exist or you lack permission to see it.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404",
        )

    # Discover all revisions in the stack.
    stacks = [r.linear_stack for r in revision.linear_stack]
    stack = set()
    for s in stacks:
        stack.update(s)

    # revision_ids here is Phabricator revision IDs, since we track the original
    # reference to predecessors in this way.
    revision_ids = set()
    for revision in stack:
        revision_ids.update(revision.data.get("predecessor", set()))
    revision_ids.update(set(r.revision_id for r in stack))

    # Now convert IDs to Lando revision IDs.
    revisions = list(
        zip(
            *Revision.query.with_entities(Revision.id)
            .filter(Revision.revision_id.in_(revision_ids))
            .distinct()
            .all()
        )
    )[0]

    rljs = RevisionLandingJob.query.filter(
        RevisionLandingJob.revision_id.in_(revisions)
    ).all()
    jobs = LandingJob.query.filter(
        LandingJob.id.in_([rlj.landing_job_id for rlj in rljs])
    )

    return [job.serialize() for job in jobs], 200
