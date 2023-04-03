# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Add revision data to commit message."""
import re

from typing import (
    Iterable,
    Optional,
)

REVISION_URL_TEMPLATE = "Differential Revision: {url}"

# These regular expressions are not very robust. Specifically, they fail to
# handle lists well.
BUG_RE = re.compile(
    r"""
    # bug followed by any sequence of numbers, or
    # a standalone sequence of numbers
    (
        (?:
            bug |
            b= |
            # a sequence of 5+ numbers preceded by whitespace
            (?=\b\#?\d{5,}) |
            # numbers at the very beginning
            ^(?=\d)
        )
        (?:\s*\#?)(\d+)(?=\b)
    )""",
    re.I | re.X,
)

# Like BUG_RE except it doesn't flag sequences of numbers, only positive
# "bug" syntax like "bug X" or "b=".
BUG_CONSERVATIVE_RE = re.compile(r"""((?:bug|b=)(?:\s*)(\d+)(?=\b))""", re.I | re.X)

SPECIFIER = r"\b(?:r|a|sr|rs|ui-r)[=?]"
SPECIFIER_RE = re.compile(SPECIFIER)

LIST = r"[;,\/\\]\s*"

# Note that we only allows a subset of legal IRC-nick characters.
# Specifically, we do not allow [ \ ] ^ ` { | }
IRC_NICK = r"[a-zA-Z0-9\-\_.]*[a-zA-Z0-9\-\_]+"

# fmt: off
REVIEWERS_RE = re.compile(  # noqa: E131
    r"([\s\(\.\[;,])"                   # before "r" delimiter
    + r"(" + SPECIFIER + r")"           # flag
    + r"("                              # capture all reviewers
        + r"#?"                         # Optional "#" group reviewer prefix
        + IRC_NICK                      # reviewer
        + r"!?"                         # Optional "!" blocking indicator
        + r"(?:"                        # additional reviewers
            + LIST                      # delimiter
            + r"(?![a-z0-9\.\-]+[=?])"  # don"t extend match into next flag
            + r"#?"                     # Optional "#" group reviewer prefix
            + IRC_NICK                  # reviewer
            + r"!?"                     # Optional "!" blocking indicator
        + r")*"
    + r")?"
)
# fmt: on

# Strip out a white-list of metadata prefixes.
# Currently just MozReview-Commit-ID
METADATA_RE = re.compile("^MozReview-Commit-ID: ")


def format_commit_message(
    title: str,
    bug: Optional[int],
    reviewers: list[str],
    approvals: list[str],
    summary: str,
    revision_url: str,
    flags: Optional[list[str]] = None,
) -> tuple[str, str]:
    """
    Creates a default format commit message using revision metadata.

    The default format is as follows:
        <Bug #> - <Message Title> r=<reviewer1>,r=<reviewer2> <flag1> <flag2>

        <Summary>

        Differential Revision: <Revision URL>

    Args:
        title: The first line of the original commit message.
        bug: The bug number to use or None.
        reviewers: A list of reviewer usernames.
        approvals: A list of approval usernames.
        summary: A string containing the revision's summary.
        revision_url: The revision's url in Phabricator.
        flags: A list of flags to append to the title.

    Returns:
        A tuple containing the formatted title and full commit message. If the
        title already contains the bug id or reviewers, only the missing part
        will be added, or the title will be used unmodified if it is already
        valid.
    """
    if bug and bug not in parse_bugs(title):
        # All we really care about is if a bug is known it should
        # appear in the first line of the commit message. If it
        # isn't already there we'll add it.
        title = f"Bug {bug} - {title}"

    # Ensure that the actual reviewers are recorded in the
    # first line of the commit message.
    title = replace_reviewers(title, reviewers, approvals)

    # Clear any leading / trailing whitespace.
    title = title.strip()
    summary = summary.strip()

    # Check if any flags are already in the title, and exclude those.
    flags = [f for f in flags if f not in title] if flags else None

    # Append any flags to the title, as needed.
    if flags:
        title = f"{title} {' '.join(flags)}"

    # Construct the final message as a series of sections with
    # a blank line between each. Blank sections are filtered out.
    sections = filter(
        None, [title, summary, REVISION_URL_TEMPLATE.format(url=revision_url)]
    )
    return title, "\n\n".join(sections)


def parse_bugs(message: str) -> list[int]:
    """Parse `commit_message` and return a list of `int` bug numbers."""
    bugs_with_duplicates = [int(m[1]) for m in BUG_RE.findall(message)]
    bugs_seen = set()
    bugs_seen_add = bugs_seen.add
    bugs = [x for x in bugs_with_duplicates if not (x in bugs_seen or bugs_seen_add(x))]
    return [bug for bug in bugs if bug < 100000000]


def replace_reviewers(
    commit_description: str, reviewers: list[str], approvals: list[str]
) -> str:
    if not reviewers:
        reviewers_str = ""
    else:
        reviewers_str = "r=" + ",".join(reviewers)

    if approvals:
        reviewers_str += " a="
        reviewers_str += ",".join(approvals)

    if commit_description == "":
        return reviewers_str

    commit_description_lines = commit_description.splitlines()
    commit_summary = commit_description_lines.pop(0)
    commit_description = "\n".join(commit_description_lines)

    if not SPECIFIER_RE.search(commit_summary):
        commit_summary += " " + reviewers_str
    else:
        # replace the first r? with the reviewer list, and all subsequent
        # occurrences with a marker to mark the blocks we need to remove
        # later
        d = {"first": True}

        def replace_first_reviewer(matchobj):
            if SPECIFIER_RE.match(matchobj.group(2)):
                if d["first"]:
                    d["first"] = False
                    return matchobj.group(1) + reviewers_str
                else:
                    return "\0"
            else:
                return matchobj.group(0)

        commit_summary = re.sub(REVIEWERS_RE, replace_first_reviewer, commit_summary)

        # remove marker values as well as leading separators.  this allows us
        # to remove runs of multiple reviewers and retain the trailing
        # separator.
        commit_summary = re.sub(LIST + "\0", "", commit_summary)
        commit_summary = re.sub("\0", "", commit_summary)

    if commit_description == "":
        return commit_summary.strip()
    else:
        return commit_summary.strip() + "\n" + commit_description


def split_title_and_summary(msg: str) -> tuple[str, str]:
    """Split a VCS commit message into its title and body.

    Returns a tuple of (title, summary) strings. The summary string may be empty.
    """
    parts = msg.split("\n", maxsplit=1)
    title = parts[0]
    tail = parts[1:]
    summary = "\n".join(tail).strip()
    return title, summary


def bug_list_to_commit_string(bug_ids: Iterable[str]) -> str:
    """Convert a list of `str` bug IDs to a string for a commit message."""
    if not bug_ids:
        return "No bug"

    return f"Bug {', '.join(sorted(set(bug_ids)))}"
