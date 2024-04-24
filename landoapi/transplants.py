# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import copy
import functools
import hashlib
import json
import logging
from collections import namedtuple
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import requests
from connexion import ProblemException
from flask import current_app

from landoapi.auth import A0User
from landoapi.models.landing_job import LandingJob, LandingJobStatus
from landoapi.models.revisions import DiffWarning, DiffWarningStatus
from landoapi.phabricator import (
    PhabricatorClient,
    PhabricatorRevisionStatus,
    ReviewerStatus,
)
from landoapi.projects import (
    get_secure_project_phid,
    get_testing_policy_phid,
    get_testing_tag_project_phids,
    project_search,
)
from landoapi.repos import Repo, get_repos_for_env
from landoapi.reviews import (
    calculate_review_extra_state,
    get_collated_reviewers,
    reviewer_identity,
)
from landoapi.revisions import (
    block_diff_author_is_known,
    gather_involved_phids,
    revision_has_needs_data_classification_tag,
    revision_is_secure,
    revision_needs_testing_tag,
)
from landoapi.stacks import (
    RevisionData,
    RevisionStack,
    get_landable_repos_for_revision_data,
)
from landoapi.transactions import get_inline_comments
from landoapi.users import user_search

logger = logging.getLogger(__name__)

RevisionWarning = namedtuple(
    "RevisionWarning",
    ("i", "display", "revision_id", "details", "articulated"),
    defaults=(None, None, None, None, False),
)

# The code freeze dates generally correspond to PST work days.
CODE_FREEZE_OFFSET = "-0800"


@dataclass
class LandingAssessmentState:
    """Encapsulates the state of a landing request for assessment.

    Holds fields that are necessary to assess if a landing is blocked,
    but are not necessary to run checks on the entire stack. This includes
    checks for permissions on a user to initiate a landing, whether the
    requested path can land at the current time, etc.
    """

    auth0_user: A0User
    landing_path_phid: list[tuple[str, int]]
    to_land: list[tuple[dict, dict]]

    # `landing_repo` is set in the single landing repo check.
    landing_repo: Optional[Repo] = None

    @classmethod
    def from_landing_path(
        cls,
        landing_path: list[tuple[int, int]],
        stack_data: RevisionData,
        auth0_user: A0User,
    ) -> LandingAssessmentState:
        landing_path_phid = convert_path_id_to_phid(landing_path, stack_data)

        to_land = [stack_data.revisions[r_phid] for r_phid, _ in landing_path_phid]
        to_land = [
            (
                revision,
                stack_data.diffs[
                    PhabricatorClient.expect(revision, "fields", "diffPHID")
                ],
            )
            for revision in to_land
        ]

        return LandingAssessmentState(
            auth0_user=auth0_user,
            landing_path_phid=landing_path_phid,
            to_land=to_land,
        )


