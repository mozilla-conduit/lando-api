# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import json
import logging
from json.decoder import JSONDecodeError

import requests
from enum import Enum, unique

logger = logging.getLogger(__name__)


@unique
class RevisionStatus(Enum):
    """Enumeration of statuses a revision may have.

    These statuses were exhaustive at the time of creation, but
    Phabricator may add statuses in the future (such as the DRAFT
    status that was recently added).
    """
    ABANDONED = "abandoned"
    ACCEPTED = "accepted"
    CHANGES_PLANNED = "changes-planned"
    PUBLISHED = "published"
    NEEDS_REVIEW = "needs-review"
    NEEDS_REVISION = "needs-revision"
    DRAFT = "draft"
    UNEXPECTED_STATUS = None

    @classmethod
    def from_deprecated_id(cls, identifier, *, name=None):
        return {
            '0': cls.DRAFT if name == 'Draft' else cls.NEEDS_REVIEW,
            '1': cls.NEEDS_REVISION,
            '2': cls.ACCEPTED,
            '3': cls.PUBLISHED,
            '4': cls.ABANDONED,
            '5': cls.CHANGES_PLANNED,
        }.get(str(identifier), cls.UNEXPECTED_STATUS)

    @classmethod
    def from_status(cls, value):
        try:
            return cls(value)
        except ValueError:
            pass

        return cls.UNEXPECTED_STATUS

    @classmethod
    def meta(cls):
        return {
            cls.ABANDONED: {
                'name': 'Abandoned',
                'closed': True,
                'color.ansi': None,
                'deprecated_id': '4',
            },
            cls.ACCEPTED: {
                'name': 'Accepted',
                'closed': False,
                'color.ansi': 'green',
                'deprecated_id': '2',
            },
            cls.CHANGES_PLANNED: {
                'name': 'Changes Planned',
                'closed': False,
                'color.ansi': 'red',
                'deprecated_id': '5',
            },
            cls.PUBLISHED: {
                'name': 'Closed',
                'closed': True,
                'color.ansi': 'cyan',
                'deprecated_id': '3',
            },
            cls.NEEDS_REVIEW: {
                'name': 'Needs Review',
                'closed': False,
                'color.ansi': 'magenta',
                'deprecated_id': '0',
            },
            cls.NEEDS_REVISION: {
                'name': 'Needs Revision',
                'closed': False,
                'color.ansi': 'red',
                'deprecated_id': '1',
            },
            cls.DRAFT: {
                'name': 'Draft',
                'closed': False,
                'color.ansi': None,
                'deprecated_id': '0',
            },
        }

    @property
    def deprecated_id(self):
        return self.meta().get(self, {}).get('deprecated_id', '')

    @property
    def output_name(self):
        return self.meta().get(self, {}).get('name', '')

    @property
    def closed(self):
        return self.meta().get(self, {}).get('closed', False)

    @property
    def color(self):
        return self.meta().get(self, {}).get('color.ansi')


@unique
class ReviewerStatus(Enum):
    """Enumeration of statuses a reviewer may have.

    These statuses were exhaustive at the time of creation, but
    Phabricator may add statuses in the future.
    """
    ADDED = 'added'
    ACCEPTED = 'accepted'
    BLOCKING = 'blocking'
    REJECTED = 'rejected'
    RESIGNED = 'resigned'
    UNEXPECTED_STATUS = None

    @classmethod
    def from_status(cls, value):
        try:
            return cls(value)
        except ValueError:
            pass

        return cls.UNEXPECTED_STATUS


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


def collate_reviewer_attachments(reviewers, reviewers_extra):
    """Return collated reviewer data.

    Args:
        reviewers: Data from the 'reviewers' attachment of
            differential.revision.search.
        reviewers_extra: Data from the 'reviewers-extra'
            attachment of differential.revision.search.
    """
    phids = {}
    for reviewer in reviewers:
        data = {}
        for k in ('reviewerPHID', 'isBlocking', 'actorPHID'):
            data[k] = PhabricatorClient.expect(reviewer, k)

        data['status'] = ReviewerStatus.from_status(
            PhabricatorClient.expect(reviewer, 'status')
        )

        phids[data['reviewerPHID']] = data

    for reviewer in reviewers_extra:
        data = {}
        for k in ('reviewerPHID', 'diffPHID', 'voidedPHID'):
            data[k] = PhabricatorClient.expect(reviewer, k)

        data.update(phids.get(data['reviewerPHID'], {}))
        phids[data['reviewerPHID']] = data

    if len(phids) > min(len(reviewers), len(reviewers_extra)):
        raise PhabricatorCommunicationException(
            'Phabricator responded with unexpected data'
        )

    return phids


def result_list_to_phid_dict(result_list, *, phid_key='phid'):
    """Return a dictionary mapping phid to items from a result list.

    Args:
        result_list: A list of result items from phabricator which
            contain a phid in the key specified by `phid_key`
        phid_key: The key to access the phid from each item.
    """
    result = {}
    for i in result_list:
        phid = PhabricatorClient.expect(i, phid_key)
        if phid in result:
            raise PhabricatorCommunicationException(
                'Phabricator responded with unexpected data'
            )

        result[phid] = i

    return result
