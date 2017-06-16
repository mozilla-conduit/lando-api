# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
from landoapi.hgexportbuilder import build_patch_for_revision
from landoapi.models.storage import db
from landoapi.phabricator_client import PhabricatorClient
from landoapi.transplant_client import TransplantClient

TRANSPLANT_JOB_STARTED = 'started'
TRANSPLANT_JOB_FINISHED = 'finished'


class Landing(db.Model):
    __tablename__ = "landings"

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, unique=True)
    revision_id = db.Column(db.String(30))
    status = db.Column(db.Integer)

    def __init__(
        self, request_id=None, revision_id=None, status=TRANSPLANT_JOB_STARTED
    ):
        self.request_id = request_id
        self.revision_id = revision_id
        self.status = status

    @classmethod
    def create(cls, revision_id, phabricator_api_key=None, save=True):
        """ Land revision and create a Transplant item in storage. """
        phab = PhabricatorClient(phabricator_api_key)
        revision = phab.get_revision(id=revision_id)

        if not revision:
            raise RevisionNotFoundException(revision_id)

        git_diff = phab.get_latest_revision_diff_text(revision)
        author = phab.get_revision_author(revision)
        hgpatch = build_patch_for_revision(git_diff, author, revision)

        repo = phab.get_revision_repo(revision)

        trans = TransplantClient()
        # The LDAP username used here has to be the username of the patch
        # pusher.
        # FIXME: what value do we use here?
        # FIXME: This client, or the person who pushed the 'Land it!' button?
        request_id = trans.land(
            'ldap_username@example.com', hgpatch, repo['uri']
        )
        if not request_id:
            raise LandingNotCreatedException

        landing = cls(
            revision_id=revision_id,
            request_id=request_id,
            status=TRANSPLANT_JOB_STARTED
        )
        if save:
            landing.save(create=True)

        return landing

    @classmethod
    def get(cls, landing_id):
        """ Get Landing object from storage. """
        landing = cls.query.get(landing_id)
        if not landing:
            raise LandingNotFoundException()

        return landing

    def save(self, create=False):
        """ Save objects in storage. """
        if create:
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
            'status': self.status
        }


class LandingNotCreatedException(Exception):
    """ Transplant service failed to land a revision. """
    pass


class LandingNotFoundException(Exception):
    """ No specific Landing was found in database. """
    pass


class RevisionNotFoundException(Exception):
    """ Phabricator returned 404 for a given revision id. """

    def __init__(self, revision_id):
        super().__init__()
        self.revision_id = revision_id
