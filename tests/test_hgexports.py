# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import io
from unittest.mock import patch

import pytest
import requests
import rs_parsepatch

from landoapi.hgexports import (
    BugReferencesCheck,
    CommitMessagesCheck,
    GitPatchHelper,
    HgPatchHelper,
    PatchCollectionAssessor,
    PreventNSPRNSSCheck,
    PreventSubmodulesCheck,
    WPTSyncCheck,
    build_patch_for_revision,
)

GIT_DIFF_FROM_REVISION = r"""diff --git a/hello.c b/hello.c
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

GIT_DIFF_CRLF = """diff --git a/hello.c b/hello.c
--- a/hello.c   Fri Aug 26 01:21:28 2005 -0700
+++ b/hello.c   Mon May 05 01:20:46 2008 +0200
@@ -12,5 +12,6 @@
 int main(int argc, char **argv)\r
 {\r
        printf("hello, world!\\n");\r
+       printf("sure am glad I'm using Mercurial!\\n");\r
        return 0;\r
 }\r
"""

COMMIT_MESSAGE = """\
Express great joy at existence of Mercurial

Make sure multiple line breaks are kept:



Using console to print out the messages.
"""

HG_PATCH = r"""# HG changeset patch
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

GIT_PATCH_UTF8 = """\
diff --git a/testing/web-platform/tests/html/dom/elements/global-attributes/dir-auto-dynamic-simple-textContent.html b/testing/web-platform/tests/html/dom/elements/global-attributes/dir-auto-dynamic-simple-textContent.html
new file mode 100644
--- /dev/null
+++ b/testing/web-platform/tests/html/dom/elements/global-attributes/dir-auto-dynamic-simple-textContent.html
@@ -0,0 +1,31 @@
+<!DOCTYPE html>
+<html class="reftest-wait">
+<meta charset="utf-8">
+<title>Dynamic changes with textContent and dir=auto</title>
+<link rel="match" href="dir-auto-dynamic-simple-ref.html">
+<div>Test for elements with dir="auto" whose content changes between directional and neutral</div>
+<div dir="auto" id="from_ltr_to_ltr">abc</div>
+<div dir="auto" id="from_ltr_to_rtl">abc</div>
+<div dir="auto" id="from_ltr_to_neutral">abc</div>
+<div dir="auto" id="from_rtl_to_ltr">אבג</div>
+<div dir="auto" id="from_rtl_to_rtl">אבג</div>
+<div dir="auto" id="from_rtl_to_neutral">אבג</div>
+<div dir="auto" id="from_neutral_to_ltr">123</div>
+<div dir="auto" id="from_neutral_to_rtl">123</div>
+<div dir="auto" id="from_neutral_to_neutral">123</div>
+<script>
+function changeContent() {
+  var directionalTexts = {ltr:"xyz", rtl:"ابج", neutral:"456"};
+
+  for (var dirFrom in directionalTexts) {
+    for (var dirTo in directionalTexts) {
+      var element = document.getElementById("from_" + dirFrom +
+                                            "_to_" + dirTo);
+      element.textContent = directionalTexts[dirTo];
+    }
+  }
+  document.documentElement.removeAttribute("class");
+}
+
+document.addEventListener("TestRendered", changeContent);
+</script>
"""

