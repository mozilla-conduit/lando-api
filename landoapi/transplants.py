# This Source Code Form is subject to the terms of the Mozilla Publc
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import functools
import logging
from collections import namedtuple

from landoapi.phabricator import PhabricatorClient
from landoapi.reviews import (
    calculate_review_extra_state,
    reviewer_identity,
)

logger = logging.getLogger(__name__)


class LandingAssessment:
    """Represents an assessment of issues that may block a revision landing.

    Attributes:
        blocker: String reason landing is blocked.
        warnings: List of warning LandingProblems.
    """

    def __init__(self, *, blocker=None, warnings=None):
        self.blocker = blocker
        self.warnings = warnings if warnings is not None else []

    def to_dict(self):
        bucketed_warnings = {}
        for w in self.warnings:
            if w.i not in bucketed_warnings:
                bucketed_warnings[w.i] = {
                    'id': w.i,
                    'display': w.display,
                    'instances': [],
                }

            bucketed_warnings[w.i]['instances'].append(
                {
                    'revision_id': w.revision_id,
                    'details': w.details,
                }
            )

        # TODO: Generate a proper confirmation token.
        return {
            'blocker': self.blocker,
            'warnings': list(bucketed_warnings.values()),
            'confirmation_token': None,
        }


RevisionWarning = namedtuple(
    'RevisionWarning', ('i', 'display', 'revision_id', 'details')
)


class RevisionWarningCheck:
    _warning_ids = set()

    def __init__(self, i, display):
        if not isinstance(i, int):
            raise ValueError('Warning ids must be provided as an integer')

        if i > 0 and (i - 1) not in self._warning_ids:
            raise ValueError(
                'Warnings may not skip an id number. Warnings should never '
                'be removed, just replaced with a noop function if they are '
                'no longer used. This prevents id re-use.'
            )

        self._warning_ids.add(i)
        self.i = i
        self.display = display

    def __call__(self, f):
        @functools.wraps(f)
        def wrapped(
            *, revision, diff, repo, landing_repo, reviewers, users, projects
        ):
            result = f(
                revision=revision,
                diff=diff,
                repo=repo,
                landing_repo=landing_repo,
                reviewers=reviewers,
                users=users,
                projects=projects,
            )
            return None if result is None else RevisionWarning(
                self.i, self.display, 'D{}'.format(revision['id']), result
            )

        return wrapped


@RevisionWarningCheck(0, 'Has a review intended to block landing.')
def warning_blocking_reviews(
    *, revision, diff, reviewers, users, projects, **kwargs
):
    reviewer_extra_state = {
        phid: calculate_review_extra_state(
            diff['phid'], r['status'], r['diffPHID'], r['voidedPHID']
        )
        for phid, r in reviewers.items()
    }
    blocking_phids = [
        phid for phid, state in reviewer_extra_state.items()
        if state['blocking_landing']
    ]
    if not blocking_phids:
        return None

    blocking_reviewers = [
        '@{}'.format(reviewer_identity(phid, users, projects).identifier)
        for phid in blocking_phids
    ]
    if len(blocking_reviewers) > 1:
        return (
            'Reviews from {all_but_last_reviewer}, and {last_reviewer} '
            'are in a state which is intended to prevent landings.'.format(
                all_but_last_reviewer=', '.join(blocking_reviewers[:-1]),
                last_reviewer=blocking_reviewers[-1],
            )
        )

    return (
        'The review from {username} is in a state which is '
        'intended to prevent landings.'.format(
            username=blocking_reviewers[0],
        )
    )


def user_block_no_auth0_email(*, auth0_user, **kwargs):
    """Check the user has a proper auth0 email."""
    return None if auth0_user.email else (
        'You do not have a Mozilla verified email address.'
    )


def user_block_scm_level(*, auth0_user, landing_repo, **kwargs):
    """Check the user has the scm level required for this repository."""
    if auth0_user.is_in_groups(landing_repo.access_group.active_group):
        return None

    if auth0_user.is_in_groups(landing_repo.access_group.membership_group):
        return 'Your {} has expired.'.format(
            landing_repo.access_group.display_name
        )

    return (
        'You have insufficient permissions to land. '
        '{} is required.'.format(landing_repo.access_group.display_name)
    )


def check_landing_warnings(
    auth0_user,
    to_land,
    repo,
    landing_repo,
    reviewers,
    users,
    projects,
    *,
    revision_warnings=[
        warning_blocking_reviews,
    ]
):
    assessment = LandingAssessment()
    for revision, diff in to_land:
        for check in revision_warnings:
            result = check(
                revision=revision,
                diff=diff,
                repo=repo,
                landing_repo=landing_repo,
                reviewers=reviewers[revision['phid']],
                users=users,
                projects=projects,
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
    user_blocks=[
        user_block_no_auth0_email,
        user_block_scm_level,
    ]
):
    revision_path = []
    revision_to_diff_id = {}
    for revision_phid, diff_id in requested_path:
        revision_path.append(revision_phid)
        revision_to_diff_id[revision_phid] = diff_id

    # Check that the provided path is a prefix to, or equal to,
    # a landable path.
    for path in landable_paths:
        if revision_path == path[:len(revision_path)]:
            break
    else:
        return LandingAssessment(
            blocker='The requested set of revisions are not landable.'
        )

    # Check the requested diffs are the latest.
    for revision_phid in revision_path:
        latest_diff_phid = PhabricatorClient.expect(
            stack_data.revisions[revision_phid], 'fields', 'diffPHID'
        )
        latest_diff_id = PhabricatorClient.expect(
            stack_data.diffs[latest_diff_phid], 'id'
        )

        if latest_diff_id != revision_to_diff_id[revision_phid]:
            return LandingAssessment(
                blocker='A requested diff is not the latest.'
            )

    # To be a landable path the entire path must have the same
    # repository, so we can get away with checking only one.
    repo = landable_repos[stack_data.revisions[revision_path[0]]['fields']
                          ['repositoryPHID']]

    # Check anything that would block the current user from
    # landing this.
    for block in user_blocks:
        result = block(auth0_user=auth0_user, landing_repo=repo)
        if result is not None:
            return LandingAssessment(blocker=result)

    return LandingAssessment()
