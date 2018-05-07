# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import logging
from collections import namedtuple

logger = logging.getLogger(__name__)

AccessGroup = namedtuple(
    'AccessGroup',
    (
        # LDAP group for active members. Required for landing.
        'active_group',
        # LDAP group for all memembers. If a user is in
        # membership_group but not active_group, their access
        # has expired.
        'membership_group',
        # Display name used for messages about this group.
        'display_name',
    )
)
SCM_LEVEL_3 = AccessGroup(
    'active_scm_level_3', 'all_scm_level_3', 'Level 3 Commit Access'
)
SCM_LEVEL_2 = AccessGroup(
    'active_scm_level_2', 'all_scm_level_2', 'Level 2 Commit Access'
)
SCM_LEVEL_1 = AccessGroup(
    'active_scm_level_1', 'all_scm_level_1', 'Level 1 Commit Access'
)
SCM_VERSIONCONTROL = AccessGroup(
    'active_scm_versioncontrol', 'all_scm_versioncontrol', 'scm_versioncontrol'
)
SCM_CONDUIT = AccessGroup(
    'active_scm_conduit', 'all_scm_conduit', 'scm_conduit'
)
SCM_L10N_INFRA = AccessGroup(
    'active_scm_l10n_infra', 'all_scm_l10n_infra', 'scm_l10n_infra'
)

Repo = namedtuple(
    'Repo',
    (
        # Name on https://treestatus.mozilla-releng.net/trees
        'tree',
        # An AccessGroup to specify the group required to land.
        'access_group',
        # Bookmark to be landed to and updated as part of push. Should be
        # an empty string to not use bookmarks.
        'push_bookmark',
    )
)
REPO_CONFIG = {
    # '<ENV>': {
    #     '<phabricator-short-name>': Repo(...)
    # }
    'default': {},
    'devsvcdev': {
        'test-repo': Repo('test-repo', SCM_LEVEL_1, ''),
    },
    'devsvcprod': {
        'phabricator-qa-stage': Repo('phabricator-qa-stage', SCM_LEVEL_3, ''),
        'version-control-tools': Repo(
            'version-control-tools', SCM_VERSIONCONTROL, '@'
        ),
        'build-tools': Repo('build-tools', SCM_LEVEL_3, ''),
        'fluent-migration': Repo('fluent-migration', SCM_L10N_INFRA, ''),
    },
}  # yapf: disable


def get_repos_for_env(env):
    if env not in REPO_CONFIG:
        logger.warning(
            'repo config requested for unknown env', extra={'env': env}
        )
        env = 'default'

    return REPO_CONFIG.get(env, {})
