# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import pytest

from landoapi import patches

SIMPLE_PATCH = """
# HG changeset patch
# User Test User <test@example.com>
# Date 1523293409 14400
#      Mon Apr 09 13:03:29 2018 -0400
# Node ID 13aafe444440154c16d0bae140470e77e2de3fbf
# Parent  0000000000000000000000000000000000000000
initial commit

diff --git a/README b/README
new file mode 100644
--- /dev/null
+++ b/README
@@ -0,0 +1,1 @@
+Testing repository for Lando/Transplant
""".lstrip()

UNICODE_CHARACTERS = """
stuff
い漢
emoji
🏄🦈
""".lstrip()

EMPTY = ""
LONG_LINE = "LOOOOOOONG" * 20000


@pytest.mark.parametrize(
    "contents", (SIMPLE_PATCH, UNICODE_CHARACTERS, EMPTY, LONG_LINE)
)
def test_upload(s3, contents):
    url = patches.upload(
        1, 1, contents, "landoapi.test.bucket", aws_access_key=None, aws_secret_key=None
    )
    patch = s3.Object("landoapi.test.bucket", patches.name(1, 1))
    patch = patch.get()["Body"].read().decode("utf-8")

    assert patch == contents
    assert url == patches.url("landoapi.test.bucket", patches.name(1, 1))
