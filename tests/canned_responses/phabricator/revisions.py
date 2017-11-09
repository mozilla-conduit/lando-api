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
                "PHID-USER-review_bot": "PHID-USER-review_bot"
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
                "PHID-USER-review_bot": "PHID-USER-review_bot"
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

CANNED_REVISION_2_REVIEWERS = {
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
                "PHID-USER-2": "PHID-USER-2",
                "PHID-USER-3": "PHID-USER-3"
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

CANNED_EMPTY_REVISION_SEARCH = {
    "result": {
        "data": [],
        "maps": {},
        "query": {
            "queryKey": None
        },
        "cursor": {
            "limit": 100,
            "after": None,
            "before": None,
            "order": None
        }
    },
    "error_code": None,
    "error_info": None
}

CANNED_EMPTY_REVIEWERS_ATT_RESPONSE = {
    "result": {
        "data": [
            {
                "id": 1,
                "type": "DREV",
                "phid": "PHID-DREV-1",
                "fields": {
                    "title": "test",
                    "authorPHID": "PHID-USER-1",
                    "status": {
                        "value": "needs-review",
                        "name": "Needs Review",
                        "closed": False,
                        "color.ansi": "magenta"
                    },
                    "dateCreated": 1504192226,
                    "dateModified": 1508942565,
                    "policy": {
                        "view": "public",
                        "edit": "admin"
                    },
                    "bugzilla.bug-id": "1"
                },
                "attachments": {
                    "reviewers": {
                        "reviewers": []
                    }
                }
            }
        ],
        "maps": {},
        "query": {
            "queryKey": None
        },
        "cursor": {
            "limit": 100,
            "after": None,
            "before": None,
            "order": None
        }
    },
    "error_code": None,
    "error_info": None
}

CANNED_TWO_REVIEWERS_SEARCH_RESPONSE = {
    "result": {
        "data": [
            {
                "id": "1",
                "type": "DREV",
                "phid": "PHID-DREV-1",
                "fields": {
                    "title": "My test diff.",
                    "authorPHID": "PHID-USER-1",
                    "dateCreated": 1508864530,
                    "dateModified": 1509376079,
                    "policy": {
                        "view": "public",
                        "edit": "users"
                    },
                    "bugzilla.bug-id": "1"
                },
                "attachments": {
                    "reviewers": {
                        "reviewers": [
                            {
                                "reviewerPHID": "PHID-USER-2",
                                "status": "accepted",
                                "isBlocking": False,
                                "actorPHID": "PHID-USER-2"
                            }, {
                                "reviewerPHID": "PHID-USER-3",
                                "status": "accepted",
                                "isBlocking": False,
                                "actorPHID": "PHID-USER-3"
                            }
                        ]
                    }
                },
                "maps": {},
                "query": {
                    "queryKey": None
                },
                "cursor": {
                    "limit": 100,
                    "after": None,
                    "before": None,
                    "order": None
                }
            },
        ],
    },
    "error_code": None,
    "error_info": None,
}
