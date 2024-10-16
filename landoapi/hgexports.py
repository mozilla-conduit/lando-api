# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import email
import io
import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from email.policy import (
    default as default_email_policy,
)
from email.utils import (
    parseaddr,
)
from typing import (
    Iterable,
    Optional,
    Type,
)

import requests
import rs_parsepatch

from landoapi.bmo import (
    get_status_code_for_bug,
    search_bugs,
)
from landoapi.commit_message import (
    ACCEPTABLE_MESSAGE_FORMAT_RES,
    INVALID_REVIEW_FLAG_RE,
    is_backout,
    parse_backouts,
    parse_bugs,
)

HG_HEADER_NAMES = (
    "User",
    "Date",
    "Node ID",
    "Parent",
    "Diff Start Line",
    "Fail HG Import",
)
DIFF_LINE_RE = re.compile(r"^diff\s+\S+\s+\S+")

_HG_EXPORT_PATCH_TEMPLATE = """
{header}
{commit_message}

{diff}
""".strip()

_HG_EXPORT_HEADER = """
# HG changeset patch
# User {author_name} <{author_email}>
# Date {patchdate}
# Diff Start Line {diff_start_line}
""".strip()

_HG_EXPORT_HEADER_LENGTH = len(_HG_EXPORT_HEADER.splitlines())


def build_patch_for_revision(
    diff: str, author_name: str, author_email: str, commit_message: str, timestamp: str
) -> str:
    """Generate a 'hg export' patch using Phabricator Revision data.

    Args:
        diff: A string holding a Git-formatted patch.
        author: A string with information about the patch's author.
        commit_message: A string containing the full commit message.
        timestamp: (str) String number of seconds since Unix Epoch representing the
            date and time to be included in the Date header.

    Returns:
        A string containing a patch in 'hg export' format.
    """

    message_lines = commit_message.strip().splitlines()
    header = _HG_EXPORT_HEADER.format(
        author_name=_no_line_breaks(author_name),
        author_email=_no_line_breaks(author_email),
        patchdate=_no_line_breaks("%s +0000" % timestamp),
        diff_start_line=len(message_lines) + _HG_EXPORT_HEADER_LENGTH + 1,
    )

    return _HG_EXPORT_PATCH_TEMPLATE.format(
        header=header, commit_message="\n".join(message_lines), diff=diff
    )


def _no_line_breaks(break_string: str) -> str:
    """Return `break_string` with all line breaks removed."""
    return "".join(break_string.strip().splitlines())


def parse_git_author_information(user_header: str) -> tuple[str, str]:
    """Parse user's name and email address from a Git style author header.

    Converts a header like 'User Name <user@example.com>' to its separate parts.

    If the parser could not split out the email from the user header,
    assume it is improperly formatted and return the entire header
    as the username instead.
    """
    name, email = parseaddr(user_header)

    if not all({name, email}):
        return user_header, ""

    return name, email


def get_timestamp_from_git_date_header(date_header: str) -> str:
    """Convert a Git patch date header into a timestamp."""
    header_datetime = datetime.strptime(date_header, "%a, %d %b %Y %H:%M:%S %z")
    return str(math.floor(header_datetime.timestamp()))


def get_timestamp_from_hg_date_header(date_header: str) -> str:
    """Return the first part of the `hg export` date header.

    >>> get_timestamp_from_hg_date_header("1686621879 14400")
    "1686621879"
    """
    return date_header.split(" ")[0]


