# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import logging
from collections import namedtuple

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
        # Repository url, e.g. as found on https://hg.mozilla.org.
        "url",
    ),
)
REPO_CONFIG = {
    # '<ENV>': {
    #     '<phabricator-short-name>': Repo(...)
    # }
    "default": {},
    "localdev": {"test-repo": Repo("test-repo", SCM_LEVEL_1, "", "http://hg.test")},
    "devsvcdev": {
        "test-repo": Repo(
            "test-repo", SCM_LEVEL_1, "", "https://autolandhg.devsvcdev.mozaws.net"
        )
    },
    "devsvcprod": {
        "phabricator-qa-stage": Repo(
            "phabricator-qa-stage",
            SCM_LEVEL_3,
            "",
            "https://hg.mozilla.org/automation/phabricator-qa-stage",
        ),
        "version-control-tools": Repo(
            "version-control-tools",
            SCM_VERSIONCONTROL,
            "@",
            "https://hg.mozilla.org/hgcustom/version-control-tools",
        ),
        "build-tools": Repo(
            "build-tools", SCM_LEVEL_3, "", "https://hg.mozilla.org/build/tools"
        ),
        "ci-admin": Repo(
            "ci-admin", SCM_LEVEL_3, "", "https://hg.mozilla.org/ci/ci-admin"
        ),
        "ci-configuration": Repo(
            "ci-configuration",
            SCM_LEVEL_3,
            "",
            "https://hg.mozilla.org/ci/ci-configuration",
        ),
        "fluent-migration": Repo(
            "fluent-migration",
            SCM_L10N_INFRA,
            "",
            "https://hg.mozilla.org/l10n/fluent-migration",
        ),
        "mozilla-central": Repo(
            "gecko", SCM_LEVEL_3, "", "https://hg.mozilla.org/integration/autoland"
        ),
        "mozilla-central-unified": Repo(
            "gecko", SCM_LEVEL_3, "", "https://hg.mozilla.org/integration/autoland"
        ),
        "comm-central": Repo(
            "comm-central", SCM_LEVEL_3, "", "https://hg.mozilla.org/comm-central"
        ),
        "nspr": Repo("nspr", SCM_NSS, "", "https://hg.mozilla.org/projects/nspr"),
        "taskgraph": Repo(
            "taskgraph", SCM_LEVEL_3, "", "https://hg.mozilla.org/ci/taskgraph"
        ),
        "nss": Repo("nss", SCM_NSS, "", "https://hg.mozilla.org/projects/nss"),
    },
}


def get_repos_for_env(env):
    if env not in REPO_CONFIG:
        logger.warning("repo config requested for unknown env", extra={"env": env})
        env = "default"

    return REPO_CONFIG.get(env, {})
