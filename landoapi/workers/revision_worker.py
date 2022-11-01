# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
from __future__ import annotations

import io
import logging
from pathlib import Path
from itertools import chain

import networkx as nx
from flask import current_app
from mots.config import FileConfig, validate
from mots.directory import Directory, QueryResult

from landoapi.hg import HgRepo
from landoapi.models.revisions import Revision
from landoapi.models.revisions import RevisionStatus as RS
from landoapi.phabricator import PhabricatorAPIException, PhabricatorClient
from landoapi.repos import repo_clone_subsystem
from landoapi.storage import db, _lock_table_for
from landoapi.workers import RevisionWorker

logger = logging.getLogger(__name__)


DIFF_CONTEXT_SIZE = 5000


class StackGraph(nx.DiGraph):
    def __eq__(self, G):
        return nx.utils.misc.graphs_equal(self, G)

    @property
    def revisions(self):
        return self.nodes


def get_phab_client():
    phab = PhabricatorClient(
        current_app.config["PHABRICATOR_URL"],
        current_app.config["PHABRICATOR_UNPRIVILEGED_API_KEY"],
    )
    return phab


def call_conduit(method, **kwargs):
    """Send data to conduit API."""
    phab = get_phab_client()
    try:
        result = phab.call_conduit(method, **kwargs)
    except PhabricatorAPIException as e:
        logger.error(e)
        # TODO: raise or return error here.
        return
    return result


def get_conduit_data(method, **kwargs):
    """Fetch result from conduit API request."""
    data = []
    result = call_conduit(method, **kwargs)
    if not result:
        return data

    data += result["data"]
    while result["cursor"]["after"]:
        result = call_conduit(method, after=result["cursor"]["after"], **kwargs)
        if result and "data" in result:
            data += result["data"]
    return data


def get_active_repos(repo_config):
    repos = [repo for repo in repo_config if repo.use_revision_worker]
    repo_phids = get_conduit_data(
        "diffusion.repository.search",
        constraints={"shortNames": [r.short_name for r in repos]},
    )
    return [r["phid"] for r in repo_phids]


def get_stacks(revisions):
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


def get_phab_revisions(statuses=None):
    """Get a list of revisions of given statuses."""
    statuses = statuses or [
        "draft",
        "needs-review",
        "accepted",
        "published",
        "changes-planned",
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
    # TODO: TEST THIS
    if missing_keys:
        stragglers = get_conduit_data(
            "differential.revision.search",
            constraints={"phids": list(missing_keys)},
        )
        revisions.update({r["phid"]: r for r in stragglers})

    # Convert back to a list.
    revisions = list(revisions.values())

    # Create a map to translate phids to revision IDs.
    revision_phid_map = {r["phid"]: r["id"] for r in revisions}

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
            "diff_phid": r["fields"]["diffPHID"],
            "repo_phid": r["fields"]["repositoryPHID"],
            "phid": r["phid"],
            "predecessor": r["fields"]["stackGraph"][r["id"]],
        }
        for r in revisions
        if r["fields"]["diffPHID"] and r["fields"]["repositoryPHID"]
    ]

    diff_phids = [r["diff_phid"] for r in revisions]
    diff_ids = get_conduit_data(
        "differential.diff.search", constraints={"phids": diff_phids}
    )
    diff_map = {d["phid"]: d["id"] for d in diff_ids}

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
        r["diff_id"] = diff_map[r["diff_phid"]]
        r.update(repo_map[r["repo_phid"]])
        r["phids"] = {
            "repo_phid": r["repo_phid"],
            "diff_phid": r["diff_phid"],
            "revision_phid": r["phid"],
        }

        del r["diff_phid"]
        del r["repo_phid"]
        del r["phid"]

    logger.debug(f"Found {len(revisions)} revisions from Phabricator API")

    revs = {r["revision_id"]: r for r in revisions}
    return revs


def parse_diff(diff):
    """Given a diff, extract list of affected files."""
    diff_lines = diff.splitlines()
    file_diffs = [
        line.split(" ")[2:] for line in diff_lines if line.strip().startswith("diff")
    ]
    file_paths = []
    for file_diff in file_diffs:
        # Parse source/destination paths.
        path1, path2 = file_diff
        file_paths.append("/".join(path1.split("/")[1:]))
        file_paths.append("/".join(path2.split("/")[1:]))
    file_paths = set(file_paths)
    return file_paths


def discover_revisions():
    """Check and update local database with available revisions."""
    phab_revisions = get_phab_revisions()

    dependency_queue = []

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

        if lando_revision.change_triggered(phab_revision):
            logger.info(f"Change detected in {lando_revision}.")
            # Update all matching fields in the revision with remote data.
            for key, value in phab_revision.items():
                if key == "phids":
                    lando_revision.update_data(**value)
                elif key == "predecessor":
                    dependency_queue.append(lando_revision)
                    lando_revision.update_data(predecessor=value)
                else:
                    setattr(lando_revision, key, value)
            lando_revision.status = RS.READY_FOR_PREPROCESSING
            if lando_revision.successors and not new:
                for successor in lando_revision.successors:
                    successor.status = RS.STALE
    db.session.commit()

    # Resolve dependency chain.
    for revision in dependency_queue:
        if revision.data["predecessor"]:
            if len(revision.data["predecessor"]) == 1:
                predecessor_revision = Revision.query.filter(
                    Revision.revision_id == revision.data["predecessor"][0]
                ).one()
                revision.predecessor_id = predecessor_revision.id
            if len(revision.data["predecessor"]) > 1:
                revision.status = RS.PROBLEM
                revision.update_data(error="Revision has more than one predecessor.")
        else:
            revision.predecessor = None
    db.session.commit()


