# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import pytest

from landoapi.phabricator import PhabricatorClient
from landoapi.stacks import build_stack_graph
from landoapi.uplift import (
    create_uplift_bug_update_payload,
    move_drev_to_original,
    parse_milestone_major_version,
)

MILESTONE_TEST_CONTENTS = """
# Holds the current milestone.
# Should be in the format of
#
#    x.x.x
#    x.x.x.x
#    x.x.x+
#
# Referenced by build/moz.configure/init.configure.
# Hopefully I'll be able to automate replacement of *all*
# hardcoded milestones in the tree from these two files.
#--------------------------------------------------------

84.0a1
"""


def test_parse_milestone_major_version():
    assert (
        parse_milestone_major_version(MILESTONE_TEST_CONTENTS) == 84
    ), "Test milestone file should have 84 as major milestone version."


def test_move_drev_to_original():
    # Ensure `Differential Revision` is moved to `Original`.
    commit_message = (
        "bug 1: title r?reviewer\n"
        "\n"
        "Differential Revision: http://phabricator.test/D1"
    )
    expected = (
        "bug 1: title r?reviewer\n\nOriginal Revision: http://phabricator.test/D1"
    )
    message = move_drev_to_original(commit_message)
    assert (
        message == expected
    ), "`Differential Revision` not re-written to `Original Revision` on uplift."

    # Ensure `Original` and `Differential` in commit message is left unchanged.
    commit_message = (
        "bug 1: title r?reviewer\n"
        "\n"
        "Original Revision: http://phabricator.test/D1\n"
        "\n"
        "Differential Revision: http://phabricator.test/D2"
    )
    message = move_drev_to_original(commit_message)
    assert (
        message == commit_message
    ), "Commit message should not have changed when original revision already present."


