# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import io
import os

import pytest

from landoapi.hg import (
    REQUEST_USER_ENV_VAR,
    HgCommandError,
    HgException,
    HgRepo,
    LostPushRace,
    NoDiffStartLine,
    PatchConflict,
    TreeApprovalRequired,
    TreeClosed,
    hglib,
)


def test_integrated_hgrepo_clean_repo(hg_clone):
    # Test is long and checks various repo cleaning cases as the startup
    # time for anything using `hg_clone` fixture is very long.
    repo = HgRepo(hg_clone.strpath)

    with repo.for_pull(), hg_clone.as_cwd():
        # Create a draft commits to clean.
        new_file = hg_clone.join("new-file.txt")
        new_file.write("text", mode="w+")
        repo.run_hg_cmds(
            [["add", new_file.strpath], ["commit", "-m", "new draft commit"]]
        )
        assert repo.run_hg_cmds([["outgoing"]])

        # Dirty the working directory.
        new_file.write("Extra data", mode="a")
        assert repo.run_hg_cmds([["status"]])

        # Can clean working directory without nuking commits
        repo.clean_repo(strip_non_public_commits=False)
        assert repo.run_hg_cmds([["outgoing"]])
        assert not repo.run_hg_cmds([["status"]])

        # Dirty the working directory again.
        new_file.write("Extra data", mode="a")
        assert repo.run_hg_cmds([["status"]])

        # Cleaning should remove commit and clean working directory.
        repo.clean_repo()
        with pytest.raises(HgCommandError, match="no changes found"):
            repo.run_hg_cmds([["outgoing"]])
        assert not repo.run_hg_cmds([["status"]])

        # Create a commit and dirty the directory before exiting
        # the context manager as entering a new context should
        # provide a clean repo.
        new_file.write("text", mode="w+")
        repo.run_hg_cmds(
            [["add", new_file.strpath], ["commit", "-m", "new draft commit"]]
        )
        new_file.write("extra data", mode="a")
        assert repo.run_hg_cmds([["outgoing"]])
        assert repo.run_hg_cmds([["status"]])

    with repo.for_pull(), hg_clone.as_cwd():
        # New context should be clean.
        with pytest.raises(HgCommandError, match="no changes found"):
            repo.run_hg_cmds([["outgoing"]])
        assert not repo.run_hg_cmds([["status"]])


def test_integrated_hgrepo_can_log(hg_clone):
    repo = HgRepo(hg_clone.strpath)
    with repo.for_pull():
        assert repo.run_hg_cmds([["log"]])


PATCH_WITHOUT_STARTLINE = rb"""
# HG changeset patch
# User Test User <test@example.com>
# Date 0 0
#      Thu Jan 01 00:00:00 1970 +0000
add another file.
diff --git a/test.txt b/test.txt
--- a/test.txt
+++ b/test.txt
@@ -1,1 +1,2 @@
 TEST
+adding another line
""".strip()


PATCH_WITH_CONFLICT = rb"""
# HG changeset patch
# User Test User <test@example.com>
# Date 0 0
#      Thu Jan 01 00:00:00 1970 +0000
# Diff Start Line 7
Add to a file that doesn't exist
diff --git a/not-real.txt b/not-real.txt
--- a/not-real.txt
+++ b/not-real.txt
@@ -1,1 +1,2 @@
 TEST
+This line doesn't exist
""".strip()


PATCH_DELETE_NO_NEWLINE_FILE = b"""
# HG changeset patch
# User Test User <test@example.com>
# Date 0 0
#      Thu Jan 01 00:00:00 1970 +0000
# Diff Start Line 7
file removed

diff --git a/test-file b/test-file
deleted file mode 100644
--- a/test-file
+++ /dev/null
@@ -1,1 +0,0 @@
-hello\r
\\ No newline at end of file
""".strip()

PATCH_NORMAL = rb"""
# HG changeset patch
# User Test User <test@example.com>
# Date 0 0
#      Thu Jan 01 00:00:00 1970 +0000
# Diff Start Line 7
add another file.
diff --git a/test.txt b/test.txt
--- a/test.txt
+++ b/test.txt
@@ -1,1 +1,2 @@
 TEST
+adding another line
""".strip()

