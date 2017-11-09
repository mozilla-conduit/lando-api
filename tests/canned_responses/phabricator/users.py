# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
# yapf: disable

CANNED_USER_1 = {
    "result": [
        {
            "phid": "PHID-USER-imaduemeadmin",
            "userName": "imadueme_admin",
            "realName": "Israel Madueme",
            "image": "https://d2kb8dptaglwte.cloudfront.net/file/data/oywgsrq6rtv5rdfbjvdv/PHID-FILE-632bsum6ksnpu77kymbq/alphanumeric_lato-dark_I.png-_5e622c-255%2C255%2C255%2C0.4.png",
            "uri": "http://phabricator.test/p/imadueme_admin/",
            "roles": [
                "admin",
                "verified",
                "approved",
                "activated"
            ]
        }
    ],
    "error_code": None,
    "error_info": None
}

CANNED_USER_WHOAMI_1 = {
    "result": {
        "phid": "PHID-USER-zlfme42o3yewh5v4k6ry",
        "userName": "imadueme_admin",
        "realName": "Israel Madueme",
        "image": "https://d2kb8dptaglwte.cloudfront.net/file/data/oywgsrq6rtv5rdfbjvdv/PHID-FILE-632bsum6ksnpu77kymbq/alphanumeric_lato-dark_I.png-_5e622c-255%2C255%2C255%2C0.4.png",
        "uri": "http://phabricator.test/p/imadueme_admin/",
        "roles": [
            "admin",
            "verified",
            "approved",
            "activated"
        ],
        "primaryEmail": "imadueme@mozilla.com"
    },
    "error_code": None,
    "error_info": None
}

CANNED_USER_SEARCH_1 = {
    "result": {
        "data": [
            {
                "id": 2,
                "type": "USER",
                "phid": "PHID-USER-2",
                "fields": {
                    "username": "johndoe",
                    "realName": "John Doe",
                    "roles": [
                        "verified",
                        "approved",
                        "activated"
                    ],
                    "dateCreated": 1504618477,
                    "dateModified": 1504882856,
                    "policy": {
                        "view": "public",
                        "edit": "no-one"
                    }
                },
                "attachments": {}
            },
        ]
    },
    "error_code": None,
    "error_info": None
}

CANNED_EMPTY_USER_SEARCH_RESPONSE = {
    'result': {
        'data': []
    },
    'error_code': None,
    'error_info': None
}


CANNED_USER_SEARCH_TWO_USERS = {
    "result": {
        "data": [
            {
                "id": 2,
                "type": "USER",
                "phid": "PHID-USER-2",
                "fields": {
                    "username": "foo",
                    "realName": "Foo Foo",
                    "roles": [
                        "verified",
                        "approved",
                        "activated"
                    ],
                    "dateCreated": 1504618477,
                    "dateModified": 1504882856,
                    "policy": {
                        "view": "public",
                        "edit": "no-one"
                    }
                },
                "attachments": {}
            }, {
                "id": 3,
                "type": "USER",
                "phid": "PHID-USER-3",
                "fields": {
                    "username": "bar",
                    "realName": "Bar Bar",
                    "roles": [
                        "verified",
                        "approved",
                        "activated"
                    ],
                    "dateCreated": 1504618477,
                    "dateModified": 1504882856,
                    "policy": {
                        "view": "public",
                        "edit": "no-one"
                    }
                },
                "attachments": {}
            },
        ]
    },
    "error_code": None,
    "error_info": None
}
