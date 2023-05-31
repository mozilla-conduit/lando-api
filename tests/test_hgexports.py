# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import io

import pytest

from landoapi.hgexports import PatchHelper, build_patch_for_revision

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
        (b"diff --git a/file b/file", True),
        (b"diff a/file b/file", True),
        (b"diff -r 23280edf8655 autoland/autoland/patch_helper.py", True),
        (b"cheese", False),
        (b"diff", False),
        (b"diff ", False),
        (b"diff file", False),
    ],
)
def test_patchhelper_is_diff_line(line, expected):
    assert bool(PatchHelper._is_diff_line(line)) is expected


def test_patchhelper_vanilla_export():
    patch = PatchHelper(
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
    assert patch.header("Date") == b"1523427125 -28800"
    assert patch.header("Node ID") == b"3379ea3cea34ecebdcb2cf7fb9f7845861ea8f07"
    assert patch.header("User") == b"byron jones <glob@mozilla.com>"
    assert patch.header("Parent") == b"46c36c18528fe2cc780d5206ed80ae8e37d3545d"
    assert patch.commit_description() == b"WIP transplant and diff-start-line"


def test_patchhelper_start_line():
    patch = PatchHelper(
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
    assert patch.header("Diff Start Line") == b"10"
    assert patch.commit_description() == b"WIP transplant and diff-start-line"


def test_patchhelper_no_header():
    patch = PatchHelper(
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
    assert patch.header("User") is None
    assert patch.commit_description() == b"WIP transplant and diff-start-line"


def test_patchhelper_diff_injection_no_start_line():
    patch = PatchHelper(
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
    assert patch.commit_description() == b"WIP transplant and diff-start-line"


def test_patchhelper_diff_injection_start_line():
    patch = PatchHelper(
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
        b"WIP transplant and diff-start-line\n"
        b"\n"
        b"diff --git a/bad b/bad\n"
        b"@@ -0,0 +0,0 @@\n"
        b"blah"
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
    patch = PatchHelper(io.BytesIO(b"%s\n%s\n\n%s" % (header, commit_desc, diff)))

    buf = io.BytesIO(b"")
    patch.write_commit_description(buf)
    assert buf.getvalue() == commit_desc

    buf = io.BytesIO(b"")
    patch.write_diff(buf)
    assert buf.getvalue() == diff


def test_patchhelper_write_no_start_line():
    header = b"""
# HG changeset patch
# User byron jones <glob@mozilla.com>
# Date 1523427125 -28800
#      Wed Apr 11 14:12:05 2018 +0800
# Node ID 3379ea3cea34ecebdcb2cf7fb9f7845861ea8f07
# Parent  46c36c18528fe2cc780d5206ed80ae8e37d3545d
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
    patch = PatchHelper(io.BytesIO(b"%s\n%s\n\n%s" % (header, commit_desc, diff)))

    buf = io.BytesIO(b"")
    patch.write_commit_description(buf)
    assert buf.getvalue() == commit_desc

    buf = io.BytesIO(b"")
    patch.write_diff(buf)
    assert buf.getvalue() == diff