@dataclass
class StackAssessmentState:
    """Handles the state of a stack for assessment.

    Holds all data relevant to a stack such that the stack blocker/warning checks
    can be run against them. This includes the optional `LandingAssessmentState`
    which includes extra fields related to an attempt to create a landing job
    for patches in the stack.
    """

    phab: PhabricatorClient
    stack_data: RevisionData
    stack: RevisionStack
    landable_stack: RevisionStack
    statuses: dict[str, PhabricatorRevisionStatus]
    landable_repos: dict[str, Repo]
    supported_repos: dict[str, Repo]
    reviewers: dict
    users: dict
    projects: dict
    data_policy_review_phid: str
    relman_group_phid: str
    secure_project_phid: str
    testing_tag_project_phids: list[str]
    testing_policy_phid: str

    # State required for assessing landing requests.
    landing_assessment: Optional[LandingAssessmentState] = None

    @classmethod
    def from_assessment(
        cls,
        phab: PhabricatorClient,
        stack_data: RevisionData,
        stack: RevisionStack,
        landable_repos: dict[str, Repo],
        supported_repos: dict[str, Repo],
        reviewers: dict,
        users: dict,
        projects: dict,
        data_policy_review_phid: str,
        relman_group_phid: str,
        secure_project_phid: str,
        testing_tag_project_phids: list[str],
        testing_policy_phid: str,
        landing_assessment: Optional[LandingAssessmentState] = None,
    ) -> StackAssessmentState:
        """Build a `StackAssessmentState` from passed arguments.

        Build any fields that are shared between checks but are derived from
        existing fields.
        """
        # Create a copy of the stack where we will remove revisions that are blocked from
        # landing, leaving a graph where each path is landable.
        landable_stack = copy.deepcopy(stack)

        # Map each revision to its existing status so we can check for closed revisions.
        statuses = {
            phid: PhabricatorRevisionStatus.from_status(
                PhabricatorClient.expect(revision, "fields", "status", "value")
            )
            for phid, revision in stack_data.revisions.items()
        }

        return StackAssessmentState(
            phab=phab,
            stack_data=stack_data,
            stack=stack,
            statuses=statuses,
            landable_stack=landable_stack,
            landable_repos=landable_repos,
            supported_repos=supported_repos,
            reviewers=reviewers,
            users=users,
            projects=projects,
            data_policy_review_phid=data_policy_review_phid,
            relman_group_phid=relman_group_phid,
            secure_project_phid=secure_project_phid,
            testing_tag_project_phids=testing_tag_project_phids,
            testing_policy_phid=testing_policy_phid,
            landing_assessment=landing_assessment,
        )

    def revision_check_pairs(self) -> list[tuple[dict, dict]]:
        """Return the appropriate list of `revision, diff` pairs for assessing.

        If this state has an associated `LandingAssessmentState`, return the pairs
        for the landing path being assessed. Otherwise, return the pairs for every
        revision in the stack.
        """
        if self.landing_assessment:
            # Only return the revisions in `landing_assessment.to_land` for checking.
            return self.landing_assessment.to_land

        # Return all revisions for checking.
        return [
            (
                revision,
                self.stack_data.diffs[
                    PhabricatorClient.expect(revision, "fields", "diffPHID")
                ],
            )
            for revision in self.stack_data.revisions.values()
        ]


class StackAssessment:
    """Represents an assessment of issues that may block a landing.

    Attributes:
        blocker: List of strings outlining why a revision is blocked from landing.
        warnings: List with each item being a RevisionWarning.
    """

    def __init__(self, *, blockers: list | None = None, warnings: list | None = None):
        self.blockers = blockers if blockers is not None else []
        self.warnings = warnings if warnings is not None else []

    def to_dict(self):
        bucketed_warnings = {}
        for w in self.warnings:
            if w.i not in bucketed_warnings:
                bucketed_warnings[w.i] = {
                    "id": w.i,
                    "display": w.display,
                    "instances": [],
                    "articulated": w.articulated,
                }

            bucketed_warnings[w.i]["instances"].append(
                {
                    "revision_id": w.revision_id,
                    "details": w.details,
                    "articulated": w.articulated,
                }
            )

        return {
            "blocker": "\n".join(self.blockers) if self.blockers else None,
            "warnings": list(bucketed_warnings.values()),
            "confirmation_token": self.confirmation_token(self.warnings),
        }

    @staticmethod
    def confirmation_token(warnings):
        """Return a hash of a serialized warning list.

        Returns: String.  Returns None if given an empty list.
        """
        if not warnings:
            return None

        # Convert warnings to JSON serializable form and sort.
        warnings = sorted((w.i, w.revision_id, w.details) for w in warnings)
        return hashlib.sha256(json.dumps(warnings).encode("utf-8")).hexdigest()

    def raise_if_blocked_or_unacknowledged(self, confirmation_token):
        if self.blockers:
            raise ProblemException(
                400,
                "Landing is Blocked",
                "There are landing blockers present which prevent landing.",
                ext=self.to_dict(),
                type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
            )

        details = self.to_dict()
        if not details["confirmation_token"] == confirmation_token:
            if confirmation_token is None:
                raise ProblemException(
                    400,
                    "Unacknowledged Warnings",
                    "There are landing warnings present which have not "
                    "been acknowledged.",
                    ext=details,
                    type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
                )

            raise ProblemException(
                400,
                "Acknowledged Warnings Have Changed",
                "The warnings present when the request was constructed have "
                "changed. Please acknowledge the new warnings and try again.",
                ext=details,
                type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
            )


