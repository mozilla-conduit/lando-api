# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Module for constructing Mercurial patches in 'hg export' format.
"""

HG_EXPORT_PATCH_TEMPLATE = """# HG changeset patch
# User {author}
# Date {patchdate}
{commitdesc}

{diff}"""


def build_patch_for_revision(git_patch, author_data, revision_data):
    """Generate a 'hg export' patch using Phabricator Revision data.

    Args:
        git_patch: A string holding a Git-formatted patch.
        author_data: A Phabricator User data dictionary for the patch's author.
        revision_data: A dictionary holding data fetched from a Phabricator
            revision.

    Returns:
        A string containing a patch in 'hg export' format.
    """
    # FIXME: This needs to use the correct email.
    # FIXME: in order: secondary phab user email, primary phab user email
    # Author has to be the LDAP username of the patch author.
    author = author_data['userName']

    # Back-date the patch to the last modification date of the Revision it's
    # based on.
    #
    # Assume Phabricator is returning valid date responses as "seconds since
    # the Unix Epoch", but cast it to int() just to be sure.  Also assume the
    #  Phabricator server is returning that number relative to UTC.
    patchdate = '%s +0000' % int(revision_data['dateModified'])

    return HG_EXPORT_PATCH_TEMPLATE.format(
        author=author,
        patchdate=patchdate,
        commitdesc=revision_data['summary'],
        diff=git_patch,
    )
