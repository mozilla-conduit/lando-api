# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
# yapf: disable

CANNED_REVISION_1 = {
    "result": [
        {
            "id": "1",
            "phid": "PHID-DREV-1",
            "title": "My test diff 1",
            "uri": "http://phabricator.test/D1",
            "dateCreated": "1495638270",
            "dateModified": "1496239141",
            "authorPHID": "PHID-USER-imaduemeadmin",
            "status": "1",
            "statusName": "Needs Revision",
            "properties": [],
            "branch": None,
            "summary": "Summary 1",
            "testPlan": "Test Plan 1",
            "lineCount": "2",
            "activeDiffPHID": "PHID-DIFF-rpzpm5wuhiuly2ujurlu",
            "diffs": ["2"],
            "commits": [],
            "reviewers": {
                "PHID-USER-egtmqukxexnsgko4dhkm": "PHID-USER-egtmqukxexnsgko4dhkm"
            },
            "ccs": [],
            "hashes": [],
            "auxiliary": {
                "bugzilla.bug-id": "1",
                "phabricator:projects": [],
                "phabricator:depends-on": []
            },
            "repositoryPHID": "PHID-REPO-mozillacentral",
            "sourcePath": None,
        }
    ],
    "error_code": None,
    "error_info": None,
}


CANNED_REVISION_2 = {
    "result": [
        {
            "id": "2",
            "phid": "PHID-DREV-2",
            "title": "My test diff 2",
            "uri": "http://phabricator.test/D2",
            "dateCreated": "1495638280",
            "dateModified": "1496239151",
            "authorPHID": "PHID-USER-imaduemeadmin",
            "status": "1",
            "statusName": "Needs Revision",
            "properties": [],
            "branch": None,
            "summary": "Summary 2",
            "testPlan": "Test Plan 2",
            "lineCount": "2",
            "activeDiffPHID": "PHID-DIFF-kd928flk230lkidwayij",
            "diffs": ["2"],
            "commits": [],
            "reviewers": {
                "PHID-USER-egtmqukxexnsgko4dhkm": "PHID-USER-egtmqukxexnsgko4dhkm"
            },
            "ccs": [],
            "hashes": [],
            "auxiliary": {
                "bugzilla.bug-id": "1",
                "phabricator:projects": [],
                "phabricator:depends-on": ["PHID-DREV-1"]
            },
            "repositoryPHID": "PHID-REPO-mozillacentral",
            "sourcePath": None,
        }
    ],
    "error_code": None,
    "error_info": None,
}

CANNED_EMPTY_RESULT = {
    "result": [],
    "error_code": None,
    "error_info": None
}

CANNED_REVISION_1_DIFF = {
    "result": {
        "PHID-DIFF-ebpygi3y26uokg4ebqde": {
            "phid": "PHID-DIFF-ebpygi3y26uokg4ebqde",
            "uri": "https://secure.phabricator.com/differential/diff/43480/",
            "typeName": "Differential Diff",
            "type": "DIFF",
            "name": "Diff 43480",
            "fullName": "Diff 43480",
            "status": "open"
        }
    },
    "error_code": None,
    "error_info": None,
}

CANNED_REVISION_1_RAW_DIFF = {
    "result": """diff --git a/hello.c b/hello.c
--- a/hello.c   Fri Aug 26 01:21:28 2005 -0700
+++ b/hello.c   Mon May 05 01:20:46 2008 +0200
@@ -12,5 +12,6 @@
 int main(int argc, char **argv)
 {
        printf("hello, world!\n");
+       printf("sure am glad I'm using Mercurial!\n");
        return 0;
 }
""",
    "error_code": None,
    "error_info": None
}
