# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging
from collections import Counter

from landoapi.models import SecApprovalRequest
from landoapi.phabricator import (
    PhabricatorAPIException,
    PhabricatorClient,
    RevisionStatus,
)
from landoapi.secapproval import (
    CommentParseError,
    CommitDescription,
    parse_comment,
    search_sec_approval_request_for_comment,
    TransactionSearchError,
)

logger = logging.getLogger(__name__)


def gather_involved_phids(revision):
    """Return the set of Phobject phids involved in a revision.

    At the time of writing Users and Projects are the type of Phobjects
    which may author or review a revision.
    """
    attachments = PhabricatorClient.expect(revision, "attachments")

    entities = {PhabricatorClient.expect(revision, "fields", "authorPHID")}
    entities.update(
        {
            PhabricatorClient.expect(r, "reviewerPHID")
            for r in PhabricatorClient.expect(attachments, "reviewers", "reviewers")
        }
    )
    entities.update(
        {
            PhabricatorClient.expect(r, "reviewerPHID")
            for r in PhabricatorClient.expect(
                attachments, "reviewers-extra", "reviewers-extra"
            )
        }
    )
    return entities


def serialize_author(phid, user_search_data):
    out = {"phid": phid, "username": None, "real_name": None}
    author = user_search_data.get(phid)
    if author is not None:
        out["username"] = PhabricatorClient.expect(author, "fields", "username")
        out["real_name"] = PhabricatorClient.expect(author, "fields", "realName")

    return out


def serialize_diff(diff):
    author_name, author_email = select_diff_author(diff)
    fields = PhabricatorClient.expect(diff, "fields")

    return {
        "id": PhabricatorClient.expect(diff, "id"),
        "phid": PhabricatorClient.expect(diff, "phid"),
        "date_created": PhabricatorClient.to_datetime(
            PhabricatorClient.expect(fields, "dateCreated")
        ).isoformat(),
        "date_modified": PhabricatorClient.to_datetime(
            PhabricatorClient.expect(fields, "dateModified")
        ).isoformat(),
        "author": {"name": author_name or "", "email": author_email or ""},
    }


def serialize_status(revision):
    status_value = PhabricatorClient.expect(revision, "fields", "status", "value")
    status = RevisionStatus.from_status(status_value)

    if status is RevisionStatus.UNEXPECTED_STATUS:
        logger.warning(
            "Revision had unexpected status",
            extra={
                "id": PhabricatorClient.expection(revision, "id"),
                "value": status_value,
            },
        )
        return {"closed": False, "value": None, "display": "Unknown"}

    return {
        "closed": status.closed,
        "value": status.value,
        "display": status.output_name,
    }


def select_diff_author(diff):
    commits = PhabricatorClient.expect(diff, "attachments", "commits", "commits")
    if not commits:
        return None, None

    authors = [c.get("author", {}) for c in commits]
    authors = Counter((a.get("name"), a.get("email")) for a in authors)
    authors = authors.most_common(1)
    return authors[0][0] if authors else (None, None)


def get_bugzilla_bug(revision):
    bug = PhabricatorClient.expect(revision, "fields").get("bugzilla.bug-id")
    return int(bug) if bug else None


def check_diff_author_is_known(*, diff, **kwargs):
    author_name, author_email = select_diff_author(diff)
    if author_name and author_email:
        return None

    return (
        "Diff does not have proper author information in Phabricator. "
        "See the Lando FAQ for help with this error."
    )


def check_author_planned_changes(*, revision, **kwargs):
    status = RevisionStatus.from_status(
        PhabricatorClient.expect(revision, "fields", "status", "value")
    )
    if status is not RevisionStatus.CHANGES_PLANNED:
        return None

    return "The author has indicated they are planning changes to this revision."


def revision_is_secure(revision, secure_project_phid):
    """Does the given revision contain security-sensitive data?

    Such revisions should be handled according to the Security Bug Approval Process.
    See https://wiki.mozilla.org/Security/Bug_Approval_Process.

    Args:
        revision: A dict of the revision data from differential.revision.search
            with the 'projects' attachment.
        secure_project_phid: The PHID of the Phabricator project used to tag
            secure revisions.
    """
    revision_project_tags = PhabricatorClient.expect(
        revision, "attachments", "projects", "projectPHIDs"
    )
    return secure_project_phid in revision_project_tags


