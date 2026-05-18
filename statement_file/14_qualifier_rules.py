#This is the final rules script :
import pandas as pd
import glob
import os
from datetime import datetime, timedelta, time
from sqlalchemy import create_engine

# ============================================================
# CONFIG
# ============================================================
# Get project root directory
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))

yesterday = (datetime.now() - timedelta(days=1)).strftime("%d-%m-%Y")

# Use raw strings for Windows paths
INPUT_PATTERN = os.path.join(BASE_DIR, "for_panel_files", "for_panel", f"{yesterday}_cleaned.csv")
OUTPUT_DIR = os.path.join(BASE_DIR, "statement_file", "qualifier_output")

TOTAL_LIMIT = 50400       # 14 hours
RULE_B_LIMIT = 5400       # 1.5 hours
MAX_SESSION = 21600       # 6 hours

os.makedirs(OUTPUT_DIR, exist_ok=True)

from dotenv import load_dotenv

# Get project root directory
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))

# Load .env file
load_dotenv(os.path.join(BASE_DIR, ".env"))

# ============================================================
# DATABASE CONFIG
# ============================================================
db_config = {
    'host': os.getenv("DB_HOST"),
    'port': int(os.getenv("DB_PORT", 5432)),
    'dbname': os.getenv("DB_NAME"),
    'user': os.getenv("DB_USER"),
    'password': os.getenv("DB_PASSWORD")
}

# Create SQLAlchemy engine
engine_url = f"postgresql://{db_config['user']}:{db_config['password']}@{db_config['host']}:{db_config['port']}/{db_config['dbname']}"
engine = create_engine(engine_url)

# ============================================================
# FETCH REGION MAPPING
# ============================================================
print("Fetching region mapping from database...")

query = """
SELECT
    h.hhid,
    m.member_code,
    city,
    region
FROM households h
JOIN members m ON h.id = m.household_id
ORDER BY h.hhid, m.member_code;
"""

region_df = pd.read_sql(query, engine)
engine.dispose()

region_map = (
    region_df[['hhid', 'region']]
    .drop_duplicates()
)

print("Region mapping loaded:", len(region_map))

# ============================================================
# RULE B WINDOW
# ============================================================
RULE_B_START = time(2, 0, 0)
RULE_B_END = time(4, 59, 59)

def is_rule_b_time(t):
    return RULE_B_START <= t <= RULE_B_END

# ============================================================
# HELPER FUNCTION TO PARSE DATES FLEXIBLY
# ============================================================
def parse_flexible_datetime(date_str, time_str):
    """
    Parse date and time strings flexibly, trying multiple formats
    """
    if pd.isna(date_str) or pd.isna(time_str):
        return pd.NaT
    
    # Clean the strings
    date_str = str(date_str).strip()
    time_str = str(time_str).strip()
    
    # Replace various separators with hyphen for consistency
    date_str = date_str.replace('/', '-').replace('\\', '-').replace('_', '-')
    
    # Try different date formats
    date_formats = [
        "%d-%m-%Y",  # 28-04-2026
        "%Y-%m-%d",  # 2026-04-28
        "%d-%m-%y",  # 28-04-26
        "%m-%d-%Y",  # 04-28-2026
        "%Y/%m/%d",  # 2026/04/28
        "%d/%m/%Y",  # 28/04/2026
        "%m/%d/%Y",  # 04/28/2026
    ]
    
    parsed_date = None
    for date_format in date_formats:
        try:
            parsed_date = datetime.strptime(date_str, date_format)
            break
        except ValueError:
            continue
    
    if parsed_date is None:
        return pd.NaT
    
    # Parse time
    time_formats = [
        "%H:%M:%S",  # 14:30:00
        "%H:%M",     # 14:30
        "%I:%M:%S %p",  # 02:30:00 PM
        "%I:%M %p",     # 02:30 PM
    ]
    
    parsed_time = None
    for time_format in time_formats:
        try:
            parsed_time = datetime.strptime(time_str, time_format)
            break
        except ValueError:
            continue
    
    if parsed_time is None:
        return pd.NaT
    
    # Combine date and time
    result = parsed_date.replace(
        hour=parsed_time.hour,
        minute=parsed_time.minute,
        second=parsed_time.second
    )
    
    return result

# ============================================================
# LOAD FILES
# ============================================================
files = glob.glob(INPUT_PATTERN)
if not files:
    raise FileNotFoundError(f"No CSV files found matching pattern: {INPUT_PATTERN}")