def mark_stale_revisions():
    """Discover any upstream changes, and mark revisions affected as stale."""
    repos = Revision.query.with_entities(Revision.repo_name).distinct().all()
    repos = tuple(repo[0] for repo in repos if repo[0])
    for repo_name in repos:
        repo = repo_clone_subsystem.repos[repo_name]
        hgrepo = HgRepo(
            str(repo_clone_subsystem.repo_paths[repo_name]),
            config=repo.config_override,
        )
        # checkout repo, pull & update
        with hgrepo.for_pull():
            if hgrepo.incoming(repo.pull_path):
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
            _lock_table_for(db.session, model=Revision)
            revisions = Revision.query.filter(
                Revision.status.in_([RS.READY_FOR_PREPROCESSING, RS.STALE])
            ).limit(self.capacity)

            picked_up = [r.id for r in revisions]

            # Mark revisions as picked up so other workers don't pick them up.
            Revision.query.filter(Revision.id.in_(picked_up)).update(
                {Revision.status: RS.PICKED_UP}
            )

            db.session.commit()

        revisions = Revision.query.filter(Revision.id.in_(picked_up))

        db.session.commit()

        # NOTE: The revisions will be processed according to their dependencies
        # at the time of fetching. If dependencies change, they will be
        # re-process on the next iteration.

        messages = []

        logger.info(f"Found {revisions.all()} to process.")
        for revision in revisions:
            warnings, errors = [], []
            logger.info(f"Running checks on revision {revision}")

            revision.status = RS.PREPROCESSING
            db.session.commit()

            try:
                warnings, errors = self.process(revision)
                if errors:
                    logger.info(f"Errors detected on revision {revision}")
                    revision.status = RS.PROBLEM
                    revision.update_data(error="".join(errors))
                else:
                    revision.status = RS.READY
                    logger.info(f"No problems detected on revision {revision}")
                db.session.commit()
            except Exception as e:
                logger.info(f"Exception encountered while processing {revision}")
                revision.status = RS.PROBLEM
                revision.update_data(error="".join(e.args))
                messages += e.args
                logger.exception(e)
                db.session.commit()

    def _mots_validate(self, mots_directory, query_result):
        warnings = []
        errors = []
        # This is to check if the config file has been modified...
        if mots_directory.config_handle.path.name in query_result.paths:
            # mots config file is being modified, clean and validate.
            try:
                mots_directory.reset_config()
                mots_directory.load()
                mots_directory.config_handle.load()
                errors = mots_directory.config_handle.check_hashes() or []
                warnings = (
                    validate(
                        mots_directory.config_handle.config, mots_directory.repo_path
                    )
                    or []
                )
            except Exception as e:
                errors.append(e)
                logger.exception(e)
        return warnings, errors

    def _get_mots_directory(self, path: str):
        try:
            return Directory(FileConfig(Path(path) / "mots.yaml"))
        except FileNotFoundError:
            logger.debug(f"No mots.yaml found at {path}")
        except Exception as e:
            logger.exception(e)

    def _mots_query(
        self,
        revision: Revision,
        hgrepo: HgRepo,
        mots_directory: Directory,
    ):
        paths = parse_diff(revision.patch)
        return mots_directory.query(*paths)

    def _process_patch(self, revision: Revision, hgrepo: HgRepo):
        """Run through all predecessors before applying revision patch."""
        errors = []
        for r in revision.predecessors + [revision]:
            try:
                hgrepo.apply_patch(io.BytesIO(r.patch.encode("utf-8")))
            except Exception as e:
                # Something is wrong (e.g. merge conflict). Log and break.
                logger.error(e)
                errors.append(f"Problem detected in {r} ({e})")
                break
        return errors

    def _get_repo_objects(self, repo_name: str):
        """Given a repo name, return the hg repo object and pull path."""
        repo = repo_clone_subsystem.repos[repo_name]
        hgrepo = HgRepo(
            str(repo_clone_subsystem.repo_paths[repo_name]),
            config=repo.config_override,
        )
        return hgrepo, repo.pull_path

    def process(self, revision: Revision):
        """Run mots query checks and return any errors or warnings."""
        # Initialize some variables that will be updated along the process.
        warnings, errors, mots_query = list(), list(), QueryResult()

        hgrepo, pull_path = self._get_repo_objects(revision.repo_name)

        # checkout repo, pull & update
        with hgrepo.for_pull():
            hgrepo.update_repo(pull_path)

            # First mots query loads the directory and module information.
            directory = self._get_mots_directory(hgrepo.path)

            if directory:
                directory.load()
                mots_query += self._mots_query(revision, hgrepo, directory)

            # Try to merge the revision patch.
            errors = self._process_patch(revision, hgrepo)
            if errors:
                return warnings, errors

            # Perform additional mots query after patch is applied.
            if directory:
                directory.load(full_paths=True)
            else:
                # Try getting directory again, in case mots was introduced in this
                # patch.
                directory = self._get_mots_directory(hgrepo.path)

            if directory:
                # Merge previous query result with this one if needed.
                mots_query += self._mots_query(revision, hgrepo, directory)

            if mots_query:
                revision.update_data(
                    **{
                        "mots": {
                            "modules": [m.serialize() for m in mots_query.modules],
                            "owners": [o.name for o in mots_query.owners],
                            "peers": [p.name for p in mots_query.peers],
                            "paths": mots_query.paths,
                            "rejected_paths": mots_query.rejected_paths,
                        }
                    }
                )

                if directory:
                    # Perform validation using directory and full query result.
                    _warnings, _errors = self._mots_validate(directory, mots_query)

                    # Update warnings and errors with any additional ones.
                    warnings += _warnings
                    errors += _errors
            db.session.commit()
            return warnings, errors