class RevisionWarningCheck:
    _warning_ids = set()

    def __init__(self, i, display, articulated=False):
        if not isinstance(i, int):
            raise ValueError("Warning ids must be provided as an integer")

        if i > 0 and (i - 1) not in self._warning_ids:
            raise ValueError(
                "Warnings may not skip an id number. Warnings should never "
                "be removed, just replaced with a noop function if they are "
                "no longer used. This prevents id re-use."
            )

        self._warning_ids.add(i)
        self.i = i
        self.display = display
        self.articulated = articulated

    def __call__(self, f):
        @functools.wraps(f)
        def wrapped(revision: dict, diff: dict, stack_state: StackAssessmentState):
            result = f(revision, diff, stack_state)
            return (
                None
                if result is None
                else RevisionWarning(
                    self.i, self.display, f'D{revision["id"]}', result, self.articulated
                )
            )

        return wrapped


@RevisionWarningCheck(0, "Has a review intended to block landing.")
def warning_blocking_reviews(
    revision: dict, diff: dict, stack_state: StackAssessmentState
):
    reviewer_extra_state = {
        phid: calculate_review_extra_state(diff["phid"], r["status"], r["diffPHID"])
        for phid, r in stack_state.reviewers[revision["phid"]].items()
    }
    blocking_phids = [
        phid
        for phid, state in reviewer_extra_state.items()
        if state["blocking_landing"]
    ]
    if not blocking_phids:
        return None

    blocking_reviewers = [
        "@{}".format(
            reviewer_identity(phid, stack_state.users, stack_state.projects).identifier
        )
        for phid in blocking_phids
    ]
    if len(blocking_reviewers) > 1:
        return (
            "Reviews from {all_but_last_reviewer}, and {last_reviewer} "
            "are in a state which is intended to prevent landings.".format(
                all_but_last_reviewer=", ".join(blocking_reviewers[:-1]),
                last_reviewer=blocking_reviewers[-1],
            )
        )

    return (
        "The review from {username} is in a state which is "
        "intended to prevent landings.".format(username=blocking_reviewers[0])
    )


@RevisionWarningCheck(1, "Has previously landed.")
def warning_previously_landed(
    revision: dict, diff: dict, stack_state: StackAssessmentState
):
    revision_id = PhabricatorClient.expect(revision, "id")
    diff_id = PhabricatorClient.expect(diff, "id")

    job = (
        LandingJob.revisions_query([revision_id])
        .filter_by(status=LandingJobStatus.LANDED)
        .order_by(LandingJob.updated_at.desc())
        .first()
    )

    if job is None:
        return None

    revision_to_diff_id = job.landed_revisions
    if job.revision_to_diff_id:
        legacy_data = {
            int(legacy_revision_id): int(legacy_diff_id)
            for legacy_revision_id, legacy_diff_id in job.revision_to_diff_id.items()
        }
        revision_to_diff_id.update(legacy_data)
    landed_diff_id = revision_to_diff_id[revision_id]
    same = diff_id == landed_diff_id
    only_revision = len(job.revisions) == 1

    return (
        "Already landed with {is_same_string} diff ({landed_diff_id}), "
        "pushed {push_string} {commit_sha}.".format(
            is_same_string=("the same" if same else "an older"),
            landed_diff_id=landed_diff_id,
            push_string=("as" if only_revision else "with new tip"),
            commit_sha=job.landed_commit_id,
        )
    )


@RevisionWarningCheck(2, "Is not Accepted.")
def warning_not_accepted(revision: dict, diff: dict, stack_state: StackAssessmentState):
    status = PhabricatorRevisionStatus.from_status(
        PhabricatorClient.expect(revision, "fields", "status", "value")
    )
    if status is PhabricatorRevisionStatus.ACCEPTED:
        return None

    return status.output_name


@RevisionWarningCheck(3, "No reviewer has accepted the current diff.")
def warning_reviews_not_current(
    revision: dict, diff: dict, stack_state: StackAssessmentState
):
    for reviewer in stack_state.reviewers[revision["phid"]].values():
        extra = calculate_review_extra_state(
            diff["phid"], reviewer["status"], reviewer["diffPHID"]
        )

        if (
            reviewer["status"] == ReviewerStatus.ACCEPTED
            and not extra["for_other_diff"]
        ):
            return None

    return "Has no accepted review on the current diff."


