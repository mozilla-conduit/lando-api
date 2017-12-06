# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Patches generated for landing process."""

LANDING_PATCH = """# HG changeset patch
# User imadueme_admin
# Date 1496239141 +0000
Bug 1 - My test diff 1 r=review_bot

Summary 1

Differential Revision: http://phabricator.test/D1

diff --git a/hello.c b/hello.c
--- a/hello.c   Fri Aug 26 01:21:28 2005 -0700
+++ b/hello.c   Mon May 05 01:20:46 2008 +0200
@@ -12,5 +12,6 @@
 int main(int argc, char **argv)
 {
        printf("hello, world!
");
+       printf("sure am glad I'm using Mercurial!
");
        return 0;
 }
"""
