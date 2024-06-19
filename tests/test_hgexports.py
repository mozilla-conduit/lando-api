# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import io

import pytest
import rs_parsepatch

from landoapi.hgexports import (
    DiffAssessor,
    GitPatchHelper,
    HgPatchHelper,
    build_patch_for_revision,
)
from landoapi.repos import get_repos_for_env

GIT_DIFF_FROM_REVISION = """diff --git a/hello.c b/hello.c
--- a/hello.c   Fri Aug 26 01:21:28 2005 -0700
+++ b/hello.c   Mon May 05 01:20:46 2008 +0200
@@ -12,5 +12,6 @@
 int main(int argc, char **argv)
 {
        printf("hello, world!\n");
+       printf("sure am glad I'm using Mercurial!\n");
        return 0;
 }
"""

COMMIT_MESSAGE = """
Express great joy at existence of Mercurial

Make sure multiple line breaks are kept:



Using console to print out the messages.
""".strip()

HG_PATCH = """# HG changeset patch
# User Joe User <joe@example.com>
# Date 1496239141 +0000
# Diff Start Line 12
Express great joy at existence of Mercurial

Make sure multiple line breaks are kept:



Using console to print out the messages.

diff --git a/hello.c b/hello.c
--- a/hello.c   Fri Aug 26 01:21:28 2005 -0700
+++ b/hello.c   Mon May 05 01:20:46 2008 +0200
@@ -12,5 +12,6 @@
 int main(int argc, char **argv)
 {
        printf("hello, world!\n");
+       printf("sure am glad I'm using Mercurial!\n");
        return 0;
 }
"""

GIT_PATCH = r"""
From 0f5a3c99e12c1e9b0e81bed245fe537961f89e57 Mon Sep 17 00:00:00 2001
From: Connor Sheehan <sheehan@mozilla.com>
Date: Wed, 6 Jul 2022 16:36:09 -0400
Subject: [PATCH] errors: add a maintenance-mode specific title to serverside
 error handlers (Bug 1724769)

Adds a conditional to the Lando-API exception handlers that
shows a maintenance-mode specific title when a 503 error is
returned from Lando. This should inform users that Lando is
unavailable at the moment and is not broken.
---
 landoui/errorhandlers.py | 8 +++++++-
 1 file changed, 7 insertions(+), 1 deletion(-)

diff --git a/landoui/errorhandlers.py b/landoui/errorhandlers.py
index f56ba1c..33391ea 100644
--- a/landoui/errorhandlers.py
+++ b/landoui/errorhandlers.py
@@ -122,10 +122,16 @@ def landoapi_exception(e):
     sentry.captureException()
     logger.exception("Uncaught communication exception with Lando API.")

+    if e.status_code == 503:
+        # Show a maintenance-mode specific title if we get a 503.
+        title = "Lando is undergoing maintenance and is temporarily unavailable"
+    else:
+        title = "Lando API returned an unexpected error"
+
     return (
         render_template(
             "errorhandlers/default_error.html",
-            title="Lando API returned an unexpected error",
+            title=title,
             message=str(e),
         ),
         500,
--
2.31.1


""".lstrip()

GIT_PATCH_ONLY_DIFF = """diff --git a/landoui/errorhandlers.py b/landoui/errorhandlers.py
index f56ba1c..33391ea 100644
--- a/landoui/errorhandlers.py
+++ b/landoui/errorhandlers.py
@@ -122,10 +122,16 @@ def landoapi_exception(e):
     sentry.captureException()
     logger.exception("Uncaught communication exception with Lando API.")

+    if e.status_code == 503:
+        # Show a maintenance-mode specific title if we get a 503.
+        title = "Lando is undergoing maintenance and is temporarily unavailable"
+    else:
+        title = "Lando API returned an unexpected error"
+
     return (
         render_template(
             "errorhandlers/default_error.html",
-            title="Lando API returned an unexpected error",
+            title=title,
             message=str(e),
         ),
         500,
""".rstrip()

