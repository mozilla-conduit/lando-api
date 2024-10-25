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

# Like BUG_RE except it doesn't flag sequences of numbers, only positive
# "bug" syntax like "bug X" or "b=".
BUG_CONSERVATIVE_RE = re.compile(r"""(\b(?:bug|b=)\b(?:\s*)(\d+)(?=\b))""", re.I | re.X)

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

ACCEPTABLE_MESSAGE_FORMAT_RES = [
    re.compile(format, re.I)
    for format in [
        r"bug [0-9]+",
        r"no bug",
        r"^(back(ing|ed)?\s+out|backout).*(\s+|\:)[0-9a-f]{12}",
        r"^(revert(ed|ing)?).*(\s+|\:)[0-9a-f]{12}",
        r"^add(ed|ing)? tag",
    ]
]
INVALID_REVIEW_FLAG_RE = re.compile(r"[\s.;]r\?(?:\w|$)")

CHANGESET_KEYWORD = r"(?:\b(?:changeset|revision|change|cset|of)\b)"
CHANGESETS_KEYWORD = r"(?:\b(?:changesets|revisions|changes|csets|of)\b)"
SHORT_NODE = r"([0-9a-f]{12}\b)"
SHORT_NODE_RE = re.compile(SHORT_NODE, re.I)
BACKOUT_KEYWORD = r"^(?:backed out|backout|back out)\b"
BACKOUT_KEYWORD_RE = re.compile(BACKOUT_KEYWORD, re.I)
BACKOUT_SINGLE_RE = re.compile(
    BACKOUT_KEYWORD
    + r"\s+"
    + CHANGESET_KEYWORD
    + r"?\s*"
    + r"(?P<node>"
    + SHORT_NODE
    + r")",
    re.I,
)
BACKOUT_MULTI_SPLIT_RE = re.compile(
    BACKOUT_KEYWORD + r"\s+(?P<count>\d+)\s+" + CHANGESETS_KEYWORD, re.I
)
BACKOUT_MULTI_ONELINE_RE = re.compile(
    BACKOUT_KEYWORD
    + r"\s+"
    + CHANGESETS_KEYWORD
    + r"?\s*"
    + r"(?P<nodes>(?:(?:\s+|and|,)+"
    + SHORT_NODE
    + r")+)",
    re.I,
)
RE_SOURCE_REPO = re.compile(r"^Source-Repo: (https?:\/\/.*)$", re.MULTILINE)
RE_SOURCE_REVISION = re.compile(r"^Source-Revision: (.*)$", re.MULTILINE)


def is_backout(commit_desc: str) -> bool:
    """Returns True if commit description indicates the changeset is a backout.

    Backout commits should always result in is_backout() returning True,
    and parse_backouts() not returning None.  Malformed backouts may return
    True here and None from parse_backouts().
    """
    return BACKOUT_KEYWORD_RE.match(commit_desc) is not None


def parse_backouts(
    commit_desc: str, strict: bool = False
) -> Optional[tuple[list[str], list[int]]]:
    """Look for backout annotations in a string.

    Returns a 2-tuple of (nodes, bugs) where each entry is an iterable of
    changeset identifiers and bug numbers that were backed out, respectively.
    Or return None if no backout info is available.

    Setting `strict` to True will enable stricter validation of the commit
    description (eg. ensuring N commits are provided when given N commits are
    being backed out).
    """
    if not is_backout(commit_desc):
        return

    lines = commit_desc.splitlines()
    first_line = lines[0]

    # Single backout.
    backout_match = BACKOUT_SINGLE_RE.match(first_line)
    if backout_match:
        return [backout_match.group("node")], parse_bugs(first_line)

    # Multiple backouts, with nodes listed in commit description.
    backout_match = BACKOUT_MULTI_SPLIT_RE.match(first_line)
    if backout_match:
        expected = int(backout_match.group("count"))
        nodes = []
        for line in lines[1:]:
            single_match = BACKOUT_SINGLE_RE.match(line)
            if single_match:
                nodes.append(single_match.group("node"))

        if strict:
            # The correct number of nodes must be specified.
            if expected != len(nodes):
                return

        return nodes, parse_bugs(commit_desc)

    # Multiple backouts, with nodes listed on the first line
    backout_match = BACKOUT_MULTI_ONELINE_RE.match(first_line)
    if backout_match:
        return SHORT_NODE_RE.findall(backout_match.group("nodes")), parse_bugs(
            first_line
        )

    return


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
    bugs_with_duplicates = [int(m[1]) for m in BUG_CONSERVATIVE_RE.findall(message)]
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
