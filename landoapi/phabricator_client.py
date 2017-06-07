# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os
import requests


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

    def get_repo(self, phid):
        """ Get basic information about a repo based on its phid. 
        
        Args:
            phid: The phid of the repo to lookup.
            
        Returns:
            A hash containing the repo info, or None if the repo isn't found.
        """
        result = self._GET('/phid.query', {'phids[]': [phid]})
        return result.get(phid) if result else None

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
