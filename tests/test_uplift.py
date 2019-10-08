from landoapi.uplift import render_uplift_form

VALID_FORM = """


= Uplift request details =

View [source revision D1234](/D1234)

===== User impact if declined  =====

Not a lot of impact.

===== Steps to reproduce =====

Crash it, that&#39;s all.

===== Why is the change risky/not risky ? =====

Really risky

===== Is this code covered by automated tests ? =====

{icon check color=green} Yes


===== Has the fix been verified in Nightly ? =====

{icon times color=red} No


===== Risk to taking this patch =====

medium

===== Needs manual test from QE ? =====

{icon check color=green} Yes


===== String changes made/needed =====

None.

===== List of other uplifts needed =====

- Bug 1233
"""


def test_form_rendering(app):
    """Test rendering the uplift form"""
    form = render_uplift_form(
        source_revision={"id": 1234},
        form_data={
            "user_impact": "Not a lot of impact.",
            "steps_to_reproduce": "Crash it, that's all.",
            "risky": "Really risky",
            "automated_tests": True,
            "nightly": False,
            "risk": "medium",
            "manual_qe": True,
            "string_changes": "None.",
            "bug_ids": ["1233"],
        },
    )
    assert form == VALID_FORM


def test_uplift_creation(phabdouble, client, auth0_mock, mock_repo_config):
    revision = phabdouble.revision()
    repo_mc = phabdouble.repo()
    repo_uplift = phabdouble.repo(name="mozilla-uplift")

    # This group is required
    phabdouble.project("release-managers")

    payload = {
        "revision_id": revision["id"],
        "repositories": [repo_mc["shortName"]],
        "user_impact": "Not a lot of impact.",
        "steps_to_reproduce": "Crash it, that's all.",
        "risky": "Really risky",
        "automated_tests": True,
        "nightly": False,
        "risk": "medium",
        "manual_qe": True,
        "string_changes": "None.",
        "bug_ids": ["1233"],
    }

    # No auth
    response = client.post("/uplift", json=payload)
    assert response.status_code == 401
    assert response.json["title"] == "Authorization Header Required"

    # Invalid repository (not uplift)
    response = client.post("/uplift", json=payload, headers=auth0_mock.mock_headers)
    assert response.status_code == 400
    assert response.json["title"] == "No valid uplift repositories"

    # Only one revision at first
    assert len(phabdouble._revisions) == 1

    # Valid uplift repository
    payload["repositories"].append(repo_uplift["shortName"])
    response = client.post("/uplift", json=payload, headers=auth0_mock.mock_headers)
    assert response.status_code == 201
    assert response.json == {
        "mozilla-uplift": [
            {
                "diff_id": 2,
                "diff_phid": "PHID-DIFF-1",
                "revision_id": 2,
                "revision_phid": 2,
                "url": "http://phabricator.test/D2",
            }
        ]
    }

    # Now we have a new uplift revision on Phabricator
    assert len(phabdouble._revisions) == 2
    new_rev = phabdouble._revisions[-1]
    assert new_rev["title"] == "Uplift request D1: my test revision title"
