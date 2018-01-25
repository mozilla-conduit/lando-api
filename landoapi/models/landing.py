# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import datetime
import enum
import logging

from flask import current_app

from landoapi.models.patch import Patch
from landoapi.storage import db
from landoapi.transplant_client import TransplantClient

logger = logging.getLogger(__name__)


@enum.unique
class LandingStatus(enum.Enum):
    """Status of the landing request."""
    # Default value - stays in database only if landing request was aborted.
    aborted = 'aborted'

    # Set from pingback
    submitted = 'submitted'
    landed = 'landed'
    failed = 'failed'


class Landing(db.Model):
    """Represents the landing process in Autoland.

    Landing is communicating with Autoland via TransplantClient.
    Landing is communicating with Phabricator via PhabricatorClient.
    Landing object might be saved to database without creation of the actual
    landing in Autoland. It is done before landing request to construct
    required "pingback URL" and save related Patch objects.
    To update the Landing status Transplant is calling provided pingback URL.
    Active Diff Id is stored on creation if it is different than diff_id.

    Attributes:
        id: Primary Key
        request_id: Id of the request in Autoland
        revision_id: Phabricator id of the revision to be landed
        diff_id: Phabricator id of the diff to be landed
        active_diff_id: Phabricator id of the diff active at the moment of
            landing
        status: Status of the landing. Modified by `update` API
        error: Text describing the error if not landed
        result: Revision (sha) of push
        requester_email: The email address of the requester of the landing.
        tree: The hg.mozilla.org tree name the revision is to land to.
        created_at: DateTime of the creation
        updated_at: DateTime of the last save
    """
    __tablename__ = "landings"

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, unique=True)
    revision_id = db.Column(db.Integer)
    diff_id = db.Column(db.Integer)
    active_diff_id = db.Column(db.Integer)
    status = db.Column(db.Enum(LandingStatus), nullable=False)
    error = db.Column(db.String(128), default='')
    result = db.Column(db.String(128), default='')
    requester_email = db.Column(db.String(128))
    tree = db.Column(db.String(128))
    created_at = db.Column(db.DateTime(), nullable=False)
    updated_at = db.Column(db.DateTime(), nullable=False)

    def __init__(
        self,
        revision_id,
        diff_id,
        active_diff_id,
        request_id=None,
        requester_email=None,
        tree=None,
        # status will remain aborted only if landing request will fail
        status=LandingStatus.aborted
    ):
        self.revision_id = revision_id
        self.diff_id = diff_id
        self.active_diff_id = active_diff_id
        self.request_id = request_id
        self.requester_email = requester_email
        self.tree = tree
        self.status = status
        self.created_at = datetime.datetime.utcnow()

    @classmethod
    def create(
        cls,
        revision_id,
        diff_id,
        requester_email,
        phab,
        override_diff_id=None
    ):
        """Land revision.

        A typical successful story:
            * Revision and Diff are loaded from Phabricator.
            * Patch is created and uploaded to S3 bucket.
            * Landing object is created (without request_id)
            * A request to land the patch is send to Transplant client.
            * Created landing object is updated with returned `request_id`
              and status `submitted`. It is then saved and returned.

        Args:
            revision_id: The integer id of the revision to be landed
            diff_id: The id of the diff to be landed
            requester_email: The LDAP email address of the person requesting
                the landing
            phab: The PhabricatorClient instance to use
            override_diff_id: override this diff id (should be equal to the
                active diff id)

        Returns:
            A new Landing object

        Raises:
            RevisionNotFoundException: PhabricatorClient returned no revision
                for given revision_id
            InactiveDiffException: Diff is not the active one and no
                override_diff_id has been provided
            OverrideDiffException: id of the diff to override is not the
                active one.
            LandingNotCreatedException: landing request in Transplant failed
        """
        revision = phab.get_revision(id=revision_id)

        if not revision:
            raise RevisionNotFoundException(revision_id)

        # Validate overriding of the diff id.
        active_id = phab.diff_phid_to_id(revision['activeDiffPHID'])
        # If diff used to land revision is not the active one Lando API will
        # fail with a 409 error. The client will then inform the user that
        # Lando API might be forced to land that diff if that's what the user
        # wants.
        # In such case the client will request a new landing with a
        # force_override_of_diff_id parameter equal to the active diff id.
        # API will proceed with the landing.
        if override_diff_id:
            if override_diff_id != active_id:
                raise OverrideDiffException(
                    diff_id, active_id, override_diff_id
                )
            logger.warning(
                {
                    'revision_id': revision_id,
                    'diff_id': diff_id,
                    'active_diff_id': active_id,
                    'override_diff_id': override_diff_id,
                    'msg': 'Forced to override the active Diff'
                }, 'landing.warning'
            )
        elif diff_id != active_id:
            raise InactiveDiffException(diff_id, active_id)

        # Check if all parent revisions are closed
        open_revision = phab.get_first_open_parent_revision(revision)
        if open_revision:
            raise OpenParentException(open_revision_id=open_revision['id'])

        # Save the initial landing request
        repo = phab.get_revision_repo(revision)
        # TODO: handle non-existent repo
        tree = repo['fields']['shortName']
        landing = cls(
            diff_id=diff_id,
            active_diff_id=active_id,
            revision_id=revision_id,
            requester_email=requester_email,
            tree=tree
        )
        landing.save()

        # Create a patch and upload it to S3
        patch = Patch(landing.id, revision, diff_id)
        patch.upload(phab)

        # Send the request to transplant for landing
        trans = TransplantClient()
        request_id = trans.land(
            revision_id=revision_id,
            ldap_username=landing.requester_email,
            patch_urls=[patch.s3_url],
            tree=tree,
            pingback=current_app.config['PINGBACK_URL']
        )
        if not request_id:
            raise LandingNotCreatedException

        landing.request_id = request_id
        landing.status = LandingStatus.submitted
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
        """Save objects in storage."""
        self.updated_at = datetime.datetime.utcnow()
        if not self.id:
            db.session.add(self)

        return db.session.commit()

    def __repr__(self):
        return '<Landing: %s>' % self.id

    def serialize(self):
        """Serialize to JSON compatible dictionary."""
        return {
            'id': self.id,
            'revision_id': 'D{}'.format(self.revision_id),
            'request_id': self.request_id,
            'diff_id': self.diff_id,
            'active_diff_id': self.active_diff_id,
            'status': self.status.value,
            'error_msg': self.error,
            'result': self.result,
            'requester_email': self.requester_email,
            'tree': self.tree,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }

    def update_from_transplant(self, landed, error='', result=''):
        """Set the status from pingback request."""
        self.error = error
        self.result = result
        self.status = (
            LandingStatus.landed if landed else LandingStatus.failed
        )


