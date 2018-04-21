# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import hashlib
import json

from connexion import ProblemException

from landoapi.decorators import lazy
from landoapi.models.landing import Landing
from landoapi.phabricator import (
    collate_reviewer_attachments,
    PhabricatorClient,
    result_list_to_phid_dict,
)
from landoapi.repos import get_repos_for_env


def tokens_are_equal(t1, t2):
    """Return whether t1 and t2 are equal.

    This function exists to make disabling confirmation_token checking
    easy until we have proper lando UI support. It also makes mocking
    or ignorning confirmation token checks very simple.
    """
    # TODO: return t1 == t2
    return True


class LandingAssessment:
    """Represents an assessment of issues that may block a revision landing.

    Attributes:
        warnings: List of warning LandingProblems.
        blockers: List of blocker LandingProblems.
            e.g. [NoAuth0Email('You do not have a Mozilla verified email')]
    """

    def __init__(self, warnings=None, blockers=None):
        self.warnings = warnings if warnings is not None else []
        self.blockers = blockers if blockers is not None else []

    def to_dict(self):
        """Return the assessment as a dict.

        Includes the appropriate confirmation_token for any warnings present.
        """
        warnings = [warning.serialize() for warning in self.warnings]
        blockers = [blocker.serialize() for blocker in self.blockers]
        return {
            'confirmation_token': self.hash_warning_list(warnings),
            'warnings': warnings,
            'blockers': blockers,
        }

    @staticmethod
    def hash_warning_list(warnings):
        """Return a hash of a serialized warning list.

        Returns: String.  Returns None if given an empty list.
        """
        if not warnings:
            return None

        sorted_warnings = sorted(
            warnings, key=lambda k: '{}:{}'.format(k['id'], k['message'])
        )
        return hashlib.sha256(
            json.dumps(sorted_warnings, sort_keys=True).encode('utf-8')
        ).hexdigest()

    def raise_if_blocked_or_unacknowledged(self, confirmation_token):
        details = self.to_dict()

        if details['blockers']:
            raise ProblemException(
                400,
                'Landing is Blocked',
                'There are landing blockers present which prevent landing.',
                ext=details,
                type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400' # noqa
            )  # yapf: disable

        if not tokens_are_equal(
            details['confirmation_token'], confirmation_token
        ):
            if confirmation_token is None:
                raise ProblemException(
                    400,
                    'Unacknowledged Warnings',
                    'There are landing warnings present which have not '
                    'been acknowledged.',
                    ext=details,
                    type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400' # noqa
                )  # yapf: disable

            raise ProblemException(
                400,
                'Acknowledged Warnings Have Changed',
                'The warnings present when the request was constructed have '
                'changed. Please acknowledge the new warnings and try again.',
                ext=details,
                type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400' # noqa
            )  # yapf: disable


class LandingProblem:
    """Represents a problem with landing.

    Attributes:
        id: A string identifier unique to this LandingProblem, e.g. 'E123'
        message: A user targeted message describing problem details.
            e.g. 'scm_level_3 requirement unmet'
    """
    id = None

    def __init__(self, message):
        if self.id is None:
            raise Exception("LandingProblems must be defined with an id")

        self.message = message

    @classmethod
    def check(
        cls, *, auth0_user, revision_id, diff_id, get_revision,
        get_latest_diff, get_latest_landed, get_repository, get_landing_repo,
        get_diff, get_open_parents, get_reviewers, get_reviewer_users
    ):
        raise NotImplementedError(
            'check(...) must be implemented on LandingProblem subclasses.'
        )

    def serialize(self):
        return {
            'id': self.id,
            'message': self.message,
        }


class NoAuth0Email(LandingProblem):
    id = "E001"

    @classmethod
    def check(cls, *, auth0_user, **kwargs):
        return None if auth0_user.email else cls(
            'You do not have a Mozilla verified email address.'
        )


class SCMLevelInsufficient(LandingProblem):
    id = "E002"

    @classmethod
    def check(cls, *, auth0_user, **kwargs):
        if auth0_user.is_in_groups('active_scm_level_3'):
            return None

        if auth0_user.is_in_groups('all_scm_level_3'):
            return cls('Your scm_level_3 access has expired.')

        return cls(
            'You have insufficient permissions to land. scm_level_3 '
            'access is required.'
        )


