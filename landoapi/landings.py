# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import hashlib
import json

from connexion import ProblemException

from landoapi.models.landing import Landing


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

        if details['confirmation_token'] != confirmation_token:
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
        cls, *, auth0_user, revision_id, diff_id, phabricator, get_revision
    ):
        pass

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
    def check(cls, *, phabricator, get_revision, **kwargs):
        open_revision = phabricator.get_first_open_parent_revision(
            get_revision()
        )
        return None if not open_revision else cls(
            'This revision depends on at least one revision which is open: '
            'D{}.'.format(open_revision['id'])
        )


class DoesNotExist(LandingProblem):
    id = "E404"

    @classmethod
    def check(cls, *, get_revision, **kwargs):
        if get_revision() is None:
            raise ProblemException(
                404,
                'Revision not found',
                'The requested revision does not exist',
                type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404' # noqa
            )  # yapf: disable


def check_landing_conditions(
    auth0_user,
    revision_id,
    diff_id,
    phabricator,
    get_revision,
    *,
    short_circuit=False,
    blockers_to_check=[
        NoAuth0Email,
        SCMLevelInsufficient,
        DoesNotExist,
        LandingInProgress,
        OpenDependencies,
    ],
    warnings_to_check=[]
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
            phabricator=phabricator,
            get_revision=get_revision
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
            phabricator=phabricator,
            get_revision=get_revision
        )

        if result is not None:
            assessment.warnings.append(result)

    return assessment
