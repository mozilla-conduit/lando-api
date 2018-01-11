# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Testing our test factories."""

from tests.canned_responses.phabricator.errors import CANNED_EMPTY_RESULT


def test_adding_diffs(phabfactory):
    # diffs is a one-item list with an active diff id
    revision = phabfactory.revision()
    assert revision['result'][0]['diffs'] == ['1']

    diff = phabfactory.diff(id=123)
    revision = phabfactory.revision(active_diff=diff)
    assert revision['result'][0]['diffs'] == ['123']

    # diffs is a list with active diff id and added a specific list
    revision = phabfactory.revision(diffs=['123'])
    assert revision['result'][0]['diffs'] == ['1', '123']

    revision = phabfactory.revision(diffs=['345', '123'])
    assert revision['result'][0]['diffs'] == ['1', '345', '123']


def test_revision_not_found(phabfactory):
    result = phabfactory.revision(not_found=True)
    assert result == CANNED_EMPTY_RESULT
