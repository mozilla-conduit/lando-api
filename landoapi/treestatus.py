# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging

from landoapi.api.treestatus import (
    get_tree_by_name,
)

logger = logging.getLogger(__name__)

# A repo is considered open for landing when either of these
# statuses are present.
# For the "approval required" status Lando will enforce the appropriate
# Phabricator group review for approval (`release-managers`) and the hg
# hook will enforce `a=<reviewer>` is present in the commit message.
OPEN_STATUSES = {"approval required", "open"}


def is_open(tree_name: str) -> bool:
    """Return `True` if the tree is considered open for landing.

    The tree is open for landing when it is `open` or `approval required`.
    If the tree cannot be found in Treestatus it is considered open.
    """
    tree = get_tree_by_name(tree_name)
    if not tree:
        # We assume missing trees are open.
        return True

    return tree.status in OPEN_STATUSES