@RevisionWarningCheck(
    4, "Is a secure revision and should follow the Security Bug Approval Process."
)
def warning_revision_secure(
    revision: dict, diff: dict, stack_state: StackAssessmentState
):
    if stack_state.secure_project_phid is None:
        return None

    if not revision_is_secure(revision, stack_state.secure_project_phid):
        return None

    return (
        "This revision is tied to a secure bug. Ensure that you are following the "
        "Security Bug Approval Process guidelines before landing this changeset."
    )


@RevisionWarningCheck(5, "Revision is missing a Testing Policy Project Tag.")
def warning_revision_missing_testing_tag(
    revision: dict, diff: dict, stack_state: StackAssessmentState
):
    if not stack_state.testing_tag_project_phids:
        return None

    repo_phid = PhabricatorClient.expect(revision, "fields", "repositoryPHID")
    repo = stack_state.stack_data.repositories[repo_phid]
    if not revision_needs_testing_tag(
        revision,
        repo,
        stack_state.testing_tag_project_phids,
        stack_state.testing_policy_phid,
    ):
        return None

    return (
        "This revision does not specify a testing tag. Please add one before landing."
    )


@RevisionWarningCheck(6, "Revision has a diff warning.", True)
def warning_diff_warning(revision: dict, diff: dict, stack_state: StackAssessmentState):
    warnings = DiffWarning.query.filter(
        DiffWarning.revision_id == revision["id"],
        DiffWarning.diff_id == diff["id"],
        DiffWarning.status == DiffWarningStatus.ACTIVE,
    )
    if warnings.count():
        return [w.data for w in warnings]


@RevisionWarningCheck(7, "Revision is marked as WIP.")
def warning_wip_commit_message(
    revision: dict, diff: dict, stack_state: StackAssessmentState
):
    title = PhabricatorClient.expect(revision, "fields", "title")
    if title.lower().startswith("wip:"):
        return "This revision is marked as a WIP. Please remove `WIP:` before landing."


@RevisionWarningCheck(8, "Repository is under a soft code freeze.", True)
def warning_code_freeze(revision: dict, diff: dict, stack_state: StackAssessmentState):
    repo_phid = PhabricatorClient.expect(revision, "fields", "repositoryPHID")
    repo = stack_state.stack_data.repositories.get(repo_phid)
    if not repo:
        return

    supported_repos = get_repos_for_env(current_app.config.get("ENVIRONMENT"))
    try:
        repo_details = supported_repos[repo["fields"]["shortName"]]
    except KeyError:
        return

    if not repo_details.product_details_url:
        # Repo does not have a product details URL.
        return

    try:
        product_details = requests.get(repo_details.product_details_url).json()
    except requests.exceptions.RequestException as e:
        logger.exception(e)
        return [{"message": "Could not retrieve repository's code freeze status."}]

    freeze_date_str = product_details.get("NEXT_SOFTFREEZE_DATE")
    merge_date_str = product_details.get("NEXT_MERGE_DATE")
    # If the JSON doesn't have these keys, this warning isn't applicable
    if not freeze_date_str or not merge_date_str:
        return

    today = datetime.now(tz=timezone.utc)
    freeze_date = datetime.strptime(
        f"{freeze_date_str} {CODE_FREEZE_OFFSET}",
        "%Y-%m-%d %z",
    ).replace(tzinfo=timezone.utc)
    if today < freeze_date:
        return

    merge_date = datetime.strptime(
        f"{merge_date_str} {CODE_FREEZE_OFFSET}",
        "%Y-%m-%d %z",
    ).replace(tzinfo=timezone.utc)

    if freeze_date <= today <= merge_date:
        return [
            {
                "message": (
                    f"Repository is under a soft code freeze "
                    f"(ends {merge_date_str})."
                )
            }
        ]


@RevisionWarningCheck(9, "Revision has unresolved comments.")
def warning_unresolved_comments(
    revision: dict, diff: dict, stack_state: StackAssessmentState
):
    if not all(
        stack_state.phab.expect(inline, "fields", "isDone")
        for inline in get_inline_comments(stack_state.phab, f"D{revision['id']}")
    ):
        return "Revision has unresolved comments."


def user_block_no_auth0_email(
    stack_state: StackAssessmentState,
) -> Optional[str]:
    """Check the user has a proper auth0 email."""
    if not stack_state.landing_assessment:
        return None

    return (
        None
        if stack_state.landing_assessment.auth0_user.email
        else "You do not have a Mozilla verified email address."
    )


