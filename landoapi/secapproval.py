# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Functions related to the Security Bug Approval Process.

See https://wiki.mozilla.org/Security/Bug_Approval_Process.
"""
import logging
from operator import itemgetter

from landoapi.projects import get_sec_approval_project_phid
from landoapi.revisions import reviewer_assigned_to_revision, revision_is_secure
from landoapi.transactions import get_raw_comments

logger = logging.getLogger(__name__)


# Templates for submitting secure commit messages as Phabricator comments.
#
# The message is written in first-person form because it is being authored by the
# user in Lando and posted under their username.
#
# The message is formatted as Remarkup.
# See https://phabricator.services.mozilla.com/book/phabricator/article/remarkup/

SECURE_COMMENT_HEADER = """I have written a sanitized comment message for this revision.
It should follow the [Security Bug Approval Guidelines](https://wiki.mozilla.org/Security/Bug_Approval_Process).

```
"""
SECURE_COMMENT_FOOTER = """
```

Could a member of the #sec-approval team please review this message?
If the message is suitable for landing in mozilla-central please mark
this code review as `Accepted`."""


def send_sanitized_commit_message_for_review(revision_phid, message, phabclient):
    """Send a sanitized commit message for review by the sec-approval team.

    Args:
        revision_phid: The PHID of the revision to edit.
        message: The sanitized commit message string we want to be reviewed.
        phabclient: A PhabClient instance.
    """
    comment = format_sanitized_message_comment_for_review(message)
    sec_approval_phid = get_sec_approval_project_phid(phabclient)
    phabclient.call_conduit(
        "differential.revision.edit",
        objectIdentifier=revision_phid,
        transactions=[
            # The caller's alternative commit message is published as a comment.
            {"type": "comment", "value": comment},
            # We must get one of the sec-approval project members to approve the
            # alternate commit message for the review to proceed.
            #
            # We need to handle the case where the sec-approval team has approved a
            # previous alternate commit message and the author has sent a new
            # message. In this case we want the review to block on the sec-approval
            # team again and for the sec-approval team to review the new message.
            # Explicitly re-adding the sec-approval team to the review will clear any
            # previous reviews the team did and change their state to "blocking,
            # needs review".  Other reviewers' reviews will be left untouched. The
            # overall state of the revision will become "Needs Review".
            #
            # NOTE: the 'blocking(PHID)' syntax is undocumented at the time of
            # writing.
            {"type": "reviewers.add", "value": [f"blocking({sec_approval_phid})"]},
        ],
    )


def format_sanitized_message_comment_for_review(message):
    """Turn a commit message into a formatted Phabricator comment.

    The message is formatted to guide the next steps in the Security
    Bug Approval Process.  People reading the revision and this comment
    in the discussion thread should understand the steps necessary to move
    the approval process forward.

    See https://wiki.mozilla.org/Security/Bug_Approval_Process.

    Args:
        message: The commit message to be reviewed.
    """
    return "{header}{message}{footer}".format(
        header=SECURE_COMMENT_HEADER, message=message, footer=SECURE_COMMENT_FOOTER
    )


def find_secure_commit_message_in_transaction_list(transactions):
    """Search a revision's transaction list for a secure commit message.

    If there are multiple matching transactions the newest one will be returned.

    Args:
        transactions: A list of Phabricator object transaction data for a
            revision.

    Returns:
        A string containing the full sanitized commit message text from Phabricator
        if a matching commit could be found.  Returns None if a secure commit message
        could not be found for the given Revision.
    """
    # See https://phabricator.services.mozilla.com/conduit/method/transaction.search/
    # for the Conduit API result object structure.
    newest_to_oldest_transactions = sorted(
        transactions, key=itemgetter("id"), reverse=True
    )

    for transaction in newest_to_oldest_transactions:
        if transaction["type"] != "comment":
            continue

        # NOTE: We can have multiple comments in a transaction, for example when
        # a reviewer posts multiple inline comments during a review.  However the
        # sanitized commit message was posted to the revision as a single comment
        # in a single transaction by Lando. Therefore we can treat all transactions
        # as if they have a single comment.
        comment = get_raw_comments(transaction).pop()
        logger.debug("found comment", extra={"value": comment})
        secure_message = parse_comment_for_sanitized_commit_message(comment)
        if secure_message:
            logger.debug("revision has a secure commit message?", extra={"value": True})
            return secure_message

    logger.debug("revision has a secure commit message?", extra={"value": False})
    return None


def parse_comment_for_sanitized_commit_message(comment: str):
    """Parse a Phabricator comment text and return it's secure message, if any.

    Returns:
        The secure message extracted from the comment text. Returns None if the
        message does not appear to be a secure message.
    """
    if comment.startswith(SECURE_COMMENT_HEADER) and comment.endswith(
        SECURE_COMMENT_FOOTER
    ):
        header_length = len(SECURE_COMMENT_HEADER)
        footer_length = len(SECURE_COMMENT_FOOTER)
        return comment[header_length:-footer_length].strip()

    return None


def may_have_secure_commit_message(
    revision, secure_project_phid, sec_approval_group_phid
):
    """Could the given revision have a secure commit message attached?

    Args:
        revision: A dict of the revision data from differential.revision.search
            with the 'projects' attachment.
        secure_project_phid: The PHID of the Phabricator project used to tag
            secure revisions.
        sec_approval_group_phid: The PHID of the sec-approval group in Phabricator.
    """
    if not revision_is_secure(revision, secure_project_phid):
        return False

    has_sec_approval_group = reviewer_assigned_to_revision(
        sec_approval_group_phid, revision
    )
    logger.debug(
        "revision has the sec-approval group as a reviewer?",
        extra={"value": has_sec_approval_group, "revision": revision["id"]},
    )
    return has_sec_approval_group