PATCH_UNICODE = r"""
# HG changeset patch
# User Test User <test@example.com>
# Date 0 0
#      Thu Jan 01 00:00:00 1970 +0000
# Diff Start Line 7
Bug 1 - こんにちは; r?cthulhu
diff --git a/test.txt b/test.txt
--- a/test.txt
+++ b/test.txt
@@ -1,1 +1,2 @@
 TEST
+adding another line
""".strip().encode(
    "utf-8"
)

PATCH_FAIL_HEADER = b"""
# HG changeset patch
# User Test User <test@example.com>
# Date 0 0
#      Thu Jan 01 00:00:00 1970 +0000
# Fail HG Import FAIL
# Diff Start Line 8
add another file.
diff --git a/test.txt b/test.txt
--- a/test.txt
+++ b/test.txt
@@ -1,1 +1,2 @@
 TEST
+adding another line
""".strip()


def test_integrated_hgrepo_apply_patch(hg_clone):
    repo = HgRepo(hg_clone.strpath)

    # We should refuse to apply patches that are missing a
    # Diff Start Line header.
    with pytest.raises(NoDiffStartLine), repo.for_pull():
        repo.apply_patch(io.BytesIO(PATCH_WITHOUT_STARTLINE))

    # Patches with conflicts should raise a proper PatchConflict exception.
    with pytest.raises(PatchConflict), repo.for_pull():
        repo.apply_patch(io.BytesIO(PATCH_WITH_CONFLICT))

    with repo.for_pull():
        repo.apply_patch(io.BytesIO(PATCH_NORMAL))
        # Commit created.
        assert repo.run_hg(["outgoing"])

    with repo.for_pull():
        repo.apply_patch(io.BytesIO(PATCH_UNICODE))
        # Commit created.

        log_output = repo.run_hg(["log"])
        assert "こんにちは" in log_output.decode("utf-8")
        assert repo.run_hg(["outgoing"])

    with repo.for_pull():
        repo.apply_patch(io.BytesIO(PATCH_FAIL_HEADER))
        # Commit created.
        assert repo.run_hg(["outgoing"])


def test_integrated_hgrepo_apply_patch_newline_bug(hg_clone):
    """Test newline bug in Mercurial

    See https://bugzilla.mozilla.org/show_bug.cgi?id=1541181 for context.
    """
    repo = HgRepo(hg_clone.strpath)

    with repo.for_pull(), hg_clone.as_cwd():
        # Create a file without a new line and with a trailing `\r`
        # Note that to reproduce this bug, this file needs to already exist
        # in the repo and not be imported in a patch.
        new_file = hg_clone.join("test-file")
        new_file.write(b"hello\r", mode="wb")
        repo.run_hg_cmds(
            [["add", new_file.strpath], ["commit", "-m", "adding file"], ["push"]]
        )
        repo.apply_patch(io.BytesIO(PATCH_DELETE_NO_NEWLINE_FILE))
        # Commit created.
        assert "file removed" in str(repo.run_hg(["outgoing"]))


def test_hg_exceptions():
    """Ensure the correct exception is raised if a particular snippet is present."""
    snippet_exception_mapping = {
        b"abort: push creates new remote head": LostPushRace,
        b"APPROVAL REQUIRED!": TreeApprovalRequired,
        b"is CLOSED!": TreeClosed,
        b"unresolved conflicts (see hg resolve": PatchConflict,
    }

    for snippet, exception in snippet_exception_mapping.items():
        exc = hglib.error.CommandError((), 1, b"", snippet)
        with pytest.raises(exception):
            raise HgException.from_hglib_error(exc)


def test_hgrepo_request_user(hg_clone):
    """Test that the request user environment variable is set and unset correctly."""
    repo = HgRepo(hg_clone.strpath)
    request_user_email = "test@example.com"

    assert REQUEST_USER_ENV_VAR not in os.environ
    with repo.for_push(request_user_email):
        assert REQUEST_USER_ENV_VAR in os.environ
        assert os.environ[REQUEST_USER_ENV_VAR] == "test@example.com"
    assert REQUEST_USER_ENV_VAR not in os.environ