GIT_PATCH_EMPTY = """
From 0f5a3c99e12c1e9b0e81bed245fe537961f89e57 Mon Sep 17 00:00:00 2001
From: Connor Sheehan <sheehan@mozilla.com>
Date: Wed, 6 Jul 2022 16:36:09 -0400
Subject: [PATCH] errors: add a maintenance-mode specific title to serverside
 error handlers (Bug 1724769)

Adds a conditional to the Lando-API exception handlers that
shows a maintenance-mode specific title when a 503 error is
returned from Lando. This should inform users that Lando is
unavailable at the moment and is not broken.
--
2.31.1
""".strip()

GIT_DIFF_FILENAME_TEMPLATE = """
diff --git a/{filename} b/{filename}
--- a/{filename}
+++ b/{filename}
@@ -12,5 +12,6 @@
 int main(int argc, char **argv)
 {{
        printf("hello, world!\n");
+       printf("sure am glad I'm using Mercurial!\n");
        return 0;
 }}
""".lstrip()


def test_build_patch():
    patch = build_patch_for_revision(
        GIT_DIFF_FROM_REVISION,
        "Joe User",
        "joe@example.com",
        COMMIT_MESSAGE,
        "1496239141",
    )

    assert patch == HG_PATCH


@pytest.mark.parametrize(
    "line, expected",
    [
        ("diff --git a/file b/file", True),
        ("diff a/file b/file", True),
        ("diff -r 23280edf8655 autoland/autoland/patch_helper.py", True),
        ("cheese", False),
        ("diff", False),
        ("diff ", False),
        ("diff file", False),
    ],
)
def test_patchhelper_is_diff_line(line, expected):
    assert bool(HgPatchHelper._is_diff_line(line)) is expected


def test_patchhelper_vanilla_export():
    patch = HgPatchHelper(
        io.StringIO(
            """
# HG changeset patch
# User byron jones <glob@mozilla.com>
# Date 1523427125 -28800
#      Wed Apr 11 14:12:05 2018 +0800
# Node ID 3379ea3cea34ecebdcb2cf7fb9f7845861ea8f07
# Parent  46c36c18528fe2cc780d5206ed80ae8e37d3545d
WIP transplant and diff-start-line

diff --git a/autoland/autoland/transplant.py b/autoland/autoland/transplant.py
--- a/autoland/autoland/transplant.py
+++ b/autoland/autoland/transplant.py
@@ -318,24 +318,58 @@ class PatchTransplant(Transplant):
# instead of passing the url to 'hg import' to make
...
""".strip()
        )
    )
    assert patch.get_header("Date") == "1523427125 -28800"
    assert patch.get_header("Node ID") == "3379ea3cea34ecebdcb2cf7fb9f7845861ea8f07"
    assert patch.get_header("User") == "byron jones <glob@mozilla.com>"
    assert patch.get_header("Parent") == "46c36c18528fe2cc780d5206ed80ae8e37d3545d"
    assert patch.get_commit_description() == "WIP transplant and diff-start-line"


def test_patchhelper_start_line():
    patch = HgPatchHelper(
        io.StringIO(
            """
# HG changeset patch
# User byron jones <glob@mozilla.com>
# Date 1523427125 -28800
#      Wed Apr 11 14:12:05 2018 +0800
# Node ID 3379ea3cea34ecebdcb2cf7fb9f7845861ea8f07
# Parent  46c36c18528fe2cc780d5206ed80ae8e37d3545d
# Diff Start Line 10
WIP transplant and diff-start-line

diff --git a/autoland/autoland/transplant.py b/autoland/autoland/transplant.py
--- a/autoland/autoland/transplant.py
+++ b/autoland/autoland/transplant.py
@@ -318,24 +318,58 @@ class PatchTransplant(Transplant):
# instead of passing the url to 'hg import' to make
...
""".strip()
        )
    )
    assert patch.get_header("Diff Start Line") == "10"
    assert patch.get_commit_description() == "WIP transplant and diff-start-line"


