# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.


def test_uplift_creation(phabdouble, client, auth0_mock, mock_repo_config):
    revision = phabdouble.revision()
    repo_mc = phabdouble.repo()
    user = phabdouble.user(username="JohnDoe")
    repo_uplift = phabdouble.repo(name="mozilla-uplift")

    # This group is required
    phabdouble.project("release-managers")

    payload = {
        "revision_id": revision["id"],
        "repository": repo_mc["shortName"],
        "form_content": "Here are all the details about my uplift request...",
    }

    # No auth
    response = client.post("/uplift", json=payload)
    assert response.status_code == 401
    assert response.json["title"] == "X-Phabricator-API-Key Required"

    # API key but no auth0
    headers = {"X-Phabricator-API-Key": user["apiKey"]}
    response = client.post("/uplift", json=payload, headers=headers)
    assert response.status_code == 401
    assert response.json["title"] == "Authorization Header Required"

    # Invalid repository (not uplift)
    headers.update(auth0_mock.mock_headers)
    response = client.post("/uplift", json=payload, headers=headers)
    assert response.status_code == 400
    assert response.json["title"] == "No valid uplift repository"

    # Only one revision at first
    assert len(phabdouble._revisions) == 1

    # Valid uplift repository
    payload["repository"] = repo_uplift["shortName"]
    response = client.post("/uplift", json=payload, headers=headers)
    assert response.status_code == 201
    assert response.json == {
        "repository": "mozilla-uplift",
        "diff_id": 2,
        "diff_phid": "PHID-DIFF-1",
        "revision_id": 2,
        "revision_phid": 2,
        "url": "http://phabricator.test/D2",
    }

    # Now we have a new uplift revision on Phabricator
    assert len(phabdouble._revisions) == 2
    new_rev = phabdouble._revisions[-1]
    assert new_rev["title"] == "Uplift request D1: my test revision title"