def find_title_and_summary_for_display(
    phab: PhabricatorClient, revision: dict, secure: bool
) -> CommitDescription:
    """Find a commit's title and summary for display in Lando UI.

    This function is intended to get the commit title and summary for display to the
    end user in Lando UI. This function does NOT produce a commit title and summary
    that are suitable for landing code in a source tree because this function may
    return placeholder text for the UI.

    If a revision has an alternate commit message given to it by the sec-approval
    process then the alternate message will be returned.

    Args:
        phab: A PhabricatorClient instance.
        revision: A Phabricator Revision object used to generate the commit title
            and summary.
        secure: Bool indicating the revision is security-sensitive and subject to the
            sec-approval process.

    Returns: A CommitDescription object that holds the title and summary. The values
        depend on the public or secure status of the revision.
    """
    if secure:
        # The revision may be somewhere in the sec-approval workflow. We need to find
        # out where in the workflow it is to determine which title and summary to use.

        # Have we already placed a request?
        sec_approval_request = SecApprovalRequest.most_recent_request_for_revision(
            revision
        )

        if sec_approval_request:
            # We have requested a new title and possibly a new summary, too, for the
            # commit.

            try:
                comment = search_sec_approval_request_for_comment(
                    phab, sec_approval_request
                )
            except (TransactionSearchError, PhabricatorAPIException) as e:
                logger.error(
                    "sec-approval: request processing failed",
                    extra={
                        "revision": sec_approval_request.revision_id,
                        "sec_approval_request_database_id": sec_approval_request.id,
                        "reason": str(e),
                    },
                )
                raise

            # Parse the comment for display.
            try:
                return parse_comment(comment)
            except CommentParseError as e:
                # Parsing failed, possibly due to a change in the sec-approval
                # request message format. To future-proof the code we'll return a
                # placeholder asking the caller to reference the original Revision if
                # they want more info.
                logger.info(
                    "sec-approval: comment parsing failed, returning placeholder text",
                    extra={
                        "revision": sec_approval_request.revision_id,
                        "sec_approval_request_database_id": sec_approval_request.id,
                        "reason": str(e),
                    },
                )
                return CommitDescription(
                    title="*** please see revision for title ***",
                    summary="",
                    sanitized=True,
                )

    # Return the revision's original title and summary.
    return CommitDescription(
        title=PhabricatorClient.expect(revision, "fields", "title"),
        summary=PhabricatorClient.expect(revision, "fields", "summary"),
        sanitized=False,
    )


def find_title_and_summary_for_landing(
    phab: PhabricatorClient, revision: dict, secure: bool
) -> CommitDescription:
    """Find a commit's title and summary for placing in a commit message.

    This function returns the title and summary so that it can be placed directly
    in a commit message and landed in-tree.  If this function fails to find a
    suitable commit message then an error will be raised.

    If a revision has an alternate commit message given to it by the sec-approval
    process then the alternate message will be returned.

    Args:
        phab: A PhabricatorClient instance.
        revision: A Phabricator Revision object used to generate the commit title
            and summary.
        secure: Bool indicating the revision is security-sensitive and subject to the
            sec-approval process.

    Returns: A CommitDescription object that holds the title and summary. The values
        depend on the public or secure status of the revision.
    """
    if secure:
        # The revision may be somewhere in the sec-approval workflow. We need to find
        # out where in the workflow it is to determine which title and summary to use.

        # Have we already placed a request?
        sec_approval_request = SecApprovalRequest.most_recent_request_for_revision(
            revision
        )

        if sec_approval_request:
            # We have requested a new title and possibly a new summary, too, for the
            # commit.

            logger.info(
                "sec-approval: using alternate title and summary for revision",
                extra={
                    "revision": sec_approval_request.revision_id,
                    "sec_approval_request_database_id": sec_approval_request.id,
                },
            )

            # NOTE: Any problem with fetching and constructing the commit message
            # should raise an exception and fail the whole process.
            try:
                comment = search_sec_approval_request_for_comment(
                    phab, sec_approval_request
                )

                return parse_comment(comment)

            except Exception as e:
                logger.error(
                    "sec-approval: request processing failed",
                    extra={
                        "revision": sec_approval_request.revision_id,
                        "sec_approval_request_database_id": sec_approval_request.id,
                        "reason": str(e),
                    },
                )
                raise

    # Return the revision's original title and summary.
    return CommitDescription(
        title=PhabricatorClient.expect(revision, "fields", "title"),
        summary=PhabricatorClient.expect(revision, "fields", "summary"),
        sanitized=False,
    )
