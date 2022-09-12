# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
from __future__ import annotations

import io
import logging
from itertools import chain

import networkx as nx

from landoapi.hg import HgRepo
from landoapi.models.revisions import Revision
from landoapi.models.revisions import RevisionStatus as RS
from landoapi.phabricator import get_conduit_data
from landoapi.repos import repo_clone_subsystem
from landoapi.storage import db
from landoapi.workers.base import RevisionWorker

logger = logging.getLogger(__name__)


DIFF_CONTEXT_SIZE = 5000


class StackGraph(nx.DiGraph):
    def __eq__(self, G):
        return nx.utils.misc.graphs_equal(self, G)

    @property
    def revisions(self):
        return self.nodes


def get_active_repos(repo_config: dict) -> list[str]:
    """Query Phabricator to determine PHIDs of active repos."""
    repos = [repo for repo in repo_config if repo.use_revision_worker]
    repo_phids = get_conduit_data(
        "diffusion.repository.search",
        constraints={"shortNames": [r.short_name for r in repos]},
    )
    return [r["phid"] for r in repo_phids]


def get_stacks(revisions: dict[str, dict]) -> list:
    """Returns a stack with revision PHIDs as nodes.

    This method fetches unique stacks from a list of stack graphs. This
    is because Phabricator returns different forms of the same stack graph
    in each revision.

    This method will return a list of StackGraph objects.
    """
    stacks = [r["fields"]["stackGraph"] for r in revisions.values()]
    parsed = [StackGraph(s).reverse() for s in stacks]

    filtered = []
    for stack in parsed:
        if stack not in filtered:
            filtered.append(stack)
    return filtered


def get_phab_revisions(statuses: list[str] | None = None) -> dict[int, dict]:
    """Get a list of revisions of given statuses."""
    statuses = statuses or [
        "accepted",
        "changes-planned",
        "draft",
        "needs-review",
        "published",
    ]

    # Get all revisions with given filters.
    repo_config = repo_clone_subsystem.repos.values()
    revisions = get_conduit_data(
        "differential.revision.search",
        constraints={
            "statuses": statuses,
            "repositoryPHIDs": get_active_repos(repo_config),
        },
    )

    # Translate into a dictionary.
    revisions = {r["phid"]: r for r in revisions}

    if not revisions:
        return {}

    # Get list of unique stacks included in these revisions.
    stacks = get_stacks(revisions)

    # Ensure that all revisions in each stack are in our revisions list.
    input_revisions = set(chain(*[stack.revisions for stack in stacks]))
    missing_keys = input_revisions.difference(revisions.keys())

    if missing_keys:
        stragglers = get_conduit_data(
            "differential.revision.search",
            constraints={"phids": list(missing_keys)},
        )
        revisions.update({r["phid"]: r for r in stragglers})

    # Convert back to a list.
    revisions = list(revisions.values())

    # Create a map to translate phids to revision IDs.
    revision_phid_map = {r["phid"]: str(r["id"]) for r in revisions}

    # Translate phids in stack graph to revision IDs.
    for revision in revisions:
        stack_graph = revision["fields"]["stackGraph"]
        stack_graph = {
            revision_phid_map[k]: [revision_phid_map[_v] for _v in v]
            for k, v in stack_graph.items()
        }
        revision["fields"]["stackGraph"] = stack_graph

    # Translate all revisions into a format that can be consumed by Lando.
    revisions = [
        {
            "revision_id": r["id"],
            "diff_id": r["fields"]["diffID"],
            "diff_phid": r["fields"]["diffPHID"],
            "repo_phid": r["fields"]["repositoryPHID"],
            "phid": r["phid"],
            "stack_graph": r["fields"]["stackGraph"],
        }
        for r in revisions
        if r["fields"]["diffPHID"] and r["fields"]["repositoryPHID"]
    ]

    repo_phids = [r["repo_phid"] for r in revisions]
    repo_ids = get_conduit_data(
        "diffusion.repository.search", constraints={"phids": repo_phids}
    )
    repo_map = {
        d["phid"]: {
            "repo_name": d["fields"]["shortName"],
            "repo_callsign": d["fields"]["callsign"],
        }
        for d in repo_ids
    }

    for r in revisions:
        r.update(repo_map[r["repo_phid"]])

        # Move PHIDs to their own key
        r["phids"] = {
            "repo_phid": r.pop("repo_phid"),
            "diff_phid": r.pop("diff_phid"),
            "revision_phid": r.pop("phid"),
        }

    logger.debug(f"Found {len(revisions)} revisions from Phabricator API")

    return {r["revision_id"]: r for r in revisions}


def parse_diff(diff: str) -> set[str]:
    """Given a diff, extract list of affected files."""
    diff_lines = diff.splitlines()
    file_diffs = [
        line.split(" ")[2:] for line in diff_lines if line.strip().startswith("diff")
    ]
    file_paths = set()
    for file_diff in file_diffs:
        # Parse source/destination paths.
        path1, path2 = file_diff
        file_paths.add("/".join(path1.split("/")[1:]))
        file_paths.add("/".join(path2.split("/")[1:]))
    return file_paths


