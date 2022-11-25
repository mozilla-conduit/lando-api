# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import pytest

from landoapi.commit_message import (
    bug_list_to_commit_string,
    format_commit_message,
    split_title_and_summary,
)

COMMIT_MESSAGE = """
Bug 1 - A title. r=reviewer_one,reviewer.two

A summary.

Differential Revision: http://phabricator.test/D123
""".strip()

FIRST_LINE = COMMIT_MESSAGE.split("\n")[0]


def test_commit_message_for_multiple_reviewers():
    reviewers = ["reviewer_one", "reviewer.two"]
    commit_message = format_commit_message(
        "A title.", 1, reviewers, [], "A summary.", "http://phabricator.test/D123"
    )
    assert commit_message == (FIRST_LINE, COMMIT_MESSAGE)


def test_commit_message_blank_summary():
    first_line, message = format_commit_message(
        "A title.", 1, ["reviewer"], [], "", "http://phabricator.test/D123"
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
        [],
        "",
        "http://phabricator.test/D123",
    )

    assert commit_message[0] == "Bug 1 - A title! r=blocker"


@pytest.mark.parametrize(
    "reviewer_text",
    [
        "r?bogus",
        "r?#group1",
        "r?#group1, #group2",
        "r?reviewer_one,#group1",
        "r?#group1 r?reviewer.two",
        "r?#group1! r?group2",
        "r?#group1 r?group2!",
        "r?#group1! r?group2!",
        "r?#group1, reviewer.two!",
        "r=.a",
        "r=..a",
        "r=a...a",
        "r=a.b",
        "r=a.b.c",
        "r=aa,.a,..a,a...a,a.b,a.b.c",
    ],
)
def test_commit_message_reviewers_replaced(reviewer_text):
    reviewers = ["reviewer_one", "reviewer.two"]
    commit_message = format_commit_message(
        "A title. {}".format(reviewer_text),
        1,
        reviewers,
        [],
        "A summary.",
        "http://phabricator.test/D123",
    )
    assert commit_message == (FIRST_LINE, COMMIT_MESSAGE)


def test_commit_message_with_flags():
    reviewers = ["reviewer_one", "reviewer.two"]
    commit_message = format_commit_message(
        title="A title.",
        bug=1,
        reviewers=reviewers,
        approvals=[],
        summary="A summary.",
        revision_url="http://phabricator.test/D123",
        flags=["DONTBUILD"],
    )
    assert commit_message[0] == FIRST_LINE + " DONTBUILD"


def test_commit_message_with_flags_does_not_duplicate_flags():
    reviewers = ["reviewer_one", "reviewer.two"]
    commit_message = format_commit_message(
        title="A title. DONTBUILD",
        bug=1,
        reviewers=reviewers,
        approvals=[],
        summary="A summary.",
        revision_url="http://phabricator.test/D123",
        flags=["DONTBUILD"],
    )
    assert commit_message[0].count("DONTBUILD") == 1


@pytest.mark.xfail(strict=True)
def test_group_reviewers_replaced_with_period_at_end():
    """Test unexpected period after reviewer name."""
    # NOTE: the parser stops parsing after the period at the end of a reviewer
    # name, therefore any other reviewers past the first period will not be
    # parsed correctly, and the output will be mangled. This should be fixed
    # and the test should be updated.

    reviewers = ["reviewer_one", "reviewer.two"]
    commit_message = format_commit_message(
        "A title. r=a.,b",
        1,
        reviewers,
        [],
        "A summary.",
        "http://phabricator.test/D123",
    )

    # This is the current behaviour
    assert commit_message == (
        "Bug 1 - A title. r=reviewer_one,reviewer.two.,b",
        "Bug 1 - A title. r=reviewer_one,reviewer.two.,b\n\n"
        "A summary.\n\nDifferential Revision: http://phabricator.test/D123",
    )

    # This is the desired future behaviour
    assert commit_message == (
        "Bug 1 - A title. r=reviewer_one,reviewer.two.",
        "Bug 1 - A title. r=reviewer_one,reviewer.two.\n\n"
        "A summary.\n\nDifferential Revision: http://phabricator.test/D123",
    )


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


def test_relman_reviews_become_approvals():
    commit_message = format_commit_message(
        "A title r?#release-managers!",
        "1",
        [],
        ["ryanvm"],
        ("A summary.\n" "\n" "Original Revision: http://phabricator.test/D1"),
        "http://phabricator.test/D123",
    )

    assert commit_message == (
        "Bug 1 - A title  a=ryanvm",
        "Bug 1 - A title  a=ryanvm\n\n"
        "A summary.\n\n"
        "Original Revision: http://phabricator.test/D1\n\n"
        "Differential Revision: http://phabricator.test/D123",
    )


def test_bug_list_to_commit_string():
    assert (
        bug_list_to_commit_string([]) == "No bug"
    ), "Empty input should return `No bug`"
    assert (
        bug_list_to_commit_string(["123"]) == "Bug 123"
    ), "Single bug should return with `bug` and number."
    assert (
        bug_list_to_commit_string(["123", "456"]) == "Bug 123, 456"
    ), "Multiple bugs should return comma separated list."
