# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import logging
import pathlib
import urllib
from collections import namedtuple
from dataclasses import dataclass

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


@dataclass
class Repo:
    """Represents the configuration of a particular repo.

    Args:
        tree (str): The name of the tree, used when checking tree status.
        url (str): The URL of the repo, used to access the web UI.
        access_group (AccessGroup): Determines access permissions to the repo, and is
            used to allow or deny landing requests, for example.
        push_bookmark (str): The bookmark to publish when pushing to the remote
            Mercurial repository.
        push_path (str): The protocol, hostname, and path to use when pushing to the
            remote Mercurial repository. Defaults to the same hostname and path as
            `url` but with `ssh` protocol.
        pull_path (str): The protocol, hostname, and path to use when cloning or pulling
            from a remote Mercurial repository. Defaults to `url`.
        transplant_locally (bool): When set to `True`, disables publishing the
            transplant requests to "Autoland Transplant" and instead queues these
            requests in the Landing Worker. Defaults to `False`.
        approval_required (bool): Whether approval is required or not for given repo.
            Note that this is not fully implemented but is included for compatibility.
            Defaults to `False`.
        commit_flags (bool): A list of supported flags that can be appended to the
            commit message at landing time (e.g. `["DONTBUILD"]`).
        config_override (dict): Parameters to override when loading the Mercurial
            configuration. The keys and values map directly to configuration keys and
            values. Defaults to `None`.
    """

    tree: str
    url: str
    access_group: AccessGroup
    push_bookmark: str = ""
    push_path: str = ""
    pull_path: str = ""
    transplant_locally: bool = False
    approval_required: bool = False
    commit_flags: list = None
    config_override: dict = None

    def __post_init__(self):
        """Set defaults based on initial values.

        Updates `push_path` and `pull_path` based on `url`, if either are missing.
        """
        if not self.push_path or not self.pull_path:
            url = urllib.parse.urlparse(self.url)
            if not self.push_path:
                self.push_path = f"ssh://{url.netloc}{url.path}"
            if not self.pull_path:
                self.pull_path = self.url

        if not self.commit_flags:
            self.commit_flags = []


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
SCM_FIREFOXCI = AccessGroup(
    active_group="active_scm_firefoxci",
    membership_group="all_scm_firefoxci",
    display_name="scm_firefoxci",
)


REPO_CONFIG = {
    # '<ENV>': {
    #     '<phabricator-short-name>': Repo(...)
    # }
    "default": {},
    "localdev": {
        "test-repo": Repo(
            tree="test-repo", url="http://hg.test/test-repo", access_group=SCM_LEVEL_1
        ),
        "first-repo": Repo(
            tree="first-repo",
            url="http://hg.test/first-repo",
            push_path="ssh://autoland.hg//first-repo",
            access_group=SCM_LEVEL_1,
            transplant_locally=True,
            commit_flags=["DONTBUILD"],
        ),
        "second-repo": Repo(
            tree="second-repo",
            url="http://hg.test/second-repo",
            access_group=SCM_LEVEL_1,
        ),
        "third-repo": Repo(
            tree="third-repo",
            url="http://hg.test/third-repo",
            access_group=SCM_LEVEL_1,
            push_path="ssh://autoland.hg//repos/third-repo",
            pull_path="http://hg.test/third-repo",
            transplant_locally=True,
        ),
        # Approval is required for the uplift dev repo
        "uplift-target": Repo(
            tree="uplift-target",
            url="http://hg.test",  # TODO: fix this? URL is probably incorrect.
            access_group=SCM_LEVEL_1,
            approval_required=True,
        ),
    },
    "devsvcdev": {
        # A general test repo that tests ssh pushes.
        "test-repo": Repo(
            tree="test-repo",
            url="https://autolandhg.devsvcdev.mozaws.net/test-repo",
            access_group=SCM_VERSIONCONTROL,
            push_path="ssh://autolandhg.devsvcdev.mozaws.net//repos/test-repo",
            pull_path="https://autolandhg.devsvcdev.mozaws.net/test-repo",
            transplant_locally=True,
        ),
        # A repo to test local transplants.
        "first-repo": Repo(
            tree="first-repo",
            url="https://autolandhg.devsvcdev.mozaws.net/first-repo",
            access_group=SCM_VERSIONCONTROL,
            transplant_locally=True,
        ),
        # A repo to test autoland transplants.
        "second-repo": Repo(
            tree="second-repo",
            url="https://autolandhg.devsvcdev.mozaws.net/second-repo",
            access_group=SCM_VERSIONCONTROL,
        ),
        # A repo to test different push/pull paths.
        "third-repo": Repo(
            tree="third-repo",
            url="https://autolandhg.devsvcdev.mozaws.net/third-repo",
            access_group=SCM_VERSIONCONTROL,
            pull_path="https://autolandhg.devsvcdev.mozaws.net/test-repo",
            transplant_locally=True,
        ),
    },
    "devsvcprod": {
        "phabricator-qa-stage": Repo(
            tree="phabricator-qa-stage",
            url="https://hg.mozilla.org/automation/phabricator-qa-stage",
            access_group=SCM_LEVEL_3,
            transplant_locally=True,
        ),
        "version-control-tools": Repo(
            tree="version-control-tools",
            url="https://hg.mozilla.org/hgcustom/version-control-tools",
            access_group=SCM_VERSIONCONTROL,
            push_bookmark="@",
            transplant_locally=True,
        ),
        "build-tools": Repo(
            tree="build-tools",
            url="https://hg.mozilla.org/build/tools/",
            access_group=SCM_LEVEL_3,
            transplant_locally=True,
        ),
        "ci-admin": Repo(
            tree="ci-admin",
            url="https://hg.mozilla.org/ci/ci-admin",
            access_group=SCM_FIREFOXCI,
            transplant_locally=True,
        ),
        "ci-configuration": Repo(
            tree="ci-configuration",
            url="https://hg.mozilla.org/ci/ci-configuration",
            access_group=SCM_FIREFOXCI,
            transplant_locally=True,
        ),
        "fluent-migration": Repo(
            tree="fluent-migration",
            url="https://hg.mozilla.org/l10n/fluent-migration",
            access_group=SCM_L10N_INFRA,
            transplant_locally=True,
        ),
        "mozilla-central": Repo(
            tree="gecko",
            url="https://hg.mozilla.org/integration/autoland",
            access_group=SCM_LEVEL_3,
        ),
        "comm-central": Repo(
            tree="comm-central",
            url="https://hg.mozilla.org/comm-central",
            access_group=SCM_LEVEL_3,
            transplant_locally=True,
        ),
        "nspr": Repo(
            tree="nspr",
            url="https://hg.mozilla.org/projects/nspr",
            access_group=SCM_NSS,
            transplant_locally=True,
        ),
        "taskgraph": Repo(
            tree="taskgraph",
            url="https://hg.mozilla.org/ci/taskgraph",
            access_group=SCM_LEVEL_3,
            transplant_locally=True,
        ),
        "nss": Repo(
            tree="nss",
            url="https://hg.mozilla.org/projects/nss",
            access_group=SCM_NSS,
            transplant_locally=True,
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
