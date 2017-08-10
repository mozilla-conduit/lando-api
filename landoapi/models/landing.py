# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import os

import logging

from landoapi.hgexportbuilder import build_patch_for_revision
from landoapi.models.storage import db
from landoapi.phabricator_client import PhabricatorClient
from landoapi.transplant_client import TransplantClient

logger = logging.getLogger(__name__)

TRANSPLANT_JOB_PENDING = 'pending'
TRANSPLANT_JOB_STARTED = 'started'
TRANSPLANT_JOB_LANDED = 'landed'
TRANSPLANT_JOB_FAILED = 'failed'


class Landing(db.Model):
    __tablename__ = "landings"

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, unique=True)
    revision_id = db.Column(db.String(30))
    diff_id = db.Column(db.Integer)
    status = db.Column(db.Integer)
    error = db.Column(db.String(128), default='')
    result = db.Column(db.String(128))

    def __init__(
        self,
        request_id=None,
        revision_id=None,
        diff_id=None,
        status=TRANSPLANT_JOB_PENDING
    ):
        self.request_id = request_id
        self.revision_id = revision_id
        self.diff_id = diff_id
        self.status = status

    @classmethod
    def create(cls, revision_id, phabricator_api_key=None, diff_id=None):
        """ Land revision and create a Transplant item in storage. """
        phab = PhabricatorClient(phabricator_api_key)
        revision = phab.get_revision(id=revision_id)

        if not revision:
            raise RevisionNotFoundException(revision_id)

        if not diff_id:
            diff_id = phab.get_diff(phid=revision['activeDiffPHID'])['id']

        git_diff = phab.get_rawdiff(diff_id)

        author = phab.get_revision_author(revision)
        hgpatch = build_patch_for_revision(git_diff, author, revision)

        repo = phab.get_revision_repo(revision)

        # save landing to make sure we've got the callback
        landing = cls(revision_id=revision_id, diff_id=diff_id).save()

        # Define the pingback URL with the port
        callback = '{host_url}/landings/{id}/update'.format(
            host_url=os.getenv('PINGBACK_HOST_URL'), id=landing.id
        )

        trans = TransplantClient()
        # The LDAP username used here has to be the username of the patch
        # pusher (the person who pushed the 'Land it!' button).
        # FIXME: change ldap_username@example.com to the real data retrieved
        #        from Auth0 userinfo
        request_id = trans.land(
            'ldap_username@example.com', hgpatch, repo['uri'], callback
        )
        if not request_id:
            raise LandingNotCreatedException

        landing.request_id = request_id
        landing.status = TRANSPLANT_JOB_STARTED
        landing.save()

        logger.info(
            {
                'revision_id': revision_id,
                'landing_id': landing.id,
                'msg': 'landing created for revision'
            }, 'landing.success'
        )

        return landing

    def save(self):
        """ Save objects in storage. """
        if not self.id:
            db.session.add(self)

        db.session.commit()
        return self

    def __repr__(self):
        return '<Landing: %s>' % self.id

    def serialize(self):
        """ Serialize to JSON compatible dictionary. """
        return {
            'id': self.id,
            'revision_id': self.revision_id,
            'request_id': self.request_id,
            'diff_id': self.diff_id,
            'status': self.status,
            'error_msg': self.error,
            'result': self.result
        }


class LandingNotCreatedException(Exception):
    """ Transplant service failed to land a revision. """
    pass


class RevisionNotFoundException(Exception):
    """ Phabricator returned 404 for a given revision id. """

    def __init__(self, revision_id):
        super().__init__()
        self.revision_id = revision_id
