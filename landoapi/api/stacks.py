# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging
import urllib.parse

from connexion import problem
from flask import current_app, g
from landoapi.commit_message import format_commit_message
from landoapi.decorators import require_phabricator_api_key
from landoapi.models.revisions import Revision
from landoapi.phabricator import PhabricatorClient, PhabricatorAPIException
from landoapi.projects import (
    get_sec_approval_project_phid,
    get_secure_project_phid,
    get_relman_group_phid,
    project_search,
)
from landoapi.repos import get_repos_for_env
from landoapi.reviews import (
    get_collated_reviewers,
    reviewers_for_commit_message,
    serialize_reviewers,
)
from landoapi.revisions import (
    find_title_and_summary_for_display,
    gather_involved_phids,
    get_bugzilla_bug,
    revision_is_secure,
    serialize_author,
    serialize_diff,
    serialize_status,
)
from landoapi.stacks import (
    build_stack_graph,
    calculate_landable_subgraphs,
    get_landable_repos_for_revision_data,
    request_extended_revision_data,
)
from landoapi.transplants import get_blocker_checks
from landoapi.users import user_search
from landoapi.validation import revision_id_to_int

logger = logging.getLogger(__name__)

not_found_problem = problem(
    404,
    "Revision not found",
    "The requested revision does not exist",
    type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404",
)


@require_phabricator_api_key(optional=True)
def get(revision_id):
    """Get the stack a revision is part of.

    Args:
        revision_id: (string) ID of the revision in 'D{number}' format
    """
    revision_id = revision_id_to_int(revision_id)

    phab = g.phabricator
    revision = phab.call_conduit(
        "differential.revision.search", constraints={"ids": [revision_id]}
    )
    revision = phab.single(revision, "data", none_when_empty=True)
    if revision is None:
        return not_found_problem

    try:
        nodes, edges = build_stack_graph(phab, phab.expect(revision, "phid"))
    except PhabricatorAPIException:
        # If a revision within the stack causes an API exception, treat the whole stack
        # as not found.
        return not_found_problem
    stack_data = request_extended_revision_data(phab, [phid for phid in nodes])

    supported_repos = get_repos_for_env(current_app.config.get("ENVIRONMENT"))
    landable_repos = get_landable_repos_for_revision_data(stack_data, supported_repos)

    other_checks = get_blocker_checks(
        repositories=supported_repos, relman_group_phid=get_relman_group_phid(phab)
    )

    landable, blocked = calculate_landable_subgraphs(
        stack_data, edges, landable_repos, other_checks=other_checks
    )
    uplift_repos = [
        name for name, repo in supported_repos.items() if repo.approval_required
    ]

    involved_phids = set()
    for revision in stack_data.revisions.values():
        involved_phids.update(gather_involved_phids(revision))

    involved_phids = list(involved_phids)

    users = user_search(phab, involved_phids)
    projects = project_search(phab, involved_phids)

    secure_project_phid = get_secure_project_phid(phab)
    sec_approval_project_phid = get_sec_approval_project_phid(phab)

    revisions_response = []
    for _phid, revision in stack_data.revisions.items():
        lando_revision = Revision.query.filter(
            Revision.revision_id == revision["id"]
        ).one_or_none()
        revision_phid = PhabricatorClient.expect(revision, "phid")
        fields = PhabricatorClient.expect(revision, "fields")
        diff_phid = PhabricatorClient.expect(fields, "diffPHID")
        diff = stack_data.diffs[diff_phid]
        human_revision_id = "D{}".format(PhabricatorClient.expect(revision, "id"))
        revision_url = urllib.parse.urljoin(
            current_app.config["PHABRICATOR_URL"], human_revision_id
        )
        secure = revision_is_secure(revision, secure_project_phid)
        commit_description = find_title_and_summary_for_display(phab, revision, secure)
        bug_id = get_bugzilla_bug(revision)
        reviewers = get_collated_reviewers(revision)
        accepted_reviewers = reviewers_for_commit_message(
            reviewers, users, projects, sec_approval_project_phid
        )
        commit_message_title, commit_message = format_commit_message(
            commit_description.title,
            bug_id,
            accepted_reviewers,
            commit_description.summary,
            revision_url,
        )
        author_response = serialize_author(phab.expect(fields, "authorPHID"), users)

        revisions_response.append(
            {
                "id": human_revision_id,
                "phid": revision_phid,
                "status": serialize_status(revision),
                "blocked_reason": blocked.get(revision_phid, ""),
                "bug_id": bug_id,
                "title": commit_description.title,
                "url": revision_url,
                "date_created": PhabricatorClient.to_datetime(
                    PhabricatorClient.expect(revision, "fields", "dateCreated")
                ).isoformat(),
                "date_modified": PhabricatorClient.to_datetime(
                    PhabricatorClient.expect(revision, "fields", "dateModified")
                ).isoformat(),
                "summary": commit_description.summary,
                "commit_message_title": commit_message_title,
                "commit_message": commit_message,
                "repo_phid": PhabricatorClient.expect(fields, "repositoryPHID"),
                "diff": serialize_diff(diff),
                "author": author_response,
                "reviewers": serialize_reviewers(reviewers, users, projects, diff_phid),
                "is_secure": secure,
                "is_using_secure_commit_message": commit_description.sanitized,
                "lando_revision": lando_revision.serialize()
                if lando_revision
                else None,
            }
        )

    repositories = []
    for phid in stack_data.repositories.keys():
        short_name = PhabricatorClient.expect(
            stack_data.repositories[phid], "fields", "shortName"
        )

        repo = supported_repos.get(short_name)
        landing_supported = repo is not None
        url = (
            repo.url
            if landing_supported
            else f"{current_app.config['PHABRICATOR_URL']}/source/{short_name}"
        )

        repositories.append(
            {
                "approval_required": landing_supported and repo.approval_required,
                "commit_flags": repo.commit_flags if repo else [],
                "landing_supported": landing_supported,
                "phid": phid,
                "short_name": short_name,
                "url": url,
            }
        )

    return {
        "repositories": repositories,
        "revisions": revisions_response,
        "edges": [e for e in edges],
        "landable_paths": landable,
        "uplift_repositories": uplift_repos,
    }