def test_patchhelper_no_header():
    patch = HgPatchHelper(
        io.StringIO(
            """
WIP transplant and diff-start-line

diff --git a/autoland/autoland/transplant.py b/autoland/autoland/transplant.py
--- a/autoland/autoland/transplant.py
+++ b/autoland/autoland/transplant.py
@@ -318,24 +318,58 @@ class PatchTransplant(Transplant):
# instead of passing the url to 'hg import' to make
...
""".strip()
        )
    )
    assert patch.get_header("User") is None
    assert patch.get_commit_description() == "WIP transplant and diff-start-line"


def test_patchhelper_diff_injection_no_start_line():
    patch = HgPatchHelper(
        io.StringIO(
            """
# HG changeset patch
# User byron jones <glob@mozilla.com>
# Date 1523427125 -28800
#      Wed Apr 11 14:12:05 2018 +0800
# Node ID 3379ea3cea34ecebdcb2cf7fb9f7845861ea8f07
# Parent  46c36c18528fe2cc780d5206ed80ae8e37d3545d
WIP transplant and diff-start-line

diff --git a/bad b/bad
@@ -0,0 +0,0 @@
blah

diff --git a/autoland/autoland/transplant.py b/autoland/autoland/transplant.py
--- a/autoland/autoland/transplant.py
+++ b/autoland/autoland/transplant.py
@@ -318,24 +318,58 @@ class PatchTransplant(Transplant):
# instead of passing the url to 'hg import' to make
...
""".strip()
        )
    )
    assert patch.get_commit_description() == "WIP transplant and diff-start-line"


def test_patchhelper_diff_injection_start_line():
    patch = HgPatchHelper(
        io.StringIO(
            """
# HG changeset patch
# User byron jones <glob@mozilla.com>
# Date 1523427125 -28800
#      Wed Apr 11 14:12:05 2018 +0800
# Node ID 3379ea3cea34ecebdcb2cf7fb9f7845861ea8f07
# Parent  46c36c18528fe2cc780d5206ed80ae8e37d3545d
# Diff Start Line 14
WIP transplant and diff-start-line

diff --git a/bad b/bad
@@ -0,0 +0,0 @@
blah

diff --git a/autoland/autoland/transplant.py b/autoland/autoland/transplant.py
--- a/autoland/autoland/transplant.py
+++ b/autoland/autoland/transplant.py
@@ -318,24 +318,58 @@ class PatchTransplant(Transplant):
# instead of passing the url to 'hg import' to make
...
""".strip()
        )
    )
    assert patch.get_commit_description() == (
        "WIP transplant and diff-start-line\n"
        "\n"
        "diff --git a/bad b/bad\n"
        "@@ -0,0 +0,0 @@\n"
        "blah"
    )


def test_patchhelper_write_start_line():
    header = """
# HG changeset patch
# User byron jones <glob@mozilla.com>
# Date 1523427125 -28800
#      Wed Apr 11 14:12:05 2018 +0800
# Node ID 3379ea3cea34ecebdcb2cf7fb9f7845861ea8f07
# Parent  46c36c18528fe2cc780d5206ed80ae8e37d3545d
# Diff Start Line 10
""".strip()
    commit_desc = """
WIP transplant and diff-start-line
""".strip()
    diff = """
diff --git a/autoland/autoland/transplant.py b/autoland/autoland/transplant.py
--- a/autoland/autoland/transplant.py
+++ b/autoland/autoland/transplant.py
@@ -318,24 +318,58 @@ class PatchTransplant(Transplant):
# instead of passing the url to 'hg import' to make
...
""".strip()
    patch = HgPatchHelper(io.StringIO("%s\n%s\n\n%s" % (header, commit_desc, diff)))

    buf = io.StringIO("")
    patch.write_commit_description(buf)
    assert buf.getvalue() == commit_desc

    buf = io.StringIO("")
    patch.write_diff(buf)
    assert buf.getvalue() == diff