GIT_FORMATPATCH_UTF8 = f"""\
From 71ce7889eaa24616632a455636598d8f5c60b765 Mon Sep 17 00:00:00 2001
From: Connor Sheehan <sheehan@mozilla.com>
Date: Wed, 21 Feb 2024 10:20:49 +0000
Subject: [PATCH] Bug 1874040 - Move 1103348-1.html to WPT, and expand it.
 r=smaug

---
 .../dir-auto-dynamic-simple-textContent.html  | 31 ++++++++++++++++
 1 files changed, 31 insertions(+), 0 deletions(-)
 create mode 100644 testing/web-platform/tests/html/dom/elements/global-attributes/dir-auto-dynamic-simple-textContent.html
{GIT_PATCH_UTF8}--
2.46.1
"""

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
"""

GIT_PATCH_EMPTY = """\
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
"""

GIT_DIFF_FILENAME_TEMPLATE = r"""\
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
"""


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
# Date 1523427125 -28800
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


def test_git_formatpatch_helper_utf8():
    helper = GitPatchHelper(io.StringIO(GIT_FORMATPATCH_UTF8))

    assert (
        helper.get_diff() == GIT_PATCH_UTF8
    ), "`get_diff()` should return unescaped unicode and match the original patch."


def test_preserves_diff_crlf():
    hg_patch = build_patch_for_revision(
        GIT_DIFF_CRLF,
        "Joe User",
        "joe@example.com",
        COMMIT_MESSAGE,
        "1496239141",
    )

    hg_helper = HgPatchHelper(io.StringIO(hg_patch))

    assert (
        hg_helper.get_diff() == "\n" + GIT_DIFF_CRLF
    ), "`get_diff()` should preserve CRLF."

    git_helper = GitPatchHelper(
        io.StringIO(
            f"""\
From: Connor Sheehan <sheehan@mozilla.com>
Date: Wed, 6 Jul 2022 16:36:09 -0400
Subject: {COMMIT_MESSAGE}
---
{GIT_DIFF_CRLF}--
2.47.1
"""
        )
    )

    assert git_helper.get_diff() == GIT_DIFF_CRLF, "`get_diff()` should preserve CRLF."


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


def test_check_commit_message_merge_automation_empty_message():
    patch_helpers = [
        HgPatchHelper(
            io.StringIO(
                """
# HG changeset patch
# User ffxbld
# Date 1523427125 -28800
#      Wed Apr 11 14:12:05 2018 +0800
# Node ID 3379ea3cea34ecebdcb2cf7fb9f7845861ea8f07
# Parent  46c36c18528fe2cc780d5206ed80ae8e37d3545d
diff --git a/autoland/autoland/transplant.py b/autoland/autoland/transplant.py
--- a/autoland/autoland/transplant.py
+++ b/autoland/autoland/transplant.py
@@ -318,24 +318,58 @@ class PatchTransplant(Transplant):
# instead of passing the url to 'hg import' to make
...
""".strip()
            )
        )
    ]

    assessor = PatchCollectionAssessor(patch_helpers=patch_helpers)

    # Test check fails for empty commit message.
    assert assessor.run_patch_collection_checks(
        patch_collection_checks=[CommitMessagesCheck], patch_checks=[]
    ) == [
        "Revision has an empty commit message."
    ], "Commit message check should fail if a commit message is passed but it is empty."


def test_check_commit_message_merge_automation_bad_message():
    patch_helpers = [
        HgPatchHelper(
            io.StringIO(
                """
# HG changeset patch
# User ffxbld
# Date 1523427125 -28800
#      Wed Apr 11 14:12:05 2018 +0800
# Node ID 3379ea3cea34ecebdcb2cf7fb9f7845861ea8f07
# Parent  46c36c18528fe2cc780d5206ed80ae8e37d3545d
this message is missing the bug.

diff --git a/autoland/autoland/transplant.py b/autoland/autoland/transplant.py
--- a/autoland/autoland/transplant.py
+++ b/autoland/autoland/transplant.py
@@ -318,24 +318,58 @@ class PatchTransplant(Transplant):
# instead of passing the url to 'hg import' to make
...
""".strip()
            )
        )
    ]

    assessor = PatchCollectionAssessor(patch_helpers=patch_helpers)

    # Test check passed for merge automation user.
    assert (
        assessor.run_patch_collection_checks(
            patch_collection_checks=[CommitMessagesCheck], patch_checks=[]
        )
        == []
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
def test_check_commit_message_valid_message(commit_message, error_message):
    patch_helpers = [
        HgPatchHelper(
            io.StringIO(
                f"""
