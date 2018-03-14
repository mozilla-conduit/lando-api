# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
REPO_CONFIG = {
    # '<phabricator-repo-short-name>': {
    #     # https://treestatus.mozilla-releng.net/trees
    #     'tree': '<TreeStatus-tree-name>',
    #     # Bookmark to be landed to and updated as part of push.
    #     'push_bookmark': '<hg-bookmark-empty-if-none>',
    # },
    'phabricator-qa-dev': {
        'tree': 'phabricator-qa-dev',
        'push_bookmark': '',
    },
    'phabricator-qa-stage': {
        'tree': 'phabricator-qa-stage',
        'push_bookmark': '',
    },
}
