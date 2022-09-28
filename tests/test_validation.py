# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import pytest
from connexion import ProblemException

from landoapi.validation import revision_id_to_int, is_valid_email


def test_convertion_success():
    assert revision_id_to_int("D123") == 123


@pytest.mark.parametrize("id", ["123D", "123", "DAB", "A123"])
def test_convertion_failure_string(id):
    with pytest.raises(ProblemException):
        revision_id_to_int(id)


def test_convertion_failure_integer():
    with pytest.raises(TypeError):
        revision_id_to_int(123)


def test_is_valid_email():
    invalid_emails = [
        "Test User",
        "test <test>",
        "test <test@test>",
        "test@",
        "-@...",
        "test@mozilla.",
        "test@.com",
    ]
    valid_emails = [
        "test@test.com",
        "test-email@test.com",
        "test_email@test.com",
        "test@test-domain.com",
        "test.name@test.co.uk",
        "colombia@test.co",
        "iceland@test.is",
        "deutsch@test.de",
    ]

    assert True not in [is_valid_email(value) for value in invalid_emails]
    assert False not in [is_valid_email(value) for value in valid_emails]
