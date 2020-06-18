# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import logging
import os
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
        # Config override (e.g. to override hgrc per repo)
        "config_override",
    ),
    defaults=(None, None, "", "", "", False, None, False, None),
)

SCM_LEVEL_3 = AccessGroup(
    active_group="active_scm_level_3",
    membership_group="all_scm_level_3",
    display_name="Level 3 Commit Access",
)
SCM_LEVEL_2 = AccessGroup(
    active_group="active_scm_level_2",
    membership_group="all_scm_level_2",
    display_name="Level 2 Commit Access",
)
SCM_LEVEL_1 = AccessGroup(
    active_group="active_scm_level_1",
    membership_group="all_scm_level_1",
    display_name="Level 1 Commit Access",
)
SCM_VERSIONCONTROL = AccessGroup(
    active_group="active_scm_versioncontrol",
    membership_group="all_scm_versioncontrol",
    display_name="scm_versioncontrol",
)
SCM_CONDUIT = AccessGroup(
    active_group="active_scm_conduit",
    membership_group="all_scm_conduit",
    display_name="scm_conduit",
)
SCM_L10N_INFRA = AccessGroup(
    active_group="active_scm_l10n_infra",
    membership_group="all_scm_l10n_infra",
    display_name="scm_l10n_infra",
)
SCM_NSS = AccessGroup(
    active_group="active_scm_nss",
    membership_group="all_scm_nss",
    display_name="scm_nss",
)

# Username and SSH port to use when connecting to remote HG server.
landing_worker_username = os.environ.get("LANDING_WORKER_USERNAME", "app")
landing_worker_target_ssh_port = os.environ.get("LANDING_WORKER_TARGET_SSH_PORT", "22")

# Configuration overrides that can be applied to any repo.
SSH_CONFIG_OVERRIDES = (
    "ssh "
    '-o "SendEnv AUTOLAND_REQUEST_USER" '
    '-o "StrictHostKeyChecking no" '
    '-o "PasswordAuthentication no" '
    f'-o "User {landing_worker_username}" '
    f'-o "Port {landing_worker_target_ssh_port}"'
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
        "first-repo": Repo(
            tree="first-repo",
            access_group=SCM_LEVEL_1,
            push_path="http://hg.test/first-repo",
            pull_path="http://hg.test/first-repo",
            transplant_locally=True,
            url="http://hg.test/first-repo",
        ),
        "second-repo": Repo(
            tree="second-repo",
            access_group=SCM_LEVEL_1,
            push_path="http://hg.test/second-repo",
            pull_path="http://hg.test/second-repo",
            url="http://hg.test/second-repo",
        ),
        "third-repo": Repo(
            tree="third-repo",
            access_group=SCM_LEVEL_1,
            push_path="ssh://autoland.hg//repos/third-repo",
            pull_path="http://hg.test/third-repo",
            transplant_locally=True,
            url="http://hg.test/third-repo",
            config_override={"ui.ssh": SSH_CONFIG_OVERRIDES},
        ),
        # Approval is required for the uplift dev repo
        "uplift-target": Repo(
            tree="uplift-target",
            access_group=SCM_LEVEL_1,
            url="http://hg.test",  # TODO: fix this? URL is probably incorrect.
            approval_required=True,
        ),
    },
    "devsvcdev": {
        # A general test repo that tests ssh pushes.
        "test-repo": Repo(
            tree="test-repo",
            access_group=SCM_VERSIONCONTROL,
            push_path="ssh://autolandhg.devsvcdev.mozaws.net//repos/test-repo",
            pull_path="https://autolandhg.devsvcdev.mozaws.net/test-repo",
            transplant_locally=True,
            url="https://autolandhg.devsvcdev.mozaws.net/test-repo",
            config_override={"ui.ssh": SSH_CONFIG_OVERRIDES},
        ),
        # A repo to test local transplants.
        "first-repo": Repo(
            tree="first-repo",
            access_group=SCM_VERSIONCONTROL,
            push_path="https://autolandhg.devsvcdev.mozaws.net/first-repo",
            pull_path="https://autolandhg.devsvcdev.mozaws.net/first-repo",
            transplant_locally=True,
            url="https://autolandhg.devsvcdev.mozaws.net/first-repo",
        ),
        # A repo to test autoland transplants.
        "second-repo": Repo(
            tree="second-repo",
            access_group=SCM_VERSIONCONTROL,
            push_path="https://autolandhg.devsvcdev.mozaws.net/second-repo",
            pull_path="https://autolandhg.devsvcdev.mozaws.net/second-repo",
            url="https://autolandhg.devsvcdev.mozaws.net/second-repo",
        ),
        # A repo to test different push/pull paths.
        "third-repo": Repo(
            tree="third-repo",
            access_group=SCM_VERSIONCONTROL,
            push_path="https://autolandhg.devsvcdev.mozaws.net/third-repo",
            pull_path="https://autolandhg.devsvcdev.mozaws.net/test-repo",
            transplant_locally=True,
            url="https://autolandhg.devsvcdev.mozaws.net/third-repo",
        ),
    },
    "devsvcprod": {
        "phabricator-qa-stage": Repo(
            tree="phabricator-qa-stage",
            access_group=SCM_LEVEL_3,
            url="https://hg.mozilla.org/automation/phabricator-qa-stage",
        ),
        "version-control-tools": Repo(
            tree="version-control-tools",
            access_group=SCM_VERSIONCONTROL,
            push_bookmark="@",
            push_path="ssh://hg.mozilla.org/hgcustom/version-control-tools",
            pull_path="https://hg.mozilla.org/hgcustom/version-control-tools",
            transplant_locally=True,
            url="https://hg.mozilla.org/hgcustom/version-control-tools",
            config_override={"ui.ssh": SSH_CONFIG_OVERRIDES},
        ),
        "build-tools": Repo(
            tree="build-tools",
            access_group=SCM_LEVEL_3,
            url="https://hg.mozilla.org/build/tools",
        ),
        "ci-admin": Repo(
            tree="ci-admin",
            access_group=SCM_LEVEL_3,
            url="https://hg.mozilla.org/ci/ci-admin",
        ),
        "ci-configuration": Repo(
            tree="ci-configuration",
            access_group=SCM_LEVEL_3,
            url="https://hg.mozilla.org/ci/ci-configuration",
        ),
        "fluent-migration": Repo(
            tree="fluent-migration",
            access_group=SCM_L10N_INFRA,
            url="https://hg.mozilla.org/l10n/fluent-migration",
        ),
        "mozilla-central": Repo(
            tree="gecko",
            access_group=SCM_LEVEL_3,
            url="https://hg.mozilla.org/integration/autoland",
        ),
        "comm-central": Repo(
            tree="comm-central",
            access_group=SCM_LEVEL_3,
            url="https://hg.mozilla.org/comm-central",
        ),
        "nspr": Repo(
            tree="nspr",
            access_group=SCM_NSS,
            url="https://hg.mozilla.org/projects/nspr",
        ),
        "taskgraph": Repo(
            tree="taskgraph",
            access_group=SCM_LEVEL_3,
            url="https://hg.mozilla.org/ci/taskgraph",
        ),
        "nss": Repo(
            tree="nss", access_group=SCM_NSS, url="https://hg.mozilla.org/projects/nss"
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
