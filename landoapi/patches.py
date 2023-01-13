# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import io

import boto3
import botocore
import logging
import tempfile

from typing import (
    Optional,
)

from landoapi.systems import Subsystem

logger = logging.getLogger(__name__)

PATCH_URL_FORMAT = "s3://{bucket}/{patch_name}"
PATCH_NAME_FORMAT = "V1_D{revision_id}_{diff_id}.patch"


def create_s3(
    aws_access_key: str, aws_secret_key: str, endpoint_url: Optional[str] = None
):
    """Create an object to access S3."""
    s3_kwargs = {
        "aws_access_key_id": aws_access_key,
        "aws_secret_access_key": aws_secret_key,
    }

    if endpoint_url:
        s3_kwargs["endpoint_url"] = endpoint_url

    return boto3.resource("s3", **s3_kwargs)


def name(revision_id: int, diff_id: int) -> str:
    """Return a patch name given a revision ID and diff ID."""
    return PATCH_NAME_FORMAT.format(revision_id=revision_id, diff_id=diff_id)


def url(bucket: str, name: str) -> str:
    """Return a patch S3 URL given an S3 bucket and patch name."""
    return PATCH_URL_FORMAT.format(bucket=bucket, patch_name=name)


def upload(
    revision_id: int,
    diff_id: int,
    patch: str,
    s3_bucket: str,
    *,
    aws_access_key: str,
    aws_secret_key: str,
    endpoint_url: Optional[str] = None,
) -> str:
    """Upload a patch to S3 Bucket.

    Build the patch contents and upload to S3.

    Args:
        revision_id: Integer ID of the Phabricator revision for
            the provided patch.
        diff_id: Integer ID of the Phabricator diff for
            the provided patch.
        patch: Raw patch string to be uploaded.
        s3_bucket: Name of the S3 bucket.
        aws_access_key: AWS access key.
        aws_secret_key: AWS secret key.

    Returns:
        The s3:// url of the uploaded patch.
    """
    s3 = create_s3(
        aws_access_key=aws_access_key,
        aws_secret_key=aws_secret_key,
        endpoint_url=endpoint_url,
    )
    patch_name = name(revision_id, diff_id)
    patch_url = url(s3_bucket, patch_name)

    with tempfile.TemporaryFile() as f:
        f.write(patch.encode("utf-8"))
        f.seek(0)
        s3.meta.client.upload_fileobj(f, s3_bucket, patch_name)

    logger.info("patch uploaded", extra={"patch_url": patch_url})
    return patch_url


def download(
    revision_id: int,
    diff_id: int,
    s3_bucket: str,
    *,
    aws_access_key: str,
    aws_secret_key: str,
    endpoint_url: Optional[str] = None,
) -> io.BytesIO:
    """Download a patch from S3 Bucket.

    Args:
        revision_id: Integer ID of the Phabricator revision for
            the patch.
        diff_id: Integer ID of the Phabricator diff for
            the patch.
        s3_bucket: Name of the S3 bucket.
        aws_access_key: AWS access key.
        aws_secret_key: AWS secret key.
        endpoint_url: Non-standard endpoint url to use for s3. Used for testing.

    Returns:
        An io.BytesIO with the patch contents.
    """
    s3 = create_s3(
        aws_access_key=aws_access_key,
        aws_secret_key=aws_secret_key,
        endpoint_url=endpoint_url,
    )
    patch_name = name(revision_id, diff_id)

    buf = io.BytesIO()
    s3.meta.client.download_fileobj(s3_bucket, patch_name, buf)
    buf.seek(0)  # Seek to the start for consumers.
    return buf


class PatchesS3Subsystem(Subsystem):
    name = "s3_patch_bucket"

    def healthy(self) -> bool | str:
        bucket = self.flask_app.config.get("PATCH_BUCKET_NAME")
        if not bucket:
            return "PATCH_BUCKET_NAME not configured"

        s3 = create_s3(
            aws_access_key=self.flask_app.config.get("AWS_ACCESS_KEY"),
            aws_secret_key=self.flask_app.config.get("AWS_SECRET_KEY"),
            endpoint_url=self.flask_app.config.get("S3_ENDPOINT_URL"),
        )
        try:
            s3.meta.client.head_bucket(Bucket=bucket)
        except botocore.exceptions.ClientError as exc:
            return "ClientError: {!s}".format(exc)
        except botocore.exceptions.BotoCoreError as exc:
            return "BotoCoreError: {!s}".format(exc)

        return True


patches_s3_subsystem = PatchesS3Subsystem()
