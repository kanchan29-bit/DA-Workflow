"""
02_downloading_files.py - Download FP matched CSVs from S3.

Replaces the old email-based download with direct S3 access.
Downloads files for the reporting window: D-1 02:00 to D 01:59.
Only downloads matched files (unmatched are not used by the pipeline).
"""

import os
import sys
from datetime import datetime, timedelta

# ============================================================
# CONFIG
# ============================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))

# Add project root to path so we can import s3_utils
sys.path.insert(0, BASE_DIR)
from s3_utils import download_file, S3_INPUT_BUCKET, S3_PREFIX_BASE

EXTRACT_DIR = os.path.join(SCRIPT_DIR, "input_data")
os.makedirs(EXTRACT_DIR, exist_ok=True)

# ============================================================
# BUILD EXPECTED FILE LIST (D-1 + D LOGIC)
# ============================================================
today = datetime.now().date()
yesterday = today - timedelta(days=1)

# Reporting window: yesterday 02:00 to today 01:59
download_plan = []

# D-1 -> hours 02 to 23
for hour in range(2, 24):
    date_str = yesterday.strftime("%Y-%m-%d")
    hour_str = f"{hour:02d}"
    download_plan.append((date_str, hour_str))

# D -> hours 00 and 01
for hour in range(0, 2):
    date_str = today.strftime("%Y-%m-%d")
    hour_str = f"{hour:02d}"
    download_plan.append((date_str, hour_str))

print(f"Downloading FP files from S3 bucket: {S3_INPUT_BUCKET}")
print(f"Prefix base: {S3_PREFIX_BASE}")
print(f"Expected {len(download_plan)} matched files")

# ============================================================
# DOWNLOAD MATCHED FILES FROM S3
# ============================================================
matched_success = 0
matched_failed = []

for date_str, hour_str in download_plan:
    # S3 key pattern: {PREFIX_BASE}/{dateStr}/{hourStr}/{dateStr}_{hourStr}_matched.csv
    base_key = f"{S3_PREFIX_BASE}/{date_str}/{hour_str}/{date_str}_{hour_str}" if S3_PREFIX_BASE else f"{date_str}/{hour_str}/{date_str}_{hour_str}"

    matched_key = f"{base_key}_matched.csv"
    matched_local = os.path.join(EXTRACT_DIR, f"{date_str}_{hour_str}_matched.csv")

    try:
        if download_file(S3_INPUT_BUCKET, matched_key, matched_local):
            matched_success += 1
        else:
            matched_failed.append(f"{date_str}_{hour_str}_matched.csv")
            print(f"  Not found: {matched_key}")
    except Exception as e:
        matched_failed.append(f"{date_str}_{hour_str}_matched.csv")
        print(f"  Error downloading {matched_key}: {e}")

# ============================================================
# SUMMARY
# ============================================================
print(f"\nDownload Summary:")
print(f"  Matched files downloaded: {matched_success}/{len(download_plan)}")

if matched_failed:
    print(f"\n  Missing matched files ({len(matched_failed)}):")
    for f in matched_failed:
        print(f"    - {f}")

# Fail if no matched files were downloaded (matched files are critical)
if matched_success == 0:
    raise RuntimeError("No matched files could be downloaded from S3. Check credentials and bucket/prefix configuration.")

print("\nS3 download complete.")