# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import pytest
from packaging.version import (
    Version,
)

from landoapi.phabricator import (
    PhabricatorClient,
)
from landoapi.stacks import (
    build_stack_graph,
)
from landoapi.uplift import (
    add_original_revision_line_if_needed,
    create_uplift_bug_update_payload,
    get_revisions_without_bugs,
    parse_milestone_version,
    strip_depends_on_from_commit_message,
)

MILESTONE_TEST_CONTENTS_1 = """
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

MILESTONE_TEST_CONTENTS_2 = """
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

105.0
"""


def test_parse_milestone_version():
    assert parse_milestone_version(MILESTONE_TEST_CONTENTS_1) == Version(
        "84.0a1"
    ), "Test milestone file 1 should have 84 as major milestone version."

    assert parse_milestone_version(MILESTONE_TEST_CONTENTS_2) == Version(
        "105.0"
    ), "Test milestone file 2 should have 84 as major milestone version."

    bad_milestone_contents = "blahblahblah"
    with pytest.raises(ValueError, match=bad_milestone_contents):
        parse_milestone_version(bad_milestone_contents)


DEPENDS_ON_MESSAGE = """
bug 123: testing r?sheehan

Something something Depends on D1234

Differential Revision: http://phab.test/D234

Depends on D567
""".strip()


def test_strip_depends_on_from_commit_message():
    assert strip_depends_on_from_commit_message(DEPENDS_ON_MESSAGE) == (
        "bug 123: testing r?sheehan\n"
        "\n"
        "Something something Depends on D1234\n"
        "\n"
        "Differential Revision: http://phab.test/D234\n"
    ), "`Depends on` line should be stripped from commit message."


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
    payload = create_uplift_bug_update_payload(
        bug, "beta", 100, "cf_status_firefox{milestone}"
    )

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
    payload = create_uplift_bug_update_payload(
        bug, "beta", 100, "cf_status_firefox{milestone}"
    )

    assert (
        "cf_status_firefox100" not in payload
    ), "Status should not have been set with `leave-open` keyword on bug."


def test_add_original_revision_line_if_needed():
    uri = "http://phabricator.test/D123"

    summary_no_original = "Bug 123: test summary r?sheehan"
    summary_with_original = (
        "Bug 123: test summary r?sheehan\n"
        "\n"
        "Original Revision: http://phabricator.test/D123"
    )

    assert (
        add_original_revision_line_if_needed(summary_no_original, uri)
        == summary_with_original
    ), "Passing summary without `Original Revision` should return with line added."

    assert (
        add_original_revision_line_if_needed(summary_with_original, uri)
        == summary_with_original
    ), "Passing summary with `Original Revision` should return the input."


def test_get_revisions_without_bugs(phabdouble):
    phab = phabdouble.get_phabricator_client()

    rev1 = phabdouble.revision(bug_id=123)
    revs = phabdouble.differential_revision_search(
        constraints={"phids": [rev1["phid"]]},
    )
    revisions = phab.expect(revs, "data")

    assert (
        get_revisions_without_bugs(phab, revisions) == set()
    ), "Empty set should be returned if all revisions have bugs."

    rev2 = phabdouble.revision()
    revs = phabdouble.differential_revision_search(
        constraints={"phids": [rev1["phid"], rev2["phid"]]},
    )
    revisions = phab.expect(revs, "data")

    assert get_revisions_without_bugs(phab, revisions) == {
        rev2["id"]
    }, "Revision without associated bug should be returned."
