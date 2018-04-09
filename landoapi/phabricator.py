# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import json
import logging
from json.decoder import JSONDecodeError

import requests
from enum import Enum

logger = logging.getLogger(__name__)


class Statuses(Enum):
    NEEDS_REVIEW = '0'
    NEEDS_REVISION = '1'
    APPROVED = '2'
    CLOSED = '3'
    ABANDONED = '4'
    CHANGES_PLANNED = '5'


CLOSED_STATUSES = [Statuses.CLOSED, Statuses.ABANDONED]
OPEN_STATUSES = [
    Statuses.NEEDS_REVIEW, Statuses.NEEDS_REVISION, Statuses.APPROVED,
    Statuses.CHANGES_PLANNED
]


class PhabricatorClient:
    """A class to interface with Phabricator's Conduit API.

    All request methods in this class will throw a PhabricatorAPIException if
    Phabricator returns an error response. If there is an actual problem with
    the request to the server or decoding the JSON response, this class will
    bubble up the exception, as a PhabricatorAPIException caused by the
    underlying exception.
    """

    def __init__(self, url, api_token, *, session=None):
        self.api_url = url + 'api/' if url[-1] == '/' else url + '/api/'
        self.api_token = api_token
        self.session = session or self.create_session()

    def call_conduit(self, method, **kwargs):
        """Return the result of an RPC call to a conduit method.

        Args:
            **kwargs: Every method parameter is passed as a keyword argument.

        Returns:
            The 'result' key of the conduit method's response or None if
            the 'result' key doesn't exist.

        Raises:
            PhabricatorAPIException:
                if conduit returns an error response.
            requests.exceptions.RequestException:
                if there is a request exception while communicating
                with the conduit API.
        """
        if '__conduit__' not in kwargs:
            kwargs['__conduit__'] = {'token': self.api_token}

        data = {
            'output': 'json',
            'params': json.dumps(kwargs),
        }

        try:
            response = self.session.get(
                self.api_url + method, data=data
            ).json()
        except requests.RequestException as exc:
            raise PhabricatorCommunicationException(
                "An error occurred when communicating with Phabricator"
            ) from exc
        except JSONDecodeError as exc:
            raise PhabricatorCommunicationException(
                "Phabricator response could not be decoded as JSON"
            ) from exc

        PhabricatorAPIException.raise_if_error(response)
        return response.get('result')

    @staticmethod
    def create_session():
        return requests.Session()

    @staticmethod
    def single(result, *, none_when_empty=False):
        """Return the first item of a phabricator result.

        Args:
            result: Data from the result key of a Phabricator API response.
            none_when_empty: `None` is returned if the result is empty if
                `none_when_empty` is True.

        Returns:
            The first result in the provided data. If `none_when_empty` is
            `True`, `None` will be returned if the result is empty.

        Raises:
            PhabricatorCommunicationException:
                If there is more or less than a single item.
        """
        if len(result) > 1 or (not result and not none_when_empty):
            raise PhabricatorCommunicationException(
                'Phabricator responded with unexpected data'
            )

        return result[0] if result else None

    @staticmethod
    def expect(result, *args):
        """Return data from a phabricator result.

        Args:
            result: Data from the result key of a Phabricator API response.
            *args: a path of keys into result which should and must
                exist. If data is missing or malformed when attempting
                to access the specific path an exception is raised.

        Returns:
            The data which exists at the path specified by args.

        Raises:
            PhabricatorCommunicationException:
                If the data is malformed or missing.
        """
        try:
            for k in args:
                result = result[k]
        except (IndexError, KeyError, ValueError, TypeError) as exc:
            raise PhabricatorCommunicationException(
                'Phabricator responded with unexpected data'
            ) from exc

        return result

    def diff_phid_to_id(self, phid):
        """Convert Diff PHID to the Diff id.

        Send a request to Phabricator's `phid.query` API.
        Extract Diff id from URI provided in result.

        Args:
            phid: The PHID of the diff.

        Returns:
            Integer representing the Diff id in Phabricator
        """
        phid_query_result = self.call_conduit('phid.query', phids=[phid])
        if not phid_query_result:
            return None

        diff_uri = self.expect(phid_query_result, phid, 'uri')
        return self._extract_diff_id_from_uri(diff_uri)

    def get_reviewers(self, revision_id):
        """Gets reviewers of the revision.

        Requests `revision.search` to get the reviewers data. Then - with the
        received reviewerPHID keys - a new request is made to `user.search`
        to get the user info. A new dict indexed by phid is created with keys
        and values from both requests.

        Attributes:
            revision_id: integer, ID of the revision in Phabricator

        Returns:
            A list sorted by phid of combined reviewers and users info.
        """
        # Get basic information about the reviewers
        # reviewerPHID, actorPHID, status, and isBlocking is provided
        result = self.call_conduit(
            'differential.revision.search',
            constraints={'ids': [revision_id]},
            attachments={'reviewers': True}
        )
        data = self.expect(result, 'data')
        reviewers = self.expect(
            data, 0, 'attachments', 'reviewers', 'reviewers'
        )

        if not reviewers:
            return {}

        # Get user info of all revision reviewers
        reviewers_phids = [self.expect(r, 'reviewerPHID') for r in reviewers]
        result = self.call_conduit(
            'user.search', constraints={'phids': reviewers_phids}
        )
        reviewers_info = self.expect(result, 'data')

        if len(reviewers) != len(reviewers_info):
            logger.warning(
                {
                    'reviewers_phids': reviewers_phids,
                    'users_phids': [r['phid'] for r in reviewers_info],
                    'revision_id': revision_id,
                    'msg': 'Number of reviewers and user accounts do not match'
                }, 'get_reviewers.warning'
            )

        # Create a dict of all reviewers and users info identified by PHID.
        reviewers_dict = {}
        for data in reviewers, reviewers_info:
            for reviewer in data:
                phid = reviewer.get('reviewerPHID') or reviewer.get('phid')
                reviewers_dict[phid] = reviewers_dict.get(phid, {})
                reviewers_dict[phid].update(reviewer)

        # Translate the dict to a list sorted by the key (PHID)
        return [
            r[1] for r in sorted(reviewers_dict.items(), key=lambda x: x[0])
        ]

    def verify_api_token(self):
        """ Verifies that the api token is valid.

        Returns False if Phabricator returns an error code when checking this
        api token. Returns True if no errors are found.
        """
        try:
            self.call_conduit('user.whoami')
        except PhabricatorAPIException:
            return False
        return True

    def get_dependency_tree(self, revision, recursive=True):
        """Generator yielding revisions from the dependency tree.

        Get parent revisions for the provided revision. If recursive is True
        try to get parent's revisions.

        Args:
            revision: Revision which dependency tree will be examined
            recursive: (bool) should parent's dependency tree be returned?

        Returns:
            A generator of the dependency tree revisions
        """
        phids = self.expect(revision,
                            'auxiliary').get('phabricator:depends-on', [])
        if phids:
            revisions = self.call_conduit('differential.query', phids=phids)
            for revision in revisions:
                yield revision

                if recursive:
                    yield from self.get_dependency_tree(revision)

    def get_first_open_parent_revision(self, revision):
        """Find first open parent revision.

        Args:
            revision: Revision which dependency tree will be examined

        Returns:
            Open Revision or None
        """

        dependency_tree = self.get_dependency_tree(revision)
        for dependency in dependency_tree:
            if Statuses(self.expect(dependency, 'status')) in OPEN_STATUSES:
                return dependency

    @classmethod
    def extract_bug_id(cls, revision):
        """Helper method to extract the bug id from a Phabricator revision.

        Args:
            revision: dict containing revision info.

        Returns:
            (int) Bugzilla bug id or None
        """
        bug_id = cls.expect(revision, 'auxiliary').get('bugzilla.bug-id', None)
        try:
            return int(bug_id)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _extract_diff_id_from_uri(uri):
        """Extract a diff ID from a Diff uri."""
        # The diff is part of a URI, such as
        # "https://secure.phabricator.com/differential/diff/43480/".
        parts = uri.rsplit('/', 4)

        # Check that the URI Path is something we understand.  Fail if the
        # URI path changed (signalling that the diff id part of the URI may
        # be in a different segment of the URI string).
        if parts[1:-2] != ['differential', 'diff']:
            raise RuntimeError(
                "Phabricator Diff URI parsing error: The "
                "URI {} is not in a format we "
                "understand!".format(uri)
            )

        # Take the second-last member because of the trailing slash on the URL.
        return int(parts[-2])


class PhabricatorAPIException(Exception):
    """Exception to be raised when Phabricator returns an error response."""

    def __init__(self, *args, error_code=None, error_info=None):
        super().__init__(*args)
        self.error_code = error_code
        self.error_info = error_info

    @classmethod
    def raise_if_error(cls, response_body):
        """Raise a PhabricatorAPIException if response_body was an error."""
        if response_body['error_code']:
            raise cls(
                response_body.get('error_info'),
                error_code=response_body.get('error_code'),
                error_info=response_body.get('error_info')
            )


class PhabricatorCommunicationException(PhabricatorAPIException):
    """Exception when communicating with Phabricator fails."""


def collect_accepted_reviewers(reviewers):
    """Return a generator of reviewers who have accepted.

    Args:
        reviewers: an iterable of reviewer data dicts.
    """
    for r in reviewers:
        if r['status'] == 'accepted':
            yield r
