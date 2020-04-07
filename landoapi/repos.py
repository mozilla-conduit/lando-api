# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import logging
import pathlib
from collections import namedtuple

from landoapi.systems import Subsystem

logger = logging.getLogger(__name__)

AccessGroup = namedtuple(
    "AccessGroup",
    (
        # LDAP group for active members. Required for landing.
        "active_group",
        # LDAP group for all members. If a user is in
        # membership_group but not active_group, their access
        # has expired.
        "membership_group",
        # Display name used for messages about this group.
        "display_name",
    ),
)
SCM_LEVEL_3 = AccessGroup(
    "active_scm_level_3", "all_scm_level_3", "Level 3 Commit Access"
)
SCM_LEVEL_2 = AccessGroup(
    "active_scm_level_2", "all_scm_level_2", "Level 2 Commit Access"
)
SCM_LEVEL_1 = AccessGroup(
    "active_scm_level_1", "all_scm_level_1", "Level 1 Commit Access"
)
SCM_VERSIONCONTROL = AccessGroup(
    "active_scm_versioncontrol", "all_scm_versioncontrol", "scm_versioncontrol"
)
SCM_CONDUIT = AccessGroup("active_scm_conduit", "all_scm_conduit", "scm_conduit")
SCM_L10N_INFRA = AccessGroup(
    "active_scm_l10n_infra", "all_scm_l10n_infra", "scm_l10n_infra"
)
SCM_NSS = AccessGroup("active_scm_nss", "all_scm_nss", "scm_nss")

Repo = namedtuple(
    "Repo",
    (
        # Name on https://treestatus.mozilla-releng.net/trees
        "tree",
        # An AccessGroup to specify the group required to land.
        "access_group",
        # Bookmark to be landed to and updated as part of push. Should be
        # an empty string to not use bookmarks.
        "push_bookmark",
        # Mercurial path to push landed changesets.
        "push_path",
        # Mercurial path to pull new changesets from.
        "pull_path",
        # Uses built-in landing jobs to transplant.
        "transplant_locally",
        # Repository url, e.g. as found on https://hg.mozilla.org.
        "url",
        # Approval required to land on that repo (for uplifts)
        "approval_required",
    ),
)
REPO_CONFIG = {
    # '<ENV>': {
    #     '<phabricator-short-name>': Repo(...)
    # }
    "default": {},
    "localdev": {
        "test-repo": Repo(
            "test-repo", SCM_LEVEL_1, "", "", "", False, "http://hg.test", False
        ),
        "localdev": Repo(
            "localdev",
            SCM_LEVEL_1,
            "",
            "https://autolandhg.devsvcdev.mozaws.net",
            "https://autolandhg.devsvcdev.mozaws.net",
            True,
            "https://autolandhg.devsvcdev.mozaws.net",
            False,
        ),
        # Approval is required for the uplift dev repo
        "uplift-target": Repo(
            "uplift-target", SCM_LEVEL_1, "", "", "", False, "http://hg.test", True
        ),
    },
    "devsvcdev": {
        "test-repo": Repo(
            "test-repo",
            SCM_LEVEL_1,
            "",
            "",
            "",
            False,
            "https://autolandhg.devsvcdev.mozaws.net",
            False,
        )
    },
    "devsvcprod": {
        "phabricator-qa-stage": Repo(
            "phabricator-qa-stage",
            SCM_LEVEL_3,
            "",
            "",
            "",
            False,
            "https://hg.mozilla.org/automation/phabricator-qa-stage",
            False,
        ),
        "version-control-tools": Repo(
            "version-control-tools",
            SCM_VERSIONCONTROL,
            "@",
            "",
            "",
            False,
            "https://hg.mozilla.org/hgcustom/version-control-tools",
            False,
        ),
        "build-tools": Repo(
            "build-tools",
            SCM_LEVEL_3,
            "",
            "",
            "",
            False,
            "https://hg.mozilla.org/build/tools",
            False,
        ),
        "ci-admin": Repo(
            "ci-admin",
            SCM_LEVEL_3,
            "",
            "",
            "",
            False,
            "https://hg.mozilla.org/ci/ci-admin",
            False,
        ),
        "ci-configuration": Repo(
            "ci-configuration",
            SCM_LEVEL_3,
            "",
            "",
            "",
            False,
            "https://hg.mozilla.org/ci/ci-configuration",
            False,
        ),
        "fluent-migration": Repo(
            "fluent-migration",
            SCM_L10N_INFRA,
            "",
            "",
            "",
            False,
            "https://hg.mozilla.org/l10n/fluent-migration",
            False,
        ),
        "mozilla-central": Repo(
            "gecko",
            SCM_LEVEL_3,
            "",
            "",
            "",
            False,
            "https://hg.mozilla.org/integration/autoland",
            False,
        ),
        "comm-central": Repo(
            "comm-central",
            SCM_LEVEL_3,
            "",
            "",
            "",
            False,
            "https://hg.mozilla.org/comm-central",
            False,
        ),
        "nspr": Repo(
            "nspr",
            SCM_NSS,
            "",
            "",
            "",
            False,
            "https://hg.mozilla.org/projects/nspr",
            False,
        ),
        "taskgraph": Repo(
            "taskgraph",
            SCM_LEVEL_3,
            "",
            "",
            "",
            False,
            "https://hg.mozilla.org/ci/taskgraph",
            False,
        ),
        "nss": Repo(
            "nss",
            SCM_NSS,
            "",
            "",
            "",
            False,
            "https://hg.mozilla.org/projects/nss",
            False,
        ),
    },
}


def get_repos_for_env(env):
    if env not in REPO_CONFIG:
        logger.warning("repo config requested for unknown env", extra={"env": env})
        env = "default"

    return REPO_CONFIG.get(env, {})


class RepoCloneSubsystem(Subsystem):
    name = "repo_clone"

    def ready(self):
        clones_path = self.flask_app.config["REPO_CLONES_PATH"]
        repo_names = self.flask_app.config["REPOS_TO_LAND"]

        if not clones_path and not repo_names:
            return None

        clones_path = pathlib.Path(self.flask_app.config["REPO_CLONES_PATH"])
        if not clones_path.exists() or not clones_path.is_dir():
            return (
                "REPO_CLONES_PATH ({}) is not a valid path to an existing "
                "directory for holding repository clones.".format(clones_path)
            )

        repo_names = set(filter(None, (r.strip() for r in repo_names.split(","))))
        if not repo_names:
            return (
                "REPOS_TO_LAND does not contain a valid comma seperated list "
                "of repository names."
            )

        repos = get_repos_for_env(self.flask_app.config.get("ENVIRONMENT"))
        if not all(r in repos for r in repo_names):
            return "REPOS_TO_LAND contains unsupported repository names."

        self.repos = {name: repos[name] for name in repo_names}
        self.repo_paths = {}

        from landoapi.hg import HgRepo

        for name, repo in ((name, repos[name]) for name in repo_names):
            path = clones_path.joinpath(name)
            r = HgRepo(str(path))

            if path.exists():
                logger.info("Repo exists, pulling.", extra={"repo": name})
                with r:
                    r.update_repo(repo.pull_path)
            else:
                logger.info("Cloning repo.", extra={"repo": name})
                r.clone(repo.pull_path)

            logger.info("Repo ready.", extra={"repo": name})
            self.repo_paths[name] = path

        return True


repo_clone_subsystem = RepoCloneSubsystem()