def user_block_scm_level(
    revision: dict,
    diff: dict,
    stack_state: StackAssessmentState,
) -> Optional[str]:
    """Check the user has the scm level required for this repository."""
    if not stack_state.landing_assessment:
        return None

    repo_phid = PhabricatorClient.expect(revision, "fields", "repositoryPHID")
    landing_repo = stack_state.landable_repos.get(repo_phid)
    if not landing_repo:
        return "Landing repository is missing for this landing."

    auth0_user = stack_state.landing_assessment.auth0_user

    if auth0_user.is_in_groups(landing_repo.access_group.active_group):
        return None

    if auth0_user.is_in_groups(landing_repo.access_group.membership_group):
        return "Your {} has expired.".format(landing_repo.access_group.display_name)

    return (
        "You have insufficient permissions to land. {} is required. "
        "See the FAQ for help.".format(landing_repo.access_group.display_name)
    )


def blocker_latest_diffs(
    revision: dict,
    diff: dict,
    stack_state: StackAssessmentState,
) -> Optional[str]:
    if not stack_state.landing_assessment:
        # If no revision/diff mapping is specified, we don't need to check for the
        # latest diff in the landing request.
        return None

    revision_phid = revision["phid"]
    latest_diff_phid = PhabricatorClient.expect(revision, "fields", "diffPHID")
    latest_diff_id = PhabricatorClient.expect(
        stack_state.stack_data.diffs[latest_diff_phid], "id"
    )

    revision_to_diff_id = dict(stack_state.landing_assessment.landing_path_phid)

    if latest_diff_id != revision_to_diff_id[revision_phid]:
        return "A requested diff is not the latest."


def blocker_landing_already_requested(
    stack_state: StackAssessmentState,
) -> Optional[str]:
    # Check if there is already a landing for something in the stack.
    existing_jobs = (
        LandingJob.revisions_query(
            [
                PhabricatorClient.expect(revision, "id")
                for revision in stack_state.stack_data.revisions.values()
            ]
        )
        .filter(
            LandingJob.status.in_(
                (
                    LandingJobStatus.SUBMITTED,
                    LandingJobStatus.DEFERRED,
                    LandingJobStatus.IN_PROGRESS,
                    None,
                )
            )
        )
        .first()
    )
    if existing_jobs is not None:
        return "A landing for revisions in this stack is already in progress."


def blocker_stack_landable(
    stack_state: StackAssessmentState,
) -> Optional[str]:
    """Assert the stack has a landable path."""
    if not stack_state.landing_assessment:
        # If no revision path is specified, we don't need to check if the path is landable.
        return None

    # Check that the provided path is a prefix to, or equal to, a landable path.
    revision_path = [
        revision_phid
        for revision_phid, diff_id in stack_state.landing_assessment.landing_path_phid
    ]
    landable_paths = stack_state.landable_stack.landable_paths()
    if not landable_paths or not any(
        revision_path == path[: len(revision_path)] for path in landable_paths
    ):
        return "The requested set of revisions are not landable."


def blocker_open_parents(
    revision: dict, diff: dict, stack_state: StackAssessmentState
) -> Optional[str]:
    phid = revision["phid"]
    parents = stack_state.stack.predecessors(phid)
    open_parents = {p for p in parents if not stack_state.statuses[p].closed}
    if not open_parents:
        return None

    if len(open_parents) > 1:
        return "Depends on multiple open parents."

    for parent in open_parents:
        if parent not in stack_state.landable_stack:
            return "Depends on D{} which is open and blocked.".format(
                PhabricatorClient.expect(stack_state.stack_data.revisions[parent], "id")
            )

    parent = open_parents.pop()
    if (
        stack_state.stack_data.revisions[phid]["fields"]["repositoryPHID"]
        != stack_state.stack_data.revisions[parent]["fields"]["repositoryPHID"]
    ):
        return "Depends on D{} which is open and has a different repository.".format(
            stack_state.stack_data.revisions[parent]["id"]
        )


def blocker_unsupported_repo(
    revision: dict, diff: dict, stack_state: StackAssessmentState
) -> Optional[str]:
    repo = PhabricatorClient.expect(revision, "fields", "repositoryPHID")
    if not repo:
        return (
            "Revision's repository unset. Specify a target using"
            '"Edit revision" in Phabricator'
        )

    if repo not in stack_state.landable_repos:
        return "Repository is not supported by Lando."


