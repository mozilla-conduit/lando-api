# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import logging
from collections import namedtuple

from landoapi.phabricator import PhabricatorClient, ReviewerStatus

logger = logging.getLogger(__name__)


def calculate_review_extra_state(
    for_diff_phid, reviewer_status, reviewer_diff_phid, reviewer_voided_phid
):
    """Return review state given a reviewer's phabricator information.

    Args:
        for_diff_phid: The diff phid that this review state is being
            calculated against. This would usually be the phid of
            the diff to be landed.
        reviewer_status: A landoapi.phabricator.ReviewerStatus.
        reviewer_diff_phid: The diff phid the reviewer is currently
            associated with. This would be the value returned in
            'diffPHID' of the 'reviewers-extra' attachment.
            'reviewers-extra' attachment for a reviewer.
        reviewer_voided_phid: The phid of a voiding action associated
            with a specific reviewer. This would be the value returned
            in 'voidedPHID' of the 'reviewers-extra' attachment.

    Returns: A dictionary of state information of the form:
        {
            'for_other_diff': Boolean # Does this status apply to a diff
                                      # other than the one provided.
            'blocking_landing': Boolean # Is this reviewer blocking landing.
        }
    """
    other_diff = (
        for_diff_phid != reviewer_diff_phid and reviewer_status.diff_specific
    )
    blocks_landing = reviewer_status is ReviewerStatus.BLOCKING or (
        reviewer_status is ReviewerStatus.REJECTED and not other_diff
    )
    return {
        'for_other_diff': other_diff,
        'blocking_landing': blocks_landing,
    }


ReviewerIdentity = namedtuple(
    'ReviewerIdentity', ('identifier', 'full_name', )
)


def reviewer_identity(phid, user_search_data, project_search_data):
    if phid in user_search_data:
        return ReviewerIdentity(
            PhabricatorClient.expect(
                user_search_data, phid, 'fields', 'username'
            ),
            PhabricatorClient.expect(
                user_search_data, phid, 'fields', 'realName'
            )
        )

    if phid in project_search_data:
        name = PhabricatorClient.expect(
            project_search_data, phid, 'fields', 'name'
        )
        return ReviewerIdentity(name, name)

    logger.info(
        'reviewer was missing from user / project search data',
        extra={'phid': phid}
    )
    return ReviewerIdentity('<unknown>', 'Unknown User/Project')
