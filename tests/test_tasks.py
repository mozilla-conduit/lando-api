# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import pytest

from landoapi.phabricator import (
    PhabricatorAPIException,
    PhabricatorCommunicationException,
)
from landoapi.tasks import admin_remove_phab_project


def test_admin_remove_phab_project_succeeds(phabdouble, app):
    p = phabdouble.project("test-project")
    r = phabdouble.revision(projects=[p])
    admin_remove_phab_project(r["phid"], p["phid"])


def test_admin_remove_phab_project_throws_exception_for_missing_revision(
    phabdouble, app
):
    p = phabdouble.project("test-project")
    with pytest.raises(PhabricatorAPIException) as excinfo:
        admin_remove_phab_project("PHID-DREV-NOTAREALPHID", p["phid"])

    # Make sure that we haven't thrown a PhabricatorCommunicationException
    # which would be a transient error. The exception should be a normal
    # PhabricatorAPIException.
    assert isinstance(excinfo.value, PhabricatorAPIException)
    assert not isinstance(excinfo.value, PhabricatorCommunicationException)
    assert "does not identify a valid object" in excinfo.value.error_info