class PatchHelper:
    """Base class for parsing patches/exports."""

    def __init__(self, fileobj: io.StringIO):
        self.patch = fileobj
        self.headers = {}

    @staticmethod
    def _is_diff_line(line: str) -> bool:
        return DIFF_LINE_RE.search(line) is not None

    def get_header(self, name: bytes | str) -> Optional[str]:
        """Returns value of the specified header, or None if missing."""
        if isinstance(name, bytes):
            name = name.decode("utf-8")

        return self.headers.get(name.lower())

    def set_header(self, name: bytes | str, value: str):
        """Set the header `name` to `value`."""
        if isinstance(name, bytes):
            name = name.decode("utf-8")

        self.headers[name.lower()] = value

    def get_commit_description(self) -> str:
        """Returns the commit description."""
        raise NotImplementedError("`commit_description` not implemented.")

    def get_diff(self) -> str:
        """Return the patch diff."""
        raise NotImplementedError("`get_diff` not implemented.")

    def write_commit_description(self, f: io.StringIO):
        """Writes the commit description to the specified file object."""
        f.write(self.get_commit_description())

    def write_diff(self, file_obj: io.StringIO):
        """Writes the diff to the specified file object."""
        file_obj.write(self.get_diff())

    def write(self, f: io.StringIO):
        """Writes whole patch to the specified file object."""
        try:
            buf = self.patch.read()
            f.write(buf)
        finally:
            self.patch.seek(0)

    def parse_author_information(self) -> tuple[str, str]:
        """Return the author name and email from the patch."""
        raise NotImplementedError("`parse_author_information` is not implemented.")

    def get_timestamp(self) -> str:
        """Return an `hg export` formatted timestamp."""
        raise NotImplementedError("`get_timestamp` is not implemented.")


class HgPatchHelper(PatchHelper):
    """Helper class for parsing Mercurial patches/exports."""

    def __init__(self, fileobj: io.StringIO):
        super().__init__(fileobj)
        self.header_end_line_no = 0
        self._parse_header()

        # "Diff Start Line" is a Lando extension to the hg export
        # format meant to prevent injection of diff hunks using the
        # commit message.
        self.diff_start_line = self.get_header(b"Diff Start Line")
        if self.diff_start_line:
            try:
                self.diff_start_line = int(self.diff_start_line)
            except ValueError:
                self.diff_start_line = None

    @staticmethod
    def _header_value(line: str, prefix: str) -> Optional[str]:
        m = re.search(
            r"^#\s+" + re.escape(prefix) + r"\s+(.*)", line, flags=re.IGNORECASE
        )
        if not m:
            return None
        return m.group(1).strip()

    def _parse_header(self):
        """Extract header values specified by HG_HEADER_NAMES."""
        self.patch.seek(0)
        try:
            for line in self.patch:
                if not line.startswith("# "):
                    break
                self.header_end_line_no += 1
                for name in HG_HEADER_NAMES:
                    value = self._header_value(line, name)
                    if value:
                        self.set_header(name, value)
                        break
        finally:
            self.patch.seek(0)

        if not self.headers:
            raise ValueError("Failed to parse headers from patch.")

    def get_commit_description(self) -> str:
        """Returns the commit description."""
        commit_desc = []

        try:
            for i, line in enumerate(self.patch, start=1):
                if i <= self.header_end_line_no:
                    continue

                # If we found a `Diff Start Line` header and we have parsed to that line,
                # the commit description has been parsed and we can break.
                # If there was no `Diff Start Line` header, iterate through each line until
                # we find a `diff` line, then break as we have parsed the commit description.
                if (self.diff_start_line and i == self.diff_start_line) or (
                    not self.diff_start_line and self._is_diff_line(line)
                ):
                    break

                commit_desc.append(line)

            return "".join(commit_desc).strip()
        finally:
            self.patch.seek(0)

    def get_diff(self) -> str:
        """Return the diff for this patch."""
        diff = []

        try:
            for i, line in enumerate(self.patch, start=1):
                # If we found a `Diff Start Line` header, parse the diff until that line.
                # If there was no `Diff Start Line` header, iterate through each line until
                # we find a `diff` line.
                if (not self.diff_start_line and self._is_diff_line(line)) or (
                    self.diff_start_line and i == self.diff_start_line
                ):
                    diff.append(line)
                    break

            buf = self.patch.read()
            diff.append(buf)

            return "".join(diff)
        finally:
            self.patch.seek(0)

    def parse_author_information(self) -> tuple[str, str]:
        """Return the author name and email from the patch."""
        user = self.get_header("User")
        if not user:
            raise ValueError(
                "Could not determine patch author information from header."
            )

        return parse_git_author_information(user)

    def get_timestamp(self) -> str:
        """Return an `hg export` formatted timestamp."""
        date = self.get_header("Date")
        if not date:
            raise ValueError("Could not determine patch timestamp from header.")

        return get_timestamp_from_hg_date_header(date)