# HG changeset patch
# User Connor Sheehan <sheehan@mozilla.com>
# Date 1523427125 -28800
#      Wed Apr 11 14:12:05 2018 +0800
# Node ID 3379ea3cea34ecebdcb2cf7fb9f7845861ea8f07
# Parent  46c36c18528fe2cc780d5206ed80ae8e37d3545d
{commit_message}

diff --git a/autoland/autoland/transplant.py b/autoland/autoland/transplant.py
--- a/autoland/autoland/transplant.py
+++ b/autoland/autoland/transplant.py
@@ -318,24 +318,58 @@ class PatchTransplant(Transplant):
# instead of passing the url to 'hg import' to make
...
""".strip()
            )
        )
    ]
    assessor = PatchCollectionAssessor(patch_helpers=patch_helpers)

    assert (
        assessor.run_patch_collection_checks(
            patch_collection_checks=[CommitMessagesCheck], patch_checks=[]
        )
        == []
    ), error_message


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
    commit_message, return_string, error_message
):
    patch_helpers = [
        HgPatchHelper(
            io.StringIO(
                f"""
# HG changeset patch
# User Connor Sheehan <sheehan@mozilla.com>
# Date 1523427125 -28800
#      Wed Apr 11 14:12:05 2018 +0800
# Node ID 3379ea3cea34ecebdcb2cf7fb9f7845861ea8f07
# Parent  46c36c18528fe2cc780d5206ed80ae8e37d3545d
{commit_message}