class LandingInProgress(LandingProblem):
    id = "E003"

    @classmethod
    def check(cls, *, revision_id, diff_id, **kwargs):
        already_submitted = Landing.is_revision_submitted(revision_id)
        if not already_submitted:
            return None

        if diff_id == already_submitted.diff_id:
            return cls(
                'This revision is already queued for landing with '
                'the same diff.'
            )
        else:
            return cls(
                'This revision is already queued for landing with '
                'diff {}'.format(already_submitted.diff_id)
            )


class OpenDependencies(LandingProblem):
    id = "E004"

    @classmethod
    def check(cls, *, get_open_parents, **kwargs):
        open_parents = get_open_parents()
        if open_parents:
            open_text = ', '.join(
                'D{}'.format(PhabricatorClient.expect(r, 'id'))
                for r in open_parents
            )
            if len(open_parents) > 1:
                return cls(
                    'This revision depends on the following revisions '
                    'which are still open: {}'.format(open_text)
                )
            else:
                return cls(
                    'This revision depends on the following revision '
                    'which is still open: {}'.format(open_text)
                )


class InvalidRepository(LandingProblem):
    id = "E005"

    @classmethod
    def check(cls, *, get_revision, get_landing_repo, **kwargs):
        if not PhabricatorClient.expect(
            get_revision(), 'fields', 'repositoryPHID'
        ):
            return cls(
                'This revision is not associated with a repository. '
                'In order to land, a revision must be associated with a '
                'repository on Phabricator.'
            )

        return None if get_landing_repo() else cls(
            'The repository this revision is associated with is not '
            'supported by Lando at this time.'
        )


class DoesNotExist(LandingProblem):
    id = "X000"

    @classmethod
    def check(cls, *, get_revision, get_diff, **kwargs):
        if get_revision() is None:
            raise ProblemException(
                404,
                'Revision not found',
                'The requested revision does not exist',
                type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404' # noqa
            )  # yapf: disable

        diff, _ = get_diff()
        if diff is None:
            raise ProblemException(
                404,
                'Diff not found',
                'The requested diff does not exist',
                type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404'  # noqa
            )  # yapf: disable


class DiffNotPartOfRevision(LandingProblem):
    id = "X000"

    @classmethod
    def check(cls, *, get_revision, get_diff, **kwargs):
        diff, _ = get_diff()
        revision = get_revision()
        if (
            PhabricatorClient.expect(revision, 'phid') !=
            PhabricatorClient.expect(diff, 'fields', 'revisionPHID')
        ):
            raise ProblemException(
                400,
                'Diff not related to the revision',
                'The requested diff is not related to the requested revision.',
                type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400'  # noqa
            )  # yapf: disable


class DiffNotLatest(LandingProblem):
    id = "W001"

    @classmethod
    def check(cls, *, diff_id, get_latest_diff, **kwargs):
        latest = PhabricatorClient.expect(get_latest_diff(), 'id')
        return None if diff_id == latest else cls(
            'Diff {} is not the latest diff for the revision. Diff {} '
            'is now the latest, you might want to land it instead.'.format(
                diff_id, latest
            )
        )


class PreviouslyLanded(LandingProblem):
    id = "W002"

    @classmethod
    def check(cls, *, diff_id, get_latest_landed, **kwargs):
        latest = get_latest_landed()
        if latest is None:
            return None

        if latest.diff_id == diff_id:
            return cls(
                'This diff ({landed_diff_id}) has already landed as '
                'commit {commit_sha}. Unless this change has been backed '
                'out, new changes should use a new revision.'.format(
                    landed_diff_id=latest.diff_id, commit_sha=latest.result
                )
            )

        return cls(
            'Another diff ({landed_diff_id}) of this revision has already '
            'landed as commit {commit_sha}. Unless this change has been '
            'backed out, new changes should use a new revision.'.format(
                landed_diff_id=latest.diff_id, commit_sha=latest.result
            )
        )