class GitPatchHelper(PatchHelper):
    """Helper class for parsing Mercurial patches/exports."""

    def __init__(self, fileobj: io.StringIO):
        super().__init__(fileobj)
        self.message = email.message_from_string(
            self.patch.read(), policy=default_email_policy
        )
        self.message.set_charset("utf-8")
        self.commit_message, self.diff = self.parse_email_body(
            self.message.get_content()
        )

    def get_header(self, name: bytes | str) -> Optional[str]:
        """Get the headers from the message."""
        if isinstance(name, bytes):
            name = name.decode("utf-8")

        # `EmailMessage` will return `None` if the header isn't found.
        return self.message[name]

    @classmethod
    def strip_git_version_info_lines(cls, patch_lines: list[str]) -> list[str]:
        """Strip the Git version info lines from the end of the given patch lines.

        Assumes the `patch_lines` is the remaining content of a `git format-patch`
        style patch with Git version info at the base of the patch. Moves backward
        through the patch to find the `--` barrier between the patch and the version
        info and strips the version info.
        """
        # Collect the lines with the enumerated line numbers in a list, then
        # iterate through them in reverse order.
        for i, line in reversed(list(enumerate(patch_lines))):
            if line.startswith("--"):
                return patch_lines[:i]

        raise ValueError("Malformed patch: could not find Git version info.")

    def parse_email_body(self, content: str) -> tuple[str, str]:
        """Parse the patch email's body, returning the commit message and diff.

        The commit message is composed of the `Subject` header and the contents of
        the email message before the diff.
        """
        subject_header = self.get_header("Subject")
        if not subject_header:
            raise ValueError("No valid subject header for commit message.")

        # Start the commit message from the stripped subject line.
        commit_message_lines = [
            subject_header.removeprefix("[PATCH] ").removesuffix("\n")
        ]

        # Create an iterator for the lines of the patch.
        line_iterator = iter(content.splitlines())

        # Add each line to the commit message until we hit `---`.
        for i, line in enumerate(line_iterator):
            if line == "---":
                break

            # Add a newline after the subject line if this is a multi-line
            # commit message.
            if i == 0:
                commit_message_lines += [""]

            commit_message_lines.append(line)
        else:
            # We never found the end of the commit message body, so this change
            # must be an empty commit. Discard the Git version info from the commit
            # message and return an empty diff.
            commit_message_lines = GitPatchHelper.strip_git_version_info_lines(
                commit_message_lines
            )
            commit_message = "\n".join(commit_message_lines)
            return commit_message, ""

        commit_message = "\n".join(commit_message_lines)

        # Move through the patch until we find the start of the diff.
        # Add the diff start line to the diff.
        diff_lines = []
        for line in line_iterator:
            if GitPatchHelper._is_diff_line(line):
                diff_lines.append(line)
                break
        else:
            raise ValueError("Patch is malformed, could not find start of patch diff.")

        # The diff is the remainder of the patch, except the last two lines of Git version info.
        remaining_lines = GitPatchHelper.strip_git_version_info_lines(
            list(line_iterator)
        )
        diff_lines += remaining_lines
        diff = "\n".join(diff_lines)

        return commit_message, diff

    def get_commit_description(self) -> str:
        """Returns the commit description."""
        return self.commit_message

    def get_diff(self) -> str:
        """Return the patch diff."""
        return self.diff

    def parse_author_information(self) -> tuple[str, str]:
        """Return the author name and email from the patch."""
        from_header = self.get_header("From")
        if not from_header:
            raise ValueError("Patch does not have a `From:` header.")

        return parse_git_author_information(from_header)

    def get_timestamp(self) -> str:
        """Return an `hg export` formatted timestamp."""
        date = self.get_header("Date")
        if not date:
            raise ValueError("Patch does not have a `Date:` header.")

        return get_timestamp_from_git_date_header(date)


# Decimal notation for the `symlink` file mode.
SYMLINK_MODE = 40960

# WPT Sync bot is restricted to paths matching this regex.
WPT_SYNC_ALLOWED_PATHS_RE = re.compile(
    r"testing/web-platform/(?:moz\.build|meta/.*|tests/.*)$"
)


def wrap_filenames(filenames: list[str]) -> str:
    """Convert a list of filenames to a string with names wrapped in backticks."""
    return ",".join(f"`{filename}`" for filename in filenames)


