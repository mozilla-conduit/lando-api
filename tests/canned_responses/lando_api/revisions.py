# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
# yapf: disable

CANNED_LANDO_REVISION_1 = {
    "status": 1,
    "status_name": "Needs Revision",
    "title": "My test diff 1",
    "summary": "Summary 1",
    "test_plan": "Test Plan 1",
    "commit_message_preview": "Bug 1 - My test diff 1 r=review_bot",
    "url": "http://phabricator.test/D1",
    "date_created": 1495638270,
    "date_modified": 1496239141,
    "id": 1,
    "parent_revisions": [],
    "bug_id": 1,
    "phid": "PHID-DREV-1",
    "diff": {
        "date_created": 1496175380,
        "date_modified": 1496175382,
        "id": 1,
        "revision_id": 1,
        "vcs_base_revision": "39d5cc0fda5e16c49a59d29d4ca186a5534cc88b",
        "authors": [
            {"email": "mcote@mozilla.example", "name": "Mark Cote"},
            {"email": "glob@mozilla.example", "name": "Byron Jones"}
        ],
    },
    "author": {
        "image_url": "https://d2kb8dptaglwte.cloudfront.net/file/data/oywgsrq6rtv5rdfbjvdv/PHID-FILE-632bsum6ksnpu77kymbq/alphanumeric_lato-dark_I.png-_5e622c-255%2C255%2C255%2C0.4.png",
        "phid": "PHID-USER-imaduemeadmin",
        "real_name": "Israel Madueme",
        "url": "http://phabricator.test/p/imadueme_admin/",
        "username": "imadueme_admin"
    },
    "repo": {
        "full_name": "rMOZILLACENTRAL mozilla-central",
        "phid": "PHID-REPO-mozillacentral",
        "short_name": "rMOZILLACENTRAL",
        "url": "http://phabricator.test/source/mozilla-central/"
    },
    'reviewers': [
        {
            'phid': 'PHID-USER-review_bot',
            'is_blocking': False,
            'real_name': 'review_bot Name',
            'status': 'added',
            'username': 'review_bot'
        }
    ]
}


CANNED_LANDO_REVISION_2 = {
    "date_created": 1495638280,
    "date_modified": 1496239151,
    "bug_id": 1,
    "id": 2,
    "parent_revisions": [
        dict(CANNED_LANDO_REVISION_1, diff=None)
    ],
    "phid": "PHID-DREV-2",
    "diff": {
        "date_created": 1496175380,
        "date_modified": 1496175382,
        "id": 1,
        "revision_id": 1,
        "vcs_base_revision": "39d5cc0fda5e16c49a59d29d4ca186a5534cc88b",
        "authors": [
            {"email": "mcote@mozilla.example", "name": "Mark Cote"},
            {"email": "glob@mozilla.example", "name": "Byron Jones"}
        ],
    },
    "author": {
        "image_url": "https://d2kb8dptaglwte.cloudfront.net/file/data/oywgsrq6rtv5rdfbjvdv/PHID-FILE-632bsum6ksnpu77kymbq/alphanumeric_lato-dark_I.png-_5e622c-255%2C255%2C255%2C0.4.png",
        "phid": "PHID-USER-imaduemeadmin",
        "real_name": "Israel Madueme",
        "url": "http://phabricator.test/p/imadueme_admin/",
        "username": "imadueme_admin"
    },
    "repo": {
        "full_name": "rMOZILLACENTRAL mozilla-central",
        "phid": "PHID-REPO-mozillacentral",
        "short_name": "rMOZILLACENTRAL",
        "url": "http://phabricator.test/source/mozilla-central/"
    },
    'reviewers': [
        {
            'phid': 'PHID-USER-review_bot',
            'is_blocking': False,
            'real_name': 'review_bot Name',
            'status': 'added',
            'username': 'review_bot'
        }
    ],
    "status": 1,
    "status_name": "Needs Revision",
    "title": "My test diff 2",
    "summary": "Summary 2",
    "test_plan": "Test Plan 2",
    "commit_message_preview": "Bug 1 - My test diff 2 r=review_bot",
    "url": "http://phabricator.test/D2"
}

CANNED_LANDO_REVISION_NOT_FOUND = {
    "detail": "The requested revision does not exist",
    "status": 404,
    "title": "Revision not found",
    "type": "https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404"
}

CANNED_LANDO_DIFF_NOT_FOUND = {
    "detail": "The requested diff does not exist",
    "status": 404,
    "title": "Diff not found",
    "type": "https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404"
}

CANNED_LANDO_REVIEWERS_PARTIAL = [
    {
        'phid': 'PHID-USER-Reviewer-foo',
        'is_blocking': False,
        'real_name': 'foo Name',
        'status': 'added',
        'username': 'foo'
    }, {
        'phid': 'PHID-USER-forced-in-test',
        'is_blocking': True,
        'real_name': 'bar Name',
        'status': 'rejected',
        'username': 'bar'
    }
]

CANNED_REVIEWERS_USER_DONT_MATCH_PARTIAL = [
    {
        'status': 'accepted',
        'is_blocking': False,
        'username': 'johndoe',
        'phid': 'PHID-USER-2',
        'real_name': 'John Doe'
    }, {
        'status': 'accepted',
        'is_blocking': False,
        'username': '',
        'phid': 'PHID-USER-3',
        'real_name': ''
    }
]
