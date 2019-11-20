# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from landoapi.phabricator import PhabricatorClient


def test_uplift_creation(monkeypatch, phabdouble, client, auth0_mock, mock_repo_config):
    def _call_conduit(client, method, **kwargs):
        if method == "differential.revision.edit":
            # Load transactions
            transactions = kwargs.get("transactions")
            assert transactions is not None
            transactions = {t["type"]: t["value"] for t in transactions}

            # Check the expected transactions
            assert transactions == {
                "update": "PHID-DIFF-1",
                "title": "Add feature XXX",
                "summary": "some really complex stuff\nNOTE: Uplifted from D1",
                "bugzilla.bug-id": "",
                "comment": "Here are all the details about my uplift request...",
                "reviewers.add": ["PHID-PROJ-0"],
            }

            # Create a new revision
            new_rev = phabdouble.revision(
                title=transactions["title"], summary=transactions["summary"]
            )
            return {
                "object": {"id": new_rev["id"], "phid": new_rev["phid"]},
                "transactions": [
                    {"phid": "PHID-XACT-DREV-fakeplaceholder"} for t in transactions
                ],
            }

        else:
            # Every other request fall back in phabdouble
            return phabdouble.call_conduit(method, **kwargs)

    # Intercept the revision creation to avoid transactions support in phabdouble
    monkeypatch.setattr(PhabricatorClient, "call_conduit", _call_conduit)

    revision = phabdouble.revision(
        title="Add feature XXX", summary="some really complex stuff"
    )
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
        "mode": "uplift",
        "repository": "mozilla-uplift",
        "diff_id": 2,
        "diff_phid": "PHID-DIFF-1",
        "revision_id": 2,
        "revision_phid": "PHID-DREV-1",
        "url": "http://phabricator.test/D2",
    }

    # Now we have a new uplift revision on Phabricator
    assert len(phabdouble._revisions) == 2
    new_rev = phabdouble._revisions[-1]
    assert new_rev["title"] == "Add feature XXX"
    assert new_rev["summary"] == "some really complex stuff\nNOTE: Uplifted from D1"


def test_approval_creation(phabdouble, client, auth0_mock, mock_repo_config):
    repo = phabdouble.repo(name="mozilla-uplift")
    revision = phabdouble.revision(repo=repo)
    user = phabdouble.user(username="JohnDoe")

    # This group is required
    phabdouble.project("release-managers")

    payload = {
        "revision_id": revision["id"],
        "repository": repo["shortName"],
        "form_content": "Here are all the details about my approval request...",
    }
    headers = {"X-Phabricator-API-Key": user["apiKey"]}
    headers.update(auth0_mock.mock_headers)

    # Only one revision at first
    assert len(phabdouble._revisions) == 1

    # Valid approval request
    response = client.post("/uplift", json=payload, headers=headers)
    assert response.status_code == 201
    assert response.json == {
        "mode": "approval",
        "revision_id": 1,
        "revision_phid": "PHID-DREV-0",
        "url": "http://phabricator.test/D1",
    }

    # We still have the same revision
    assert len(phabdouble._revisions) == 1
    new_rev = phabdouble._revisions[0]
    assert new_rev["title"] == "my test revision title"
