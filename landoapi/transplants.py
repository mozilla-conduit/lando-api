# This Source Code Form is subject to the terms of the Mozilla Publc
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import functools
import hashlib
import json
import logging
from collections import namedtuple

from connexion import ProblemException

from landoapi.repos import Repo
from landoapi.models.transplant import Transplant, TransplantStatus
from landoapi.models.revisions import DiffWarning, DiffWarningStatus
from landoapi.phabricator import PhabricatorClient, ReviewerStatus, RevisionStatus
from landoapi.reviews import calculate_review_extra_state, reviewer_identity
from landoapi.revisions import (
    check_author_planned_changes,
    check_diff_author_is_known,
    check_relman_approval,
    revision_is_secure,
    revision_needs_testing_tag,
)

logger = logging.getLogger(__name__)

DEFAULT_OTHER_BLOCKER_CHECKS = [
    check_author_planned_changes,
    check_diff_author_is_known,
]

RevisionWarning = namedtuple(
    "RevisionWarning",
    ("i", "display", "revision_id", "details", "articulated"),
    defaults=(None, None, None, None, False),
)


def tokens_are_equal(t1, t2):
    """Return whether t1 and t2 are equal.

    This function exists to make mocking or ignoring confirmation token
    checks very simple.
    """
    return t1 == t2


class TransplantAssessment:
    """Represents an assessment of issues that may block a revision landing.

    Attributes:
        blocker: String reason landing is blocked.
        warnings: List with each item being a RevisionWarning.
    """

    def __init__(self, *, blocker=None, warnings=None):
        self.blocker = blocker
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
            "blocker": self.blocker,
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
        if self.blocker is not None:
            raise ProblemException(
                400,
                "Landing is Blocked",
                "There are landing blockers present which prevent landing.",
                ext=self.to_dict(),
                type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
            )

        details = self.to_dict()
        if not tokens_are_equal(details["confirmation_token"], confirmation_token):
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
        def wrapped(*, revision, **kwargs):
            kwargs["revision"] = revision
            result = f(**kwargs)
            return (
                None
                if result is None
                else RevisionWarning(
                    self.i, self.display, f'D{revision["id"]}', result, self.articulated
                )
            )

        return wrapped


