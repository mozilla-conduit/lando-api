# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import enum
import rs_parsepatch as pp


class FileType(enum.Enum):
    TEXT = 1
    IMAGE = 2
    BINARY = 3
    DIRECTORY = 4  # Should never show up...
    SYMLINK = 5  # Support symlinks (do we care?)
    DELETED = 6
    NORMAL = 7


class ChangeKind(enum.Enum):
    ADD = 1
    CHANGE = 2
    DELETE = 3
    MOVE_AWAY = 4
    COPY_AWAY = 5
    MOVE_HERE = 6
    COPY_HERE = 7
    MULTICOPY = 8


def lines_to_hunks(lines: list) -> list:
    """Build hunks from straight list of lines"""

    def is_contiguous(x, y):
        if x is None or y is None:
            return True
        return abs(x - y) <= 1

    last_pos = 0
    prev_old, prev_new = None, None
    hunks = []
    for i, (old, new, _) in enumerate(lines):
        if i == 0:
            continue

        prev_old = lines[i - 1][0] or prev_old
        prev_new = lines[i - 1][1] or prev_new
        if i + 1 == len(lines) or (
            not is_contiguous(old, prev_old) and not is_contiguous(new, prev_new)
        ):
            hunks.append(lines[last_pos : i + 1])
            last_pos = i + 1

    return hunks


def serialize_hunk(hunk: list) -> dict:
    prev_op = " "
    old_eof_newline, new_eof_newline = True, True
    corpus = []
    olds = [l[0] for l in hunk if l[0] is not None]
    news = [l[1] for l in hunk if l[1] is not None]
    add_lines, del_lines = 0, 0
    for (old, new, line) in hunk:
        line = line.decode("utf-8")

        # Rebuild each line as patch
        op = " "
        if old is None and new is not None:
            op = "+"
            add_lines += 1
        elif old is not None and new is None:
            op = "-"
            del_lines += 1
        corpus.append(f"{op}{line}")

        # Detect end of lines
        if line.endswith("No newline at end of file"):
            if prev_op != "+":
                old_eof_newline = False
            if prev_op != "-":
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


def serialize_patched_file(f: dict, public_node: str) -> dict:

    # Detect binary or test (not images)
    metadata = {}
    if f["binary"] is True:
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
    if f["new"] is True:
        change_kind = ChangeKind.ADD
    elif f["deleted"] is True:
        change_kind = ChangeKind.DELETE
        old_path = f["filename"]
    elif f["copied_from"] is not None:
        change_kind = ChangeKind.COPY_HERE
        old_path = f["copied_from"]
    elif f["renamed_from"] is not None:
        change_kind = ChangeKind.MOVE_HERE
        old_path = f["renamed_from"]
    else:
        change_kind = ChangeKind.CHANGE
        old_path = f["filename"]

    return {
        "metadata": metadata,
        "oldPath": old_path,
        "currentPath": f["filename"],
        "awayPaths": [old_path]
        if change_kind in (ChangeKind.COPY_HERE, ChangeKind.MOVE_HERE)
        else [],
        "commitHash": public_node,
        "type": change_kind.value,
        "fileType": file_type.value,
        "hunks": [serialize_hunk(hunk) for hunk in lines_to_hunks(f["lines"])],
        # TODO: support unix:filemode
        # See https://github.com/mozilla/pyo3-parsepatch/issues/10
        "oldProperties": {},
        "newProperties": {},
    }


def patch_to_changes(patch_content: str, public_node: str) -> list:
    """Build a list of Phabricator changes from a raw diff"""
    patch = pp.get_diffs(patch_content)
    return [serialize_patched_file(f, public_node) for f in patch]