@dataclass
class PatchCheck:
    """Provides an interface to implement patch checks.

    When looping over each diff in the patch, `next_diff` is called to give the
    current diff to the patch as a `rs_parsepatch` diff `dict`. Then, `result` is
    called to receive the result of the check.
    """

    author: Optional[str] = None
    email: Optional[str] = None
    commit_message: Optional[str] = None

    def next_diff(self, diff: dict):
        """Pass the next `rs_parsepatch` diff `dict` into the check."""
        raise NotImplementedError()

    def result(self) -> Optional[str]:
        """Calcuate and return the result of the check."""
        raise NotImplementedError()


@dataclass
class PreventSymlinksCheck(PatchCheck):
    """Check for symlinks introduced in the diff."""

    symlinked_files: list[str] = field(default_factory=list)

    def next_diff(self, diff: dict):
        modes = diff["modes"]

        # Check the file mode on each file and ensure the file is not a symlink.
        # `rs_parsepatch` has a `new` and `old` mode key, we are interested in
        # only the newly introduced modes.
        if "new" in modes and modes["new"] == SYMLINK_MODE:
            self.symlinked_files.append(diff["filename"])

    def result(self) -> Optional[str]:
        if self.symlinked_files:
            return (
                "Revision introduces symlinks in the files "
                f"{wrap_filenames(self.symlinked_files)}."
            )


@dataclass
class TryTaskConfigCheck(PatchCheck):
    """Check for `try_task_config.json` introduced in the diff."""

    includes_try_task_config: bool = False

    def next_diff(self, diff: dict):
        """Check each diff for the `try_task_config.json` file."""
        if diff["filename"] == "try_task_config.json":
            self.includes_try_task_config = True

    def result(self) -> Optional[str]:
        """Return an error if the `try_task_config.json` was found."""
        if self.includes_try_task_config:
            return "Revision introduces the `try_task_config.json` file."


@dataclass
class PreventNSPRNSSCheck(PatchCheck):
    """Prevent changes to vendored NSPR directories."""

    nss_disallowed_changes: list[str] = field(default_factory=list)
    nspr_disallowed_changes: list[str] = field(default_factory=list)

    def build_prevent_nspr_nss_error_message(self) -> str:
        """Build the `check_prevent_nspr_nss` error message.

        Assumes at least one of `nss_disallowed_changes` or `nspr_disallowed_changes`
        are non-empty lists.
        """
        # Build the error message.
        return_error_message = ["Revision makes changes to restricted directories:"]

        if self.nss_disallowed_changes:
            return_error_message.append("vendored NSS directories:")

            return_error_message.append(wrap_filenames(self.nss_disallowed_changes))

        if self.nspr_disallowed_changes:
            return_error_message.append("vendored NSPR directories:")

            return_error_message.append(wrap_filenames(self.nspr_disallowed_changes))

        return f"{' '.join(return_error_message)}."

    def next_diff(self, diff: dict):
        """Pass the next `rs_parsepatch` diff `dict` into the check."""
        if not self.commit_message:
            return

        filename = diff["filename"]

        if (
            filename.startswith("security/nss/")
            and "UPGRADE_NSS_RELEASE" not in self.commit_message
        ):
            self.nss_disallowed_changes.append(filename)

        if (
            filename.startswith("nsprpub/")
            and "UPGRADE_NSPR_RELEASE" not in self.commit_message
        ):
            self.nspr_disallowed_changes.append(filename)

    def result(self) -> Optional[str]:
        """Calcuate and return the result of the check."""
        if not self.nss_disallowed_changes and not self.nspr_disallowed_changes:
            # Return early if no disallowed changes were found.
            return

        return self.build_prevent_nspr_nss_error_message()


@dataclass
class PreventSubmodulesCheck(PatchCheck):
    """Prevent introduction of Git submodules into the repository."""

    includes_gitmodules: bool = False

    def next_diff(self, diff: dict):
        """Check if a diff adds the `.gitmodules` file."""
        if diff["filename"] == ".gitmodules":
            self.includes_gitmodules = True

    def result(self) -> Optional[str]:
        """Return an error if the `.gitmodules` file was found."""
        if self.includes_gitmodules:
            return "Revision introduces a Git submodule into the repository."


