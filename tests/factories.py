# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Data factories for writing integration tests.
"""
import os
from copy import deepcopy

from tests.canned_responses.phabricator.diffs import CANNED_DIFF_1
from tests.canned_responses.phabricator.errors import CANNED_EMPTY_RESULT
from tests.canned_responses.phabricator.phid_queries import (
    CANNED_DIFF_PHID_QUERY_RESULT_1
)
from tests.canned_responses.phabricator.raw_diffs import CANNED_RAW_DIFF_1
from tests.canned_responses.phabricator.repos import (
    CANNED_REPO_MOZCENTRAL, CANNED_REPO_SEARCH_MOZCENTRAL
)
from tests.canned_responses.phabricator.revisions import (
    CANNED_EMPTY_REVIEWERS_ATT_RESPONSE, CANNED_REVISION_1
)
from tests.canned_responses.phabricator.users import (
    CANNED_EMPTY_USER_SEARCH_RESPONSE, CANNED_USER_1, CANNED_USER_SEARCH_1
)
from tests.utils import (
    first_result_in_response, form_matcher, phab_url, phid_for_response,
    trans_url
)


class PhabResponseFactory:
    """Mock Phabricator service responses with generated data."""

    def __init__(self, requestmocker):
        """
        Args:
            requestmocker: A requests_mock.mock() object.
        """
        self.mock = requestmocker
        self.mock_responses = {}
        self._install_404_responses()

    def user(self, username=None, phid=None):
        """Return a Phabricator User."""
        response = deepcopy(CANNED_USER_1)
        user = first_result_in_response(response)
        if username:
            user['userName'] = username
            user['realName'] = "{} Name".format(username)
            user['uri'] = 'http://phabricator.test/p/{}'.format(username)
        if phid:
            user['phid'] = phid

        self.mock.get(
            phab_url('user.query'),
            status_code=200,
            additional_matcher=form_matcher('phids[]', user['phid']),
            json=response
        )
        return response

    def revision(self, **kwargs):
        """Create a Phabricator Revision along with stub API endpoints.

        Use the kwargs to customize the revision being created. If they are not
        provided, a default template will be used instead.

        kwargs:
            id: String ID to give the generated revision. E.g. 'D2233'.
            author_phid: PHID of the author user to use, instead of making a
                default user.
            template: A template revision to base this on from.
            depends_on: Response data for a Revision this revision should
                depend on.
            active_diff: Response data for a Diff that should be this
                Revision's "active diff" (usually this Revision's most recently
                uploaded patch). If you manually set an active diff, it must
                have been made with this factory.
            reviewers: List of dicts with reviewer info. A default reviewer
                will be created if not provided. No reviewer is added
                to the revision if equals to empty list. Keys:
                - username: (required) username of the reviewer.
                - id: ID of the reviewer, optional, but suggested if more than
                    one reviewer is created.
                - isBlocking: (boolean) is the reviewer blocking
                - phid: PHID of the reviewer.
                - status: Status in revision (added, accepted, blocking,
                    rejected, resigned).

        Returns:
            The full JSON response dict for the generated Revision.
        """
        if 'template' in kwargs:
            result_json = deepcopy(kwargs['template'])
        else:
            result_json = deepcopy(CANNED_REVISION_1)
        revision = first_result_in_response(result_json)

        if 'id' in kwargs:
            # Convert 'D000' form to just '000'.
            str_id = kwargs['id']
            num_id = str_id[1:]
            revision['id'] = num_id
            revision['phid'] = "PHID-DREV-%s" % num_id

        if 'author_phid' in kwargs:
            revision['authorPHID'] = kwargs['author_phid']
        else:
            self.user()

        if 'depends_on' in kwargs:
            parent_revision_response_data = kwargs['depends_on']
            if parent_revision_response_data:
                # This Revisions depends on another Revision.
                new_value = [phid_for_response(parent_revision_response_data)]
            else:
                # The user passed in None or an empty list, saying "this
                # revision has no parent revisions."
                new_value = []
            revision['auxiliary']['phabricator:depends-on'] = new_value

        default_reviewer = {
            'username': 'review_bot',
            'phid': 'PHID-USER-review_bot'
        }
        revision['reviewers'] = self._reviewers(
            revision['id'], kwargs.get('reviewers', [default_reviewer])
        )

        # Revisions have at least one Diff.
        if 'active_diff' in kwargs:
            diff = kwargs['active_diff']
        else:
            diff = self.diff()

        revision['activeDiffPHID'] = 'PHID-DIFF-{}'.format(
            first_result_in_response(diff)['id']
        )

        # Revisions may have a Repo.
        repo = self.repo()
        revision['repositoryPHID'] = phid_for_response(repo)

        def match_revision(request):
            # Revisions can be looked up by PHID or ID.
            found_phid = form_matcher('phids[]', revision['phid'])(request)
            found_id = form_matcher('ids[]', revision['id'])(request)
            return found_phid or found_id

        self.mock.get(
            phab_url('differential.query'),
            status_code=200,
            json=result_json,
            additional_matcher=match_revision
        )
        return result_json

    def _reviewers(self, revision_id, reviewers):
        """Add mocks for reviewers.

        Mocks a differential.revision.search api response containing the
        reviewers attachment.
        Mocks user.search api to get the reviewers in one request.

        Attributes:
            revision_id: an id of the revision
            reviewers: a list of dict about reviewer.

        Returns:
            dict in the form of {phid: phid} to append to revision['reviewers']
        """
        revision_response = deepcopy(CANNED_EMPTY_REVIEWERS_ATT_RESPONSE)
        revision_atts = revision_response['result']['data'][0]['attachments']
        users_response = deepcopy(CANNED_EMPTY_USER_SEARCH_RESPONSE)
        revision_reviewers = {}

        for reviewer in reviewers:
            phid = reviewer.get(
                'phid', 'PHID-USER-Reviewer-{}'.format(reviewer['username'])
            )
            # Update differential.revision.search response
            revision_atts['reviewers']['reviewers'].append(
                {
                    'reviewerPHID': phid,
                    'status': reviewer.get('status', 'added'),
                    'isBlocking': reviewer.get('isBlocking', False),
                    'actorPHID': phid
                }
            )
            # Update user.search response
            user = deepcopy(CANNED_USER_SEARCH_1['result']['data'][0])
            user['id'] = reviewer.get('id', user['id'])
            user['phid'] = phid
            user['fields']['username'] = reviewer['username']
            user['fields']['realName'] = "{} Name".format(reviewer['username'])
            users_response['result']['data'].append(user)

            # Update revision.query response
            revision_reviewers[phid] = phid

        # Mock differential.revision.search
        def revision_matcher(request):
            """Match revision search with reviewers attachment."""
            find_revision = form_matcher('constraints[ids][]',
                                         revision_id)(request)
            wants_reviewers = form_matcher('attachments[reviewers]',
                                           '1')(request)
            return find_revision and wants_reviewers

        self.mock.get(
            phab_url('differential.revision.search'),
            status_code=200,
            json=revision_response,
            additional_matcher=revision_matcher
        )

        # We don't search for user info if no reviewers found
        if not reviewers:
            return {}

        # Mock user.search
        def users_matcher(request):
            """Match search user requests with all phids."""
            matches = [
                form_matcher('constraints[phids][]', phid)(request)
                for phid in revision_reviewers
            ]
            return all(matches)

        self.mock.get(
            phab_url('user.search'),
            status_code=200,
            json=users_response,
            additional_matcher=users_matcher
        )

        return revision_reviewers

    def diff(self, **kwargs):
        """Create a Phabricator Diff along with stub API endpoints.

        Use the kwargs to customize the diff being created. If they are not
        provided, a default template will be used instead.

        kwargs:
            id: The integer diff id to be used. The diff's phid will be
                based on this.
            patch: The patch file to be used when generating the diff's
                rawdiff. All diffs must have a corresponding rawdiff.

        Returns:
            The full JSON response dict for the generated Diff.
        """
        diff = deepcopy(CANNED_DIFF_1)
        if 'id' in kwargs:
            diff_id = kwargs['id']
        else:
            diff_id = first_result_in_response(diff)['id']
        diff = self._replace_key(diff, 'id', diff_id)

        # Create the mock PHID endpoint.
        diff_phid = 'PHID-DIFF-{diff_id}'.format(diff_id=diff_id)
        diff_phid_resp = self._replace_key(
            CANNED_DIFF_PHID_QUERY_RESULT_1, 'phid', diff_phid
        )
        diff_phid_resp['result'][diff_phid][
            'uri'
        ] = "{url}/differential/diff/{diff_id}/".format(
            url=os.getenv('PHABRICATOR_URL'), diff_id=diff_id
        )
        name = "Diff {diff_id}".format(diff_id=diff_id)
        diff_phid_resp['result'][diff_phid]['name'] = name
        diff_phid_resp['result'][diff_phid]['full_name'] = name
        self.phid(diff_phid_resp)

        # Create the mock raw diff endpoint.
        if 'patch' in kwargs:
            self.rawdiff(diff_id=diff_id, patch=kwargs['patch'])
        else:
            self.rawdiff(diff_id=diff_id)

        # Create the mock diff endpoint.
        self.mock.get(
            phab_url('differential.querydiffs'),
            status_code=200,
            json=diff,
            additional_matcher=form_matcher('ids[]', str(diff_id))
        )

        return diff

    def rawdiff(self, diff_id='1', patch=None):
        """Return raw diff text for a Revision Diff."""
        rawdiff = deepcopy(CANNED_RAW_DIFF_1)
        if patch is not None:
            rawdiff['result'] = patch

        self.mock.get(
            phab_url('differential.getrawdiff'),
            status_code=200,
            json=rawdiff,
            additional_matcher=form_matcher('diffID', str(diff_id))
        )
        return rawdiff

    def repo(self):
        """Return a Phabricator Repo."""
        # Prepare phid.query response
        repo = deepcopy(CANNED_REPO_MOZCENTRAL)
        phid = self.phid(repo)
        # Prepare diffusion.repository.search response
        repo_info = deepcopy(CANNED_REPO_SEARCH_MOZCENTRAL)
        self.mock.get(
            phab_url('diffusion.repository.search'),
            status_code=200,
            json=repo_info,
            additional_matcher=form_matcher('constraints[phids][]', phid)
        )
        return repo

    def phid(self, response_data):
        """Add a phid.query matcher for the given Phabricator response object.
        """
        phid = phid_for_response(response_data)
        self.mock.get(
            phab_url('phid.query'),
            status_code=200,
            additional_matcher=form_matcher('phids[]', phid),
            json=response_data
        )
        return phid

    def _install_404_responses(self):
        """Install catch-all 404 response handlers for API queries."""
        query_urls = [
            'differential.query', 'phid.query', 'user.query',
            'differential.getrawdiff', 'differential.querydiffs'
        ]
        for query_url in query_urls:
            self.mock.get(
                phab_url(query_url), status_code=404, json=CANNED_EMPTY_RESULT
            )

    @staticmethod
    def _replace_key(old_response, key_name, new_value):
        """ Helper method to update the key name in a phabricator response dict.

        Phabricator's API decides to return a hash of keyed entries instead
        of an array of hashes which contain the key for each entry. This means
        that the key is located in two places and must be updated twice when
        creating dummy data, as shown below (phid is the key_name below).

        Before: {'result': {'EXP-PHID-1': {'phid': 'EXP-PHID-1', ...}}, ...}
        _replace_key(Before, 'phid', 'NEW-PHID-X')
        After:  {'result': {'NEW-PHID-X': {'phid': 'NEW-PHID-X', ...}}, ...}

        Args:
            old_response: The dict containing the phabricator query response.
            key_name: The name of the key which should be updated.
            new_value: The new key value that should be set.

        Returns:
            A new deep-copied dict with the correct data.
        """
        old_value = list(old_response['result'].keys())[0]
        response = deepcopy(old_response)
        if new_value != old_value and response['result']:
            response['result'][old_value][key_name] = new_value
            response['result'][str(new_value)] = response['result'][old_value]
            del response['result'][old_value]
        return response


class TransResponseFactory:
    """Mock Transplant service responses."""

    def __init__(self, requestmocker):
        """
        Args:
            requestmocker: A requests Mocker object.
        """
        self.mock = requestmocker

    def create_autoland_response(self, request_id=1):
        """Add response to autoland endpoint."""
        self.mock.post(
            trans_url('autoland'),
            json={'request_id': request_id},
            status_code=200
        )
