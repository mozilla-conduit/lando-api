# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
# yapf: disable

CANNED_DIFF_1 = {
    "result": {
        "1": {
            "id": "1",
            "revisionID": "1",
            "dateCreated": "1496175380",
            "dateModified": "1496175382",
            "sourceControlBaseRevision": "39d5cc0fda5e16c49a59d29d4ca186a5534cc88b",
            "sourceControlPath": "/",
            "sourceControlSystem": "hg",
            "branch": "default",
            "bookmark": "delete-test",
            "creationMethod": "arc",
            "description": None,
            "unitStatus": "0",
            "lintStatus": "0",
            "changes": [
                {
                    "id": "3",
                    "metadata": {
                        "raw:old:phid": "PHID-FILE-guzn3dhrhslehrawm4tj"
                    },
                    "oldPath": "CLOBBER",
                    "currentPath": "CLOBBER",
                    "awayPaths": [],
                    "oldProperties": {
                        "unix:filemode": "100644"
                    },
                    "newProperties": [],
                    "type": "3",
                    "fileType": "1",
                    "commitHash": None,
                    "addLines": "0",
                    "delLines": "26",
                    "hunks": [
                        {
                            "oldOffset": "1",
                            "newOffset": "0",
                            "oldLength": "26",
                            "newLength": "0",
                            "addLines": None,
                            "delLines": None,
                            "isMissingOldNewline": None,
                            "isMissingNewNewline": None,
                            "corpus": "-# To trigger a clobber replace ALL of the textual description below,\n-# giving a bug number and a one line description of why a clobber is\n-# required. Modifying this file will make configure check that a\n-# clobber has been performed before the build can continue.\n-#\n-# MERGE NOTE: When merging two branches that require a CLOBBER, you should\n-#             merge both CLOBBER descriptions, to ensure that users on\n-#             both branches correctly see the clobber warning.\n-#\n-#                  O   <-- Users coming from both parents need to Clobber\n-#               /     \\\n-#          O               O\n-#          |               |\n-#          O <-- Clobber   O  <-- Clobber\n-#\n-# Note: The description below will be part of the error message shown to users.\n-#\n-# Modifying this file will now automatically clobber the buildbot machines \\o/\n-#\n-\n-# Are you updating CLOBBER because you think it's needed for your WebIDL\n-# changes to stick? As of bug 928195, this shouldn't be necessary! Please\n-# don't change CLOBBER for WebIDL changes any more.\n-\n-Bug 1361661 - Update Telemetry build and headers.\n-\n"
                        }
                    ]
                }
            ],
            "properties": {
                "arc.staging": {
                    "status": "repository.unsupported",
                    "refs": []
                },
                "local:commits": {
                    "f6780b8b22a343cbb8bd61038f37fa77c80615e8": {
                        "author": "Mark Cote",
                        "time": 1496175317,
                        "branch": "default",
                        "tag": "",
                        "commit": "f6780b8b22a343cbb8bd61038f37fa77c80615e8",
                        "rev": "f6780b8b22a343cbb8bd61038f37fa77c80615e8",
                        "local": "362118",
                        "parents": [
                            "39d5cc0fda5e16c49a59d29d4ca186a5534cc88b"
                        ],
                        "summary": "Remove CLOBBER file.",
                        "message": "Remove CLOBBER file.\n\nMozReview-Commit-ID: 1Fys7LV1jIw",
                        "authorEmail": "mcote@mozilla.com"
                    }
                }
            },
            "authorName": "Mark Cote",
            "authorEmail": "mcote@mozilla.com"
        }
    },
    "error_code": None,
    "error_info": None,
}