diff --git a/autoland/autoland/transplant.py b/autoland/autoland/transplant.py
--- a/autoland/autoland/transplant.py
+++ b/autoland/autoland/transplant.py
@@ -318,24 +318,58 @@ class PatchTransplant(Transplant):
# instead of passing the url to 'hg import' to make
...
""".strip()
            )
        )
    ]
    assessor = PatchCollectionAssessor(patch_helpers=patch_helpers)

    assert assessor.run_patch_collection_checks(
        patch_collection_checks=[CommitMessagesCheck], patch_checks=[]
    ) == [return_string], error_message


def test_check_wpt_sync_irrelevant_user():
    parsed_diff = rs_parsepatch.get_diffs(
        GIT_DIFF_FILENAME_TEMPLATE.format(filename="somefile.txt")
    )
    wpt_sync_check = WPTSyncCheck(
        email="sheehan@mozilla.com",
        commit_message=COMMIT_MESSAGE,
    )
    for diff in parsed_diff:
        wpt_sync_check.next_diff(diff)
    assert (
        wpt_sync_check.result() is None
    ), "Check should pass when user is not `wptsync@mozilla.com`."


def test_check_wpt_sync_invalid_paths():
    parsed_diff = rs_parsepatch.get_diffs(
        GIT_DIFF_FILENAME_TEMPLATE.format(filename="somefile.txt")
    )
    wpt_sync_check = WPTSyncCheck(
        email="wptsync@mozilla.com",
        commit_message=COMMIT_MESSAGE,
    )
    for diff in parsed_diff:
        wpt_sync_check.next_diff(diff)
    assert wpt_sync_check.result() == (
        "Revision has WPTSync bot making changes to disallowed " "files `somefile.txt`."
    ), "Check should fail if WPTSync bot pushes disallowed files."


def test_check_wpt_sync_valid_paths():
    parsed_diff = rs_parsepatch.get_diffs(
        GIT_DIFF_FILENAME_TEMPLATE.format(filename="testing/web-platform/moz.build")
    )
    wpt_sync_check = WPTSyncCheck(
        email="wptsync@mozilla.com",
        commit_message=COMMIT_MESSAGE,
    )
    for diff in parsed_diff:
        wpt_sync_check.next_diff(diff)
    assert (
        wpt_sync_check.result() is None
    ), "Check should pass if WPTSync bot makes changes to allowed files."


def test_check_prevent_nspr_nss_missing_fields():
    parsed_diff = rs_parsepatch.get_diffs(
        GIT_DIFF_FILENAME_TEMPLATE.format(filename="security/nss/testfile.txt")
    )
    prevent_nspr_nss_check = PreventNSPRNSSCheck(
        email="testuser@mozilla.com",
    )
    for diff in parsed_diff:
        prevent_nspr_nss_check.next_diff(diff)
    assert (
        prevent_nspr_nss_check.result() is None
    ), "Missing commit message should result in passing check."


def test_check_prevent_nspr_nss_nss():
    parsed_diff = rs_parsepatch.get_diffs(
        GIT_DIFF_FILENAME_TEMPLATE.format(filename="security/nss/testfile.txt")
    )
    prevent_nspr_nss_check = PreventNSPRNSSCheck(
        email="testuser@mozilla.com",
        commit_message=COMMIT_MESSAGE,
    )
    for diff in parsed_diff:
        prevent_nspr_nss_check.next_diff(diff)
    assert prevent_nspr_nss_check.result() == (
        "Revision makes changes to restricted directories: vendored NSS directories: "
        "`security/nss/testfile.txt`."
    ), "Check should disallow changes to NSS without proper commit message."

    prevent_nspr_nss_check = PreventNSPRNSSCheck(
        email="testuser@mozilla.com",
        commit_message="bug 123: upgrade NSS UPGRADE_NSS_RELEASE",
    )
    for diff in parsed_diff:
        prevent_nspr_nss_check.next_diff(diff)
    assert (
        prevent_nspr_nss_check.result() is None
    ), "Check should allow changes to NSS with proper commit message."


def test_check_prevent_nspr_nss_nspr():
    parsed_diff = rs_parsepatch.get_diffs(
        GIT_DIFF_FILENAME_TEMPLATE.format(filename="nsprpub/testfile.txt")
    )
    prevent_nspr_nss_check = PreventNSPRNSSCheck(
        email="testuser@mozilla.com",
        commit_message=COMMIT_MESSAGE,
    )
    for diff in parsed_diff:
        prevent_nspr_nss_check.next_diff(diff)
    assert prevent_nspr_nss_check.result() == (
        "Revision makes changes to restricted directories: vendored NSPR directories: "
        "`nsprpub/testfile.txt`."
    ), "Check should disallow changes to NSPR without proper commit message."

    prevent_nspr_nss_check = PreventNSPRNSSCheck(
        email="testuser@mozilla.com",
        commit_message="bug 123: upgrade NSS UPGRADE_NSPR_RELEASE",
    )
    for diff in parsed_diff:
        prevent_nspr_nss_check.next_diff(diff)
    assert (
        prevent_nspr_nss_check.result() is None
    ), "Check should allow changes to NSPR with proper commit message."


def test_check_prevent_nspr_nss_combined():
    nspr_patch = GIT_DIFF_FILENAME_TEMPLATE.format(filename="nsprpub/testfile.txt")
    nss_patch = GIT_DIFF_FILENAME_TEMPLATE.format(filename="security/nss/testfile.txt")
    combined_patch = "\n".join((nspr_patch, nss_patch))

    parsed_diff = rs_parsepatch.get_diffs(combined_patch)
    prevent_nspr_nss_check = PreventNSPRNSSCheck(
        email="testuser@mozilla.com",
        commit_message=COMMIT_MESSAGE,
    )
    for diff in parsed_diff:
        prevent_nspr_nss_check.next_diff(diff)
    assert prevent_nspr_nss_check.result() == (
        "Revision makes changes to restricted directories: vendored NSS directories: "
        "`security/nss/testfile.txt` vendored NSPR directories: `nsprpub/testfile.txt`."
    ), "Check should disallow changes to both NSS and NSPR without proper commit message."

    prevent_nspr_nss_check = PreventNSPRNSSCheck(
        email="testuser@mozilla.com",
        commit_message="bug 123: upgrade NSS UPGRADE_NSPR_RELEASE",
    )
    for diff in parsed_diff:
        prevent_nspr_nss_check.next_diff(diff)
    assert prevent_nspr_nss_check.result() == (
        "Revision makes changes to restricted directories: "
        "vendored NSS directories: `security/nss/testfile.txt`."
    ), "Check should allow changes to NSPR with proper commit message."

    prevent_nspr_nss_check = PreventNSPRNSSCheck(
        email="testuser@mozilla.com",
        commit_message="bug 123: upgrade NSS UPGRADE_NSS_RELEASE",
    )
    for diff in parsed_diff:
        prevent_nspr_nss_check.next_diff(diff)
    assert prevent_nspr_nss_check.result() == (
        "Revision makes changes to restricted directories: "
        "vendored NSPR directories: `nsprpub/testfile.txt`."
    ), "Check should allow changes to NSPR with proper commit message."

    prevent_nspr_nss_check = PreventNSPRNSSCheck(
        email="testuser@mozilla.com",
        commit_message="bug 123: upgrade NSS UPGRADE_NSS_RELEASE UPGRADE_NSPR_RELEASE",
    )
    for diff in parsed_diff:
        prevent_nspr_nss_check.next_diff(diff)
    assert (
        prevent_nspr_nss_check.result() is None
    ), "Check should allow changes to NSPR with proper commit message."


def test_check_prevent_submodules():
    parsed_diff = rs_parsepatch.get_diffs(
        GIT_DIFF_FILENAME_TEMPLATE.format(filename="security/nss/testfile.txt")
    )
    prevent_submodules_check = PreventSubmodulesCheck()
    for diff in parsed_diff:
        prevent_submodules_check.next_diff(diff)

    assert (
        prevent_submodules_check.result() is None
    ), "Check should pass when no submodules are introduced."

    parsed_diff = rs_parsepatch.get_diffs(
        GIT_DIFF_FILENAME_TEMPLATE.format(filename=".gitmodules")
    )
    prevent_submodules_check = PreventSubmodulesCheck()
    for diff in parsed_diff:
        prevent_submodules_check.next_diff(diff)

    assert (
        prevent_submodules_check.result()
        == "Revision introduces a Git submodule into the repository."
    ), "Check should prevent revisions from introducing submodules."


def test_check_bug_references_public_bugs():
    patch_helper = HgPatchHelper(
        io.StringIO(
            """
