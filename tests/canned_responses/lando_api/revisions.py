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
    "commit_message_title": "Bug 1 - My test diff 1 r=review_bot",
    "commit_message": (
        "Bug 1 - My test diff 1 r=review_bot\n\n"
        "Summary 1\n\nDifferential Revision: http://phabricator.test/D1"
    ),
    "url": "http://phabricator.test/D1",
    "date_created": "2017-05-24T15:04:30+00:00",
    "date_modified": "2017-05-31T13:59:01+00:00",
    "id": 'D1',
    "parent_revisions": [],
    "bug_id": 1,
    "phid": "PHID-DREV-1",
    "diff": {
        "date_created": "2017-05-30T20:16:20+00:00",
        "date_modified": "2017-05-30T20:16:22+00:00",
        "id": 1,
        "revision_id": 'D1',
        "vcs_base_revision": "39d5cc0fda5e16c49a59d29d4ca186a5534cc88b",
        "authors": [],
        "author": {"email": "mcote@mozilla.example", "name": "Mark Cote"},
    },
    "latest_diff_id": 1,
    "author": {
        "image_url": "https://d2kb8dptaglwte.cloudfront.net/file/data/oywgsrq6rtv5rdfbjvdv/PHID-FILE-632bsum6ksnpu77kymbq/alphanumeric_lato-dark_I.png-_5e622c-255%2C255%2C255%2C0.4.png", # noqa
        "phid": "PHID-USER-imaduemeadmin",
        "real_name": "Israel Madueme",
        "url": "http://phabricator.test/p/imadueme_admin/",
        "username": "imadueme_admin"
    },
    "repo": {
        "name": "mozilla-central",
        "phid": "PHID-REPO-mozillacentral",
    },
    'reviewers': [
        {
            'phid': 'PHID-USER-review_bot',
            'is_blocking': False,
            'real_name': 'review_bot Name',
            'status': 'accepted',
            'username': 'review_bot'
        }
    ]
}


CANNED_LANDO_REVISION_2 = {
    "date_created": "2017-05-24T15:04:40+00:00",
    "date_modified": "2017-05-31T13:59:11+00:00",
    "bug_id": 1,
    "id": 'D2',
    "parent_revisions": [
        dict(CANNED_LANDO_REVISION_1, diff=None, latest_diff_id=None)
    ],
    "phid": "PHID-DREV-2",
    "diff": {
        "date_created": "2017-05-30T20:16:20+00:00",
        "date_modified": "2017-05-30T20:16:22+00:00",
        "id": 1,
        "revision_id": "D1",
        "vcs_base_revision": "39d5cc0fda5e16c49a59d29d4ca186a5534cc88b",
        "authors": [],
        "author": {"email": "mcote@mozilla.example", "name": "Mark Cote"},
    },
    "latest_diff_id": 1,
    "author": {
        "image_url": "https://d2kb8dptaglwte.cloudfront.net/file/data/oywgsrq6rtv5rdfbjvdv/PHID-FILE-632bsum6ksnpu77kymbq/alphanumeric_lato-dark_I.png-_5e622c-255%2C255%2C255%2C0.4.png",  # noqa
        "phid": "PHID-USER-imaduemeadmin",
        "real_name": "Israel Madueme",
        "url": "http://phabricator.test/p/imadueme_admin/",
        "username": "imadueme_admin"
    },
    "repo": {
        "name": "mozilla-central",
        "phid": "PHID-REPO-mozillacentral",
    },
    'reviewers': [
        {
            'phid': 'PHID-USER-review_bot',
            'is_blocking': False,
            'real_name': 'review_bot Name',
            'status': 'accepted',
            'username': 'review_bot'
        }
    ],
    "status": 1,
    "status_name": "Needs Revision",
    "title": "My test diff 2",
    "summary": "Summary 2",
    "test_plan": "Test Plan 2",
    "commit_message_title": "Bug 1 - My test diff 2 r=review_bot",
    "commit_message": (
        "Bug 1 - My test diff 2 r=review_bot\n\n"
        "Summary 2\n\nDifferential Revision: http://phabricator.test/D2"
    ),
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
