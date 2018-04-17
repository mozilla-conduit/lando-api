# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import pytest

from landoapi.models.patch import DiffNotInRevisionException, Patch


def test_patch_uploads_to_s3(app, phabdouble, s3, get_phab_client):
    diff = phabdouble.diff()
    revision = phabdouble.revision(diff=diff, repo=phabdouble.repo())

    phab = get_phab_client()
    revision_data = phab.call_conduit(
        'differential.query', ids=[revision['id']]
    )[0]
    patch = Patch(1, revision_data, diff['id'])
    expected_body = patch.build(phab)
    patch.upload(phab)

    assert patch.s3_url == 's3://landoapi.test.bucket/L1_D{}_{}.patch'.format(
        revision['id'], diff['id']
    )
    body = s3.Object(
        'landoapi.test.bucket',
        'L1_D{}_{}.patch'.format(revision['id'], diff['id'])
    ).get()['Body'].read().decode("utf-8")
    assert body == expected_body


def test_integrity_active_diff(phabdouble, get_phab_client):
    diff = phabdouble.diff()
    revision = phabdouble.revision(diff=diff)

    phab = get_phab_client()
    revision_data = phab.call_conduit(
        'differential.query', ids=[revision['id']]
    )[0]
    assert Patch.validate_diff_assignment(diff['id'], revision_data) is None


def test_integrity_inactive_diff(phabdouble, get_phab_client):
    inactive_diff = phabdouble.diff()
    revision = phabdouble.revision(diff=inactive_diff)
    phabdouble.diff(revision=revision)  # Make the first diff inactive.

    phab = get_phab_client()
    rdata = phab.call_conduit('differential.query', ids=[revision['id']])[0]
    assert Patch.validate_diff_assignment(inactive_diff['id'], rdata) is None


def test_failed_integrity(phabdouble, get_phab_client):
    diff = phabdouble.diff()
    revision = phabdouble.revision(diff=diff)

    bogus_diff_id = 111
    assert diff['id'] != bogus_diff_id

    phab = get_phab_client()
    revision_data = phab.call_conduit(
        'differential.query', ids=[revision['id']]
    )[0]
    with pytest.raises(DiffNotInRevisionException):
        Patch.validate_diff_assignment(bogus_diff_id, revision_data)
