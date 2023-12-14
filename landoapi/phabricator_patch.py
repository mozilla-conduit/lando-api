# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
# Largely inspired by moz-phab:
# https://github.com/mozilla-conduit/review/blob/1.40/moz-phab#L1187
import enum

import rs_parsepatch


class FileType(enum.Enum):
    """Enum representing the possible filetypes in the Phabricator format."""

    TEXT = 1
    IMAGE = 2
    BINARY = 3
    DIRECTORY = 4  # Should never show up...
    SYMLINK = 5  # Su
    DELETED = 6
    NORMAL = 7


class ChangeKind(enum.Enum):
    """Enum representing the possible change kinds in the Phabricator format."""

    ADD = 1
    CHANGE = 2
    DELETE = 3
    MOVE_AWAY = 4
    COPY_AWAY = 5
    MOVE_HERE = 6
    COPY_HERE = 7
    MULTICOPY = 8


class DiffOperation(enum.Enum):
    """Enum representing the different types of line operations in diffs."""

    NOOP = " "
    ADD = "+"
    DELETE = "-"


def serialize_hunk(hunk: list) -> dict:
    """Convert a list of diff hunks into a dict representation."""
    prev_op = DiffOperation.NOOP
    old_eof_newline, new_eof_newline = True, True
    corpus = []
    olds = []
    news = []
    add_lines, del_lines = 0, 0
    for old, new, line in hunk:
        # Collect all the old and new lines.
        if old is not None:
            olds.append(old)
        if new is not None:
            news.append(new)

        line = line.decode("utf-8")

        # Rebuild each line as patch.
        op = DiffOperation.NOOP
        if old is None and new is not None:
            op = DiffOperation.ADD
            add_lines += 1
        elif old is not None and new is None:
            op = DiffOperation.DELETE
            del_lines += 1
        corpus.append(f"{op.value}{line}")

        # Detect end of lines.
        if line.endswith("No newline at end of file"):
            if prev_op != DiffOperation.ADD:
                old_eof_newline = False
            if prev_op != DiffOperation.DELETE:
                new_eof_newline = False
        prev_op = op

    return {
        "oldOffset": olds[0] if olds else 0,
        "oldLength": olds[-1] - olds[0] + 1 if olds else 0,
        "newOffset": news[0] if news else 0,
        "newLength": news[-1] - news[0] + 1 if news else 0,
        "addLines": add_lines,
        "delLines": del_lines,
        "isMissingOldNewline": not old_eof_newline,
        "isMissingNewNewline": not new_eof_newline,
        "corpus": "\n".join(corpus),
    }


def unix_file_mode(value: int) -> str:
    """Convert a uint32_t into base 8 for unix file modes"""
    return "{:06o}".format(value)


def serialize_patched_file(querydiffs_diff: dict, diff: dict, public_node: str) -> dict:
    """Convert a patch diff from `rs-parsepatch` format to Phabricator format."""
    # Detect binary or test (not images)
    metadata = {}
    if diff["binary"] is True and querydiffs_diff:
        file_type = FileType.BINARY
        # Search the list of changes in the `differential.querydiffs` response for the
        # change the corresponds to this file.
        changes = [
            change
            for change in querydiffs_diff["changes"]
            if change["currentPath"] == diff["filename"]
        ]

        # There should only be one change that corresponds to this file.
        if not changes or len(changes) > 1:
            raise Exception("Found more than one change for this diff.")

        # Use the metadata from the original diff for this new diff, since that diff
        # will already have uploaded the file as binary and will have a PHID that can be
        # used for reference.
        metadata = changes[0]["metadata"]

    elif diff["binary"] is True:
        # We cannot detect the mime type from a file in the patch
        # So no support for image file type
        file_type = FileType.BINARY

        # Add binary metadata
        for upload_type in ("old", "new"):
            metadata[f"{upload_type}:binary-phid"] = None
            # TODO support metadata[f"{upload_type}:file:size"]
            # See https://github.com/mozilla/pyo3-parsepatch/issues/11
    else:
        file_type = FileType.TEXT

    # Detect change kind
    old_path = None
    if diff["new"] is True:
        change_kind = ChangeKind.ADD
    elif diff["deleted"] is True:
        change_kind = ChangeKind.DELETE
        old_path = diff["filename"]
    elif diff["copied_from"] is not None:
        change_kind = ChangeKind.COPY_HERE
        old_path = diff["copied_from"]
    elif diff["renamed_from"] is not None:
        change_kind = ChangeKind.MOVE_HERE
        old_path = diff["renamed_from"]
    else:
        change_kind = ChangeKind.CHANGE
        old_path = diff["filename"]

    # File modes
    old_props = (
        {"unix:filemode": unix_file_mode(diff["modes"]["old"])}
        if "old" in diff["modes"]
        else {}
    )
    new_props = (
        {"unix:filemode": unix_file_mode(diff["modes"]["new"])}
        if "new" in diff["modes"]
        else {}
    )

    return {
        "metadata": metadata,
        "oldPath": old_path,
        "currentPath": diff["filename"],
        "awayPaths": [old_path]
        if change_kind in (ChangeKind.COPY_HERE, ChangeKind.MOVE_HERE)
        else [],
        "commitHash": public_node,
        "type": change_kind.value,
        "fileType": file_type.value,
        "hunks": [serialize_hunk(hunk) for hunk in diff["hunks"]],
        "oldProperties": old_props,
        "newProperties": new_props,
    }


def patch_to_changes(
    querydiffs_diff: dict, patch_content: str, public_node: str
) -> list[dict]:
    """Build a list of Phabricator changes from a raw diff"""
    patch = rs_parsepatch.get_diffs(patch_content, hunks=True)
    return [
        serialize_patched_file(querydiffs_diff, diff, public_node) for diff in patch
    ]