def discover_revisions() -> None:
    """Check and update local database with available revisions."""
    phab_revisions = get_phab_revisions()
    revisions_to_stale_successors_of = []
    new_revisions = []
    all_revisions = []

    for phab_revision in phab_revisions.values():
        revision_id = phab_revision["revision_id"]
        diff_id = phab_revision["diff_id"]
        lando_revision = Revision.query.filter(
            Revision.revision_id == revision_id
        ).one_or_none()

        if lando_revision and lando_revision.status in RS.LANDING_STATES:
            continue

        new = not lando_revision
        if new:
            logger.info(f"Picked up new revision {revision_id}.")
            lando_revision = Revision(revision_id=revision_id, diff_id=diff_id)
            db.session.add(lando_revision)
            new_revisions.append(lando_revision)

        all_revisions.append(lando_revision)

        if lando_revision.change_triggered(phab_revision) or new:
            logger.info(f"Change detected in {lando_revision}.")
            # Update all matching fields in the revision with remote data.
            for key, value in phab_revision.items():
                if key == "phids":
                    lando_revision.update_data(**value)
                else:
                    setattr(lando_revision, key, value)
            lando_revision.set_temporary_patch()
            lando_revision.status = RS.WAITING
            revisions_to_stale_successors_of.append(lando_revision)
            db.session.commit()

    for revision in set(revisions_to_stale_successors_of) - set(new_revisions):
        for successor in revision.successors:
            successor.status = RS.STALE

    for revision in all_revisions:
        if len(list(revision.stack.predecessors(revision))) > 1:
            revision.status = RS.PROBLEM
            revision.update_data(error="Revision has more than one predecessor.")
    db.session.commit()


def mark_stale_revisions() -> None:
    """Discover any upstream changes, and mark revisions affected as stale."""
    repos = Revision.query.with_entities(Revision.repo_name).distinct().all()
    repos = tuple(repo[0] for repo in repos if repo[0])
    for repo_name in repos:
        repo = repo_clone_subsystem.repos[repo_name]
        hgrepo = HgRepo(
            str(repo_clone_subsystem.repo_paths[repo_name]),
        )
        # checkout repo, pull & update
        with hgrepo.for_pull():
            if hgrepo.has_incoming(repo.pull_path):
                hgrepo.update_repo(repo.pull_path)
                logger.info(f"Incoming changes detected in {repo_name}.")
                revisions = Revision.query.filter(
                    Revision.status.not_in(RS.LANDING_STATES),
                    Revision.repo_name == repo_name,
                )
                logger.info(f"Marking {revisions.count()} revisions as stale.")
                revisions.update({Revision.status: RS.STALE})
    db.session.commit()


class Supervisor(RevisionWorker):
    """A worker that pre-processes revisions.

    This worker continuously synchronises revisions with the remote Phabricator API
    and runs all applicable checks and processes on each revision, if needed.
    """

    def loop(self):
        """Run the event loop for the revision worker."""
        self.throttle()
        mark_stale_revisions()
        discover_revisions()


class Processor(RevisionWorker):
    """A worker that pre-processes revisions.

    This worker continuously synchronises revisions with the remote Phabricator API
    and runs all applicable checks and processes on each revision, if needed.
    """

    def loop(self):
        """Run the event loop for the revision worker."""
        self.throttle()

        # Fetch revisions that require pre-processing.
        with db.session.begin_nested():
            Revision.lock_table()
            revisions = Revision.query.filter(
                Revision.status.in_([RS.WAITING, RS.STALE])
            ).limit(self.capacity)

            picked_up = [r.id for r in revisions]

            # Mark revisions as picked up so other workers don't pick them up.
            Revision.query.filter(Revision.id.in_(picked_up)).update(
                {Revision.status: RS.PICKED_UP}
            )

        db.session.commit()

        revisions = Revision.query.filter(Revision.id.in_(picked_up))

        # NOTE: The revisions will be processed according to their dependencies
        # at the time of fetching. If dependencies change, they will be
        # re-processed on the next iteration. This has the effect of processing
        # revisions as they become available, if, for example, a large stack is
        # being uploaded.

        logger.info(f"Found {revisions.all()} to process.")
        for revision in revisions:
            errors = []
            logger.info(f"Running checks on revision {revision}")

            revision.status = RS.CHECKING
            db.session.commit()

            try:
                errors = self.process(revision)
            except Exception as e:
                logger.info(f"Exception encountered while processing {revision}")
                revision.status = RS.PROBLEM
                revision.update_data(error="".join(e.args))
                logger.exception(e)
                db.session.commit()
                continue

            if errors:
                logger.info(f"Errors detected on revision {revision}")
                revision.status = RS.PROBLEM
                revision.update_data(error="".join(errors))
            else:
                revision.status = RS.READY
                logger.info(f"No problems detected on revision {revision}")
            db.session.commit()

    def _process_patch(self, revision: Revision, hgrepo: HgRepo) -> list[str]:
        """Run through all predecessors before applying revision patch."""
        errors = []
        for r in revision.predecessors + [revision]:
            try:
                hgrepo.apply_patch(io.BytesIO(r.patch_bytes))
            except Exception as e:
                # Something is wrong (e.g., merge conflict). Log and break.
                logger.error(e)
                errors.append(f"Problem detected in {r} ({e})")
                break
        return errors

    def _get_repo_objects(self, repo_name: str) -> tuple[HgRepo, str]:
        """Given a repo name, return the hg repo object and pull path."""
        repo = repo_clone_subsystem.repos[repo_name]
        hgrepo = HgRepo(
            str(repo_clone_subsystem.repo_paths[repo_name]),
        )
        return hgrepo, repo.pull_path

    def process(self, revision: Revision) -> list[str]:
        """Update repo and attempt to import patch."""
        errors = list()

        hgrepo, pull_path = self._get_repo_objects(revision.repo_name)

        # checkout repo, pull & update
        with hgrepo.for_pull():
            hgrepo.update_repo(pull_path)

            # Try to merge the revision patch and its predecessors.
            errors = self._process_patch(revision, hgrepo)
        return errors
