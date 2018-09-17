# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import boto3
import logging
import tempfile

logger = logging.getLogger(__name__)

PATCH_URL_FORMAT = "s3://{bucket}/{patch_name}"
PATCH_NAME_FORMAT = "V1_D{revision_id}_{diff_id}.patch"


def name(revision_id, diff_id):
    return PATCH_NAME_FORMAT.format(revision_id=revision_id, diff_id=diff_id)


def url(bucket, name):
    return PATCH_URL_FORMAT.format(bucket=bucket, patch_name=name)


def upload(revision_id, diff_id, patch, s3_bucket, *, aws_access_key, aws_secret_key):
    """Upload a patch to S3 Bucket.

    Build the patch contents and upload to S3.

    Args:
        revision_id: Integer ID of the Phabricator revision for
            the provided patch.
        diff_id: Integer ID of the Phabricator diff for
            the provided patch
        patch: Raw patch string to be uploaded.
        s3_bucket: Name of the S3 bucket.
        aws_access_key: AWS access key.
        aws_secret_key: AWS secret key.

    Returns:
        The s3:// url of the uploaded patch.
    """
    s3 = boto3.resource(
        "s3", aws_access_key_id=aws_access_key, aws_secret_access_key=aws_secret_key
    )
    patch_name = name(revision_id, diff_id)
    patch_url = url(s3_bucket, patch_name)

    with tempfile.TemporaryFile() as f:
        f.write(patch.encode("utf-8"))
        f.seek(0)
        s3.meta.client.upload_fileobj(f, s3_bucket, patch_name)

    logger.info("patch uploaded", extra={"patch_url": patch_url})
    return patch_url
