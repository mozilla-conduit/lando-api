# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Code Style Tests.
"""

import pytest
import subprocess

from landoapi.cli import LINT_PATHS


def test_check_python_style():
    cmd = ("black", "--diff")
    output = subprocess.check_output(cmd + LINT_PATHS)
    assert not output, "The python code does not adhere to the project style."


@pytest.mark.xfail
def test_check_python_ruff():
    passed = []
    for lint_path in LINT_PATHS:
        passed.append(
            subprocess.call(("ruff", "check", lint_path, "--target-version", "py39"))
            == 0
        )
    assert all(passed), "ruff did not run cleanly."
