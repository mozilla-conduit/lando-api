# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import email
import io
import math
import re
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
        remaining_lines = list(line_iterator)
        diff_lines += list(remaining_lines[:-2])
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