def test_patchhelper_write_no_start_line():
    header = """
# HG changeset patch
# User byron jones <glob@mozilla.com>
# Date 1523427125 -28800
#      Wed Apr 11 14:12:05 2018 +0800
# Node ID 3379ea3cea34ecebdcb2cf7fb9f7845861ea8f07
# Parent  46c36c18528fe2cc780d5206ed80ae8e37d3545d
""".strip()
    commit_desc = """
WIP transplant and diff-start-line
""".strip()
    diff = """
diff --git a/autoland/autoland/transplant.py b/autoland/autoland/transplant.py
--- a/autoland/autoland/transplant.py
+++ b/autoland/autoland/transplant.py
@@ -318,24 +318,58 @@ class PatchTransplant(Transplant):
# instead of passing the url to 'hg import' to make
...
""".strip()
    patch = HgPatchHelper(io.StringIO(f"{header}\n{commit_desc}\n\n{diff}"))

    buf = io.StringIO("")
    patch.write_commit_description(buf)
    assert buf.getvalue() == commit_desc

    assert patch.get_diff() == diff

    buf = io.StringIO("")
    patch.write_diff(buf)
    assert buf.getvalue() == diff


def test_git_formatpatch_helper_parse():
    patch = GitPatchHelper(io.StringIO(GIT_PATCH))
    assert (
        patch.get_header("From") == "Connor Sheehan <sheehan@mozilla.com>"
    ), "`From` header should contain author information."
    assert (
        patch.get_header("Date") == "Wed, 06 Jul 2022 16:36:09 -0400"
    ), "`Date` header should contain raw date info."
    assert patch.get_header("Subject") == (
        "[PATCH] errors: add a maintenance-mode specific title to serverside error handlers "
        "(Bug 1724769)"
    ), "`Subject` header should contain raw subject header."
    assert patch.get_commit_description() == (
        "errors: add a maintenance-mode specific title to serverside error handlers "
        "(Bug 1724769)\n\n"
        "Adds a conditional to the Lando-API exception handlers that\n"
        "shows a maintenance-mode specific title when a 503 error is\n"
        "returned from Lando. This should inform users that Lando is\n"
        "unavailable at the moment and is not broken."
    ), "`commit_description()` should return full commit message."
    assert (
        patch.get_diff() == GIT_PATCH_ONLY_DIFF
    ), "`get_diff()` should return the full diff."


def test_git_formatpatch_helper_empty_commit():
    patch = GitPatchHelper(io.StringIO(GIT_PATCH_EMPTY))
    assert (
        patch.get_header("From") == "Connor Sheehan <sheehan@mozilla.com>"
    ), "`From` header should contain author information."
    assert (
        patch.get_header("Date") == "Wed, 06 Jul 2022 16:36:09 -0400"
    ), "`Date` header should contain raw date info."
    assert patch.get_header("Subject") == (
        "[PATCH] errors: add a maintenance-mode specific title to serverside error handlers "
        "(Bug 1724769)"
    ), "`Subject` header should contain raw subject header."
    assert patch.get_commit_description() == (
        "errors: add a maintenance-mode specific title to serverside error handlers "
        "(Bug 1724769)\n\n"
        "Adds a conditional to the Lando-API exception handlers that\n"
        "shows a maintenance-mode specific title when a 503 error is\n"
        "returned from Lando. This should inform users that Lando is\n"
        "unavailable at the moment and is not broken."
    ), "`commit_description()` should return full commit message."
    assert patch.get_diff() == "", "`get_diff()` should return an empty string."


def test_strip_git_version_info_lines():
    lines = [
        "blah",
        "blah",
        "--",
        "git version info",
        "",
        "",
    ]

    assert GitPatchHelper.strip_git_version_info_lines(lines) == [
        "blah",
        "blah",
    ]


