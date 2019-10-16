# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import pytest

from landoapi.commit_message import format_commit_message, split_title_and_summary

COMMIT_MESSAGE = """
Bug 1 - A title. r=reviewer_one,reviewer_two

A summary.

Differential Revision: http://phabricator.test/D123
""".strip()

FIRST_LINE = "Bug 1 - A title. r=reviewer_one,reviewer_two"


def test_commit_message_for_multiple_reviewers():
    reviewers = ["reviewer_one", "reviewer_two"]
    commit_message = format_commit_message(
        "A title.", 1, reviewers, "A summary.", "http://phabricator.test/D123"
    )
    assert commit_message == (FIRST_LINE, COMMIT_MESSAGE)


def test_commit_message_reviewers_replaced():
    reviewers = ["reviewer_one", "reviewer_two"]
    commit_message = format_commit_message(
        "A title. r=not_reviewer r?bogus",
        1,
        reviewers,
        "A summary.",
        "http://phabricator.test/D123",
    )
    assert commit_message == (FIRST_LINE, COMMIT_MESSAGE)


def test_commit_message_blank_summary():
    first_line, message = format_commit_message(
        "A title.", 1, ["reviewer"], "", "http://phabricator.test/D123"
    )

    # A blank summary should result in only a single blank line between
    # the title and other fields, not several.
    assert len(message.splitlines()) == 3


@pytest.mark.parametrize(
    "reviewer_text",
    [
        "r?blocker! r?didnt_review",
        "r?blocker!,didnt_review",
        "r?blocker! r?didnt_review!",
        "r?blocker!,didnt_review!",
        "r?didnt_review r?blocker!",
        "r?didnt_review,blocker!",
        "r?didnt_review! r?blocker",
        "r?didnt_review!,blocker",
        "r=blocker! r=didnt_review",
        "r=blocker!,didnt_review",
        "r=blocker! r=didnt_review!",
        "r=blocker!,didnt_review!",
        "r=didnt_review r=blocker!",
        "r=didnt_review,blocker!",
        "r=didnt_review! r=blocker",
        "r=didnt_review!,blocker",
    ],
)
def test_commit_message_blocking_reviewers_requested(reviewer_text):
    commit_message = format_commit_message(
        "A title! {}".format(reviewer_text),
        1,
        ["blocker"],
        "",
        "http://phabricator.test/D123",
    )

    assert commit_message[0] == "Bug 1 - A title! r=blocker"


@pytest.mark.parametrize(
    "reviewer_text",
    [
        "r?#group1",
        "r?#group1, #group2",
        "r?reviewer_one,#group1",
        "r?#group1 r?reviewer_two",
        "r?#group1! r?group2",
        "r?#group1 r?group2!",
        "r?#group1! r?group2!",
        "r?#group1, reviewer_two!",
    ],
)
def test_group_reviewers_replaced(reviewer_text):
    reviewers = ["reviewer_one", "reviewer_two"]
    commit_message = format_commit_message(
        "A title. {}".format(reviewer_text),
        1,
        reviewers,
        "A summary.",
        "http://phabricator.test/D123",
    )
    assert commit_message == (FIRST_LINE, COMMIT_MESSAGE)


@pytest.mark.parametrize(
    "message, title, summary",
    [
        ("title only", "title only", ""),
        ("title only\n\n", "title only", ""),
        ("title\n\nand summary", "title", "and summary"),
        ("title\n\nmultiline\n\nsummary", "title", "multiline\n\nsummary"),
    ],
)
def test_split_title_and_summary(message, title, summary):
    parsed_title, parsed_summary = split_title_and_summary(message)
    assert parsed_title == title
    assert parsed_summary == summary