def check_landing_conditions(
    auth0_user,
    revision_id,
    diff_id,
    get_revision,
    get_latest_diff,
    get_latest_landed,
    get_repository,
    get_landing_repo,
    get_diff,
    get_open_parents,
    get_reviewers,
    get_reviewer_users,
    *,
    short_circuit=False,
    blockers_to_check=[
        NoAuth0Email,
        SCMLevelInsufficient,
        DoesNotExist,
        LandingInProgress,
        InvalidRepository,
        DiffNotPartOfRevision,
        OpenDependencies,
    ],
    warnings_to_check=[
        DiffNotLatest,
        PreviouslyLanded,
    ]
):
    """Return a LandingAssessment indicating any warnings or blockers.

    If `short_circuit` is True, the check will stop at the first blocker
    found and return immediately. This is useful for calling this function
    when attempting an actual landing, so any blocker will immediately
    stop processing.
    """
    assessment = LandingAssessment()
    for check in blockers_to_check:
        result = check.check(
            auth0_user=auth0_user,
            revision_id=revision_id,
            diff_id=diff_id,
            get_revision=get_revision,
            get_latest_diff=get_latest_diff,
            get_latest_landed=get_latest_landed,
            get_repository=get_repository,
            get_landing_repo=get_landing_repo,
            get_diff=get_diff,
            get_open_parents=get_open_parents,
            get_reviewers=get_reviewers,
            get_reviewer_users=get_reviewer_users,
        )

        if result is not None:
            assessment.blockers.append(result)

            if short_circuit:
                return assessment

    for check in warnings_to_check:
        result = check.check(
            auth0_user=auth0_user,
            revision_id=revision_id,
            diff_id=diff_id,
            get_revision=get_revision,
            get_latest_diff=get_latest_diff,
            get_latest_landed=get_latest_landed,
            get_repository=get_repository,
            get_landing_repo=get_landing_repo,
            get_diff=get_diff,
            get_open_parents=get_open_parents,
            get_reviewers=get_reviewers,
            get_reviewer_users=get_reviewer_users,
        )

        if result is not None:
            assessment.warnings.append(result)

    return assessment


@lazy
def lazy_get_latest_diff(phabricator, revision):
    """Return the latest diff as define by the Phabricator API.

    Args:
        phabricator: A PhabricatorClient instance.
        revision: A dict of the revision data just as it is returned
            by Phabricator.
    """
    return phabricator.single(
        phabricator.call_conduit(
            'differential.diff.search',
            constraints={
                'phids': [phabricator.expect(revision, 'fields', 'diffPHID')]
            },
        ), 'data'
    )


@lazy
def lazy_get_revision(phabricator, revision_id):
    """Return a revision as defined by the Phabricator API.

    Args:
        phabricator: A PhabricatorClient instance.
        revision_id: The integer id of the revision.

    Returns:
        The revision data from the Phabricator API for the provided
        `revision_id`. If the revision is not found None is returned.
    """
    revision = phabricator.call_conduit(
        'differential.revision.search',
        constraints={'ids': [revision_id]},
        attachments={
            'reviewers': True,
            'reviewers-extra': True,
        }
    )
    revision = phabricator.expect(revision, 'data')
    revision = phabricator.single(revision, none_when_empty=True)
    return revision


@lazy
def lazy_get_diff(phabricator, diff_id, latest_diff):
    """Return diff objects as defined by the Phabricator API.

    Args:
        phabricator: A PhabricatorClient instance.
        diff_id: The integer id of the diff.

    Returns:
        A 2-tuple of diff data from the Phabricator API for the provided
        `diff_id`. Data for the first entry comes from a
        'differential.diff.search', with the second entry coming from
        'differential.querydiffs'. If the diff is not found None is returned.
    """
    latest_diff_id = phabricator.expect(latest_diff, 'id')
    if diff_id is not None and diff_id != latest_diff_id:
        diff = phabricator.single(
            phabricator.call_conduit(
                'differential.diff.search',
                constraints={'ids': [diff_id]},
            ),
            'data',
            none_when_empty=True
        )
    else:
        diff = latest_diff

    if diff is None:
        return None, None

    # TODO: Remove this and return only above diff result after
    # 'commits' attachment can be accessed on 'differential.diff.search'.
    querydiffs_diff = phabricator.call_conduit(
        'differential.querydiffs', ids=[diff_id]
    )
    querydiffs_diff = querydiffs_diff.get(str(diff_id))
    return diff, querydiffs_diff