# ============================================================
# PROCESS FILES
# ============================================================
for file_path in files:
    df = pd.read_csv(file_path)
    original_rows = len(df)

    # ========================================================
    # ADD REGION
    # ========================================================
    df = df.merge(region_map, on="hhid", how="left")
    df["region"] = df["region"].fillna("Unknown")

    # ========================================================
    # FLEXIBLE DATE PARSING - NO ROWS DROPPED
    # ========================================================
    
    # Apply flexible parsing to each row
    df["start_dt"] = df.apply(
        lambda row: parse_flexible_datetime(row.get("date"), row.get("start_time")), 
        axis=1
    )
    df["end_dt"] = df.apply(
        lambda row: parse_flexible_datetime(row.get("date"), row.get("end_time")), 
        axis=1
    )
    
    # For rows that failed to parse, try to extract from other columns or use defaults
    missing_start = df["start_dt"].isna()
    missing_end = df["end_dt"].isna()
    
    print(f"Rows with missing start_dt: {missing_start.sum()}")
    print(f"Rows with missing end_dt: {missing_end.sum()}")
    
    # If date is missing but we have timestamp or datetime column, try those
    if missing_start.any():
        for col in ['timestamp', 'datetime', 'created_at', 'updated_at']:
            if col in df.columns:
                df.loc[missing_start, "start_dt"] = pd.to_datetime(df.loc[missing_start, col], errors='coerce')
                missing_start = df["start_dt"].isna()
                if not missing_start.any():
                    break
    
    if missing_end.any():
        for col in ['timestamp', 'datetime', 'created_at', 'updated_at']:
            if col in df.columns:
                df.loc[missing_end, "end_dt"] = pd.to_datetime(df.loc[missing_end, col], errors='coerce')
                missing_end = df["end_dt"].isna()
                if not missing_end.any():
                    break
    
    # For remaining missing dates, use the date from working rows or current date
    if missing_start.any():
        # Try to infer from other rows with same hhid and member_id
        for idx in df[missing_start].index:
            hhid = df.loc[idx, 'hhid']
            member_id = df.loc[idx, 'member_id']
            
            # Find a working row with same hhid and member_id
            mask = (df['hhid'] == hhid) & (df['member_id'] == member_id) & (~df['start_dt'].isna())
            if mask.any():
                working_date = df.loc[mask, 'start_dt'].iloc[0].date()
                # Try to parse the time from the original string
                time_str = str(df.loc[idx, 'start_time']).strip()
                for time_format in ["%H:%M:%S", "%H:%M"]:
                    try:
                        parsed_time = datetime.strptime(time_str, time_format)
                        df.loc[idx, 'start_dt'] = datetime.combine(working_date, parsed_time.time())
                        break
                    except ValueError:
                        continue
            else:
                # Use today's date as fallback
                today = datetime.now().date()
                time_str = str(df.loc[idx, 'start_time']).strip()
                for time_format in ["%H:%M:%S", "%H:%M"]:
                    try:
                        parsed_time = datetime.strptime(time_str, time_format)
                        df.loc[idx, 'start_dt'] = datetime.combine(today, parsed_time.time())
                        break
                    except ValueError:
                        df.loc[idx, 'start_dt'] = datetime.now()
    
    if missing_end.any():
        for idx in df[missing_end].index:
            hhid = df.loc[idx, 'hhid']
            member_id = df.loc[idx, 'member_id']
            
            mask = (df['hhid'] == hhid) & (df['member_id'] == member_id) & (~df['end_dt'].isna())
            if mask.any():
                working_date = df.loc[mask, 'end_dt'].iloc[0].date()
                time_str = str(df.loc[idx, 'end_time']).strip()
                for time_format in ["%H:%M:%S", "%H:%M"]:
                    try:
                        parsed_time = datetime.strptime(time_str, time_format)
                        df.loc[idx, 'end_dt'] = datetime.combine(working_date, parsed_time.time())
                        break
                    except ValueError:
                        continue
            else:
                today = datetime.now().date()
                time_str = str(df.loc[idx, 'end_time']).strip()
                for time_format in ["%H:%M:%S", "%H:%M"]:
                    try:
                        parsed_time = datetime.strptime(time_str, time_format)
                        df.loc[idx, 'end_dt'] = datetime.combine(today, parsed_time.time())
                        break
                    except ValueError:
                        df.loc[idx, 'end_dt'] = datetime.now()
    
    # Standardize date column
    df["date"] = df["start_dt"].dt.strftime("%Y-%m-%d")
    
    # Handle end time in 00 or 01 - next day
    df.loc[
        (df["end_dt"].dt.hour.isin([0, 1])) & 
        (df["end_dt"] < df["start_dt"]),
        "end_dt"
    ] += timedelta(days=1)
    
    # Recalculate duration
    df["duration_seconds"] = (df["end_dt"] - df["start_dt"]).dt.total_seconds()
    
    # For any negative durations, swap start and end
    negative_duration = df["duration_seconds"] < 0
    if negative_duration.any():
        print(f"Fixing {negative_duration.sum()} rows with negative duration")
        temp_start = df.loc[negative_duration, "start_dt"].copy()
        df.loc[negative_duration, "start_dt"] = df.loc[negative_duration, "end_dt"]
        df.loc[negative_duration, "end_dt"] = temp_start
        df.loc[negative_duration, "duration_seconds"] = (
            df.loc[negative_duration, "end_dt"] - df.loc[negative_duration, "start_dt"]
        ).dt.total_seconds()
    
    # For zero duration, set minimum 1 second
    df.loc[df["duration_seconds"] == 0, "duration_seconds"] = 1

    # ========================================================
    # Create Indi
    # ========================================================
    df["Indi"] = df["hhid"].astype(str) + df["member_id"].astype(str)

    # ========================================================
    # SORT BEFORE MERGING
    # ========================================================
    df = df.sort_values(
        ["Indi", "date", "start_dt"],
        kind="mergesort"
    ).reset_index(drop=True)

    # ========================================================
    # MERGE CONTINUOUS SESSIONS
    # ========================================================
    merged_rows = []

    for indi, g in df.groupby("Indi", sort=False):
        g = g.sort_values("start_dt").reset_index(drop=True)
        
        if len(g) == 0:
            continue
            
        current = g.iloc[0].copy()

        for i in range(1, len(g)):
            next_row = g.iloc[i]

            # Check merge condition
            if (
                current["channelid"] == next_row["channelid"] and
                current["end_time"] == next_row["start_time"]
            ):
                # Extend current session
                current["end_time"] = next_row["end_time"]
                current["end_dt"] = next_row["end_dt"]

                # Recalculate duration
                duration_sec = (current["end_dt"] - current["start_dt"]).total_seconds()
                current["duration_seconds"] = duration_sec
                current["duration"] = str(timedelta(seconds=duration_sec))

            else:
                merged_rows.append(current)
                current = next_row.copy()

        merged_rows.append(current)

    df = pd.DataFrame(merged_rows)

    # ========================================================
    # Prepare for rules
    # ========================================================
    df["start_time_dt"] = pd.to_datetime(df["start_time"], format="%H:%M:%S", errors='coerce')
    # For any rows where start_time parsing failed, extract from start_dt
    df.loc[df["start_time_dt"].isna(), "start_time_dt"] = df.loc[df["start_time_dt"].isna(), "start_dt"]
    df["start_time_t"] = df["start_time_dt"].dt.time

    df = df.sort_values(
        ["hhid", "member_id", "date", "start_time"],
        kind="mergesort"
    ).reset_index(drop=True)

    # ========================================================
    # Remove sessions > 6 hours
    # ========================================================
    long_sessions = df["duration_seconds"] > MAX_SESSION
    if long_sessions.any():
        print(f"Removing {long_sessions.sum()} sessions longer than {MAX_SESSION/3600} hours")
    df = df[df["duration_seconds"] <= MAX_SESSION]

    # ========================================================
    # APPLY RULES
    # ========================================================
    output_rows = []
    
    for indi, g in df.groupby("Indi", sort=False):
        total_used = 0
        cutoff = False

        for _, row in g.iterrows():
            if cutoff:
                break

            dur = row["duration_seconds"]
            row_copy = row.copy()

            # Rule A
            if total_used + dur > TOTAL_LIMIT:
                allowed = TOTAL_LIMIT - total_used
                if allowed > 0:
                    row_copy["duration_seconds"] = allowed
                    new_end = row["start_time_dt"] + timedelta(seconds=allowed)
                    row_copy["end_time"] = new_end.strftime("%H:%M:%S")
                    row_copy["duration"] = str(timedelta(seconds=allowed))
                    output_rows.append(row_copy)
                cutoff = True
                break

            # Rule B
            if is_rule_b_time(row["start_time_t"]) and dur > RULE_B_LIMIT:
                continue

            total_used += dur
            output_rows.append(row_copy)

    # ========================================================
    # OUTPUT
    # ========================================================
    final_df = pd.DataFrame(output_rows)

    final_df = final_df.drop(
        columns=["start_time_dt", "start_time_t", "start_dt", "end_dt"],
        errors="ignore"
    )

    # Use date from the data or filename
    if "date" in final_df.columns and not final_df["date"].isna().all():
        date_str = str(final_df["date"].iloc[0])
    elif "date" in df.columns and not df["date"].isna().all():
        date_str = str(df["date"].iloc[0])
    else:
        date_str = os.path.splitext(os.path.basename(file_path))[0]

    # Convert date to dd-mm-yy format for filename
    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    formatted_date = date_obj.strftime("%d-%m-%Y")
    out_file = os.path.join(OUTPUT_DIR, f"{formatted_date}_ruled.csv")
    final_df.to_csv(out_file, index=False)

    cleaned_rows = len(final_df)
    rows_removed = original_rows - cleaned_rows

    print(f"Processed: {os.path.basename(file_path)}")
    print(f"  Original rows: {original_rows}")
    print(f"  Final rows: {cleaned_rows}")
    print(f"  Rows removed: {rows_removed} (due to rules, not date parsing)")
    print(f"  Output: {os.path.basename(out_file)}")
    print("-" * 50)

print("\nBatch cleaning completed successfully.")
print(f"Output directory: {OUTPUT_DIR}")