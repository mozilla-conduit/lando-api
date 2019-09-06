# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from landoapi.hgexports import build_patch_for_revision

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