@RevisionWarningCheck(0, "Has a review intended to block landing.")
def warning_blocking_reviews(*, revision, diff, reviewers, users, projects, **kwargs):
    reviewer_extra_state = {
        phid: calculate_review_extra_state(
            diff["phid"], r["status"], r["diffPHID"], r["voidedPHID"]
        )
        for phid, r in reviewers.items()
    }
    blocking_phids = [
        phid
        for phid, state in reviewer_extra_state.items()
        if state["blocking_landing"]
    ]
    if not blocking_phids:
        return None

    blocking_reviewers = [
        "@{}".format(reviewer_identity(phid, users, projects).identifier)
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
def warning_previously_landed(*, revision, diff, **kwargs):
    revision_id = PhabricatorClient.expect(revision, "id")
    diff_id = PhabricatorClient.expect(diff, "id")

    landed_transplant = (
        Transplant.revisions_query([revision_id])
        .filter_by(status=TransplantStatus.landed)
        .order_by(Transplant.updated_at.desc())
        .first()
    )

    if landed_transplant is None:
        return None

    landed_diff_id = landed_transplant.revision_to_diff_id[str(revision_id)]
    same = diff_id == landed_diff_id
    only_revision = len(landed_transplant.revision_order) == 1

    return (
        "Already landed with {is_same_string} diff ({landed_diff_id}), "
        "pushed {push_string} {commit_sha}.".format(
            is_same_string=("the same" if same else "an older"),
            landed_diff_id=landed_diff_id,
            push_string=("as" if only_revision else "with new tip"),
            commit_sha=landed_transplant.result,
        )
    )


@RevisionWarningCheck(2, "Is not Accepted.")
def warning_not_accepted(*, revision, **kwargs):
    status = RevisionStatus.from_status(
        PhabricatorClient.expect(revision, "fields", "status", "value")
    )
    if status is RevisionStatus.ACCEPTED:
        return None

    return status.output_name


@RevisionWarningCheck(3, "No reviewer has accepted the current diff.")
def warning_reviews_not_current(*, diff, reviewers, **kwargs):
    for _, r in reviewers.items():
        extra = calculate_review_extra_state(
            diff["phid"], r["status"], r["diffPHID"], r["voidedPHID"]
        )

        if r["status"] is ReviewerStatus.ACCEPTED and not extra["for_other_diff"]:
            return None

    return "Has no accepted review on the current diff."


@RevisionWarningCheck(
    4, "Is a secure revision and should follow the Security Bug Approval Process."
)
def warning_revision_secure(*, revision, secure_project_phid, **kwargs):
    if secure_project_phid is None:
        return None

    if not revision_is_secure(revision, secure_project_phid):
        return None

    return (
        "This revision is tied to a secure bug. Ensure that you are following the "
        "Security Bug Approval Process guidelines before landing this changeset."
    )


@RevisionWarningCheck(5, "Revision is missing a Testing Policy Project Tag.")
def warning_revision_missing_testing_tag(
    *, revision, testing_tag_project_phids, testing_policy_phid, **kwargs
):
    if not testing_tag_project_phids:
        return None

    if not revision_needs_testing_tag(
        revision, testing_tag_project_phids, testing_policy_phid
    ):
        return None

    return (
        "This revision does not specify a testing tag. Please add one before landing."
    )


@RevisionWarningCheck(6, "Revision has a diff warning.", True)
def warning_diff_warning(*, revision, diff, **kwargs):
    warnings = DiffWarning.query.filter(
        DiffWarning.revision_id == revision["id"],
        DiffWarning.diff_id == diff["id"],
        DiffWarning.status == DiffWarningStatus.ACTIVE,
    )
    if warnings.count():
        return [w.data for w in warnings]


def user_block_no_auth0_email(*, auth0_user, **kwargs):
    """Check the user has a proper auth0 email."""
    return (
        None
        if auth0_user.email
        else ("You do not have a Mozilla verified email address.")
    )


def user_block_scm_level(*, auth0_user, landing_repo, **kwargs):
    """Check the user has the scm level required for this repository."""
    if auth0_user.is_in_groups(landing_repo.access_group.active_group):
        return None

    if auth0_user.is_in_groups(landing_repo.access_group.membership_group):
        return "Your {} has expired.".format(landing_repo.access_group.display_name)

    return (
        "You have insufficient permissions to land. {} is required. "
        "See the FAQ for help.".format(landing_repo.access_group.display_name)
    )


def check_landing_warnings(
    auth0_user,
    to_land,
    repo,
    landing_repo,
    reviewers,
    users,
    projects,
    secure_project_phid,
    testing_tag_project_phids,
    testing_policy_phid,
    *,
    revision_warnings=[
        warning_blocking_reviews,
        warning_previously_landed,
        warning_not_accepted,
        warning_reviews_not_current,
        warning_revision_secure,
        warning_revision_missing_testing_tag,
        warning_diff_warning,
    ],
):
    assessment = TransplantAssessment()
    for revision, diff in to_land:
        for check in revision_warnings:
            result = check(
                revision=revision,
                diff=diff,
                repo=repo,
                landing_repo=landing_repo,
                reviewers=reviewers[revision["phid"]],
                users=users,
                projects=projects,
                secure_project_phid=secure_project_phid,
                testing_tag_project_phids=testing_tag_project_phids,
                testing_policy_phid=testing_policy_phid,
            )

            if result is not None:
                assessment.warnings.append(result)

    return assessment


def check_landing_blockers(
    auth0_user,
    requested_path,
    stack_data,
    landable_paths,
    landable_repos,
    *,
    user_blocks=[user_block_no_auth0_email, user_block_scm_level],
):
    revision_path = []
    revision_to_diff_id = {}
    for revision_phid, diff_id in requested_path:
        revision_path.append(revision_phid)
        revision_to_diff_id[revision_phid] = diff_id

    # Check that the provided path is a prefix to, or equal to,
    # a landable path.
    for path in landable_paths:
        if revision_path == path[: len(revision_path)]:
            break
    else:
        return TransplantAssessment(
            blocker="The requested set of revisions are not landable."
        )

    # Check the requested diffs are the latest.
    for revision_phid in revision_path:
        latest_diff_phid = PhabricatorClient.expect(
            stack_data.revisions[revision_phid], "fields", "diffPHID"
        )
        latest_diff_id = PhabricatorClient.expect(
            stack_data.diffs[latest_diff_phid], "id"
        )

        if latest_diff_id != revision_to_diff_id[revision_phid]:
            return TransplantAssessment(blocker="A requested diff is not the latest.")

    # Check if there is already a landing for something in the stack.
    if (
        Transplant.revisions_query(
            [PhabricatorClient.expect(r, "id") for r in stack_data.revisions.values()]
        )
        .filter_by(status=TransplantStatus.submitted)
        .first()
        is not None
    ):
        return TransplantAssessment(
            blocker=("A landing for revisions in this stack is already in progress.")
        )

    # To be a landable path the entire path must have the same
    # repository, so we can get away with checking only one.
    repo = landable_repos[
        stack_data.revisions[revision_path[0]]["fields"]["repositoryPHID"]
    ]

    # Check anything that would block the current user from
    # landing this.
    for block in user_blocks:
        result = block(auth0_user=auth0_user, landing_repo=repo)
        if result is not None:
            return TransplantAssessment(blocker=result)

    return TransplantAssessment()


def get_blocker_checks(repositories: dict, relman_group_phid: str):
    """Build all transplant blocker checks that need extra Phabricator data"""
    assert all(map(lambda r: isinstance(r, Repo), repositories.values()))

    return DEFAULT_OTHER_BLOCKER_CHECKS + [
        # Configure relman check with extra data
        check_relman_approval(relman_group_phid, repositories)
    ]
