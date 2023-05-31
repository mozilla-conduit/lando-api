# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.


import json
import os.path

import pytest

from landoapi.phabricator_patch import patch_to_changes


@pytest.mark.parametrize("patch_name", ["basic", "random", "add"])
def test_patch_to_changes(patch_directory, patch_name):
    """Test the method to convert a raw patch into a list of Phabricator changes"""

    patch_path = os.path.join(patch_directory, f"{patch_name}.diff")
    result_path = os.path.join(patch_directory, f"{patch_name}.json")
    with open(patch_path) as p:
        output = patch_to_changes(p.read(), "deadbeef123")

    assert output == json.load(open(result_path))
