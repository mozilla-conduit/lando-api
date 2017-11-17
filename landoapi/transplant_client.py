# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging
import os
import requests

logger = logging.getLogger(__name__)


class TransplantClient:
    """A class to interface with Transplant's API."""

    def __init__(self):
        self.api_url = os.getenv('TRANSPLANT_URL')

    def land(self, ldap_username, patch_urls, tree, pingback):
        """Sends a POST request to Transplant API to land a patch

        Args:
            ldap_username: user landing the patch
            patch_urls: list of patch URLs in S3
                       (ex. ['s3://{bucket_name}/L15_D123_1.patch'])
            tree: tree name as per treestatus
            pingback: The URL of the endpoint to POST landing updates

        Returns:
            Integer request_id received from Transplant API.
        """
        # API structure from VCT/testing/autoland_mach_commands.py
        result = self._POST(
            '/autoland', {
                'ldap_username': ldap_username,
                'tree': tree,
                'rev': 'rev',
                'patch_urls': patch_urls,
                'destination': 'destination',
                'push_bookmark': 'push_bookmark',
                'commit_descriptions': 'commit_descriptions',
                'pingback_url': pingback
            }
        )

        if result:
            logger.info(
                {
                    'service': 'transplant',
                    'username': ldap_username,
                    'pingback_url': pingback,
                    'tree': tree,
                    'request_id': result.get('request_id'),
                    'msg': 'patch sent to transplant service',
                }, 'transplant.success'
            )
            return result.get('request_id')

        # Transplant API responded with no data, indicating an error of
        # some sort.
        logger.info(
            {
                'service': 'transplant',
                'username': ldap_username,
                'pingback_url': pingback,
                'msg': ('received an empty response from the transplant '
                        'service'),
            }, 'transplant.failure'
        )   # yapf: disable
        return None

    def _request(self, url, data=None, params=None, method='GET'):
        data = data if data else {}

        response = requests.request(
            method=method,
            url=self.api_url + url,
            params=params,
            data=data,
            timeout=10
        )

        status_code = response.status_code
        response = response.json()

        logger.info(
            {
                'code': status_code,
                'method': method,
                'service': 'transplant',
                'url': self.api_url,
                'path': url,
            }, 'request.summary'
        )

        if 'error' in response:
            exp = TransplantAPIException()
            exp.error_code = status_code
            exp.error_info = response.get('error')
            raise exp

        return response

    def _GET(self, url, data=None, params=None):
        return self._request(url, data, params, 'GET')

    def _POST(self, url, data=None, params=None):
        return self._request(url, data, params, 'POST')


class TransplantAPIException(Exception):
    """An exception class to handle errors from the Transplant API."""
    error_code = None
    error_info = None
