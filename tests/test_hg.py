# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import io

import pytest

from landoapi.hg import HgCommandError, HgRepo, NoDiffStartLine, PatchConflict


def test_integrated_hgrepo_clean_repo(hg_clone):
    # Test is long and checks various repo cleaning cases as the startup
    # time for anything using `hg_clone` fixture is very long.
    repo = HgRepo(hg_clone.strpath)

    with repo, hg_clone.as_cwd():
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

    with repo, hg_clone.as_cwd():
        # New context should be clean.
        with pytest.raises(HgCommandError, match="no changes found"):
            repo.run_hg_cmds([["outgoing"]])
        assert not repo.run_hg_cmds([["status"]])


def test_integrated_hgrepo_can_log(hg_clone):
    repo = HgRepo(hg_clone.strpath)
    with repo:
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


PATCH_ADD_NO_NEWLINE_FILE = rb"""
# HG changeset patch
# User Test User <test@example.com>
# Date 0 0
#      Thu Jan 01 00:00:00 1970 +0000
# Diff Start Line 7
file added
diff --git a/test-newline-file b/test-newline-file
new file mode 100644
--- /dev/null
+++ b/test-newline-file
@@ -0,0 +1,1 @@
+hello
\ No newline at end of file
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


def test_integrated_hgrepo_apply_patch(hg_clone):
    repo = HgRepo(hg_clone.strpath)

    # We should refuse to apply patches that are missing a
    # Diff Start Line header.
    with pytest.raises(NoDiffStartLine), repo:
        repo.apply_patch(io.BytesIO(PATCH_WITHOUT_STARTLINE))

    # Patches with conflicts should raise a proper PatchConflict exception.
    with pytest.raises(PatchConflict), repo:
        repo.apply_patch(io.BytesIO(PATCH_WITH_CONFLICT))

    # Patches that fail to be applied by the default import should
    # also be tried using import with the patch command.
    with repo:
        repo.apply_patch(io.BytesIO(PATCH_ADD_NO_NEWLINE_FILE))
        # Commit created.
        assert repo.run_hg_cmds([["outgoing"]])

    with repo:
        repo.apply_patch(io.BytesIO(PATCH_NORMAL))
        # Commit created.
        assert repo.run_hg_cmds([["outgoing"]])