def blocker_closed_revisions(
    revision: dict, diff: dict, stack_state: StackAssessmentState
) -> Optional[str]:
    phid = revision["phid"]
    if stack_state.statuses[phid].closed:
        return "Revision is closed."


def blocker_open_ancestor(
    revision: dict, diff: dict, stack_state: StackAssessmentState
) -> Optional[str]:
    if revision["phid"] not in stack_state.landable_stack:
        return "Has an open ancestor revision that is blocked."


def block_author_planned_changes(
    revision: dict, diff: dict, stack_state: StackAssessmentState
) -> Optional[str]:
    status = PhabricatorRevisionStatus.from_status(
        PhabricatorClient.expect(revision, "fields", "status", "value")
    )
    if status is not PhabricatorRevisionStatus.CHANGES_PLANNED:
        return None

    return "The author has indicated they are planning changes to this revision."


def block_uplift_approval(
    revision: dict, diff: dict, stack_state: StackAssessmentState
) -> Optional[str]:
    """Check that Release Managers group approved a revision"""
    repo_phid = PhabricatorClient.expect(revision, "fields", "repositoryPHID")
    repo = stack_state.stack_data.repositories.get(repo_phid)
    if not repo or not stack_state.supported_repos:
        return None

    # Check if this repository needs an approval from relman.
    local_repo = stack_state.supported_repos.get(repo["fields"]["shortName"])
    if not local_repo or local_repo.approval_required is False:
        return None

    # Check that relman approval was requested and that the
    # approval was granted.
    reviewers = get_collated_reviewers(revision)
    relman_review = reviewers.get(stack_state.relman_group_phid)
    if relman_review is None or relman_review["status"] != ReviewerStatus.ACCEPTED:
        return (
            "The release-managers group did not accept the stack: "
            "you need to wait for a group approval from release-managers, "
            "or request a new review."
        )

    return None


def block_revision_data_classification(
    revision: dict, diff: dict, stack_state: StackAssessmentState
) -> Optional[str]:
    """Check that the `needs-data-classification` tag is not present on a revision."""
    if revision_has_needs_data_classification_tag(
        revision, stack_state.data_policy_review_phid
    ):
        return (
            "Revision makes changes to data collection and "
            "should have its data classification assessed before landing."
        )


def blocker_single_landing_repo(
    stack_state: StackAssessmentState,
) -> Optional[str]:
    """Assert that a landing request has a single landing repository."""
    if not stack_state.landing_assessment:
        return None

    repo_phid = None
    for revision, _diff in stack_state.landing_assessment.to_land:
        revision_repo_phid = PhabricatorClient.expect(
            revision, "fields", "repositoryPHID"
        )
        if not repo_phid:
            repo_phid = revision_repo_phid
            continue

        if revision_repo_phid != repo_phid:
            return "Landing path contains multiple repositories."

    if not repo_phid:
        return "Landing path has no repository specified."

    # Set the landing repo field on the `LandingAssessmentState`.
    landing_repo = stack_state.landable_repos.get(repo_phid)
    stack_state.landing_assessment.landing_repo = landing_repo


STACK_BLOCKER_CHECKS = [
    # This check needs to be first.
    blocker_stack_landable,
    blocker_landing_already_requested,
    user_block_no_auth0_email,
    blocker_single_landing_repo,
]

REVISION_BLOCKER_CHECKS = [
    user_block_scm_level,
    blocker_unsupported_repo,
    blocker_open_parents,
    blocker_closed_revisions,
    blocker_latest_diffs,
    block_author_planned_changes,
    block_diff_author_is_known,
    block_uplift_approval,
    block_revision_data_classification,
    # This check needs to be last.
    blocker_open_ancestor,
]

WARNING_CHECKS = [
    warning_blocking_reviews,
    warning_previously_landed,
    warning_not_accepted,
    warning_reviews_not_current,
    warning_revision_secure,
    warning_revision_missing_testing_tag,
    warning_diff_warning,
    warning_wip_commit_message,
    warning_code_freeze,
    warning_unresolved_comments,
]


