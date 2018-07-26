# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Add revision data to commit message."""
import re

REVISION_URL_TEMPLATE = 'Differential Revision: {url}'

# These regular expressions are not very robust. Specifically, they fail to
# handle lists well.
BUG_RE = re.compile(
    r'''
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
    )''', re.I | re.X
)

# Like BUG_RE except it doesn't flag sequences of numbers, only positive
# "bug" syntax like "bug X" or "b=".
BUG_CONSERVATIVE_RE = re.compile(
    r'''((?:bug|b=)(?:\s*)(\d+)(?=\b))''', re.I | re.X
)

SPECIFIER = r'(?:r|a|sr|rs|ui-r)[=?]'
R_SPECIFIER = r'\br[=?]'
R_SPECIFIER_RE = re.compile(R_SPECIFIER)

LIST = r'[;,\/\\]\s*'

# Note that we only allows a subset of legal IRC-nick characters.
# Specifically we not allow [ \ ] ^ ` { | }
IRC_NICK = r'[a-zA-Z0-9\-\_]+'

REVIEWERS_RE = re.compile(
    r'([\s\(\.\[;,])' +                 # before 'r' delimiter
    r'(' + SPECIFIER + r')' +           # flag
    r'(' +                              # capture all reviewers
        IRC_NICK +                      # reviewer
        r'!?' +                        # Optional '!' blocking indicator
        r'(?:' +                        # additional reviewers
            LIST +                      # delimiter
            r'(?![a-z0-9\.\-]+[=?])' +  # don't extend match into next flag
            IRC_NICK +                  # reviewer
            r'!?' +                    # Optional '!' blocking indicator
        r')*' +
    r')?')                              # noqa yapf: disable

# Strip out a white-list of metadata prefixes.
# Currently just MozReview-Commit-ID
METADATA_RE = re.compile('^MozReview-Commit-ID: ')


def format_commit_message(title, bug, reviewers, summary, revision_url):
    """
    Creates a default format commit message using revision metadata.

    The default format is as follows:
        <Bug #> - <Message Title> r=<reviewer1>,r=<reviewer2>

        <Summary>

        Differential Revision: <Revision URL>

    Args:
        title: The first line of the original commit message.
        bug: The bug number to use or None.
        reviewers: A list of reviewer usernames.
        summary: A string containing the revision's summary
        revision_url: The revision's url in Phabricator

    Returns:
        A tuple of strings with the formatted title and full commit message.
        If the title already contains the bug id or reviewers, only the missing
        part will be added, or the title will be used unmodified if it is
        already valid.
    """
    if bug and bug not in parse_bugs(title):
        # All we really care about is if a bug is known it should
        # appear in the first line of the commit message. If it
        # isn't already there we'll add it.
        title = 'Bug {} - {}'.format(bug, title)

    # Ensure that the actual reviewers are recorded in the
    # first line of the commit message.
    title = replace_reviewers(title, reviewers)

    # Clear any leading / trailing whitespace.
    title = title.strip()
    summary = summary.strip()

    # Construct the final message as a series of sections with
    # a blank line between each. Blank sections are filtered out.
    sections = filter(
        None, [title, summary, REVISION_URL_TEMPLATE.format(url=revision_url)]
    )
    return title, '\n\n'.join(sections)


def parse_bugs(s):
    bugs_with_duplicates = [int(m[1]) for m in BUG_RE.findall(s)]
    bugs_seen = set()
    bugs_seen_add = bugs_seen.add
    bugs = [
        x for x in bugs_with_duplicates
        if not (x in bugs_seen or bugs_seen_add(x))
    ]
    return [bug for bug in bugs if bug < 100000000]


def replace_reviewers(commit_description, reviewers):
    if not reviewers:
        reviewers_str = ''
    else:
        reviewers_str = 'r=' + ','.join(reviewers)

    if commit_description == '':
        return reviewers_str

    commit_description = commit_description.splitlines()
    commit_summary = commit_description.pop(0)
    commit_description = '\n'.join(commit_description)

    if not R_SPECIFIER_RE.search(commit_summary):
        commit_summary += ' ' + reviewers_str
    else:
        # replace the first r? with the reviewer list, and all subsequent
        # occurences with a marker to mark the blocks we need to remove
        # later
        d = {'first': True}

        def replace_first_reviewer(matchobj):
            if R_SPECIFIER_RE.match(matchobj.group(2)):
                if d['first']:
                    d['first'] = False
                    return matchobj.group(1) + reviewers_str
                else:
                    return '\0'
            else:
                return matchobj.group(0)

        commit_summary = re.sub(
            REVIEWERS_RE, replace_first_reviewer, commit_summary
        )

        # remove marker values as well as leading separators.  this allows us
        # to remove runs of multiple reviewers and retain the trailing
        # separator.
        commit_summary = re.sub(LIST + '\0', '', commit_summary)
        commit_summary = re.sub('\0', '', commit_summary)

    if commit_description == "":
        return commit_summary.strip()
    else:
        return commit_summary.strip() + "\n" + commit_description


def strip_commit_metadata(s):
    """Strips metadata related to commit tracking.

    Will strip lines like "MozReview-Commit-ID: foo" from the commit
    message.
    """
    # TODO this parsing is overly simplied. There is room to handle
    # empty lines before the metadata.
    lines = [l for l in s.splitlines() if not METADATA_RE.match(l)]

    while lines and not lines[-1].strip():
        lines.pop(-1)

    if type(s) == bytes:
        joiner = b'\n'
    elif type(s) == str:
        joiner = u'\n'
    else:
        raise TypeError('do not know type of commit message: %s' % type(s))

    return joiner.join(lines)


def parse_commit_id(s):
    """Parse a MozReview-Commit-ID value out of a string.

    Returns None if the commit ID is not found.
    """
    m = re.search('^MozReview-Commit-ID: ([a-zA-Z0-9]+)$', s, re.MULTILINE)
    if not m:
        return None

    return m.group(1)