@pytest.mark.xfail
def test_uplift_creation(
    db,
    monkeypatch,
    phabdouble,
    client,
    auth0_mock,
    mock_repo_config,
    release_management_project,
):
    def _call_conduit(client, method, **kwargs):
        if method == "differential.revision.edit":
            # Load transactions
            transactions = kwargs.get("transactions")
            assert transactions is not None
            transactions = {t["type"]: t["value"] for t in transactions}

            # Check the state of the added transactions is valid for the first uplift.
            if transactions["update"] == "PHID-DIFF-1":
                # Check the expected transactions
                expected = {
                    "update": "PHID-DIFF-1",
                    "title": "Add feature XXX",
                    "summary": (
                        "some really complex stuff\n"
                        "\n"
                        "Original Revision: http://phabricator.test/D1"
                    ),
                    "bugzilla.bug-id": "",
                    "reviewers.add": ["blocking(PHID-PROJ-0)"],
                }
                for key in expected:
                    assert (
                        transactions[key] == expected[key]
                    ), f"key does not match: {key}"

            depends_on = []
            if "parents.set" in transactions:
                depends_on.append({"phid": transactions["parents.set"][0]})

            # Create a new revision
            new_rev = phabdouble.revision(
                title=transactions["title"],
                summary=transactions["summary"],
                depends_on=depends_on,
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

    diff = phabdouble.diff()
    revision = phabdouble.revision(
        title="Add feature XXX",
        summary=(
            "some really complex stuff\n"
            "\n"
            "Differential Revision: http://phabricator.test/D1"
        ),
        diff=diff,
    )
    repo_mc = phabdouble.repo()
    user = phabdouble.user(username="JohnDoe")
    repo_uplift = phabdouble.repo(name="mozilla-uplift")

    payload = {
        "landing_path": [
            {"revision_id": f"D{revision['id']}", "diff_id": diff["id"]},
        ],
        "repository": repo_mc["shortName"],
    }

    # No auth
    response = client.post("/uplift", json=payload)
    assert response.json["title"] == "X-Phabricator-API-Key Required"
    assert response.status_code == 401

    # API key but no auth0
    headers = {"X-Phabricator-API-Key": user["apiKey"]}
    response = client.post("/uplift", json=payload, headers=headers)
    assert response.status_code == 401
    assert response.json["title"] == "Authorization Header Required"

    # Invalid repository (not uplift)
    headers.update(auth0_mock.mock_headers)
    response = client.post("/uplift", json=payload, headers=headers)
    assert response.status_code == 400
    assert (
        response.json["title"]
        == "Repository mozilla-central is not an uplift repository."
    )

    # Only one revision at first
    assert len(phabdouble._revisions) == 1

    # Valid uplift repository
    payload["repository"] = repo_uplift["shortName"]
    response = client.post("/uplift", json=payload, headers=headers)
    assert response.status_code == 201
    assert response.json == {
        "PHID-DREV-1": {
            "mode": "uplift",
            "repository": "mozilla-uplift",
            "diff_id": 2,
            "diff_phid": "PHID-DIFF-1",
            "revision_id": 2,
            "revision_phid": "PHID-DREV-1",
            "url": "http://phabricator.test/D2",
        },
        "tip_differential": {
            "mode": "uplift",
            "repository": "mozilla-uplift",
            "diff_id": 2,
            "diff_phid": "PHID-DIFF-1",
            "revision_id": 2,
            "revision_phid": "PHID-DREV-1",
            "url": "http://phabricator.test/D2",
        },
    }

    # Now we have a new uplift revision on Phabricator
    assert len(phabdouble._revisions) == 2
    new_rev = phabdouble._revisions[-1]
    assert new_rev["title"] == "Add feature XXX"
    assert (
        new_rev["summary"]
        == "some really complex stuff\n\nOriginal Revision: http://phabricator.test/D1"
    )

    # Add some more revisions to test uplifting a stack.
    diff2 = phabdouble.diff()
    rev2 = phabdouble.revision(
        title="bug 1: xxx r?reviewer",
        summary=("summary info.\n\nDifferential Revision: http://phabricator.test/D3"),
        diff=diff2,
    )
    diff3 = phabdouble.diff()
    rev3 = phabdouble.revision(
        title="bug 1: yyy r?reviewer",
        summary=("summary two.\n\nDifferential Revision: http://phabricator.test/D4"),
        depends_on=[rev2],
        diff=diff3,
    )
    diff4 = phabdouble.diff()
    rev4 = phabdouble.revision(
        title="bug 1: yyy r?reviewer",
        summary=("summary two.\n\nDifferential Revision: http://phabricator.test/D4"),
        depends_on=[rev3],
        diff=diff4,
    )

    # Send an uplift request for a stack.
    payload["landing_path"] = [
        {"revision_id": f"D{rev2['id']}", "diff_id": diff2["id"]},
        {"revision_id": f"D{rev3['id']}", "diff_id": diff3["id"]},
        {"revision_id": f"D{rev4['id']}", "diff_id": diff4["id"]},
    ]
    response = client.post("/uplift", json=payload, headers=headers)
    assert response.status_code == 201, "Response should have status code 201."
    assert len(response.json) == 4, "API call should have created 3 revisions."
    assert response.json == {
        "PHID-DREV-5": {
            "mode": "uplift",
            "repository": "mozilla-uplift",
            "diff_id": 7,
            "diff_phid": "PHID-DIFF-6",
            "revision_id": 6,
            "revision_phid": "PHID-DREV-5",
            "url": "http://phabricator.test/D6",
        },
        "PHID-DREV-6": {
            "mode": "uplift",
            "repository": "mozilla-uplift",
            "diff_id": 9,
            "diff_phid": "PHID-DIFF-8",
            "revision_id": 7,
            "revision_phid": "PHID-DREV-6",
            "url": "http://phabricator.test/D7",
        },
        "PHID-DREV-7": {
            "mode": "uplift",
            "repository": "mozilla-uplift",
            "diff_id": 11,
            "diff_phid": "PHID-DIFF-10",
            "revision_id": 8,
            "revision_phid": "PHID-DREV-7",
            "url": "http://phabricator.test/D8",
        },
        "tip_differential": {
            "mode": "uplift",
            "repository": "mozilla-uplift",
            "diff_id": 11,
            "diff_phid": "PHID-DIFF-10",
            "revision_id": 8,
            "revision_phid": "PHID-DREV-7",
            "url": "http://phabricator.test/D8",
        },
    }, "Response JSON does not match expected."

    # Check that parent-child relationships are preserved.
    phab = phabdouble.get_phabricator_client()
    last_phid = response.json["tip_differential"]["revision_phid"]
    _nodes, edges = build_stack_graph(phab, last_phid)

    assert edges == {
        ("PHID-DREV-7", "PHID-DREV-6"),
        ("PHID-DREV-6", "PHID-DREV-5"),
    }, "Uplift does not preserve parent/child relationships."
    # We still have the same revision
    assert len(phabdouble._revisions) == 1
    new_rev = phabdouble._revisions[0]
    assert new_rev["title"] == "my test revision title"


def test_create_uplift_bug_update_payload():
    bug = {
        "cf_status_firefox100": "---",
        "id": 123,
        "keywords": [],
        "whiteboard": "[checkin-needed-beta]",
    }
    payload = create_uplift_bug_update_payload(bug, "beta", 100)

    assert payload["ids"] == [123], "Passed bug ID should be present in the payload."
    assert (
        payload["whiteboard"] == ""
    ), "checkin-needed flag should be removed from whiteboard."
    assert (
        payload["cf_status_firefox100"] == "fixed"
    ), "Custom tracking flag should be set to `fixed`."

    bug = {
        "cf_status_firefox100": "---",
        "id": 123,
        "keywords": ["leave-open"],
        "whiteboard": "[checkin-needed-beta]",
    }
    payload = create_uplift_bug_update_payload(bug, "beta", 100)

    assert (
        "cf_status_firefox100" not in payload
    ), "Status should not have been set with `leave-open` keyword on bug."
