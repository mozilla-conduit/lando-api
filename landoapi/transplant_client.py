# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import json
import logging
import os
from random import randint

import requests

from landoapi.sentry import sentry

logger = logging.getLogger(__name__)


class TransplantClient:
    """A class to interface with Transplant's API."""

    def __init__(self, transplant_url, username, password):
        self.transplant_url = transplant_url
        self.username = username
        self.password = password

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
        transplant_mock_option = os.getenv('LOCALDEV_MOCK_TRANSPLANT_SUBMIT')
        if os.getenv('ENV') == 'localdev':
            if transplant_mock_option == 'succeed':
                return randint(0, 10000000)
            elif transplant_mock_option == 'fail':
                return None

        # TODO: Although transplant accepts multiple patch urls to land
        # our use of a single revision in 'rev' would open up a number
        # of broken edge cases. Make sure we're not landing more than
        # one patch before this has been fixed.
        assert len(patch_urls) == 1

        try:
            # API structure from VCT/testing/autoland_mach_commands.py
            response = self._submit_landing_request(
                ldap_username=ldap_username,
                tree=tree,
                # This must be unique but consistent for the
                # landing. This is important as 'rev' is the
                # field used to prevent requesting the same
                # thing land when it is already queued. After
                # the landing is processed and has succeeded or
                # failed 'rev' may be reused for a new landing
                # request.
                rev='D{}'.format(revision_id),
                patch_urls=patch_urls,
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
                destination='upstream',
                # TODO: We'll need to start sending 'push_bookmark'
                # for the repoositories that require it (such as
                # version-control-tools). It's fine to ignore for
                # now though as mozilla-central landings do not
                # use it.
                pingback_url=pingback
            )
            return response.json()['request_id']
        except requests.HTTPError as e:
            sentry.captureException()
            logger.info(
                {
                    'message': 'Transplant Submission HTTPError: %s' % str(e),
                    'status_code': e.response.status_code,
                    'body': e.response.text,
                }, '_submit_landing_request.http_error'
            )
            raise TransplantError()
        except (requests.ConnectionError, requests.ConnectTimeout) as e:
            logger.info(
                {
                    'message': 'Transplant Connection Error: %s' % str(e),
                }, '_submit_landing_request.connection_error'
            )
            raise TransplantError()
        except requests.RequestException as e:
            sentry.captureException()
            logger.info(
                {
                    'message': 'Transplant Request Exception: %s' % str(e),
                }, '_submit_landing_request.request_exception'
            )
            raise TransplantError()
        except (json.JSONDecodeError, KeyError) as e:
            sentry.captureException()
            logger.info(
                {
                    'message': 'Transplant Data Parse Error: %s' % str(e),
                    'status_code': response.status_code,
                    'body': response.text,
                }, '_submit_landing_request.data_parse_error'
            )
            raise TransplantError()

    def _submit_landing_request(
        self, *, ldap_username, tree, rev, patch_urls, destination,
        pingback_url
    ):
        logger.info(
            {
                'message': 'Initiating transplant landing request.',
                'ldap_username': ldap_username,
                'tree': tree,
                'rev': rev,
                'patch_urls': patch_urls,
                'destination': destination,
                'pingback_url': pingback_url
            }, '_submit_landing_request.initiation'
        )

        submit_url = self.transplant_url + '/autoland'
        response = requests.post(
            url=submit_url,
            json={
                'ldap_username': ldap_username,
                'tree': tree,
                'rev': rev,
                'patch_urls': patch_urls,
                'destination': destination,
                'pingback_url': pingback_url
            },
            auth=(self.username, self.password),
            timeout=10
        )
        response.raise_for_status()

        logger.info(
            {
                'message': 'Successfully submitted landing request.',
                'status_code': response.status_code,
            }, '_submit_landing_request.completion'
        )
        return response


class TransplantError(Exception):
    pass
