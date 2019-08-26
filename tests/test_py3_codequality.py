# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Code Style Tests.
"""
import subprocess

from landoapi.cli import LINT_PATHS


def test_check_python_style():
    cmd = ("black", "--diff")
    output = subprocess.check_output(cmd + LINT_PATHS)
    assert not output, "The python code does not adhear to the project style."


def test_check_python_flake8():
    cmd = ("flake8",)
    passed = subprocess.call(cmd + LINT_PATHS) == 0
    assert passed, "Flake8 did not run cleanly."
