# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.


def extract_rawdiff_id_from_uri(uri):
    """Extract a raw diff ID from a Diff uri."""
    # The raw diff is part of a URI, such as
    # "https://secure.phabricator.com/differential/diff/43480/".
    parts = uri.rsplit('/', 4)

    # Check that the URI Path is something we understand.  Fail if the
    # URI path changed (signalling that the raw diff part of the URI may
    # be in a different segment of the URI string).
    if parts[1:-2] != ['differential', 'diff']:
        raise RuntimeError(
            "Phabricator Raw Diff URI parsing error: The "
            "URI {} is not in a format we "
            "understand!".format(uri)
        )

    # Take the second-last member because of the trailing slash on the URL.
    return int(parts[-2])
