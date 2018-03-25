# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Add revision data to commit message."""
import re

COMMIT_MSG_TEMPLATE = """
{title}

{summary}

Differential Revision: {url}
""".strip()

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
        r'(?:' +                        # additional reviewers
            LIST +                      # delimiter
            r'(?![a-z0-9\.\-]+[=?])' +  # don't extend match into next flag
            IRC_NICK +                  # reviewer
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
    first_line = title

    if bug and get_commit_message_errors(title, check_reviewers=False):
        # The commit message is missing the bug number.
        first_line = "Bug {} - {}".format(bug, first_line)

    if reviewers and get_commit_message_errors(title, check_bug=False):
        # The commit message is missing the reviewer list.
        reviewers_str = ",".join(["r={}".format(r) for r in reviewers])
        first_line = "{} {}".format(first_line, reviewers_str)

    return first_line, COMMIT_MSG_TEMPLATE.format(
        title=first_line, summary=summary, url=revision_url
    )


def get_commit_message_errors(
    commit_message, check_bug=True, check_reviewers=True
):
    """
    Validates the format of a commit message title.

    Checks to ensure it adheres to standard hg.mozilla.org format which
    _loosely_ follows the pattern:
        <Bug #> - <Message Title> r=<reviewer1>,r=<reviewer2>...

    Notes:
    - The bug # does not have to be at the beginning of the commit message,
      it just needs to be present somewhere.
    - There are many 'valid' variations of the reviewer list, currently this
      only checks for an r= somewhere in the string. In the future this method
      should use the mozautomation.commitparser library to do a proper check.
    - The <Message Title> portion is treated as optional, although that is
      probably a bad idea.
    - An empty commit_message is invalid.

    Args:
        commit_message: The commit message to validate.
        check_bug: Whether or not to check for a bug id.
        check_reviewers: Whether or not to check for a reviewers list.

    Returns:
        None if and only if the commit message is valid.
        Or, a list containing an error message string for each error found.
    """
    # TODO refactor using the mozautomation.commitparser library.
    errors = []

    if check_bug:
        bug_id_regex = re.compile(r'bug[ -:]{1,4}\d+', re.IGNORECASE)
        if bug_id_regex.search(commit_message) is None:
            errors.append(
                'The commit message is missing a bug or it is'
                ' invalid.'
            )

    if check_reviewers:
        # TODO add support for different reviewer list formats, e.g.:
        # r=reviewer1, r=reviewer2, ...
        # r=reviewer1,r=reviewer2, ...
        # r=reviewer1,reviewer2, ...
        # r=reviewer1, reviewer2, ...
        # ...(r=reviewer1)
        # r=reviewer1, a=*, ... (not sure, but, I see this in moz-central log)
        # Possibly others
        reviewer_regex = re.compile(r'\A.*(r=)', re.IGNORECASE)
        if reviewer_regex.match(commit_message) is None:
            errors.append(
                'The commit message is missing the reviewers list or'
                ' it is invalid.'
            )

    if len(commit_message) < 1:
        errors.append('The commit message is empty.')

    return errors if errors else None


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
