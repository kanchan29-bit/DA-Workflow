import pandas as pd
import glob
import os
import re
from datetime import datetime, timedelta
from typing import List

# ============================================================
# CONFIG
# ============================================================
# Get project root directory
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))

yesterday_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
INPUT_DIR = os.path.join(BASE_DIR, "sessions", "merging", "Final_merged_file")
INPUT_PATTERN = "*.csv"  # Get all CSV files, we'll filter by date
OUTPUT_DIR = os.path.join(BASE_DIR, "for_panel_files", "for_panel")

# Channel IDs to remove
CHANNELS_TO_REMOVE = {6, 9, 10, 13, 15, 14}

os.makedirs(OUTPUT_DIR, exist_ok=True)

# ============================================================
# Helper: convert HH:MM:SS(.ms) → reporting-day seconds
# ============================================================
def time_to_seconds(t):
    try:
        if pd.isna(t):
            return None

        h, m, s = str(t).split(":")
        secs = int(h) * 3600 + int(m) * 60 + float(s)

        # Reporting day: 2 AM to 2 AM
        if secs < 7200:
            secs += 86400

        return int(secs)
    except Exception:
        return None

# ============================================================
# NEW FUNCTION: Handles next-day sessions properly
# Example: 23:00 → 01:00 = 2 hours
# ============================================================
def calculate_duration(df):

    if {"date", "start_time", "end_time"}.issubset(df.columns):

        # Create datetime columns
        df["start_dt"] = pd.to_datetime(
            df["date"].astype(str) + " " + df["start_time"].astype(str),
            errors="coerce"
        )

        df["end_dt"] = pd.to_datetime(
            df["date"].astype(str) + " " + df["end_time"].astype(str),
            errors="coerce"
        )

        # If crossed midnight
        df.loc[df["end_dt"] < df["start_dt"], "end_dt"] += timedelta(days=1)

        # Duration
        df["duration_seconds"] = (
            df["end_dt"] - df["start_dt"]
        ).dt.total_seconds()

        # Remove invalid rows
        df = df[df["duration_seconds"] > 0]

    return df


