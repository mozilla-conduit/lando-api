# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import io

import pytest

from landoapi.hgexports import (
    GitPatchHelper,
    HgPatchHelper,
    build_patch_for_revision,
)

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

GIT_PATCH = rb"""
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
""".strip()

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
        io.BytesIO(
            b"""
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
    assert patch.commit_description() == "WIP transplant and diff-start-line"


def test_patchhelper_start_line():
    patch = HgPatchHelper(
        io.BytesIO(
            b"""
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
    assert patch.commit_description() == "WIP transplant and diff-start-line"


def test_patchhelper_no_header():
    patch = HgPatchHelper(
        io.BytesIO(
            b"""
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
    assert patch.commit_description() == "WIP transplant and diff-start-line"


def test_patchhelper_diff_injection_no_start_line():
    patch = HgPatchHelper(
        io.BytesIO(
            b"""
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
    assert patch.commit_description() == "WIP transplant and diff-start-line"


def test_patchhelper_diff_injection_start_line():
    patch = HgPatchHelper(
        io.BytesIO(
            b"""
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
    assert patch.commit_description() == (
        "WIP transplant and diff-start-line\n"
        "\n"
        "diff --git a/bad b/bad\n"
        "@@ -0,0 +0,0 @@\n"
        "blah"
    )


def test_patchhelper_write_start_line():
    header = b"""
# HG changeset patch
# User byron jones <glob@mozilla.com>
# Date 1523427125 -28800
#      Wed Apr 11 14:12:05 2018 +0800
# Node ID 3379ea3cea34ecebdcb2cf7fb9f7845861ea8f07
# Parent  46c36c18528fe2cc780d5206ed80ae8e37d3545d
# Diff Start Line 10
""".strip()
    commit_desc = b"""
WIP transplant and diff-start-line
""".strip()
    diff = b"""
diff --git a/autoland/autoland/transplant.py b/autoland/autoland/transplant.py
--- a/autoland/autoland/transplant.py
+++ b/autoland/autoland/transplant.py
@@ -318,24 +318,58 @@ class PatchTransplant(Transplant):
# instead of passing the url to 'hg import' to make
...
""".strip()
    patch = HgPatchHelper(io.BytesIO(b"%s\n%s\n\n%s" % (header, commit_desc, diff)))

    buf = io.BytesIO(b"")
    patch.write_commit_description(buf)
    assert buf.getvalue() == commit_desc

    buf = io.BytesIO(b"")
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
    patch = HgPatchHelper(
        io.BytesIO(f"{header}\n{commit_desc}\n\n{diff}".encode("utf-8"))
    )

    buf = io.BytesIO(b"")
    patch.write_commit_description(buf)
    assert buf.getvalue().decode("utf-8") == commit_desc

    assert patch.get_diff() == diff

    buf = io.BytesIO(b"")
    patch.write_diff(buf)
    assert buf.getvalue().decode("utf-8") == diff


def test_git_formatpatch_helper_parse():
    patch = GitPatchHelper(io.BytesIO(GIT_PATCH))
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
    assert patch.commit_description() == (
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
