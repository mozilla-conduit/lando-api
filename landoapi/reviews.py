# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import logging
from collections import namedtuple

from landoapi.phabricator import (
    PhabricatorClient,
    PhabricatorCommunicationException,
    ReviewerStatus,
)

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


def get_collated_reviewers(revision):
    """Return a dictionary mapping phid to collated reviewer attachment data.

    Args:
        revision: A dict of the revision data from differential.revision.search
            with the 'reviewers' and 'reviewers-extra' attachments.
    """
    attachments = PhabricatorClient.expect(revision, 'attachments')
    return collate_reviewer_attachments(
        PhabricatorClient.expect(attachments, 'reviewers', 'reviewers'),
        PhabricatorClient.expect(
            attachments, 'reviewers-extra', 'reviewers-extra'
        )
    )


def collate_reviewer_attachments(reviewers, reviewers_extra):
    """Return collated reviewer data.

    Args:
        reviewers: Data from the 'reviewers' attachment of
            differential.revision.search.
        reviewers_extra: Data from the 'reviewers-extra'
            attachment of differential.revision.search.
    """
    phids = {}
    for reviewer in reviewers:
        data = {}
        for k in ('reviewerPHID', 'isBlocking', 'actorPHID'):
            data[k] = PhabricatorClient.expect(reviewer, k)

        data['status'] = ReviewerStatus.from_status(
            PhabricatorClient.expect(reviewer, 'status')
        )

        phids[data['reviewerPHID']] = data

    for reviewer in reviewers_extra:
        data = {}
        for k in ('reviewerPHID', 'diffPHID', 'voidedPHID'):
            data[k] = PhabricatorClient.expect(reviewer, k)

        data.update(phids.get(data['reviewerPHID'], {}))
        phids[data['reviewerPHID']] = data

    if len(phids) > min(len(reviewers), len(reviewers_extra)):
        raise PhabricatorCommunicationException(
            'Phabricator responded with unexpected data'
        )

    return phids


def serialize_reviewers(
    collated_reviewers, user_search_data, project_search_data, diff_phid
):
    reviewers = []

    for phid, r in collated_reviewers.items():
        identity = reviewer_identity(
            phid, user_search_data, project_search_data
        )
        state = calculate_review_extra_state(
            diff_phid, r['status'], r['diffPHID'], r['voidedPHID']
        )
        reviewers.append(
            {
                'phid': phid,
                'status': r['status'].value,
                'for_other_diff': state['for_other_diff'],
                'blocking_landing': state['blocking_landing'],
                'identifier': identity.identifier,
                'full_name': identity.full_name,
            }
        )

    return reviewers
