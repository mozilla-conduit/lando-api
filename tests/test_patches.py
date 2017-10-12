# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import pytest

from landoapi.models.patch import Patch
from landoapi.phabricator_client import PhabricatorClient


def test_patch_uploads_to_s3(app, phabfactory, s3):
    phabfactory.user()
    phabfactory.revision()
    phabfactory.rawdiff(1)

    phab = PhabricatorClient(None)
    revision = phab.get_revision(1)
    patch = Patch(1, revision, 1)
    expected_body = patch.build(phab)
    patch.upload(phab)

    assert patch.s3_url == 's3://landoapi.test.bucket/L1_D1_1.patch'
    body = s3.Object('landoapi.test.bucket',
                     'L1_D1_1.patch').get()['Body'].read().decode("utf-8")
    assert body == expected_body
