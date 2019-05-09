# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Functions related to the Security Bug Approval Process.

See https://wiki.mozilla.org/Security/Bug_Approval_Process.
"""
import inspect

from landoapi.projects import get_sec_approval_project_phid

dedent = inspect.cleandoc


def send_sanitized_commit_message_for_review(revision_phid, message, phabclient):
    """Send a sanitized commit message for review by the sec-approval team.

    See https://wiki.mozilla.org/Security/Bug_Approval_Process.

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
    # The message is written in first-person form because it is being authored by the
    # user in Lando and posted under their username.
    #
    # The message is formatted as Remarkup.
    # See https://phabricator.services.mozilla.com/book/phabricator/article/remarkup/
    return dedent(
        f"""
        I have written a sanitized comment message for this revision. It should
        follow the [Security Bug Approval Guidelines](https://wiki.mozilla.org/Security/Bug_Approval_Process).
        
        ````
        {message}
        ````
        
        Could a member of the `sec-approval` team please review this message?
        If the message is suitable for landing in mozilla-central please mark
        this code review as `Accepted`.
    """
    )
