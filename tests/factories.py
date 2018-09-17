# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Data factories for writing integration tests.
"""
import os

import requests

from tests.utils import trans_url


class TransResponseFactory:
    """Mock Transplant service responses."""

    def __init__(self, requestmocker):
        """
        Args:
            requestmocker: A requests Mocker object.
        """
        self.mock = requestmocker
        self.expected_auth_header = (
            requests.Request(
                "GET",
                "http://example.com",
                auth=(
                    os.getenv("TRANSPLANT_USERNAME"),
                    os.getenv("TRANSPLANT_PASSWORD"),
                ),
            )
            .prepare()
            .headers["Authorization"]
        )

    def mock_successful_response(self, request_id=1):
        """Add response to autoland endpoint."""
        self.mock.post(
            trans_url("autoland"),
            json={"request_id": request_id},
            status_code=200,
            request_headers={"Authorization": self.expected_auth_header},
        )

    def mock_http_error_response(self):
        """Add response to autoland endpoint."""
        self.mock.post(
            trans_url("autoland"),
            status_code=500,
            request_headers={"Authorization": self.expected_auth_header},
        )

    def mock_connection_error_response(self):
        """Add response to autoland endpoint."""
        self.mock.post(trans_url("autoland"), exc=requests.exceptions.ConnectTimeout)

    def mock_malformed_data_response(self):
        """Add response to autoland endpoint."""
        self.mock.post(
            trans_url("autoland"),
            text="no json for you",
            status_code=200,
            request_headers={"Authorization": self.expected_auth_header},
        )