class LandingNotCreatedException(Exception):
    """Transplant service failed to land a revision."""
    pass


class RevisionNotFoundException(Exception):
    """Phabricator returned 404 for a given revision id."""

    def __init__(self, revision_id):
        super().__init__('Revision {} not found'.format(revision_id))
        self.revision_id = revision_id


class InactiveDiffException(Exception):
    """Diff chosen to land is not the active one."""

    def __init__(self, diff_id, active_diff_id):
        super().__init__(
            'Diff chosen to land ({}) is not the active one ({})'.
            format(diff_id, active_diff_id)
        )
        self.diff_id = diff_id
        self.active_diff_id = active_diff_id


class OverrideDiffException(Exception):
    """Diff chosen to override is not the active one."""

    def __init__(self, diff_id, active_diff_id, override_diff_id):
        super().__init__(
            'Diff chosen to override ({}) is not the active one ({})'
            .format(override_diff_id, active_diff_id)
        )
        self.diff_id = diff_id
        self.active_diff_id = active_diff_id
        self.override_diff_id = override_diff_id


class OpenParentException(Exception):
    """Revision chosen to land has an open parent."""

    def __init__(self, open_revision_id):
        super().__init__(
            'Revision chosen to land has an open parent ({})'
            .format(open_revision_id)
        )
        self.open_revision_id = open_revision_id
