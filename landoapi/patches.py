# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import hashlib
import io
import logging

logger = logging.getLogger(__name__)


def calculate_patch_hash(patch: bytes) -> str:
    """Given a patch, calculate the sha1 hash and return the hex digest."""
    with io.BytesIO() as stream:
        stream.write(patch)
        return hashlib.sha1(stream.getvalue()).hexdigest()