def test_check_commit_message_api_states(mocked_repo_config):
    supported_repos = get_repos_for_env("test")
    parsed_diff = rs_parsepatch.get_diffs(GIT_DIFF_FROM_REVISION)

    # Test check doesn't run on try.
    try_repo = supported_repos["try"]
    diff_assessor = DiffAssessor(
        parsed_diff=parsed_diff, repo=try_repo, commit_message=COMMIT_MESSAGE
    )
    assert (
        diff_assessor.check_commit_message() is None
    ), "Commit message check should pass when repo is `try`."

    # Test check doesn't run for null commit message.
    valid_repo = supported_repos["mozilla-central"]
    diff_assessor = DiffAssessor(parsed_diff=parsed_diff, repo=valid_repo)
    assert (
        diff_assessor.check_commit_message() is None
    ), "Commit message check should pass if `commit_message` is `None`."

    # Test check fails for empty commit message.
    diff_assessor = DiffAssessor(
        parsed_diff=parsed_diff, repo=valid_repo, commit_message=""
    )
    assert (
        diff_assessor.check_commit_message() == "Revision has an empty commit message."
    ), "Commit message check should fail if a commit message is passed but it is empty."

    # Test check passed for merge automation user.
    diff_assessor = DiffAssessor(
        parsed_diff=parsed_diff,
        repo=valid_repo,
        commit_message=COMMIT_MESSAGE,
        author="ffxbld",
    )
    assert (
        diff_assessor.check_commit_message() is None
    ), "Commit message check should pass if a merge automation user is the author."


@pytest.mark.parametrize(
    "commit_message,error_message",
    [
        (
            "Bug 123: this message has a bug number",
            "Bug XYZ syntax is accepted.",
        ),
        (
            "No bug: this message has a bug number",
            "'No bug' syntax is accepted.",
        ),
        (
            "Backed out changeset 4910f543acd8",
            "'Backed out' backout syntax is accepted.",
        ),
        (
            "Backout of ceac31c0ce89 due to bustage",
            "'Backout of' backout syntax is accepted.",
        ),
        (
            "Revert to changeset 41f80b316d60 due to incomplete backout",
            "'Revert to' backout syntax is accepted.",
        ),
        (
            "Backout changesets  9e4ab3907b29, 3abc0dbbf710 due to m-oth permaorange",
            "Multiple changesets are allowed for backout syntax.",
        ),
        (
            "Added tag AURORA_BASE_20110412 for changeset 2d4e565cf83f",
            "Tag syntax should be allowed.",
        ),
    ],
)
def test_check_commit_message_valid_message(
    mocked_repo_config, commit_message, error_message
):
    supported_repos = get_repos_for_env("test")
    parsed_diff = rs_parsepatch.get_diffs(GIT_DIFF_FROM_REVISION)
    valid_repo = supported_repos["mozilla-central"]

    diff_assessor = DiffAssessor(
        parsed_diff=parsed_diff, repo=valid_repo, commit_message=commit_message
    )
    assert diff_assessor.check_commit_message() is None, error_message


@pytest.mark.parametrize(
    "commit_message,return_string,error_message",
    [
        (
            "this message is missing the bug.",
            "Revision needs 'Bug N' or 'No bug' in the commit message.",
            "Commit message is rejected without a bug number.",
        ),
        (
            "Mass revert m-i to the last known good state",
            "Revision needs 'Bug N' or 'No bug' in the commit message.",
            "Revision missing a bug number or no bug should result in a failed check.",
        ),
        (
            "update revision of Add-on SDK tests to latest tip; test-only",
            "Revision needs 'Bug N' or 'No bug' in the commit message.",
            "Revision missing a bug number or no bug should result in a failed check.",
        ),
        (
            "Fix stupid bug in foo::bar()",
            "Revision needs 'Bug N' or 'No bug' in the commit message.",
            "Commit message with 'bug' bug in improper format should result in a failed check.",
        ),
        (
            "Back out Dao's push because of build bustage",
            "Revision is a backout but commit message does not indicate backed out revisions.",
            "Backout should be rejected when a reference to the original patch is missing.",
        ),
        (
            "Bug 100 - Foo. r?bar",
            "Revision contains 'r?' in the commit message. Please use 'r=' instead.",
            "Improper review specifier should be rejected.",
        ),
        (
            "WIP: bug 123: this is a wip r=reviewer",
            "Revision seems to be marked as WIP.",
            "WIP revisions should be rejected.",
        ),
        (
            "[PATCH 1/2] first part of my git patch",
            (
                "Revision contains git-format-patch '[PATCH]' cruft. "
                "Use git-format-patch -k to avoid this."
            ),
            "`git-format-patch` cruft should result in a failed check.",
        ),
    ],
)
def test_check_commit_message_invalid_message(
    mocked_repo_config, commit_message, return_string, error_message
):
    supported_repos = get_repos_for_env("test")
    parsed_diff = rs_parsepatch.get_diffs(GIT_DIFF_FROM_REVISION)
    valid_repo = supported_repos["mozilla-central"]

    diff_assessor = DiffAssessor(
        parsed_diff=parsed_diff, repo=valid_repo, commit_message=commit_message
    )
    assert diff_assessor.check_commit_message() == return_string, error_message


