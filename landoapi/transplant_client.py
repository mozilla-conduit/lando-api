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

    def land(
        self, revision_id, ldap_username, patch_urls, tree, pingback, push_bookmark=""
    ):
        """Sends a POST request to Transplant API to land a patch

        Args:
            revision_id: integer id of the revision being landed
            ldap_username: user landing the patch
            patch_urls: list of patch URLs in S3, currently restricted to 1
                entry. (ex. ['s3://{bucket_name}/L15_D123_1.patch'])
            tree: tree name as per https://treestatus.mozilla-releng.net/trees
            pingback: The URL of the endpoint to POST landing updates

        Returns:
            Integer request_id received from Transplant API.
        """
        transplant_mock_option = os.getenv("LOCALDEV_MOCK_TRANSPLANT_SUBMIT")
        if os.getenv("ENV") == "localdev":
            if transplant_mock_option == "succeed":
                return randint(0, 10000000)
            elif transplant_mock_option == "fail":
                return None

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
                rev="D{}".format(revision_id),
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
                destination="upstream",
                pingback_url=pingback,
                # push_bookmark should be sent to transplant as an empty
                # string '' to indicate the repository does not use a
                # push_bookmark. Sending null (None) will result in
                # incorrect behaviour. Protect against this by
                # making sure any falsey value is converted to ''.
                push_bookmark=push_bookmark or "",
            )
            return response.json()["request_id"]
        except requests.HTTPError as e:
            sentry.captureException()
            logger.warning(
                "Transplant Submission HTTPError",
                extra={"status_code": e.response.status_code, "body": e.response.text},
                exc_info=e,
            )
            raise TransplantError()
        except (requests.ConnectionError, requests.ConnectTimeout) as e:
            logger.warning("Transplant Connection Error", exc_info=e)
            raise TransplantError()
        except requests.RequestException as e:
            sentry.captureException()
            logger.warning("Transplant Request Exception", exc_info=e)
            raise TransplantError()
        except (json.JSONDecodeError, KeyError) as e:
            sentry.captureException()
            logger.warning(
                "Transplant Data Parse Error",
                extra={"status_code": response.status_code, "body": response.text},
                exc_info=e,
            )
            raise TransplantError()

    def _submit_landing_request(
        self,
        *,
        ldap_username,
        tree,
        rev,
        patch_urls,
        destination,
        pingback_url,
        push_bookmark
    ):
        logger.info(
            "Initiating transplant landing request",
            extra={
                "ldap_username": ldap_username,
                "tree": tree,
                "rev": rev,
                "patch_urls": patch_urls,
                "destination": destination,
                "push_bookmark": push_bookmark,
                "pingback_url": pingback_url,
            },
        )

        submit_url = self.transplant_url + "/autoland"
        response = requests.post(
            url=submit_url,
            json={
                "ldap_username": ldap_username,
                "tree": tree,
                "rev": rev,
                "patch_urls": patch_urls,
                "destination": destination,
                "push_bookmark": push_bookmark,
                "pingback_url": pingback_url,
            },
            auth=(self.username, self.password),
            timeout=10,
        )
        response.raise_for_status()

        logger.info(
            "Successfully submitted landing request",
            extra={"status_code": response.status_code},
        )
        return response

    def ping(self):
        """Make a GET request to Transplant to check connectivity."""
        return requests.get(url=self.transplant_url)


class TransplantError(Exception):
    pass
