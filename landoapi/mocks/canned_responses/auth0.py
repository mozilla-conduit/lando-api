# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import copy


# flake8: noqa
CANNED_USERINFO_STANDARD = {
    "sub": "ad|Example-LDAP|testuser",
    "email": "tuser@example.com",
    "email_verified": True,
    "name": "Test User",
    "given_name": "Test",
    "family_name": "User",
    "nickname": "Test User",
    "picture": "https://s.gravatar.com/avatar/7ec7606c46a14a7ef514d1f1f9038823?s=480&r=pg&d=https%3A%2F%2Fcdn.auth0.com%2Favatars%2Ftu.png",
    "updated_at": "2017-10-24T13:15:12.120Z",
    "https://sso.mozilla.com/claim/groups": [
        "active_scm_level_1",
        "all_scm_level_1",
        "active_scm_level_3",
        "all_scm_level_3",
        "active_scm_level_2",
        "all_scm_level_2",
    ],
    "https://sso.mozilla.com/claim/emails": ["tuser@example.com", "test@example.com"],
    "https://sso.mozilla.com/claim/dn": "mail=tuser@example.com,o=com,dc=example",
    "https://sso.mozilla.com/claim/organizationUnits": "mail=tuser@example.com,o=com,dc=example",
    "https://sso.mozilla.com/claim/email_aliases": "test@example.com",
    "https://sso.mozilla.com/claim/_HRData": {"placeholder": "empty"},
}

CANNED_USERINFO = {"STANDARD": CANNED_USERINFO_STANDARD}

CANNED_USERINFO["NO_CUSTOM_CLAIMS"] = copy.deepcopy(
    {
        key: value
        for key, value in CANNED_USERINFO_STANDARD.items()
        if not key.startswith("https://sso.mozilla.com/claim")
    }
)

CANNED_USERINFO["EXPIRED_L3"] = copy.deepcopy(CANNED_USERINFO_STANDARD)
CANNED_USERINFO["EXPIRED_L3"].update(
    {
        "https://sso.mozilla.com/claim/groups": [
            "active_scm_level_1",
            "all_scm_level_1",
            "active_scm_level_2",
            "all_scm_level_2",
            "all_scm_level_3",
        ]
    }
)

CANNED_USERINFO["SINGLE_GROUP"] = copy.deepcopy(CANNED_USERINFO_STANDARD)
CANNED_USERINFO["SINGLE_GROUP"].update(
    {"https://sso.mozilla.com/claim/groups": ["all_scm_level_1"]}
)

CANNED_USERINFO["STRING_GROUP"] = copy.deepcopy(CANNED_USERINFO_STANDARD)
CANNED_USERINFO["STRING_GROUP"].update(
    {"https://sso.mozilla.com/claim/groups": "all_scm_level_1"}
)

CANNED_USERINFO["NO_EMAIL"] = copy.deepcopy(CANNED_USERINFO_STANDARD)
CANNED_USERINFO["NO_EMAIL"].pop("email")

CANNED_USERINFO["UNVERIFIED_EMAIL"] = copy.deepcopy(CANNED_USERINFO_STANDARD)
CANNED_USERINFO["UNVERIFIED_EMAIL"].update({"email_verified": False})

CANNED_USERINFO["MISSING_L1"] = copy.deepcopy(CANNED_USERINFO_STANDARD)
CANNED_USERINFO["MISSING_L1"].update({"https://sso.mozilla.com/claim/groups": []})

CANNED_USERINFO["EXPIRED_L1"] = copy.deepcopy(CANNED_USERINFO_STANDARD)
CANNED_USERINFO["EXPIRED_L1"].update(
    {
        "https://sso.mozilla.com/claim/groups": [
            "all_scm_level_1",
            "expired_scm_level_1",
        ]
    }
)

CANNED_USERINFO["MISSING_ACTIVE_L1"] = copy.deepcopy(CANNED_USERINFO_STANDARD)
CANNED_USERINFO["MISSING_ACTIVE_L1"].update(
    {"https://sso.mozilla.com/claim/groups": ["all_scm_level_1"]}
)