@dataclass
class WPTSyncCheck(PatchCheck):
    """Check the WPT Sync bot has only made changes to relevant subset of the tree."""

    wpt_disallowed_files: list[str] = field(default_factory=list)

    def next_diff(self, diff: dict):
        """Check each diff to assert the WPT-Sync bot is only updating allowed files."""
        if self.email != "wptsync@mozilla.com":
            return

        filename = diff["filename"]
        if not WPT_SYNC_ALLOWED_PATHS_RE.match(filename):
            self.wpt_disallowed_files.append(filename)

    def result(self) -> Optional[str]:
        """Return an error if the WPT-Sync bot touched disallowed files."""
        if self.wpt_disallowed_files:
            return (
                "Revision has WPTSync bot making changes to disallowed files "
                f"{wrap_filenames(self.wpt_disallowed_files)}."
            )


@dataclass
class DiffAssessor:
    """Assess diffs for landing issues.

    Diffs should be passed in `rs-parsepatch` format.
    """

    parsed_diff: list[dict]
    author: Optional[str] = None
    email: Optional[str] = None
    commit_message: Optional[str] = None

    def run_diff_checks(self, patch_checks: list[Type[PatchCheck]]) -> list[str]:
        """Execute the set of checks on the diffs."""
        issues = []

        checks = [
            check(
                author=self.author,
                commit_message=self.commit_message,
                email=self.email,
            )
            for check in patch_checks
        ]

        # Iterate through each diff in the patch and pass it into each check.
        for parsed in self.parsed_diff:
            for check in checks:
                check.next_diff(parsed)

        # Collect the results from each check.
        for check in checks:
            if issue := check.result():
                issues.append(issue)

        return issues


@dataclass
class PatchCollectionCheck:
    """Provides an interface to implement patch collection checks.

    When looping over each patch in the collection, `next_diff` is called to give the
    current diff to the patch as a `PatchHelper` subclass. Then, `result` is
    called to receive the result of the check.
    """

    def next_diff(self, patch_helper: PatchHelper):
        """Pass the next `PatchHelper` into the check."""
        raise NotImplementedError()

    def result(self) -> Optional[str]:
        """Calcuate and return the result of the check."""
        raise NotImplementedError()


@dataclass
class CommitMessagesCheck(PatchCollectionCheck):
    """Check the format of the passed commit message for issues."""

    ignore_bad_commit_message: bool = False
    commit_message_issues: list[str] = field(default_factory=list)

    def next_diff(self, patch_helper: PatchHelper):
        """Pass the next `rs_parsepatch` diff `dict` into the check."""
        commit_message = patch_helper.get_commit_description()
        author, _email = patch_helper.parse_author_information()

        if not commit_message:
            self.commit_message_issues.append("Revision has an empty commit message.")
            return

        firstline = commit_message.splitlines()[0]

        if self.ignore_bad_commit_message or "IGNORE BAD COMMIT MESSAGES" in firstline:
            self.ignore_bad_commit_message = True
            return

        # Ensure backout commit descriptions are well formed.
        if is_backout(firstline):
            backouts = parse_backouts(firstline, strict=True)
            if not backouts or not backouts[0]:
                self.commit_message_issues.append(
                    "Revision is a backout but commit message "
                    "does not indicate backed out revisions."
                )
                return

        # Avoid checks for the merge automation users.
        if author in {"ffxbld", "seabld", "tbirdbld", "cltbld"}:
            return

        # Match against [PATCH] and [PATCH n/m].
        if "[PATCH" in firstline:
            self.commit_message_issues.append(
                "Revision contains git-format-patch '[PATCH]' cruft. Use "
                "git-format-patch -k to avoid this."
            )
            return

        if INVALID_REVIEW_FLAG_RE.search(firstline):
            self.commit_message_issues.append(
                "Revision contains 'r?' in the commit message. "
                "Please use 'r=' instead."
            )
            return

        if firstline.lower().startswith("wip:"):
            self.commit_message_issues.append("Revision seems to be marked as WIP.")
            return

        if any(regex.search(firstline) for regex in ACCEPTABLE_MESSAGE_FORMAT_RES):
            # Exit if the commit message matches any of our acceptable formats.
            # Conditions after this are failure states.
            return

        if firstline.lower().startswith(("back", "revert")):
            # Purposely ambiguous: it's ok to say "backed out rev N" or
            # "reverted to rev N-1"
            self.commit_message_issues.append(
                "Backout revision needs a bug number or a rev id."
            )
            return

        self.commit_message_issues.append(
            "Revision needs 'Bug N' or 'No bug' in the commit message."
        )

    def result(self) -> Optional[str]:
        """Calcuate and return the result of the check."""
        if not self.ignore_bad_commit_message and self.commit_message_issues:
            return ", ".join(self.commit_message_issues)