# HG changeset patch
# User byron jones <glob@mozilla.com>
# Date 1523427125 -28800
#      Wed Apr 11 14:12:05 2018 +0800
# Node ID 3379ea3cea34ecebdcb2cf7fb9f7845861ea8f07
# Parent  46c36c18528fe2cc780d5206ed80ae8e37d3545d
bug 123: WIP transplant and diff-start-line

diff --git a/autoland/autoland/transplant.py b/autoland/autoland/transplant.py
--- a/autoland/autoland/transplant.py
+++ b/autoland/autoland/transplant.py
@@ -318,24 +318,58 @@ class PatchTransplant(Transplant):
# instead of passing the url to 'hg import' to make
...
""".strip()
        )
    )
    patch_helpers = [patch_helper]

    # Simulate contacting BMO returning a public bug state.
    with patch("landoapi.hgexports.get_status_code_for_bug") as mock_status_code, patch(
        "landoapi.hgexports.search_bugs"
    ) as mock_bug_search:
        mock_bug_search.side_effect = lambda bug_ids: bug_ids

        # Mock out the status code check to simulate a public bug.
        mock_status_code.return_value = 200

        assessor = PatchCollectionAssessor(patch_helpers=patch_helpers)

        assert (
            assessor.run_patch_collection_checks(
                patch_collection_checks=[BugReferencesCheck],
                patch_checks=[],
            )
            == []
        )


def test_check_bug_references_private_bugs():
    # Simulate a patch that references a private bug.
    patch_helper = HgPatchHelper(
        io.StringIO(
            """
