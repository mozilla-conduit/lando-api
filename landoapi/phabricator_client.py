# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import logging
import os
import requests

from landoapi.utils import extract_rawdiff_id_from_uri

logger = logging.getLogger(__name__)


class PhabricatorClient:
    """ A class to interface with Phabricator's Conduit API.

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
        """ Gets a revision as defined by the Phabricator API.

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
            id_num = str(id).strip().replace('D', '')
            result = self._GET('/differential.query', {'ids[]': [id_num]})
        elif phid:
            result = self._GET('/differential.query', {'phids[]': [phid]})
        return result[0] if result else None

    def get_current_user(self):
        """ Gets the information of the user making this request.

        Returns:
            A hash containing the information of the user that owns the api key
            that was used to initialize this PhabricatorClient.
        """
        return self._GET('/user.whoami')

    def get_user(self, phid):
        """ Gets the information of the user based on their phid.

        Args:
            phid: The phid of the user to lookup.

        Returns:
            A hash containing the user information, or an None if the user
            could not be found.
        """
        result = self._GET('/user.query', {'phids[]': [phid]})
        return result[0] if result else None

    def get_diff(self, phid):
        """ Get basic information about a Diff based on the Diff phid.

        Args:
            phid: The phid of the Diff to lookup.

        Returns:
            A hash containing the Diff info, or None if the Diff isn't found.
        """
        result = self._GET('/phid.query', {'phids[]': [phid]})
        return result.get(phid) if result else None

    def get_rawdiff(self, diff_id):
        """ Get a raw diff text by raw diff ID.

        Args:
            diff_id: The integer ID of the raw diff.

        Returns:
            A string holding a Git Diff.
        """
        result = self._GET('/differential.getrawdiff', {'diffID': diff_id})
        return result if result else None

    def get_repo(self, phid):
        """ Get basic information about a repo based on its phid.

        Args:
            phid: The phid of the repo to lookup.

        Returns:
            A hash containing the repo info, or None if the repo isn't found.
        """
        result = self._GET('/phid.query', {'phids[]': [phid]})
        return result.get(phid) if result else None

    def get_latest_revision_diff_text(self, revision):
        """Return the raw diff text for the latest Diff on a Revision.

        Args:
            revision: A dictionary representation of phabricator revision data.

        Returns:
            A string holding the Git Diff of the Revision's latest Diff.
        """
        latest_diff_phid = revision['activeDiffPHID']
        diff = self.get_diff(latest_diff_phid)

        # We got a raw diff ID as part of a URI, such as
        # "https://secure.phabricator.com/differential/diff/43480/". We need to
        # parse out the raw diff ID so we can call differential.rawdiff.
        rawdiff_id = extract_rawdiff_id_from_uri(diff['uri'])
        return self.get_rawdiff(rawdiff_id)

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
        return self.get_repo(revision['repositoryPHID'])

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
    """ An exception class to handle errors from the Phabricator API """
    error_code = None
    error_info = None
