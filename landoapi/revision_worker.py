# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
from __future__ import annotations

import io
import logging
from pathlib import Path
from time import sleep

from flask import current_app

from landoapi.hg import (
    HgRepo,
)
from landoapi.models.revisions import Revision
from landoapi.repos import repo_clone_subsystem
from landoapi.storage import db
from landoapi.landing_worker import LandingWorker
from landoapi.phabricator import PhabricatorClient

from mots.config import FileConfig
from mots.directory import Directory

logger = logging.getLogger(__name__)


def get_conduit_data(method, **kwargs):
    """Fetch result from conduit API request."""
    phab = PhabricatorClient(
        current_app.config["PHABRICATOR_URL"],
        current_app.config["PHABRICATOR_UNPRIVILEGED_API_KEY"],
    )
    data = []
    result = phab.call_conduit(method, **kwargs)
    data += result["data"]
    while result["cursor"]["after"]:
        result = phab.call_conduit(method, after=result["cursor"]["after"], **kwargs)
        data += result["data"]
    return data


def get_revisions_list(statuses=None):
    """Get a list of revisions of given statuses."""
    statuses = statuses or ["needs-review", "accepted"]
    revisions = get_conduit_data(
        "differential.revision.search",
        constraints={"statuses": statuses},
    )
    revisions = [
        {
            "revision_id": r["id"],
            "diff_phid": r["fields"]["diffPHID"],
            "repo_phid": r["fields"]["repositoryPHID"],
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
    repo_map = {d["phid"]: d["fields"]["shortName"] for d in repo_ids}

    for r in revisions:
        r["diff_id"] = diff_map[r["diff_phid"]]
        r["repo_name"] = repo_map[r["repo_phid"]]
        del r["diff_phid"]
        del r["repo_phid"]

    return revisions


def parse_diff(diff):
    """Given a diff, extract list of affected files."""
    diff_lines = diff.splitlines()
    file_diffs = [line.split(" ")[2:] for line in diff_lines if line.startswith("diff")]
    file_paths = []
    for file_diff in file_diffs:
        # Parse source/destination paths.
        path1, path2 = file_diff
        file_paths.append("/".join(path1.split("/")[1:]))
        file_paths.append("/".join(path2.split("/")[1:]))
    file_paths = set(file_paths)
    return file_paths


def sync_revisions():
    """Check and update local database with available revisions."""
    revisions = get_revisions_list()
    logger.debug(f"Processing {len(revisions)} revisions...")
    for r in revisions:
        logger.debug(f"Processing {r}...")
        query = (
            Revision.revision_id == r["revision_id"],
            Revision.diff_id == r["diff_id"],
        )
        revision = Revision.query.filter(*query)
        if revision.count():
            logger.debug(f"{r} already exists in DB, skipping.")
            continue
        revision = Revision.query.filter(Revision.revision_id == r["revision_id"])
        if revision.count():
            logger.debug(f"{r} already exists in DB, updating diff ID.")
            revision.diff_id = r["diff_id"]
            db.session.add(revision)
            db.session.commit()
            continue
        logger.debug(f"Creating {r} in DB.")
        revision = Revision(**r)

        # Download and store the patch diff in the DB.
        revision.store_patch()

        db.session.add(revision)
        db.session.commit()
    # TODO: identify stale revisions (e.g. when a repo has been updated and the
    # parsed state of the revision is no longer relevant, e.g. check hash.)


class RevisionWorker(LandingWorker):
    """A worker that pre-processes revisions.

    This worker continuously synchronises revisions with the remote Phabricator API
    and runs all applicable checks and processes on each revision, if needed.

    TODO: this should extend an abstract worker class, not landing worker.
    """

    processes = [
        "mots",
    ]

    def start(self):
        logger.info("Revision worker starting")
        logger.info(
            f"{len(self.applicable_repos)} applicable repos: {self.applicable_repos}"
        )
        self.running = True

        while self.running:
            sync_revisions()

            # get stale revisions
            revisions = Revision.query.filter(Revision.is_stale == True)
            if not revisions.count():
                sleep(1)
            for revision in revisions:
                logger.info(
                    "Running mots checks on revision", extra={"id": revision.id}
                )
                for process in self.processes:
                    getattr(self, f"process_{process}")(revision)

    def process_mots(self, revision):
        repo = repo_clone_subsystem.repos[revision.repo_name]
        hgrepo = HgRepo(
            str(repo_clone_subsystem.repo_paths[revision.repo_name]),
            config=repo.config_override,
        )
        # checkout repo, pull & update
        with hgrepo.for_pull():
            hgrepo.update_repo(repo.pull_path)

        # load mots.yml config
        wd = hgrepo.path
        mots_config = FileConfig(Path(wd) / "mots.yaml")
        mots_directory = Directory(mots_config)

        # CHECK query before applying patch, and again after.
        mots_directory.load()
        paths = parse_diff(revision.patch)
        query = {}
        query["pre"] = mots_directory.query(*paths)

        with hgrepo.for_pull():
            hgrepo.update_repo(repo.pull_path)
            try:
                hgrepo.apply_patch(io.BytesIO(revision.patch.encode("utf-8")))
            except Exception as e:
                # Possible merge conflict, skip for now...
                logger.error(e)
                return
            # hg_cmd = ["diff", "-c", "tip"]  # TODO: replace this with rev id
            # hg_out = hgrepo.run_hg(hg_cmd)

            # Reload directory with new patch.
            mots_directory.load(full_paths=True)

            # query mots for diff files
            query["post"] = mots_directory.query(*paths)

            query_result = query["pre"] + query["post"]
            revision.data = {}
            revision.data["mots"] = {
                "modules": [m.serialize() for m in query_result.modules],
                "owners": [o.real_name for o in query_result.owners],
                "peers": [p.real_name for p in query_result.peers],
                "paths": query_result.paths,
                "rejected_paths": query_result.rejected_paths,
            }
            revision.is_stale = False
            db.session.commit()
