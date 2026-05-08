"""
Shared S3 utility module for the DA-Workflow pipeline.
Provides download and upload functions using boto3.
"""

import os
import boto3
from botocore.exceptions import ClientError
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load .env from project root
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_SCRIPT_DIR, ".env"))

# ============================================================
# S3 CONFIG
# ============================================================
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY")
S3_REGION = os.getenv("S3_REGION", "ap-south-1")

# Bucket for downloading FP input files
S3_INPUT_BUCKET = os.getenv("S3_INPUT_BUCKET", "meter-fp-sorted")
S3_PREFIX_BASE = os.getenv("S3_PREFIX_BASE", "")

# Bucket for uploading pipeline outputs
S3_OUTPUT_BUCKET = os.getenv("S3_OUTPUT_BUCKET", "indi-analytics-output")
S3_OUTPUT_PREFIX = os.getenv("S3_OUTPUT_PREFIX", "DA-Output")

# ============================================================
# S3 CLIENT
# ============================================================
def get_s3_client():
    """Create and return a boto3 S3 client with configured credentials."""
    return boto3.client(
        "s3",
        region_name=S3_REGION,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
    )

# ============================================================
# DOWNLOAD
# ============================================================
def download_file(bucket, key, local_path):
    """
    Download a single file from S3.
    Returns True if successful, False if the key does not exist.
    Raises on other errors.
    """
    s3 = get_s3_client()
    os.makedirs(os.path.dirname(local_path), exist_ok=True)

    try:
        s3.download_file(bucket, key, local_path)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "404":
            return False
        raise

# ============================================================
# UPLOAD
# ============================================================
def upload_file(local_path, bucket, key):
    """
    Upload a single local file to S3.
    Returns True on success.
    """
    s3 = get_s3_client()
    s3.upload_file(local_path, bucket, key)
    return True


def upload_pipeline_output(local_path, category, filename, date_str=None):
    """
    Upload a pipeline output file to S3 in a structured folder.

    S3 path: {S3_OUTPUT_PREFIX}/{date_str}/{category}/{filename}

    Parameters
    ----------
    local_path : str
        Absolute path to the local file to upload.
    category : str
        Subfolder name (e.g. 'logo', 'fp', 'statement').
    filename : str
        Destination filename (should NOT include date).
    date_str : str, optional
        Date folder name in DD-MM-YYYY format. Defaults to yesterday.
    """
    if date_str is None:
        date_str = (datetime.now() - timedelta(days=1)).strftime("%d-%m-%Y")

    key = f"{S3_OUTPUT_PREFIX}/{date_str}/{category}/{filename}"

    print(f"  Uploading {os.path.basename(local_path)} -> s3://{S3_OUTPUT_BUCKET}/{key}")
    upload_file(local_path, S3_OUTPUT_BUCKET, key)
    print(f"  Upload complete: {key}")
    return key