def run_landing_checks(stack_state: StackAssessmentState) -> StackAssessment:
    """Build a `StackAssessment` by running landing checks.

    Run each landing check and append the result to the `StackAssessment`.
    There are three categories of checks:
        - `stack_blockers` are checks that inspect the entire state of the stack, and
          will block landing the stack if the check does not pass.
        - `revision_blockers` are checks that inspect each individual revision and diff
          pair, and will block landing the revision if the check does not pass.
        - `revision_warnings` are checks that inspect each individual revision and diff
          pair, and will present a warning that must be acknowledged to land if the
          check does not pass.

    Each type of check takes the `StackAssessmentState` object, and the revision-level
    blockers and warnings also take each `(revision, diff)` pair as arguments. Checks return
    `None` on success, and a string reason explaining what went wrong in the check on error.
    """
    assessment = StackAssessment()

    # Run stack-level blocker checks.
    for block in STACK_BLOCKER_CHECKS:
        if reason := block(stack_state=stack_state):
            assessment.blockers.append(reason)

    # Get the appropriate list of pairs to run checks against.
    revision_check_pairs = stack_state.revision_check_pairs()

    # Run revision-level blockers checks.
    for revision, diff in revision_check_pairs:
        phid = revision["phid"]
        for block in REVISION_BLOCKER_CHECKS:
            if reason := block(
                revision=revision,
                diff=diff,
                stack_state=stack_state,
            ):
                assessment.blockers.append(reason)

                if phid is not None and phid in stack_state.landable_stack:
                    stack_state.landable_stack.remove_node(phid)
                    stack_state.stack.nodes[phid]["blocked"].append(reason)

    # Run revision-level warning checks.
    for revision, diff in revision_check_pairs:
        for check in WARNING_CHECKS:
            if reason := check(revision=revision, diff=diff, stack_state=stack_state):
                assessment.warnings.append(reason)

    return assessment


def assess_stack_state(
    phab: PhabricatorClient,
    supported_repos: dict[str, Repo],
    stack_data: RevisionData,
    stack: RevisionStack,
    relman_group_phid: str,
    data_policy_review_phid: str,
    landing_assessment: Optional[LandingAssessmentState] = None,
) -> tuple[StackAssessment, StackAssessmentState]:
    """Assess the state of a given stack.

    Given the required state information for a stack, build a `StackAssessmentState`
    and run stack checks, returning a `StackAssessment` and the built
    `StackAssessmentState`.
    """
    landable_repos = get_landable_repos_for_revision_data(stack_data, supported_repos)

    involved_phids = set()
    reviewers = {}
    for revision in stack_data.revisions.values():
        involved_phids.update(gather_involved_phids(revision))
        reviewers[revision["phid"]] = get_collated_reviewers(revision)

    # Get more Phabricator data.
    involved_phids = list(involved_phids)
    users = user_search(phab, involved_phids)
    projects = project_search(phab, involved_phids)

    secure_project_phid = get_secure_project_phid(phab)
    testing_tag_project_phids = get_testing_tag_project_phids(phab)
    testing_policy_phid = get_testing_policy_phid(phab)

    stack_state = StackAssessmentState.from_assessment(
        phab=phab,
        stack_data=stack_data,
        stack=stack,
        landable_repos=landable_repos,
        supported_repos=supported_repos,
        reviewers=reviewers,
        users=users,
        projects=projects,
        data_policy_review_phid=data_policy_review_phid,
        relman_group_phid=relman_group_phid,
        secure_project_phid=secure_project_phid,
        testing_tag_project_phids=testing_tag_project_phids,
        testing_policy_phid=testing_policy_phid,
        landing_assessment=landing_assessment,
    )
    # Where we check the landing blockers.
    assessment = run_landing_checks(stack_state)

    return assessment, stack_state


def convert_path_id_to_phid(
    landing_path: list[tuple[int, int]], stack_data: RevisionData
) -> list[tuple[str, int]]:
    """Convert a landing path list into a mapping of PHIDs to `int` diff IDs."""
    mapping = {
        PhabricatorClient.expect(r, "id"): PhabricatorClient.expect(r, "phid")
        for r in stack_data.revisions.values()
    }
    try:
        mapped = [
            (mapping[revision_id], diff_id) for revision_id, diff_id in landing_path
        ]
    except IndexError:
        raise ProblemException(
            400,
            "Stack data invalid",
            "The provided stack_data is not valid.",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
        )

    return mapped
