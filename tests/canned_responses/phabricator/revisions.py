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
            "uri": "https://mozphab.dev.mozaws.net/D1",
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
            "uri": "https://mozphab.dev.mozaws.net/D2",
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

CANNED_REVISION_EMPTY = {
    "result": [],
    "error_code": None,
    "error_info": None
}
