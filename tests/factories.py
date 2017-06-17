# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Data factories for writing integration tests.
"""
from copy import deepcopy

from landoapi.utils import extract_rawdiff_id_from_uri
from tests.canned_responses.phabricator.repos import CANNED_REPO_MOZCENTRAL
from tests.canned_responses.phabricator.revisions import CANNED_EMPTY_RESULT, \
    CANNED_REVISION_1, CANNED_REVISION_1_DIFF, CANNED_REVISION_1_RAW_DIFF
from tests.canned_responses.phabricator.users import CANNED_USER_1
from tests.utils import phab_url, first_result_in_response, phid_for_response, \
    form_matcher


class PhabResponseFactory:
    """Mock Phabricator service responses with generated data."""

    def __init__(self, requestmocker):
        """
        Args:
            requestmocker: A requests_mock.mock() object.
        """
        self.mock = requestmocker
        self.mock_responses = {}
        self.install_404_responses()

    def install_404_responses(self):
        """Install catch-all 404 response handlers for API queries."""
        query_urls = ['differential.query', 'phid.query', 'user.query']
        for query_url in query_urls:
            self.mock.get(
                phab_url(query_url), status_code=404, json=CANNED_EMPTY_RESULT
            )

    def user(self):
        """Return a Phabricator User."""
        user = deepcopy(CANNED_USER_1)
        self.mock.get(phab_url('user.query'), status_code=200, json=user)
        return user

    def revision(self, **kwargs):
        """Return a Phabricator Revision."""
        result_json = deepcopy(CANNED_REVISION_1)
        revision = first_result_in_response(result_json)

        if 'id' in kwargs:
            # Convert 'D000' form to just '000'.
            str_id = kwargs['id']
            num_id = str_id[1:]
            revision['id'] = num_id
            revision['phid'] = "PHID-DREV-%s" % num_id

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

        # Revisions have at least one Diff.
        diff = self.diff()
        diffID = extract_rawdiff_id_from_uri(
            first_result_in_response(diff)['uri']
        )
        rawdiff = self.rawdiff(diffID=str(diffID))
        revision['activeDiffPHID'] = phid_for_response(diff)

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

        # Revisions can also be looked up by phid.query.
        self.phid(result_json)

        return result_json

    def diff(self):
        """Return a Revision Diff."""
        diff = deepcopy(CANNED_REVISION_1_DIFF)
        self.phid(diff)
        return diff

    def rawdiff(self, diffID='12345'):
        """Return raw diff text for a Revision Diff."""
        rawdiff = deepcopy(CANNED_REVISION_1_RAW_DIFF)
        self.mock.get(
            phab_url('differential.getrawdiff'),
            status_code=200,
            json=rawdiff,
            additional_matcher=form_matcher('diffID', diffID)
        )
        return rawdiff

    def repo(self):
        """Return a Phabricator Repo."""
        repo = deepcopy(CANNED_REPO_MOZCENTRAL)
        self.phid(repo)
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