BMO_SKIP_HINT = "Use `SKIP_BMO_CHECK` in your commit message to push anyway."

BUG_REFERENCES_BMO_ERROR_TEMPLATE = (
    "Could not contact BMO to check for security bugs referenced in commit message. "
    f"{BMO_SKIP_HINT}. Error: {{error}}."
)


@dataclass
class BugReferencesCheck(PatchCollectionCheck):
    """Prevent commit messages referencing non-public bugs from try."""

    bug_ids: set[int] = field(default_factory=set)
    skip_check: bool = False

    def next_diff(self, patch_helper: PatchHelper):
        """Parse each diff for bug references information.

        If `SKIP_BMO_CHECK` is detected in any commit message, set the
        `skip_check` flag so the flag is disabled.
        """
        commit_message = patch_helper.get_commit_description()

        # Skip the check if the `skip_check` flag is set.
        if self.skip_check or "SKIP_BMO_CHECK" in commit_message:
            self.skip_check = True
            return

        self.bug_ids |= set(parse_bugs(commit_message))

    def result(self) -> Optional[str]:
        """Ensure all bug numbers detected in commit messages reference public bugs."""
        if self.skip_check or not self.bug_ids:
            return

        try:
            found_bugs = search_bugs(self.bug_ids)
        except requests.exceptions.RequestException as exc:
            return BUG_REFERENCES_BMO_ERROR_TEMPLATE.format(error=str(exc))

        invalid_bugs = self.bug_ids - found_bugs
        if not invalid_bugs:
            return

        # Check a single bug to determine which error to return.
        bug_id = invalid_bugs.pop()
        try:
            status_code = get_status_code_for_bug(bug_id)
        except requests.exceptions.RequestException as exc:
            return BUG_REFERENCES_BMO_ERROR_TEMPLATE.format(error=str(exc))

        if status_code == 401:
            return (
                f"Your commit message references bug {bug_id}, which is currently private. To avoid "
                "disclosing the nature of this bug publicly, please remove the affected bug ID "
                f"from the commit message. {BMO_SKIP_HINT}"
            )

        if status_code == 404:
            return (
                f"Your commit message references bug {bug_id}, which does not exist. "
                f"Please check your commit message and try again. {BMO_SKIP_HINT}"
            )

        return (
            f"While checking if bug {bug_id} in your commit message is a security bug, "
            f"an error occurred and the bug could not be verified. {BMO_SKIP_HINT}"
        )


@dataclass
class PatchCollectionAssessor:
    """Assess pushes for landing issues."""

    patch_helpers: Iterable[PatchHelper]

    def run_patch_collection_checks(
        self,
        patch_collection_checks: list[Type[PatchCollectionCheck]],
        patch_checks: list[Type[PatchCheck]],
    ) -> list[str]:
        """Execute the set of checks on the diffs, returning a list of issues.

        `push_checks` specifies the push-wide checks to run on the push, otherwise
        all checks will be run.
        """
        issues = []

        checks = [check() for check in patch_collection_checks]

        for patch_helper in self.patch_helpers:
            # Pass the patch information into the push-wide check.
            for check in checks:
                check.next_diff(patch_helper)

            parsed_diff = rs_parsepatch.get_diffs(patch_helper.get_diff())

            author, email = patch_helper.parse_author_information()

            # Run diff-wide checks.
            diff_assessor = DiffAssessor(
                author=author,
                email=email,
                commit_message=patch_helper.get_commit_description(),
                parsed_diff=parsed_diff,
            )
            if diff_issues := diff_assessor.run_diff_checks(patch_checks):
                issues.extend(diff_issues)

        # Collect the result of the push-wide checks.
        for check in checks:
            if issue := check.result():
                issues.append(issue)

        return issues