# ============================================================
# NEW FUNCTION: Shift values from s3_date to date and chname to channel
# ============================================================
def shift_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Shift values from s3_date column to date column, and from chname column to channel column.
    This function is called BEFORE any other processing.
    """
    print("    Shifting column values (s3_date → date, chname → channel)...")
    
    # Shift s3_date to date column
    if 's3_date' in df.columns:
        # If date column exists, replace its values with s3_date where s3_date is not null/empty
        if 'date' in df.columns:
            # Create mask for valid s3_date values (not null and not empty string)
            s3_date_valid = df['s3_date'].notna() & (df['s3_date'].astype(str).str.strip() != '')
            # Shift values from s3_date to date column
            df.loc[s3_date_valid, 'date'] = df.loc[s3_date_valid, 's3_date']
            print(f"       Shifted {s3_date_valid.sum()} value(s) from s3_date to date column")
        else:
            # If date column doesn't exist, create it with s3_date values
            df['date'] = df['s3_date']
            print(f"       Created date column with {df['s3_date'].notna().sum()} value(s) from s3_date")
        
        # Optionally drop s3_date column after shifting
        # df = df.drop(columns=['s3_date'])
    else:
        print("       s3_date column not found in dataframe")
    
    # Shift chname to channel column
    if 'chname' in df.columns:
        # If channel column exists, replace its values with chname where chname is not null/empty
        if 'channel' in df.columns:
            # Create mask for valid chname values (not null and not empty string)
            chname_valid = df['chname'].notna() & (df['chname'].astype(str).str.strip() != '')
            # Shift values from chname to channel column
            df.loc[chname_valid, 'channel'] = df.loc[chname_valid, 'chname']
            print(f"       Shifted {chname_valid.sum()} value(s) from chname to channel column")
        else:
            # If channel column doesn't exist, create it with chname values
            df['channel'] = df['chname']
            print(f"       Created channel column with {df['chname'].notna().sum()} value(s) from chname")
        
        # Optionally drop chname column after shifting
        # df = df.drop(columns=['chname'])
    else:
        print("       chname column not found in dataframe")
    
    return df

# ============================================================
# Channel Mapping
# ============================================================
CHANNEL_MAP = {
    "Shant TV": 3, "ShantTV": 3,
    "MIR TV": 8, "MirTV": 8,
    "Boon Tv": 11, "BoonTV": 11,
    "Nur TV": 10, "NurTV": 10,
    "Shoghakat TV": 9,
    "1st TV channel": 2,
    "FirstNewsChannel": 1,
    "Nor Hayastan": 13, "NorHayastan": 13,
    "First News Channel": 1,
    "Public TV": 2, "PublicTV": 2,
    "Fast Sports": 6,
    "Kentron Tv HD": 5, "KentronTVHD": 5,
    "Free News": 14, "FreeNews": 14,
    "Armenia TV": 4, "ArmeniaTV": 4,
    "TV 5": 12, "TV5": 12,
    "Dar 21 TV": 7, "Dar21TV": 7,
    "A TV": 15, "ATV": 15,
    "Others": 99
}

CHANNEL_MAP_NORM = {k.strip().lower(): v for k, v in CHANNEL_MAP.items()}

# ============================================================
# Utilities - FIXED for DD-MM-YYYY format
# ============================================================
# Updated regex to match DD-MM-YYYY format
DATE_REGEX = re.compile(r"(\d{4}-\d{2}-\d{2})")  # Matches DD-MM-YYYY

def extract_date_from_filename(filename: str):
    match = DATE_REGEX.search(filename)
    if not match:
        return None
    try:
        # Parse DD-MM-YYYY format
        return datetime.strptime(match.group(1), "%Y-%m-%d").date()
    except ValueError:
        return None

def get_files_in_date_range(start_date, end_date) -> List[str]:
    files = glob.glob(os.path.join(INPUT_DIR, INPUT_PATTERN))
    selected = []

    for file_path in files:
        fname = os.path.basename(file_path)
        file_date = extract_date_from_filename(fname)

        if file_date and start_date <= file_date <= end_date:
            selected.append(file_path)

    return sorted(selected)

def prompt_date(prompt_text: str):
    while True:
        val = input(prompt_text).strip()
        try:
            return datetime.strptime(val, "%Y-%m-%d").date()
        except ValueError:
            print(" Invalid format. Please use YYYY-MM-DD")

# ============================================================
# Core Processing
# ============================================================
def process_file(file_path: str):
    print(f"\n Processing: {file_path}")

    df = pd.read_csv(file_path)
    original_rows = len(df)
    
    # ============================================================
    # NEW: Shift values BEFORE all other processing
    # ============================================================
    df = shift_columns(df)

    # --------------------------------------------------------
    # 1. Assign channelid FIRST 
    # --------------------------------------------------------
    df["channelid"] = (
        df["channel"]
        .astype(str)
        .str.strip()
        .str.lower()
        .map(CHANNEL_MAP_NORM)
        .fillna(99)
        .astype(int)
    )

    # --------------------------------------------------------
    # 2. Remove unwanted channel IDs 
    # --------------------------------------------------------
    removed_count = df["channelid"].isin(CHANNELS_TO_REMOVE).sum()
    df = df[~df["channelid"].isin(CHANNELS_TO_REMOVE)]

    # --------------------------------------------------------
    # 3. Add start_time_secs
    # --------------------------------------------------------
    if "start_time" not in df.columns:
        raise ValueError("Missing 'start_time' column")

    df["start_time_secs"] = df["start_time"].apply(time_to_seconds)

    # --------------------------------------------------------
    # 4. Remove empty member_id
    # --------------------------------------------------------
    if "member_id" in df.columns:
        df = df.dropna(subset=["member_id"])
        df = df[df["member_id"].astype(str).str.strip() != ""]

    # --------------------------------------------------------
    # 5. Remove channel == "Others"
    # --------------------------------------------------------
    df = df[df["channel"] != "Others"]

    cleaned_rows = len(df)

    # --------------------------------------------------------
    # Output filename - FIXED: Use yesterday_date
    # --------------------------------------------------------
    if "date" in df.columns and not df["date"].isna().all():
        # Convert date if needed
        first_date = df["date"].iloc[0]
        if isinstance(first_date, str):
            try:
                date_obj = datetime.strptime(first_date, "%Y-%m-%d")
                date_str = date_obj.strftime("%Y-%m-%d")
            except:
                date_str = yesterday_date
        else:
            date_str = yesterday_date
    else:
        date_str = yesterday_date

    output_file = os.path.join(OUTPUT_DIR, f"{date_str}_cleaned.csv")

    df.to_csv(output_file, index=False)

    print(
        f" Rows: {original_rows} → {cleaned_rows} | "
        f" Removed: {removed_count} | "
        f"Saved: {output_file}"
    )

# ============================================================
# MAIN - FIXED
# ============================================================
def main():
    print("\n Auto-processing D-1 files")

    # --------------------------------------------------------
    # Get yesterday's date (as date object for comparison)
    # --------------------------------------------------------
    yesterday = (datetime.now() - timedelta(days=1)).date()
    yesterday_str = yesterday.strftime("%Y-%m-%d")  # For matching filenames

    print(f" Target date: {yesterday_str}")

    # --------------------------------------------------------
    # Get all CSV files and filter for yesterday's date
    # --------------------------------------------------------
    all_files = glob.glob(os.path.join(INPUT_DIR, INPUT_PATTERN))
    files = []

    print(f"\n Checking {len(all_files)} file(s) in {INPUT_DIR}")
    
    for file_path in all_files:
        fname = os.path.basename(file_path)
        print(f"   Found: {fname}")
        file_date = extract_date_from_filename(fname)

        if file_date == yesterday:
            files.append(file_path)
            print(f"       Matched: {fname}")
        else:
            if file_date:
                print(f"       Skipped (date: {file_date})")

    if not files:
        print(f"\n No files found for {yesterday_str}")
        print(f"   Expected filename pattern: *{yesterday_str}*.csv")
        return

    print(f"\n {len(files)} file(s) found for processing")

    # --------------------------------------------------------
    # Process files
    # --------------------------------------------------------
    for file_path in sorted(files):
        process_file(file_path)

    print("\n D-1 processing completed successfully.")

if __name__ == "__main__":
    main()