def test_check_wpt_sync_irrelevant_user(mocked_repo_config):
    supported_repos = get_repos_for_env("test")
    valid_repo = supported_repos["mozilla-central"]

    parsed_diff = rs_parsepatch.get_diffs(
        GIT_DIFF_FILENAME_TEMPLATE.format(filename="somefile.txt")
    )
    diff_assessor = DiffAssessor(
        author="sheehan@mozilla.com",
        parsed_diff=parsed_diff,
        repo=valid_repo,
        commit_message=COMMIT_MESSAGE,
    )
    assert (
        diff_assessor.check_wpt_sync() is None
    ), "Check should pass when user is not `wptsync@mozilla.com`."


def test_check_wpt_sync_no_repo():
    parsed_diff = rs_parsepatch.get_diffs(
        GIT_DIFF_FILENAME_TEMPLATE.format(filename="somefile.txt")
    )
    diff_assessor = DiffAssessor(
        author="wptsync@mozilla.com",
        parsed_diff=parsed_diff,
        commit_message=COMMIT_MESSAGE,
    )
    assert (
        diff_assessor.check_wpt_sync() is None
    ), "Check should pass without repo information."


def test_check_wpt_sync_try(mocked_repo_config):
    supported_repos = get_repos_for_env("test")
    try_repo = supported_repos["try"]

    parsed_diff = rs_parsepatch.get_diffs(
        GIT_DIFF_FILENAME_TEMPLATE.format(filename="somefile.txt")
    )
    diff_assessor = DiffAssessor(
        author="wptsync@mozilla.com",
        parsed_diff=parsed_diff,
        commit_message=COMMIT_MESSAGE,
        repo=try_repo,
    )
    assert diff_assessor.check_wpt_sync() is None, "Check should pass for try repo."


def test_check_wpt_sync_non_central_repo(mocked_repo_config):
    supported_repos = get_repos_for_env("test")
    invalid_repo = supported_repos["mozilla-new"]

    parsed_diff = rs_parsepatch.get_diffs(
        GIT_DIFF_FILENAME_TEMPLATE.format(filename="somefile.txt")
    )
    diff_assessor = DiffAssessor(
        author="wptsync@mozilla.com",
        parsed_diff=parsed_diff,
        commit_message=COMMIT_MESSAGE,
        repo=invalid_repo,
    )
    assert (
        diff_assessor.check_wpt_sync() == "WPT Sync bot can not push to mozilla-new."
    ), "Check should fail if WPTSync bot pushes to disallowed repo."


def test_check_wpt_sync_invalid_paths(mocked_repo_config):
    supported_repos = get_repos_for_env("test")
    valid_repo = supported_repos["mozilla-central"]

    parsed_diff = rs_parsepatch.get_diffs(
        GIT_DIFF_FILENAME_TEMPLATE.format(filename="somefile.txt")
    )
    diff_assessor = DiffAssessor(
        author="wptsync@mozilla.com",
        parsed_diff=parsed_diff,
        commit_message=COMMIT_MESSAGE,
        repo=valid_repo,
    )
    assert diff_assessor.check_wpt_sync() == (
        "Revision has WPTSync bot making changes to disallowed " "files `somefile.txt`."
    ), "Check should fail if WPTSync bot pushes disallowed files."


