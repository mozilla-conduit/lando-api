# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import email
import io
import math
import re
from dataclasses import dataclass
from datetime import datetime
from email.policy import (
    default as default_email_policy,
)
from email.utils import (
    parseaddr,
)
from typing import (
    Optional,
)

from landoapi.commit_message import (
    ACCEPTABLE_MESSAGE_FORMAT_RES,
    INVALID_REVIEW_FLAG_RE,
    is_backout,
    parse_backouts,
)
from landoapi.repos import Repo

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
    """
    name, email = parseaddr(user_header)
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
            # must be an empty commit. Discard the last two lines of the
            # constructed commit message which are Git version info and return
            # an empty diff.
            commit_message = "\n".join(commit_message_lines[:-2])
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
class DiffAssessor:
    """Assess diffs for landing issues.

    Diffs should be passed in `rs-parsepatch` format.
    """

    parsed_diff: list[dict]
    author: Optional[str] = None
    commit_message: Optional[str] = None
    repo: Optional[Repo] = None

    def check_prevent_symlinks(self) -> Optional[str]:
        """Check for symlinks introduced in the diff."""
        symlinked_files = []
        for parsed in self.parsed_diff:
            modes = parsed["modes"]

            # Check the file mode on each file and ensure the file is not a symlink.
            # `rs_parsepatch` has a `new` and `old` mode key, we are interested in
            # only the newly introduced modes.
            if "new" in modes and modes["new"] == SYMLINK_MODE:
                symlinked_files.append(parsed["filename"])

        if symlinked_files:
            return f"Revision introduces symlinks in the files {wrap_filenames(symlinked_files)}."

    def check_try_task_config(self) -> Optional[str]:
        """Check for `try_task_config.json` introduced in the diff."""
        if self.repo and self.repo.tree == "try":
            return

        for parsed in self.parsed_diff:
            if parsed["filename"] == "try_task_config.json":
                return "Revision introduces the `try_task_config.json` file."

    def check_commit_message(self, is_merge: bool = False) -> Optional[str]:
        """Check the format of the passed commit message for issues."""
        if self.repo and self.repo.tree == "try":
            return

        if self.commit_message is None:
            return

        if not self.commit_message:
            return "Revision has an empty commit message."

        firstline = self.commit_message.splitlines()[0]

        # Ensure backout commit descriptions are well formed.
        if is_backout(firstline):
            backouts = parse_backouts(firstline, strict=True)
            if not backouts or not backouts[0]:
                return "Revision is a backout but commit message does not indicate backed out revisions."

        # Avoid checks for the merge automation user.
        if self.author in {"ffxbld", "seabld", "tbirdbld", "cltbld"}:
            return

        # Match against [PATCH] and [PATCH n/m].
        if "[PATCH" in firstline:
            return (
                "Revision contains git-format-patch '[PATCH]' cruft. Use "
                "git-format-patch -k to avoid this."
            )

        if INVALID_REVIEW_FLAG_RE.search(firstline):
            return (
                "Revision contains 'r?' in the commit message. Please use 'r=' instead."
            )

        if firstline.lower().startswith("wip:"):
            return "Revision seems to be marked as WIP."

        if any(regex.search(firstline) for regex in ACCEPTABLE_MESSAGE_FORMAT_RES):
            # Exit if the commit message matches any of our acceptable formats.
            # Conditions after this are failure states.
            return

        if firstline.lower().startswith(("merge", "merging", "automated merge")):
            if is_merge:
                return

            return "Revision claims to be a merge, but it has only one parent."

        if firstline.lower().startswith(("back", "revert")):
            # Purposely ambiguous: it's ok to say "backed out rev N" or
            # "reverted to rev N-1"
            return "Backout revision needs a bug number or a rev id."

        return "Revision needs 'Bug N' or 'No bug' in the commit message."

    def check_wpt_sync(self) -> Optional[str]:
        """Check the WPT Sync bot has only made changes to relevant subset of the tree."""
        if self.author != "wptsync@mozilla.com":
            return

        if not self.repo or self.repo.tree == "try":
            return

        if self.repo.tree != "mozilla-central":
            return f"WPT Sync bot can not push to {self.repo.tree}."

        disallowed_files = []
        for parsed in self.parsed_diff:
            filename = parsed["filename"]
            if not WPT_SYNC_ALLOWED_PATHS_RE.match(filename):
                disallowed_files.append(filename)

        if disallowed_files:
            return (
                "Revision has WPTSync bot making changes to disallowed files "
                f"{wrap_filenames(disallowed_files)}."
            )

    def build_prevent_nspr_nss_error_message(
        self, nss_disallowed_changes: list[str], nspr_disallowed_changes: list[str]
    ) -> str:
        """Build the `check_prevent_nspr_nss` error message.

        Assumes at least one of `nss_disallowed_changes` or `nspr_disallowed_changes`
        are non-empty lists.
        """
        # Build the error message.
        return_error_message = ["Revision makes changes to restricted directories:"]

        if nss_disallowed_changes:
            return_error_message.append("vendored NSS directories:")

            return_error_message.append(wrap_filenames(nss_disallowed_changes))

        if nspr_disallowed_changes:
            return_error_message.append("vendored NSPR directories:")

            return_error_message.append(wrap_filenames(nspr_disallowed_changes))

        return f"{' '.join(return_error_message)}."

    def check_prevent_nspr_nss(self) -> Optional[str]:
        """Prevent changes to vendored NSPR directories."""
        if not self.repo or not self.commit_message:
            return

        if self.repo.tree == "try":
            return

        nss_disallowed_changes = []
        nspr_disallowed_changes = []
        for parsed in self.parsed_diff:
            filename = parsed["filename"]

            if (
                filename.startswith("security/nss/")
                and "UPGRADE_NSS_RELEASE" not in self.commit_message
            ):
                nss_disallowed_changes.append(filename)

            if (
                filename.startswith("nsprpub/")
                and "UPGRADE_NSPR_RELEASE" not in self.commit_message
            ):
                nspr_disallowed_changes.append(filename)

        if not nss_disallowed_changes and not nspr_disallowed_changes:
            # Return early if no disallowed changes were found.
            return

        return self.build_prevent_nspr_nss_error_message(
            nss_disallowed_changes, nspr_disallowed_changes
        )

    def check_prevent_submodules(self) -> Optional[str]:
        """Prevent introduction of Git submodules into the repository."""
        for parsed in self.parsed_diff:
            if parsed["filename"] == ".gitmodules":
                return "Revision introduces a Git submodule into the repository."

    def run_diff_checks(self) -> list[str]:
        """Execute the set of checks on the diffs."""
        issues = []
        for check in (
            self.check_prevent_symlinks,
            self.check_try_task_config,
            self.check_commit_message,
            self.check_wpt_sync,
            self.check_prevent_nspr_nss,
            self.check_prevent_submodules,
        ):
            if issue := check():
                issues.append(issue)

        return issues
