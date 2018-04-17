# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import os


def phab_url(path):
    """ Utility to generate a url to Phabricator's API """
    return '%s/api/%s' % (os.getenv('PHABRICATOR_URL'), path)


def trans_url(path):
    """ Utility to generate a url to Transplant's API """
    return '%s/%s' % (os.getenv('TRANSPLANT_URL'), path)
