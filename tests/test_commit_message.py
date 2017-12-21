# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
from landoapi.commit_message import format_commit_message

COMMIT_MESSAGE = """
Bug 1 - A title. r=reviewer_one,r=reviewer_two

A summary.

Differential Revision: http://phabricator.test/D123
""".strip()

FIRST_LINE = 'Bug 1 - A title. r=reviewer_one,r=reviewer_two'


def test_commit_message_for_multiple_reviewers():
    reviewers = ['reviewer_one', 'reviewer_two']
    commit_message = format_commit_message(
        'A title.', 1, reviewers, 'A summary.', 'http://phabricator.test/D123'
    )
    assert commit_message == (FIRST_LINE, COMMIT_MESSAGE)
