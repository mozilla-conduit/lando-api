# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import json
import logging
import re
from datetime import datetime, timezone
from json.decoder import JSONDecodeError

import requests
from enum import Enum, unique

from landoapi.systems import Subsystem

logger = logging.getLogger(__name__)

PHAB_API_KEY_RE = re.compile(r"^api-.{28}$")


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
            "0": cls.DRAFT if name == "Draft" else cls.NEEDS_REVIEW,
            "1": cls.NEEDS_REVISION,
            "2": cls.ACCEPTED,
            "3": cls.PUBLISHED,
            "4": cls.ABANDONED,
            "5": cls.CHANGES_PLANNED,
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
                "name": "Abandoned",
                "closed": True,
                "color.ansi": None,
                "deprecated_id": "4",
            },
            cls.ACCEPTED: {
                "name": "Accepted",
                "closed": False,
                "color.ansi": "green",
                "deprecated_id": "2",
            },
            cls.CHANGES_PLANNED: {
                "name": "Changes Planned",
                "closed": False,
                "color.ansi": "red",
                "deprecated_id": "5",
            },
            cls.PUBLISHED: {
                "name": "Closed",
                "closed": True,
                "color.ansi": "cyan",
                "deprecated_id": "3",
            },
            cls.NEEDS_REVIEW: {
                "name": "Needs Review",
                "closed": False,
                "color.ansi": "magenta",
                "deprecated_id": "0",
            },
            cls.NEEDS_REVISION: {
                "name": "Needs Revision",
                "closed": False,
                "color.ansi": "red",
                "deprecated_id": "1",
            },
            cls.DRAFT: {
                "name": "Draft",
                "closed": False,
                "color.ansi": None,
                "deprecated_id": "0",
            },
        }

    @property
    def deprecated_id(self):
        return self.meta().get(self, {}).get("deprecated_id", "")

    @property
    def output_name(self):
        return self.meta().get(self, {}).get("name", "")

    @property
    def closed(self):
        return self.meta().get(self, {}).get("closed", False)

    @property
    def color(self):
        return self.meta().get(self, {}).get("color.ansi")


@unique
class ReviewerStatus(Enum):
    """Enumeration of statuses a reviewer may have.

    These statuses were exhaustive at the time of creation, but
    Phabricator may add statuses in the future.
    """

    ADDED = "added"
    ACCEPTED = "accepted"
    BLOCKING = "blocking"
    REJECTED = "rejected"
    RESIGNED = "resigned"
    UNEXPECTED_STATUS = None

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
            cls.ADDED: {"voidable": False, "diff_specific": False},
            cls.ACCEPTED: {"voidable": True, "diff_specific": True},
            cls.BLOCKING: {"voidable": False, "diff_specific": False},
            cls.REJECTED: {"voidable": False, "diff_specific": True},
            cls.RESIGNED: {"voidable": False, "diff_specific": False},
            cls.UNEXPECTED_STATUS: {"voidable": False, "diff_specific": False},
        }

    @property
    def voidable(self):
        return self.meta().get(self, {}).get("voidable", False)

    @property
    def diff_specific(self):
        return self.meta().get(self, {}).get("diff_specific", False)


