# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging
import os
import requests

logger = logging.getLogger(__name__)


class PhabricatorClient:
    """A class to interface with Phabricator's Conduit API.

    All request methods in this class will throw a PhabricatorAPIException if
    Phabricator returns an error response. If there is an actual problem with
    the request to the server or decoding the JSON response, this class will
    bubble up the exception. These exceptions can be one of the request library
    exceptions or a JSONDecodeError.
    """

    def __init__(self, api_key):
        self.api_url = os.getenv('PHABRICATOR_URL') + '/api'
        if api_key:
            self.api_key = api_key
        else:
            self.api_key = os.getenv('PHABRICATOR_UNPRIVILEGED_API_KEY')

    def get_revision(self, id=None, phid=None):
        """Gets a revision as defined by the Phabricator API.

        Args:
            id: The id of the revision if known. This can be in the form of
                an integer or an integer prefixed with 'D', e.g. 'D12345'.
            phid: The phid of the revision to be used if the id isn't provided.

        Returns:
            A hash of the revision data just as it is returned by Phabricator.
            Returns None, if the revision doesn't exist, or if the api key that
            was used to create the PhabricatorClient doesn't have permission to
            view the revision.
        """
        result = None
        if id:
            result = self._GET('/differential.query', {'ids[]': [id]})
        elif phid:
            result = self._GET('/differential.query', {'phids[]': [phid]})
        return result[0] if result else None

    def get_rawdiff(self, diff_id):
        """Get the raw git diff text by diff id.

        Args:
            diff_id: The integer ID of the diff.

        Returns:
            A string holding a Git Diff.
        """
        result = self._GET('/differential.getrawdiff', {'diffID': diff_id})
        return result if result else None

    def get_diff(self, id=None, phid=None):
        """Get a diff by either integer id or phid.

        Args:
            id: The integer id of the diff.
            phid: The PHID of the diff. This will be used instead if provided.

        Returns
            A hash containing the full information about the diff exactly
            as returned by Phabricator's API.

            Note: Due to the nature of Phabricator's API, the diff request may
            be very large if the diff itself is large. This is because
            Phabricator includes the line by line changes in the JSON payload.
            Be aware of this, as it can lead to large and long requests.
        """
        diff_id = int(id) if id else None
        if phid:
            diff_id = self.diff_phid_to_id(phid)

        if not diff_id:
            return None

        result = self._GET('/differential.querydiffs', {'ids[]': [diff_id]})
        return result[str(diff_id)] if result else None

    def diff_phid_to_id(self, phid):
        """Convert Diff PHID to the Diff id.

        Send a request to Phabricator's `phid.query` API.
        Extract Diff id from URI provided in result.

        Args:
            phid: The PHID of the diff.

        Returns:
            Integer representing the Diff id in Phabricator
        """
        phid_query_result = self._GET('/phid.query', {'phids[]': [phid]})
        if phid_query_result:
            diff_uri = phid_query_result[phid]['uri']
            return self._extract_diff_id_from_uri(diff_uri)
        else:
            return None

    def get_reviewers(self, revision_id):
        """Gets reviewers of the revision.

        Requests `revision.search` to get the reviewers data. Then - with the
        received reviewerPHID keys - a new request is made to `user.search`
        to get the user info. A new dict indexed by phid is created with keys
        and values from both requests.

        Attributes:
            revision_id: integer, ID of the revision in Phabricator

        Returns:
            A dict indexed by phid of combined reviewers and users info.
        """
        # Get basic information about the reviewers
        # reviewerPHID, actorPHID, status, and isBlocking is provided
        result = self._GET(
            '/differential.revision.search', {
                'constraints[ids][]': [revision_id],
                'attachments[reviewers]': 1,
            }
        )

        has_reviewers = (
            result['data'] and
            result['data'][0]['attachments']['reviewers']['reviewers']
        )
        if not has_reviewers:
            return {}

        reviewers_data = (
            result['data'][0]['attachments']['reviewers']['reviewers']
        )

        # Get user info of all revision reviewers
        reviewers_phids = [r['reviewerPHID'] for r in reviewers_data]
        result = self._GET(
            '/user.search', {'constraints[phids][]': reviewers_phids}
        )
        reviewers_info = result['data']

        if len(reviewers_data) != len(reviewers_info):
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
        for data in reviewers_data, reviewers_info:
            for reviewer in data:
                phid = reviewer.get('reviewerPHID') or reviewer.get('phid')
                reviewers_dict[phid] = reviewers_dict.get(phid, {})
                reviewers_dict[phid].update(reviewer)

        return reviewers_dict

    def get_current_user(self):
        """Gets the information of the user making this request.

        Returns:
            A hash containing the information of the user that owns the api key
            that was used to initialize this PhabricatorClient.
        """
        return self._GET('/user.whoami')

    def get_user(self, phid):
        """Gets the information of the user based on their phid.

        Args:
            phid: The phid of the user to lookup.

        Returns:
            A hash containing the user information, or an None if the user
            could not be found.
        """
        result = self._GET('/user.query', {'phids[]': [phid]})
        return result[0] if result else None

    def get_repo_info_by_phid(self, phid):
        """Get full information about a repo based on its phid.

        Args:
            phid: The phid of the repo to lookup.

        Returns:
            A dict containing the repo info, or None if the repo isn't found.
        """
        result = self._GET(
            '/diffusion.repository.search', {'constraints[phids][]': [phid]}
        )
        return result['data'][0] if result['data'] else None

    def get_repo(self, phid):
        """Get basic information about a repo based on its phid.

        Args:
            phid: The phid of the repo to lookup.

        Returns:
            A hash containing the repo info, or None if the repo isn't found.
        """
        result = self._GET('/phid.query', {'phids[]': [phid]})
        return result.get(phid) if result else None

    def get_revision_author(self, revision):
        """Return the Phabricator User data for a revision's author.

        Args:
            revision: A dictionary of Phabricator Revision data.

        Returns:
            A dictionary of Phabricator User data.
        """
        return self.get_user(revision['authorPHID'])

    def get_revision_repo(self, revision):
        """Return the Phabricator Repository data for a revision's author.

        Args:
            revision: A dictionary of Phabricator Revision data.

        Returns:
            A dictionary of Phabricator Repository data.
        """
        return self.get_repo_info_by_phid(revision['repositoryPHID'])

    def check_connection(self):
        """Test the Phabricator API connection with conduit.ping.

        Will return success iff the response has a HTTP status code of 200, the
        JSON response is a well-formed Phabricator API response, and if there
        is no connection error (like a hostname lookup error or timeout).

        Raises a PhabricatorAPIException on error.
        """
        try:
            self._GET('/conduit.ping')
        except (requests.ConnectionError, requests.Timeout) as exc:
            logging.debug("error calling 'conduit.ping': %s", exc)
            raise PhabricatorAPIException from exc

    def verify_api_key(self):
        """ Verifies that the api key this instance was created with is valid.

        Returns False if Phabricator returns an error code when checking this
        api key. Returns True if no errors are found.
        """
        try:
            self.get_current_user()
        except PhabricatorAPIException:
            return False
        return True

    def _extract_diff_id_from_uri(self, uri):
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

    def _request(self, url, data=None, params=None, method='GET'):
        data = data if data else {}
        data['api.token'] = self.api_key
        response = requests.request(
            method=method,
            url=self.api_url + url,
            params=params,
            data=data,
            timeout=10
        ).json()

        if response['error_code']:
            exp = PhabricatorAPIException(response.get('error_info'))
            exp.error_code = response.get('error_code')
            exp.error_info = response.get('error_info')
            raise exp

        return response.get('result')

    def _GET(self, url, data=None, params=None):
        return self._request(url, data, params, 'GET')

    def _POST(self, url, data=None, params=None):
        return self._request(url, data, params, 'POST')


class PhabricatorAPIException(Exception):
    """An exception class to handle errors from the Phabricator API."""
    error_code = None
    error_info = None
