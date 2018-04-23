# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import logging
from collections import namedtuple

logger = logging.getLogger(__name__)

Repo = namedtuple(
    'Repo',
    (
        # Name on https://treestatus.mozilla-releng.net/trees
        'tree',
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
        'test-repo': Repo('test-repo', ''),
    },
    'devsvcprod': {
        'phabricator-qa-stage': Repo('phabricator-qa-stage', ''),
        'version-control-tools': Repo('version-control-tools', '@'),
        'build-tools': Repo('build-tools', ''),
    },
}


def get_repos_for_env(env):
    if env not in REPO_CONFIG:
        logger.warning(
            'Repo config requested for unkown env: "{}"'.format(env)
        )
        env = 'default'

    return REPO_CONFIG.get(env, {})