def test_check_wpt_sync_valid_paths(mocked_repo_config):
    supported_repos = get_repos_for_env("test")
    valid_repo = supported_repos["mozilla-central"]

    parsed_diff = rs_parsepatch.get_diffs(
        GIT_DIFF_FILENAME_TEMPLATE.format(filename="testing/web-platform/moz.build")
    )
    diff_assessor = DiffAssessor(
        author="wptsync@mozilla.com",
        parsed_diff=parsed_diff,
        commit_message=COMMIT_MESSAGE,
        repo=valid_repo,
    )
    assert (
        diff_assessor.check_wpt_sync() is None
    ), "Check should pass if WPTSync bot makes changes to allowed files."


def test_check_prevent_nspr_nss_missing_fields(mocked_repo_config):
    supported_repos = get_repos_for_env("test")
    valid_repo = supported_repos["mozilla-central"]

    parsed_diff = rs_parsepatch.get_diffs(
        GIT_DIFF_FILENAME_TEMPLATE.format(filename="security/nss/testfile.txt")
    )
    diff_assessor = DiffAssessor(
        author="testuser@mozilla.com",
        parsed_diff=parsed_diff,
        repo=valid_repo,
    )
    assert (
        diff_assessor.check_prevent_nspr_nss() is None
    ), "Missing commit message should result in passing check."

    diff_assessor = DiffAssessor(
        author="wptsync@mozilla.com",
        parsed_diff=parsed_diff,
        commit_message=COMMIT_MESSAGE,
    )
    assert (
        diff_assessor.check_prevent_nspr_nss() is None
    ), "Missing repo should result in passing check."


def test_check_prevent_nspr_nss_try_allowed(mocked_repo_config):
    supported_repos = get_repos_for_env("test")
    valid_repo = supported_repos["try"]

    parsed_diff = rs_parsepatch.get_diffs(
        GIT_DIFF_FILENAME_TEMPLATE.format(filename="security/nss/testfile.txt")
    )
    diff_assessor = DiffAssessor(
        author="testuser@mozilla.com",
        parsed_diff=parsed_diff,
        repo=valid_repo,
        commit_message=COMMIT_MESSAGE,
    )
    assert (
        diff_assessor.check_prevent_nspr_nss() is None
    ), "Check should pass for disallowed changes pushed to try."


def test_check_prevent_nspr_nss_nss(mocked_repo_config):
    supported_repos = get_repos_for_env("test")
    valid_repo = supported_repos["mozilla-central"]

    parsed_diff = rs_parsepatch.get_diffs(
        GIT_DIFF_FILENAME_TEMPLATE.format(filename="security/nss/testfile.txt")
    )
    diff_assessor = DiffAssessor(
        author="testuser@mozilla.com",
        parsed_diff=parsed_diff,
        repo=valid_repo,
        commit_message=COMMIT_MESSAGE,
    )
    assert diff_assessor.check_prevent_nspr_nss() == (
        "Revision makes changes to restricted directories: vendored NSS directories: "
        "`security/nss/testfile.txt`."
    ), "Check should disallow changes to NSS without proper commit message."

    diff_assessor = DiffAssessor(
        author="testuser@mozilla.com",
        parsed_diff=parsed_diff,
        repo=valid_repo,
        commit_message="bug 123: upgrade NSS UPGRADE_NSS_RELEASE",
    )
    assert (
        diff_assessor.check_prevent_nspr_nss() is None
    ), "Check should allow changes to NSS with proper commit message."


