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

    def land(self, revision_id, ldap_username, patch_urls, tree, pingback):
        """Sends a POST request to Transplant API to land a patch

        Args:
            revision_id: integer id of the revision being landed
            ldap_username: user landing the patch
            patch_urls: list of patch URLs in S3, currently restricted to 1
                entry. (ex. ['s3://{bucket_name}/L15_D123_1.patch'])
            tree: tree name as per treestatus
            pingback: The URL of the endpoint to POST landing updates

        Returns:
            Integer request_id received from Transplant API.
        """
        # TODO: Although transplant accepts multiple patch urls to land
        # our use of a single revision in 'rev' would open up a number
        # of broken edge cases. Make sure we're not landing more than
        # one patch before this has been fixed.
        assert len(patch_urls) == 1

        # API structure from VCT/testing/autoland_mach_commands.py
        result = self._POST(
            '/autoland',
            {
                'ldap_username': ldap_username,
                'tree': tree,
                # This must be unique but consistent for the
                # landing. This is important as 'rev' is the
                # field used to prevent requesting the same
                # thing land when it is already queued. After
                # the landing is processed and has succeeded or
                # failed 'rev' may be reused for a new landing
                # request.
                'rev': 'D{}'.format(revision_id),
                'patch_urls': patch_urls,
                # TODO: The main purpose of destination is to
                # support landing on try as well as the main
                # repository. Until we add try support we can
                # get away with just sending 'upstream' for
                # all requests. This is actually different
                # than mozreview which sends things like
                # 'gecko' or 'version-control-tools' here
                # but it should work since the 'upstream'
                # path is present in all of transplants
                # repositories ('upstream' is hardcoded as
                # the path that is pulled from).
                'destination': 'upstream',
                # TODO: We'll need to start sending 'push_bookmark'
                # for the repoositories that require it (such as
                # version-control-tools). It's fine to ignore for
                # now though as mozilla-central landings do not
                # use it.
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