# HG changeset patch
# User byron jones <glob@mozilla.com>
# Date 1523427125 -28800
# Node ID 3379ea3cea34ecebdcb2cf7fb9f7845861ea8f07
# Parent  46c36c18528fe2cc780d5206ed80ae8e37d3545d
Bug 999999: Fix issue with feature X
""".strip()
        )
    )
    patch_helpers = [patch_helper]

    # Simulate Bugzilla (BMO) responding that the bug is private.
    with patch("landoapi.hgexports.get_status_code_for_bug") as mock_status_code, patch(
        "landoapi.hgexports.search_bugs"
    ) as mock_bug_search:
        # Mock out bug search to simulate our bug not being found.
        mock_bug_search.return_value = set()

        # Mock out the status code check to simulate a private bug.
        mock_status_code.return_value = 401

        assessor = PatchCollectionAssessor(patch_helpers=patch_helpers)
        issues = assessor.run_patch_collection_checks(
            patch_collection_checks=[BugReferencesCheck],
            patch_checks=[],
        )

        assert (
            "Your commit message references bug 999999, which is currently private."
            in issues[0]
        )


def test_check_bug_references_skip_check():
    # Simulate a patch with SKIP_BMO_CHECK in the commit message.
    patch_helper = HgPatchHelper(
        io.StringIO(
            """
# HG changeset patch
# User byron jones <glob@mozilla.com>
# Date 1523427125 -28800
# Node ID 3379ea3cea34ecebdcb2cf7fb9f7845861ea8f07
# Parent  46c36c18528fe2cc780d5206ed80ae8e37d3545d
Bug 999999: Fix issue with feature X
SKIP_BMO_CHECK
""".strip()
        )
    )
    patch_helpers = [patch_helper]

    # Simulate Bugzilla (BMO) responding that the bug is private.
    with patch("landoapi.hgexports.get_status_code_for_bug") as mock_status_code, patch(
        "landoapi.hgexports.search_bugs"
    ) as mock_bug_search:
        # Mock out bug search to simulate our bug not being found.
        mock_bug_search.return_value = set()

        # Mock out the status code check to simulate a private bug.
        mock_status_code.return_value = 401

        assessor = PatchCollectionAssessor(patch_helpers=patch_helpers)
        issues = assessor.run_patch_collection_checks(
            patch_collection_checks=[BugReferencesCheck],
            patch_checks=[],
        )

        assert (
            issues == []
        ), "Check should always pass when `SKIP_BMO_CHECK` is present."


def test_check_bug_references_bmo_error():
    # Simulate a patch that references a bug.
    patch_helper = HgPatchHelper(
        io.StringIO(
            """
# HG changeset patch
# User byron jones <glob@mozilla.com>
# Date 1523427125 -28800
# Node ID 3379ea3cea34ecebdcb2cf7fb9f7845861ea8f07
# Parent  46c36c18528fe2cc780d5206ed80ae8e37d3545d
Bug 123456: Fix issue with feature Y
""".strip()
        )
    )
    patch_helpers = [patch_helper]

    # Simulate an error occurring when trying to contact BMO.
    with patch("landoapi.hgexports.get_status_code_for_bug") as mock_status_code, patch(
        "landoapi.hgexports.search_bugs"
    ) as mock_bug_search:
        mock_bug_search.return_value = set()

        def status_error(*args, **kwargs):
            raise requests.exceptions.RequestException("BMO connection failed")

        mock_status_code.side_effect = status_error

        assessor = PatchCollectionAssessor(patch_helpers=patch_helpers)
        issues = assessor.run_patch_collection_checks(
            patch_collection_checks=[BugReferencesCheck],
            patch_checks=[],
        )

        assert (
            issues
            and "Could not contact BMO to check for security bugs referenced in commit message."
            in issues[0]
        )
