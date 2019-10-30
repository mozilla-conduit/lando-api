# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.


import pytest
import os.path
import json

from landoapi.phabricator_patch import patch_to_changes

PATCHES_DIR = os.path.join(os.path.dirname(__file__), "patches")


@pytest.mark.parametrize("patch_name", ["basic", "random", "add"])
def test_patch_to_changes(patch_name):
    """Test the method to convert a raw patch into a list of Phabricator changes"""

    patch_path = os.path.join(PATCHES_DIR, f"{patch_name}.diff")
    result_path = os.path.join(PATCHES_DIR, f"{patch_name}.json")
    with open(patch_path) as p:
        output = patch_to_changes(p.read(), "deadbeef123")

    assert output == json.load(open(result_path))