@lazy
def lazy_get_repository(phabricator, revision):
    """Return a repository as defined by the Phabricator API.

    Args:
        phabricator: A PhabricatorClient instance.
        revision: A dict of the revision data just as it is returned
            by Phabricator.

    Returns:
        The repository data from the Phabricator API associated with the
        provided `revision`. If the revision is not associated with a
        repository `None` is returned.

    Raises:
        landoapi.phabricator.PhabricatorCommunicationException:
            If the provided revision is associated with a repository but
            the PHID cannot be found when searching. This should almost
            never happen unless something has gone seriously wrong.
    """
    repo_phid = phabricator.expect(revision, 'fields', 'repositoryPHID')
    if not repo_phid:
        return None

    return phabricator.expect(
        phabricator.call_conduit(
            'diffusion.repository.search', constraints={'phids': [repo_phid]}
        ), 'data', 0
    )


@lazy
def lazy_get_landing_repo(repository, env):
    """Return a landoapi.repos.Repo for the provided repository.

    Args:
        repository: A dict of the repository data just as it is returned
            by Phabricator.
        env: The environment Lando API is running in.

    Returns:
        A landoapi.repos.Repo corresponding to the provided Phabricator
        repository data or None if the repository is not configured.

    Raises:
        landoapi.phabricator.PhabricatorCommunicationException:
            If the provided repository data does not adhere to the format
            expected from Phabricator. This should almost never happen
            when passing a repository response from phabricator unless
            something has gone seriously wrong.
    """
    if not repository:
        return None

    shortname = PhabricatorClient.expect(repository, 'fields', 'shortName')
    return get_repos_for_env(env).get(shortname)


@lazy
def lazy_get_open_parents(phabricator, revision):
    """Return a list of open parents for a revision.

    Args:
        phabricator: A PhabricatorClient instance.
        revision: A dict of the revision data just as it is returned
            by Phabricator.
    """
    phids = phabricator.call_conduit(
        'edge.search',
        sourcePHIDs=[phabricator.expect(revision, 'phid')],
        types=['revision.parent']
    )
    phids = phabricator.expect(phids, 'data')
    phids = [phabricator.expect(p, 'destinationPHID') for p in phids]

    if not phids:
        return []

    open_parents = phabricator.call_conduit(
        'differential.revision.search',
        constraints={
            'statuses': ['open()'],
            'phids': phids,
        }
    )
    open_parents = phabricator.expect(open_parents, 'data')
    return open_parents


@lazy
def lazy_user_search(phabricator, user_phids):
    """Return a dictionary mapping phid to user information from a user.search.

    Args:
        phabricator: A PhabricatorClient instance.
        user_phids: A list of user phids to search.
    """
    users = phabricator.call_conduit(
        'user.search', constraints={'phids': user_phids}
    )
    return result_list_to_phid_dict(phabricator.expect(users, 'data'))


@lazy
def lazy_reviewers_search(phabricator, reviewers):
    """Return a dictionary mapping phid to user information for reviewers.

    Args:
        phabricator: A PhabricatorClient instance.
        reviewers: A dict of reviewer attachment data as returned by
            `landoapi.phabricator.collate_reviewer_attachments`.
    """
    phids = list(reviewers.keys())

    # Immediately execute the lazy function.
    return lazy_user_search(phabricator, phids)()


@lazy
def lazy_get_reviewers(revision):
    """Return a dictionary mapping phid to collated reviewer attachment data.

    Args:
        revision: A dict of the revision data from differential.revision.search
            with the 'reviewers' and 'reviewers-extra' attachments.
    """
    attachments = PhabricatorClient.expect(revision, 'attachments')
    return collate_reviewer_attachments(
        PhabricatorClient.expect(attachments, 'reviewers', 'reviewers'),
        PhabricatorClient.expect(
            attachments, 'reviewers-extra', 'reviewers-extra'
        )
    )
