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

S3_INPUT_BUCKET = os.getenv("S3_INPUT_BUCKET", "meter-fp-sorted")
S3_PREFIX_BASE = os.getenv("S3_PREFIX_BASE", "")

S3_OUTPUT_BUCKET = os.getenv("S3_OUTPUT_BUCKET", "indi-analytics-output")
S3_OUTPUT_PREFIX = os.getenv("S3_OUTPUT_PREFIX", "DA-Output")

# ============================================================
# S3 CLIENT
# ============================================================
def get_s3_client():
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
    s3 = get_s3_client()
    s3.upload_file(local_path, bucket, key)
    return True

# ============================================================
# DATE HANDLING
# ============================================================
def parse_date_flex(date_str):
    """
    Parse date in:
    - DD-MM-YYYY
    - YYYY-MM-DD
    """
    for fmt in ("%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    raise ValueError(f"Unsupported date format: {date_str}")


def generate_date_formats(date_str):
    """
    Generate both formats for lookup:
    - DD-MM-YYYY
    - YYYY-MM-DD
    """
    date_obj = parse_date_flex(date_str)
    return [
        date_obj.strftime("%d-%m-%Y"),
        date_obj.strftime("%Y-%m-%d"),
    ]

# ============================================================
# FLEXIBLE FILE FINDER (NEW FIX)
# ============================================================
def find_file_with_date(folder, suffix, date_str):
    """
    Find file by checking all files in folder and matching:
    - date in either format
    - correct suffix
    """
    date_formats = generate_date_formats(date_str)

    if not os.path.exists(folder):
        return None

    for file in os.listdir(folder):
        for d in date_formats:
            if file.startswith(d) and file.endswith(suffix):
                return os.path.join(folder, file)

    return None

# ============================================================
# PIPELINE UPLOAD
# ============================================================
def upload_pipeline_output(local_path, category, filename, date_str=None):
    if date_str is None:
        date_obj = datetime.now() - timedelta(days=1)
    else:
        date_obj = parse_date_flex(date_str)

    # Always normalize for S3
    date_str = date_obj.strftime("%d-%m-%Y")

    key = f"{S3_OUTPUT_PREFIX}/{date_str}/{category}/{filename}"

    print(f"  Uploading {os.path.basename(local_path)} -> s3://{S3_OUTPUT_BUCKET}/{key}")
    upload_file(local_path, S3_OUTPUT_BUCKET, key)
    print(f"  Upload complete: {key}")
    return key

# ============================================================
# EXAMPLE USAGE (FIXED SKIP ISSUE)
# ============================================================
def upload_with_fallback(folder, suffix, category, output_filename, date_str):
    """
    Wrapper to:
    - find file in either date format
    - upload if found
    - skip if not found
    """
    file_path = find_file_with_date(folder, suffix, date_str)

    if file_path:
        upload_pipeline_output(file_path, category, output_filename, date_str)
        return "uploaded"
    else:
        print(f"  SKIP (not found): {folder}/{date_str}{suffix}")
        return "skipped"