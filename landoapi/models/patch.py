# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import boto3
import logging
import tempfile

from flask import current_app

from landoapi.hgexportbuilder import build_patch_for_revision

logger = logging.getLogger(__name__)

PATCH_URL_FORMAT = 's3://{bucket}/{patch_name}'
PATCH_NAME_FORMAT = 'L{landing_id}_D{revision_id}_{diff_id}.patch'


class Patch:
    def __init__(self, landing_id, revision, diff_id):
        """Create a patch instance.

        Args:
            landing_id: Id of the landing in Lando API
            revision: The revision as returned by PhabricatorClient
            diff_id: The id of the diff to be landed
        """
        self.landing_id = landing_id
        self.diff_id = diff_id
        self.revision = revision

    def build(self, phab):
        """Build the patch contents using diff.

        Request diff and revision author from Phabricator API and build the
        patch using the result.

        Returns:
            A string containing a patch in 'hg export' format.

        Raises:
            DiffNotFoundException: PhabricatorClient returned no diff for
                given diff_id
        """
        diff = phab.get_rawdiff(self.diff_id)

        if not diff:
            raise DiffNotFoundException(self.diff_id)

        author = phab.get_revision_author(self.revision)
        return build_patch_for_revision(diff, author, self.revision)

    def upload(self, phab):
        """Upload the patch to S3 Bucket.

        Build the patch contents and upload to S3.

        Args:
            phab: PhabricatorClient instance
        """
        hgpatch = self.build(phab)

        # Upload patch to S3.
        s3 = boto3.resource(
            's3',
            aws_access_key_id=current_app.config['AWS_ACCESS_KEY'],
            aws_secret_access_key=current_app.config['AWS_SECRET_KEY']
        )
        patch_name = PATCH_NAME_FORMAT.format(
            landing_id=self.landing_id,
            revision_id=self.revision['id'],
            diff_id=self.diff_id
        )
        bucket = current_app.config['PATCH_BUCKET_NAME']
        self.s3_url = PATCH_URL_FORMAT.format(
            bucket=bucket, patch_name=patch_name
        )
        with tempfile.TemporaryFile() as patchfile:
            patchfile.write(hgpatch.encode('utf-8'))
            patchfile.seek(0)
            s3.meta.client.upload_fileobj(patchfile, bucket, patch_name)

        logger.info(
            {
                'patch_url': self.s3_url,
                'msg': 'Patch file uploaded'
            }, 'landing.patch_uploaded'
        )


class DiffNotFoundException(Exception):
    """Phabricator returned 404 for a given diff id."""

    def __init__(self, diff_id):
        super().__init__()
        self.diff_id = diff_id
