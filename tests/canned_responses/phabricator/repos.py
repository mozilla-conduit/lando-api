# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
# yapf: disable

CANNED_REPO_MOZCENTRAL = {
    "result": {
        "PHID-REPO-mozillacentral": {
            "phid": "PHID-REPO-mozillacentral",
            "uri": "http://phabricator.test/source/mozilla-central/",
            "typeName": "Repository",
            "type": "REPO",
            "name": "rMOZILLACENTRAL",
            "fullName": "rMOZILLACENTRAL mozilla-central",
            "status": "open"
        }
    },
    "error_code": None,
    "error_info": None
}

CANNED_REPO_SEARCH_MOZCENTRAL = {
    "result": {
        "data": [
            {
                "id": 1,
                "type": "REPO",
                "phid": "PHID-REPO-mozillacentral",
                "fields": {
                    "name": "mozilla-central",
                    "vcs": "hg",
                    "callsign": "MOZILLACENTRAL",
                    "shortName": "mozilla-central",
                    "status": "active",
                    "isImporting": False,
                    "spacePHID": None,
                    "dateCreated": 1502986064,
                    "dateModified": 1505659447,
                    "policy": {
                        "view": "public",
                        "edit": "admin",
                        "diffusion.push": "no-one"
                    }
                },
                "attachments": {}
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
