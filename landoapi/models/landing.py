# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
from landoapi.models.storage import db
from landoapi.phabricator_client import PhabricatorClient
from landoapi.transplant_client import TransplantClient

TRANSPLANT_JOB_STARTED = 'started'
TRANSPLANT_JOB_FINISHED = 'finished'


def _get_revision(revision_id, api_key=None):
    """ Gets revision from Phabricator.

    Returns None or revision.
    """
    phab = PhabricatorClient(api_key)
    revision = phab.get_revision(id=revision_id)
    if not revision:
        return None

    raw_repo = phab.get_repo(revision['repositoryPHID'])
    return {
        'id': int(revision['id']),
        'phid': revision['phid'],
        'repo_url': raw_repo['uri'],
        'title': revision['title'],
        'url': revision['uri'],
        'date_created': int(revision['dateCreated']),
        'date_modified': int(revision['dateModified']),
        'status': int(revision['status']),
        'status_name': revision['statusName'],
        'summary': revision['summary'],
        'test_plan': revision['testPlan'],
    }


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
        revision = _get_revision(revision_id, phabricator_api_key)
        if not revision:
            raise RevisionNotFoundException(revision_id)

        trans = TransplantClient()
        request_id = trans.land(
            'ldap_username@example.com', revision['repo_url']
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
