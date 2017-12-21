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
