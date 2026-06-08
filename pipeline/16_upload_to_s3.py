"""
17_upload_to_s3.py - Upload all pipeline outputs to S3, then clean up local files.

Uploads to: s3://indi-analytics-output/DA-Output/{DD-MM-YYYY}/{category}/{filename}

Output files are uploaded WITHOUT dates in the filename.
The date is encoded in the S3 folder path instead.

After successful upload, local output files and downloaded FP input files are deleted.
"""

import os
import sys
import glob
from datetime import datetime, timedelta

# ============================================================
# CONFIG
# ============================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))

# Add project root to path so we can import s3_utils
sys.path.insert(0, BASE_DIR)
from s3_utils import upload_pipeline_output

# ============================================================
# DATE SETUP
# ============================================================
yesterday_obj = datetime.now() - timedelta(days=1)

# Date formats used by different scripts for filenames
date_ymd = yesterday_obj.strftime("%Y-%m-%d")   # 2026-05-07
date_dmy = yesterday_obj.strftime("%d-%m-%Y")   # 07-05-2026

# Date string for S3 folder (DD-MM-YYYY)
s3_date = date_dmy

print(f"Uploading outputs to S3 for date: {s3_date}")
print(f"  YYYY-MM-DD filenames: {date_ymd}")
print(f"  DD-MM-YYYY filenames: {date_dmy}")
print()

# ============================================================
# OUTPUT FILE MAPPING
# ============================================================
# Each entry: (local_path, s3_category, s3_filename)
# local_path is relative to BASE_DIR
# s3_filename should NOT include the date

UPLOADS = [
    # --- Logo Sessions ---
    {
        "local": os.path.join("sessions", "logo", "household_viewership_memberwise_output", f"{date_ymd}_logo_sessions.csv"),
        "category": "logo",
        "filename": "logo_sessions.csv",
    },

    # --- FP Sessions ---
    {
        "local": os.path.join("sessions", "fp", "output", f"{date_ymd}_fp_sessions.csv"),
        "category": "fp",
        "filename": "fp_sessions.csv",
    },

    # --- Merging: Sessions without rejuvenation ---
    {
        "local": os.path.join("sessions", "merging", "sessions_without_rejuvenation", f"{date_ymd}_Sessions.csv"),
        "category": "merging",
        "filename": "Sessions_without_rejuvenation.csv",
    },

    # --- Merging: Sessions with rejuvenation (Logo) ---
    {
        "local": os.path.join("sessions", "merging", "sessions_with_rejuvenation", f"{date_ymd}Members_Updatedlogo.csv"),
        "category": "merging",
        "filename": "Sessions_with_rejuvenation_logo.csv",
    },

    # --- Merging: Sessions with rejuvenation (FP) ---
    {
        "local": os.path.join("sessions", "merging", "sessions_with_rejuvenation", f"{date_ymd}Members_UpdatedFP.csv"),
        "category": "merging",
        "filename": "Sessions_with_rejuvenation_FP.csv",
    },

    # --- Merging: Final merged file ---
    {
        "local": os.path.join("sessions", "merging", "Final_merged_file", f"{date_ymd}_Sessions.csv"),
        "category": "merging",
        "filename": "Sessions_final_merged.csv",
    },

    # --- For Panel: Cleaned file ---
    {
        "local": os.path.join("for_panel_files", "for_panel", f"{date_dmy}_cleaned.csv"),
        "category": "for_panel",
        "filename": "cleaned.csv",
    },

    # --- Qualifier: Ruled file ---
    {
        "local": os.path.join("statement_file", "qualifier_output", f"{date_dmy}_ruled.csv"),
        "category": "qualifier",
        "filename": "ruled.csv",
    },

    # --- Qualifier: Ruled + Processed file ---
    {
        "local": os.path.join("statement_file", "qualifier_output", f"{date_dmy}_ruled_PROCESSED.csv"),
        "category": "qualifier",
        "filename": "ruled_PROCESSED.csv",
    },

    # --- Statement: Final statement file ---
    {
        "local": os.path.join("statement_file", "statement", f"{date_dmy}_statement.csv"),
        "category": "statement",
        "filename": "statement.csv",
    },
]

# ============================================================
# UPLOAD
# ============================================================
uploaded = 0
skipped = 0
failed = 0
uploaded_paths = []  # Track successfully uploaded files for deletion

for item in UPLOADS:
    local_path = os.path.join(BASE_DIR, item["local"])

    if not os.path.exists(local_path):
        print(f"  SKIP (not found): {item['local']}")
        skipped += 1
        continue

    try:
        upload_pipeline_output(
            local_path=local_path,
            category=item["category"],
            filename=item["filename"],
            date_str=s3_date,
        )
        uploaded += 1
        uploaded_paths.append(local_path)
    except Exception as e:
        print(f"  FAILED: {item['local']} -> {e}")
        failed += 1

# ============================================================
# UPLOAD SUMMARY
# ============================================================
print(f"\nUpload Summary:")
print(f"  Uploaded: {uploaded}")
print(f"  Skipped:  {skipped}")
print(f"  Failed:   {failed}")
print(f"  Total:    {len(UPLOADS)}")

if failed > 0:
    raise RuntimeError(f"{failed} file(s) failed to upload to S3. Skipping cleanup.")

# ============================================================
# CLEANUP: DELETE UPLOADED OUTPUT FILES
# ============================================================
print("\nCleaning up uploaded output files...")
deleted_outputs = 0

for path in uploaded_paths:
    try:
        os.remove(path)
        deleted_outputs += 1
    except Exception as e:
        print(f"  Warning: Could not delete {path}: {e}")

print(f"  Deleted {deleted_outputs} output file(s)")

# ============================================================
# CLEANUP: DELETE DOWNLOADED FP INPUT FILES
# ============================================================
print("\nCleaning up downloaded FP input files...")
fp_input_dir = os.path.join(BASE_DIR, "sessions", "fp", "input_data")
deleted_inputs = 0

if os.path.exists(fp_input_dir):
    for csv_file in glob.glob(os.path.join(fp_input_dir, "*.csv")):
        try:
            os.remove(csv_file)
            deleted_inputs += 1
        except Exception as e:
            print(f"  Warning: Could not delete {csv_file}: {e}")

print(f"  Deleted {deleted_inputs} FP input file(s)")

# ============================================================
# CLEANUP: DELETE FP INTERMEDIATE FILES
# ============================================================
print("\nCleaning up FP intermediate files...")
fp_output_dir = os.path.join(BASE_DIR, "sessions", "fp", "output")
fp_download_dir = os.path.join(BASE_DIR, "sessions", "fp", "downloads")
deleted_intermediate = 0

for cleanup_dir in [fp_output_dir, fp_download_dir]:
    if os.path.exists(cleanup_dir):
        for f in glob.glob(os.path.join(cleanup_dir, "*.csv")):
            try:
                os.remove(f)
                deleted_intermediate += 1
            except Exception as e:
                print(f"  Warning: Could not delete {f}: {e}")

print(f"  Deleted {deleted_intermediate} intermediate file(s)")

# ============================================================
# CLEANUP: DELETE REJUVENATION AUDIT FILES
# ============================================================
rejuv_dir = os.path.join(BASE_DIR, "sessions", "merging", "sessions_with_rejuvenation")
if os.path.exists(rejuv_dir):
    for txt_file in glob.glob(os.path.join(rejuv_dir, "*.txt")):
        try:
            os.remove(txt_file)
        except Exception:
            pass

print(f"\nAll cleanup complete. S3 upload and cleanup finished successfully.")
