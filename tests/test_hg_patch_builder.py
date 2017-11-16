# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from landoapi.hgexportbuilder import build_patch_for_revision
from landoapi.phabricator_client import PhabricatorClient

git_diff_from_revision = """diff --git a/hello.c b/hello.c
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

hg_patch = """# HG changeset patch
# User mpm_at_selenic
# Date 1496239141 +0000
Express great joy at existence of Mercurial

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


def test_build_patch(phabfactory, docker_env_vars):
    phabfactory.user(username='mpm_at_selenic', phid='PHID-USER-mpm')
    phabfactory.revision(id='D5', author_phid='PHID-USER-mpm')

    phab = PhabricatorClient(api_key='api-key')
    revision = phab.get_revision(id=5)
    revision['summary'] = "Express great joy at existence of Mercurial"
    author = phab.get_revision_author(revision)

    patch = build_patch_for_revision(git_diff_from_revision, author, revision)

    assert patch == hg_patch
