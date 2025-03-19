# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import logging
import pathlib
import urllib
from collections import namedtuple
from dataclasses import (
    dataclass,
    field,
)
from typing import Optional

from landoapi.systems import Subsystem

logger = logging.getLogger(__name__)

AccessGroup = namedtuple(
    "AccessGroup",
    (
        # LDAP group for active members. Required for landing.
        "active_group",
        # LDAP group for expired members. Indicates the user had the
        # permissions but has lost them due to inactivity.
        "expired_group",
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
        short_name (str): The Phabricator short name field for this repo, if different
            from the `tree`. Defaults to `tree`.
        approval_required (bool): Whether approval is required or not for given repo.
            Note that this is not fully implemented but is included for compatibility.
            Defaults to `False`.
        milestone_tracking_flag_template (str): A format string that takes the current
            release milestone and returns the relevant Bugzilla status tracking flag.
        commit_flags (list of tuple): A list of supported flags that can be appended to
            the commit message at landing time (e.g. `[("DONTBUILD", "help text")]`).
        product_details_url (str): The URL which contains product-related information
            relevant to the repo. Defaults to an empty string.
        is_phabricator_repo (bool): Boolean indicating if the repo is available on
            Phabricator or not.
        force_push (bool): Boolean that controls the use of force pushes for a repo.
    """

    tree: str
    url: str
    access_group: AccessGroup
    push_bookmark: str = ""
    push_path: str = ""
    pull_path: str = ""
    short_name: str = ""
    approval_required: bool = False
    milestone_tracking_flag_template: str = ""
    autoformat_enabled: bool = False
    commit_flags: list[tuple[str, str]] = field(default_factory=list)
    product_details_url: str = ""
    is_phabricator_repo: bool = True
    force_push: bool = False

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

        if not self.short_name:
            self.short_name = self.tree

    @property
    def phab_identifier(self) -> str | None:
        """Return a valid Phabricator identifier as a `str`."""
        if not self.is_phabricator_repo:
            return None

        return self.short_name if self.short_name else self.tree


SCM_ALLOW_DIRECT_PUSH = AccessGroup(
    active_group="active_scm_allow_direct_push",
    expired_group="expired_scm_allow_direct_push",
    membership_group="all_scm_allow_direct_push",
    display_name="Above Level 3 Commit Access",
)
SCM_LEVEL_3 = AccessGroup(
    active_group="active_scm_level_3",
    expired_group="expired_scm_level_3",
    membership_group="all_scm_level_3",
    display_name="Level 3 Commit Access",
)
SCM_LEVEL_2 = AccessGroup(
    active_group="active_scm_level_2",
    expired_group="expired_scm_level_2",
    membership_group="all_scm_level_2",
    display_name="Level 2 Commit Access",
)
SCM_LEVEL_1 = AccessGroup(
    active_group="active_scm_level_1",
    expired_group="expired_scm_level_1",
    membership_group="all_scm_level_1",
    display_name="Level 1 Commit Access",
)
SCM_VERSIONCONTROL = AccessGroup(
    active_group="active_scm_versioncontrol",
    expired_group="expired_scm_versioncontrol",
    membership_group="all_scm_versioncontrol",
    display_name="scm_versioncontrol",
)
SCM_CONDUIT = AccessGroup(
    active_group="active_scm_conduit",
    expired_group="expired_scm_conduit",
    membership_group="all_scm_conduit",
    display_name="scm_conduit",
)
SCM_L10N_INFRA = AccessGroup(
    active_group="active_scm_l10n_infra",
    expired_group="expired_scm_l10n_infra",
    membership_group="all_scm_l10n_infra",
    display_name="scm_l10n_infra",
)
SCM_NSS = AccessGroup(
    active_group="active_scm_nss",
    expired_group="expired_scm_nss",
    membership_group="all_scm_nss",
    display_name="scm_nss",
)
SCM_FIREFOXCI = AccessGroup(
    active_group="active_scm_firefoxci",
    expired_group="expired_scm_firefoxci",
    membership_group="all_scm_firefoxci",
    display_name="scm_firefoxci",
)

# DONTBUILD flag and help text.
DONTBUILD = (
    "DONTBUILD",
    (
        "Should be used only for trivial changes (typo, comment changes,"
        " documentation changes, etc.) where the risk of introducing a"
        " new bug is close to none."
    ),
)

REPO_CONFIG = {
    # '<ENV>': {
    #     '<phabricator-short-name>': Repo(...)
    # }
    "default": {},
    "localdev": {
        "test-repo": Repo(
            tree="test-repo",
            url="http://hg.test/test-repo",
            access_group=SCM_LEVEL_1,
            product_details_url="http://product-details.test/1.0/firefox_versions.json",
        ),
        "first-repo": Repo(
            tree="first-repo",
            url="http://hg.test/first-repo",
            push_path="ssh://autoland.hg//repos/first-repo",
            access_group=SCM_LEVEL_1,
            commit_flags=[DONTBUILD],
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
            approval_required=True,
            milestone_tracking_flag_template="cf_status_firefox{milestone}",
        ),
    },
    "devsvcdev": {
        "test-repo": Repo(
            tree="test-repo",
            url="https://hg.mozilla.org/conduit-testing/test-repo",
            access_group=SCM_CONDUIT,
        ),
        "large-repo": Repo(
            tree="large-repo",
            url="https://hg.mozilla.org/conduit-testing/m-c",
            access_group=SCM_CONDUIT,
            commit_flags=[DONTBUILD],
            milestone_tracking_flag_template="cf_status_firefox{milestone}",
            product_details_url="https://raw.githubusercontent.com/mozilla-conduit"
            "/suite/main/docker/product-details/1.0/firefox_versions.json",
        ),
        "m-c": Repo(
            tree="m-c",
            url="https://hg.mozilla.org/conduit-testing/m-c",
            access_group=SCM_CONDUIT,
            commit_flags=[DONTBUILD],
            approval_required=True,
            milestone_tracking_flag_template="cf_status_firefox{milestone}",
            product_details_url="https://raw.githubusercontent.com/mozilla-conduit"
            "/suite/main/docker/product-details/1.0/firefox_versions.json",
        ),
        "vct": Repo(
            tree="vct",
            url="https://hg.mozilla.org/conduit-testing/vct",
            access_group=SCM_CONDUIT,
            push_bookmark="@",
        ),
        # Use real `try` for testing since `try` is a testing environment anyway.
        "try": Repo(
            tree="try",
            url="https://hg.mozilla.org/try",
            push_path="ssh://hg.mozilla.org/try",
            pull_path="https://hg.mozilla.org/mozilla-unified",
            access_group=SCM_LEVEL_1,
            short_name="try",
            is_phabricator_repo=False,
            force_push=True,
        ),
    },
    "devsvcstage": {
        "test-repo-clone": Repo(
            tree="test-repo-clone",
            url="https://hg.mozilla.org/conduit-testing/test-repo-clone",
            access_group=SCM_CONDUIT,
        ),
        # Use real `try` for testing since `try` is a testing environment anyway.
        "try": Repo(
            tree="try",
            url="https://hg.mozilla.org/try",
            push_path="ssh://hg.mozilla.org/try",
            pull_path="https://hg.mozilla.org/mozilla-unified",
            access_group=SCM_LEVEL_1,
            short_name="try",
            is_phabricator_repo=False,
            force_push=True,
        ),
    },
    "devsvcprod": {
        # Try uses `mozilla-unified` as the `pull_path` as using try
        # proper is exceptionally slow. `mozilla-unified` includes both
        # autoland and central and is the most likely to contain the passed
        # base commit.
        "try": Repo(
            tree="try",
            url="https://hg.mozilla.org/try",
            push_path="ssh://hg.mozilla.org/try",
            pull_path="https://hg.mozilla.org/mozilla-unified",
            access_group=SCM_LEVEL_1,
            short_name="try",
            is_phabricator_repo=False,
            force_push=True,
        ),
    },
}


def get_repos_for_env(env: str) -> dict[str, Repo]:
    if env not in REPO_CONFIG:
        logger.warning("repo config requested for unknown env", extra={"env": env})
        env = "default"

    return REPO_CONFIG.get(env, {})


class RepoCloneSubsystem(Subsystem):
    name = "repo_clone"

    def ready(self) -> Optional[bool | str]:
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

        repo_names = set(filter(None, (name.strip() for name in repo_names.split(","))))
        if not repo_names:
            return (
                "REPOS_TO_LAND does not contain a valid comma seperated list "
                "of repository names."
            )

        repos = get_repos_for_env(self.flask_app.config.get("ENVIRONMENT"))
        if not all(name in repos for name in repo_names):
            return "REPOS_TO_LAND contains unsupported repository names."

        self.repos = {name: repos[name] for name in repo_names}
        self.repo_paths = {}

        from landoapi.hg import HgRepo

        for name, repo in self.repos.items():
            path = clones_path.joinpath(name)
            hgrepo = HgRepo(str(path))

            if path.exists():
                logger.info("Repo exists, pulling.", extra={"repo": name})
                with hgrepo.for_pull():
                    hgrepo.update_repo(repo.pull_path)
            else:
                logger.info("Cloning repo.", extra={"repo": name})
                hgrepo.clone(repo.pull_path)

            # Ensure packages required for automated code formatting are installed.
            if repo.autoformat_enabled:
                hgrepo.run_mach_bootstrap()

            logger.info("Repo ready.", extra={"repo": name})
            self.repo_paths[name] = path

        return True


repo_clone_subsystem = RepoCloneSubsystem()
