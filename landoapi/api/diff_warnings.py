# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""
This module provides the API controllers for the `DiffWarning` model.

These API endpoints can be used by clients (such as Lando UI, Code Review bot, etc.) to
get, create, or archive warnings.
"""

import logging

from connexion import problem

from landoapi.decorators import require_phabricator_api_key
from landoapi.models.revisions import DiffWarning, DiffWarningStatus
from landoapi.storage import db

logger = logging.getLogger(__name__)


@require_phabricator_api_key()
def post(data):
    """Create a new `DiffWarning` based on provided revision and diff IDs.

    Args:
        data (dict): A dictionary containing data to store in the warning. `data`
            should contain at least a `message` key that contains the message to
            show in the warning.

    Returns:
        dict: a dictionary representation of the object that was created.
    """
    # TODO: validate whether revision/diff exist or not.
    if "message" not in data["data"]:
        return problem(
            400,
            "Provided data is not in correct format",
            "Missing required 'message' key in data",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
        )
    warning = DiffWarning(**data)
    db.session.add(warning)
    db.session.commit()
    return warning.serialize(), 201


@require_phabricator_api_key()
def delete(pk):
    """Archive a `DiffWarning` based on provided pk."""
    warning = DiffWarning.query.get(pk)
    if not warning:
        return problem(
            400,
            "DiffWarning does not exist",
            f"DiffWarning with primary key {pk} does not exist",
            type="https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400",
        )
    warning.status = DiffWarningStatus.ARCHIVED
    db.session.commit()
    return warning.serialize(), 200


@require_phabricator_api_key()
def get(revision_id, diff_id, group):
    """Return a list of active revision diff warnings, if any."""
    warnings = DiffWarning.query.filter(
        DiffWarning.revision_id == revision_id,
        DiffWarning.diff_id == diff_id,
        DiffWarning.status == DiffWarningStatus.ACTIVE,
        DiffWarning.group == group,
    )
    return [w.serialize() for w in warnings], 200