class PhabricatorClient:
    """A class to interface with Phabricator's Conduit API.

    All request methods in this class will throw a PhabricatorAPIException if
    Phabricator returns an error response. If there is an actual problem with
    the request to the server or decoding the JSON response, this class will
    bubble up the exception, as a PhabricatorAPIException caused by the
    underlying exception.
    """

    def __init__(self, url, api_token, *, session=None):
        self.api_url = url + "api/" if url[-1] == "/" else url + "/api/"
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
        if "__conduit__" not in kwargs:
            kwargs["__conduit__"] = {"token": self.api_token}

        data = {"output": "json", "params": json.dumps(kwargs)}

        extra_data = {
            "params": kwargs.copy(),
            "method": method,
            "api_url": self.api_url,
        }
        del extra_data["params"]["__conduit__"]  # Sanitize the api token.
        logger.debug("call to conduit", extra=extra_data)

        try:
            response = self.session.get(self.api_url + method, data=data).json()
        except requests.RequestException as exc:
            raise PhabricatorCommunicationException(
                "An error occurred when communicating with Phabricator"
            ) from exc
        except JSONDecodeError as exc:
            raise PhabricatorCommunicationException(
                "Phabricator response could not be decoded as JSON"
            ) from exc

        PhabricatorAPIException.raise_if_error(response)
        return response.get("result")

    @staticmethod
    def create_session():
        return requests.Session()

    @classmethod
    def single(cls, result, *subkeys, none_when_empty=False):
        """Return the first item of a phabricator result.

        Args:
            cls: class this method is called on.
            result: Data from the result key of a Phabricator API response.
            *subkeys: An iterable of subkeys which the list of items is
                present under. A common value would be ['data'] for standard
                search conduit methods.
            none_when_empty: `None` is returned if the result is empty if
                `none_when_empty` is True.

        Returns:
            The first result in the provided data. If `none_when_empty` is
            `True`, `None` will be returned if the result is empty.

        Raises:
            PhabricatorCommunicationException:
                If there is more or less than a single item.
        """
        if subkeys:
            result = cls.expect(result, *subkeys)

        if len(result) > 1 or (not result and not none_when_empty):
            raise PhabricatorCommunicationException(
                "Phabricator responded with unexpected data"
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
                "Phabricator responded with unexpected data"
            ) from exc

        return result

    @staticmethod
    def to_datetime(timestamp):
        """Return a datetime corresponding to a Phabricator timestamp.

        Args:
            timestamp: An integer, or integer string, timestamp from
            Phabricator which is the epoch in seconds UTC.

        Returns:
            A python datetime object for the same time.
        """
        return datetime.fromtimestamp(int(timestamp), timezone.utc)

    def verify_api_token(self):
        """ Verifies that the api token is valid.

        Returns False if Phabricator returns an error code when checking this
        api token. Returns True if no errors are found.
        """
        try:
            self.call_conduit("user.whoami")
        except PhabricatorAPIException:
            return False
        return True


class PhabricatorAPIException(Exception):
    """Exception to be raised when Phabricator returns an error response."""

    def __init__(self, *args, error_code=None, error_info=None):
        super().__init__(*args)
        self.error_code = error_code
        self.error_info = error_info

    @classmethod
    def raise_if_error(cls, response_body):
        """Raise a PhabricatorAPIException if response_body was an error."""
        if response_body["error_code"]:
            raise cls(
                response_body.get("error_info"),
                error_code=response_body.get("error_code"),
                error_info=response_body.get("error_info"),
            )


class PhabricatorCommunicationException(PhabricatorAPIException):
    """Exception when communicating with Phabricator fails."""


def result_list_to_phid_dict(result_list, *, phid_key="phid"):
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
                "Phabricator responded with unexpected data"
            )

        result[phid] = i

    return result


class PhabricatorSubsystem(Subsystem):
    name = "phabricator"

    def ready(self):
        unpriv_key = self.flask_app.config["PHABRICATOR_UNPRIVILEGED_API_KEY"]
        priv_key = self.flask_app.config["PHABRICATOR_ADMIN_API_KEY"]

        if unpriv_key and PHAB_API_KEY_RE.search(unpriv_key) is None:
            return (
                "PHABRICATOR_UNPRIVILEGED_API_KEY has the wrong format, "
                'it must begin with "api-" and be 32 characters long.'
            )

        if priv_key and PHAB_API_KEY_RE.search(priv_key) is None:
            return (
                "PHABRICATOR_ADMIN_API_KEY has the wrong format, "
                'it must begin with "api-" and be 32 characters long.'
            )

        return True

    def healthy(self):
        try:
            PhabricatorClient(
                self.flask_app.config["PHABRICATOR_URL"],
                self.flask_app.config["PHABRICATOR_UNPRIVILEGED_API_KEY"],
            ).call_conduit("conduit.ping")
        except PhabricatorAPIException as exc:
            return "PhabricatorAPIException: {!s}".format(exc)

        return True


phabricator_subsystem = PhabricatorSubsystem()