def test_check_prevent_nspr_nss_nspr(mocked_repo_config):
    supported_repos = get_repos_for_env("test")
    valid_repo = supported_repos["mozilla-central"]

    parsed_diff = rs_parsepatch.get_diffs(
        GIT_DIFF_FILENAME_TEMPLATE.format(filename="nsprpub/testfile.txt")
    )
    diff_assessor = DiffAssessor(
        author="testuser@mozilla.com",
        parsed_diff=parsed_diff,
        repo=valid_repo,
        commit_message=COMMIT_MESSAGE,
    )
    assert diff_assessor.check_prevent_nspr_nss() == (
        "Revision makes changes to restricted directories: vendored NSPR directories: "
        "`nsprpub/testfile.txt`."
    ), "Check should disallow changes to NSPR without proper commit message."

    diff_assessor = DiffAssessor(
        author="testuser@mozilla.com",
        parsed_diff=parsed_diff,
        repo=valid_repo,
        commit_message="bug 123: upgrade NSS UPGRADE_NSPR_RELEASE",
    )
    assert (
        diff_assessor.check_prevent_nspr_nss() is None
    ), "Check should allow changes to NSPR with proper commit message."


def test_check_prevent_nspr_nss_combined(mocked_repo_config):
    supported_repos = get_repos_for_env("test")
    valid_repo = supported_repos["mozilla-central"]

    nspr_patch = GIT_DIFF_FILENAME_TEMPLATE.format(filename="nsprpub/testfile.txt")
    nss_patch = GIT_DIFF_FILENAME_TEMPLATE.format(filename="security/nss/testfile.txt")
    combined_patch = "\n".join((nspr_patch, nss_patch))

    parsed_diff = rs_parsepatch.get_diffs(combined_patch)
    diff_assessor = DiffAssessor(
        author="testuser@mozilla.com",
        parsed_diff=parsed_diff,
        repo=valid_repo,
        commit_message=COMMIT_MESSAGE,
    )
    assert diff_assessor.check_prevent_nspr_nss() == (
        "Revision makes changes to restricted directories: vendored NSS directories: "
        "`security/nss/testfile.txt` vendored NSPR directories: `nsprpub/testfile.txt`."
    ), "Check should disallow changes to both NSS and NSPR without proper commit message."

    diff_assessor = DiffAssessor(
        author="testuser@mozilla.com",
        parsed_diff=parsed_diff,
        repo=valid_repo,
        commit_message="bug 123: upgrade NSS UPGRADE_NSPR_RELEASE",
    )
    assert diff_assessor.check_prevent_nspr_nss() == (
        "Revision makes changes to restricted directories: "
        "vendored NSS directories: `security/nss/testfile.txt`."
    ), "Check should allow changes to NSPR with proper commit message."

    diff_assessor = DiffAssessor(
        author="testuser@mozilla.com",
        parsed_diff=parsed_diff,
        repo=valid_repo,
        commit_message="bug 123: upgrade NSS UPGRADE_NSS_RELEASE",
    )
    assert diff_assessor.check_prevent_nspr_nss() == (
        "Revision makes changes to restricted directories: "
        "vendored NSPR directories: `nsprpub/testfile.txt`."
    ), "Check should allow changes to NSPR with proper commit message."

    diff_assessor = DiffAssessor(
        author="testuser@mozilla.com",
        parsed_diff=parsed_diff,
        repo=valid_repo,
        commit_message="bug 123: upgrade NSS UPGRADE_NSS_RELEASE UPGRADE_NSPR_RELEASE",
    )
    assert (
        diff_assessor.check_prevent_nspr_nss() is None
    ), "Check should allow changes to NSPR with proper commit message."


def test_check_prevent_submodules():
    parsed_diff = rs_parsepatch.get_diffs(
        GIT_DIFF_FILENAME_TEMPLATE.format(filename="security/nss/testfile.txt")
    )
    diff_assessor = DiffAssessor(parsed_diff=parsed_diff)

    assert (
        diff_assessor.check_prevent_submodules() is None
    ), "Check should pass when no submodules are introduced."

    parsed_diff = rs_parsepatch.get_diffs(
        GIT_DIFF_FILENAME_TEMPLATE.format(filename=".gitmodules")
    )
    diff_assessor = DiffAssessor(parsed_diff=parsed_diff)

    assert (
        diff_assessor.check_prevent_submodules()
        == "Revision introduces a Git submodule into the repository."
    ), "Check should prevent revisions from introducing submodules."
