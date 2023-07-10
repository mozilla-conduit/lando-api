# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import io
import re
from typing import (
    Optional,
)

HG_HEADER_NAMES = (
    b"User",
    b"Date",
    b"Node ID",
    b"Parent",
    b"Diff Start Line",
    b"Fail HG Import",
)
DIFF_LINE_RE = re.compile(rb"^diff\s+\S+\s+\S+")

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


class HgPatchHelper(object):
    """Helper class for parsing Mercurial patches/exports."""

    def __init__(self, fileobj: io.BytesIO):
        self.patch = fileobj
        self.headers = {}
        self.header_end_line_no = 0
        self._parse_header()

        # "Diff Start Line" is a Lando extension to the hg export
        # format meant to prevent injection of diff hunks using the
        # commit message.
        self.diff_start_line = self.header(b"Diff Start Line")
        if self.diff_start_line:
            try:
                self.diff_start_line = int(self.diff_start_line)
            except ValueError:
                self.diff_start_line = None

    @staticmethod
    def _is_diff_line(line: bytes) -> bool:
        return DIFF_LINE_RE.search(line) is not None

    @staticmethod
    def _header_value(line: bytes, prefix: bytes) -> Optional[bytes]:
        m = re.search(
            rb"^#\s+" + re.escape(prefix) + rb"\s+(.*)", line, flags=re.IGNORECASE
        )
        if not m:
            return None
        return m.group(1).strip()

    def _parse_header(self):
        """Extract header values specified by HG_HEADER_NAMES."""
        self.patch.seek(0)
        try:
            for line in self.patch:
                if not line.startswith(b"# "):
                    break
                self.header_end_line_no += 1
                for name in HG_HEADER_NAMES:
                    value = self._header_value(line, name)
                    if value:
                        self.headers[name.lower()] = value
                        break
        finally:
            self.patch.seek(0)

    def header(self, name: bytes | str) -> Optional[bytes]:
        """Returns value of the specified header, or None if missing."""
        name = name.encode("utf-8") if isinstance(name, str) else name
        return self.headers.get(name.lower())

    def commit_description(self) -> bytes:
        """Returns the commit description."""
        try:
            line_no = 0
            commit_desc = []
            for line in self.patch:
                line_no += 1

                if line_no <= self.header_end_line_no:
                    continue

                if self.diff_start_line:
                    if line_no == self.diff_start_line:
                        break
                    commit_desc.append(line)
                else:
                    if self._is_diff_line(line):
                        break
                    commit_desc.append(line)

            return b"".join(commit_desc).strip()
        finally:
            self.patch.seek(0)

    def write(self, f: io.BytesIO):
        """Writes whole patch to the specified file object."""
        try:
            while 1:
                buf = self.patch.read(16 * 1024)
                if not buf:
                    break
                f.write(buf)
        finally:
            self.patch.seek(0)

    def write_commit_description(self, f: io.BytesIO):
        """Writes the commit description to the specified file object."""
        f.write(self.commit_description())

    def write_diff(self, f: io.BytesIO):
        """Writes the diff to the specified file object."""
        try:
            line_no = 0
            for line in self.patch:
                line_no += 1

                if self.diff_start_line:
                    if line_no == self.diff_start_line:
                        f.write(line)
                        break
                else:
                    if self._is_diff_line(line):
                        f.write(line)
                        break

            while 1:
                buf = self.patch.read(16 * 1024)
                if not buf:
                    break
                f.write(buf)
        finally:
            self.patch.seek(0)


class GitPatchHelper(object):
    """Helper class for parsing Mercurial patches/exports."""

    GIT_HEADERS = (
        "From ",
        "From: ",
        "Date: ",
        "Subject: ",
    )

    def __init__(self, fileobj: io.BytesIO):
        self.patch = fileobj
        self.headers = {}

        mail_from_line = next(self.patch)
        if not mail_from_line.startswith(b"From "):
            raise ValueError("Patch is malformed, first line is not `From `.")

        author_from_line = next(self.patch)
        if not author_from_line.startswith(b"From: "):
            raise ValueError("Patch is malformed, second line is not `From:`.")
        self.headers[b"From"] = author_from_line.removeprefix(b"From: ")

        date_line = next(self.patch)
        if not date_line.startswith(b"Date: "):
            raise ValueError("Patch is malformed, third line is not `Date:`.")
        self.headers[b"Date"] = date_line.removeprefix(b"Date: ")

        # Get the main `Subject` header line.
        subject_line = next(self.patch)
        if not subject_line.startswith(b"Subject: "):
            raise ValueError("Patch is malformed, fourth line is not `Subject:`.")
        subject_line = subject_line.removeprefix(b"Subject: ")

        # Get the extended commit message, which ends with a `---` line.
        for line in self.patch:
            if line == b"---\n":
                self.headers[b"Subject"] = subject_line
                break

            subject_line += line
        else:
            raise ValueError(
                "Patch is malformed, commit message does not end with `---`."
            )

        # Move through the patch until we find the start of the diff.
        for line in self.patch:
            if GitPatchHelper._is_diff_line(line):
                break
        else:
            raise ValueError("Patch is malformed, could not find start of patch diff.")

        # The diff is the remainder of the patch.
        self.diff = b"".join(line for line in self.patch)

    @staticmethod
    def _is_diff_line(line: bytes) -> bool:
        return DIFF_LINE_RE.search(line) is not None

    def header(self, name: bytes | str) -> Optional[bytes]:
        """Returns value of the specified header, or None if missing."""
        # TODO do we need to access by both strings and bytes?
        # name = name.encode("utf-8") if isinstance(name, str) else name
        # return self.headers.get(name.lower())
        return self.headers.get(name)

    def commit_description(self) -> bytes:
        """Returns the commit description."""
        try:
            line_no = 0
            commit_desc = []
            for line in self.patch:
                line_no += 1

                if line_no <= self.header_end_line_no:
                    continue

                if self.diff_start_line:
                    if line_no == self.diff_start_line:
                        break
                    commit_desc.append(line)
                else:
                    if self._is_diff_line(line):
                        break
                    commit_desc.append(line)

            return b"".join(commit_desc).strip()
        finally:
            self.patch.seek(0)

    def write(self, f: io.BytesIO):
        """Writes whole patch to the specified file object."""
        try:
            while 1:
                buf = self.patch.read(16 * 1024)
                if not buf:
                    break
                f.write(buf)
        finally:
            self.patch.seek(0)

    def write_commit_description(self, f: io.BytesIO):
        """Writes the commit description to the specified file object."""
        f.write(self.commit_description())

    def write_diff(self, f: io.BytesIO):
        """Writes the diff to the specified file object."""
        try:
            line_no = 0
            for line in self.patch:
                line_no += 1

                if self.diff_start_line:
                    if line_no == self.diff_start_line:
                        f.write(line)
                        break
                else:
                    if self._is_diff_line(line):
                        f.write(line)
                        break

            while 1:
                buf = self.patch.read(16 * 1024)
                if not buf:
                    break
                f.write(buf)
        finally:
            self.patch.seek(0)
