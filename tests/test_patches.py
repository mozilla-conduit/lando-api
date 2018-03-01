# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import pytest

from landoapi.models.patch import DiffNotInRevisionException, Patch


def test_patch_uploads_to_s3(app, phabfactory, s3, get_phab_client):
    phabfactory.revision()
    phabfactory.rawdiff(1)

    phab = get_phab_client()
    revision = phab.get_revision(1)
    patch = Patch(1, revision, 1)
    expected_body = patch.build(phab)
    patch.upload(phab)

    assert patch.s3_url == 's3://landoapi.test.bucket/L1_D1_1.patch'
    body = s3.Object('landoapi.test.bucket',
                     'L1_D1_1.patch').get()['Body'].read().decode("utf-8")
    assert body == expected_body


def test_integrity_active_diff(phabfactory, get_phab_client):
    phabfactory.revision()
    phab = get_phab_client()
    revision = phab.get_revision(1)
    assert Patch.validate_diff_assignment(1, revision) is None


def test_integrity_inactive_diff(phabfactory, get_phab_client):
    phabfactory.revision(diffs=['111'])
    phab = get_phab_client()
    revision = phab.get_revision(1)
    assert Patch.validate_diff_assignment(111, revision) is None


def test_failed_integrity(phabfactory, get_phab_client):
    phabfactory.revision()
    phab = get_phab_client()
    revision = phab.get_revision(1)
    with pytest.raises(DiffNotInRevisionException):
        Patch.validate_diff_assignment(111, revision)
