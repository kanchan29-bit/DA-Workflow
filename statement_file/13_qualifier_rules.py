# ============================================================
# FINAL RULES SCRIPT (UPDATED WITH SECONDS-BASED ENGINE)
# ============================================================

import pandas as pd
import glob
import os
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from dotenv import load_dotenv

# ============================================================
# CONFIG
# ============================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))

yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

INPUT_PATTERN = os.path.join(
    BASE_DIR, "for_panel_files", "for_panel", f"{yesterday}_cleaned.csv"
)

OUTPUT_DIR = os.path.join(BASE_DIR, "statement_file", "qualifier_output")

TOTAL_LIMIT = 50400       # 14 hours
RULE_B_LIMIT = 5400       # 1.5 hours
MAX_SESSION = 21600       # 6 hours

# Rule B Window (seconds)
RULE_B_START_SEC = 7200
RULE_B_END_SEC   = 17999

os.makedirs(OUTPUT_DIR, exist_ok=True)

# ============================================================
# LOAD ENV + DB
# ============================================================

load_dotenv(os.path.join(BASE_DIR, ".env"))

db_config = {
    'host': os.getenv("DB_HOST"),
    'port': int(os.getenv("DB_PORT", 5432)),
    'dbname': os.getenv("DB_NAME"),
    'user': os.getenv("DB_USER"),
    'password': os.getenv("DB_PASSWORD")
}

engine_url = f"postgresql://{db_config['user']}:{db_config['password']}@" \
             f"{db_config['host']}:{db_config['port']}/{db_config['dbname']}"

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

region_map = region_df[['hhid', 'region']].drop_duplicates()

print("Region mapping loaded:", len(region_map))

# ============================================================
# HELPER FUNCTIONS
# ============================================================

def hms_to_sec(t):
    try:
        h, m, s = map(int, str(t).split(":"))
        return h * 3600 + m * 60 + s
    except:
        return None

def sec_to_hms(sec):
    sec = int(sec) % 86400
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:02d}"

def duration_to_text(sec):
    return str(timedelta(seconds=int(sec)))

# ============================================================
# LOAD FILES
# ============================================================

files = glob.glob(INPUT_PATTERN)

if not files:
    raise FileNotFoundError(f"No CSV files found: {INPUT_PATTERN}")

# ============================================================
# PROCESS FILES
# ============================================================

for file_path in files:

    print("\n================================================")
    print("Processing:", os.path.basename(file_path))
    print("================================================")

    df = pd.read_csv(file_path)
    original_rows = len(df)

    # ========================================================
    # ADD REGION
    # ========================================================
    df = df.merge(region_map, on="hhid", how="left")
    df["region"] = df["region"].fillna("Unknown")

    # ========================================================
    # CLEAN DATE
    # ========================================================
    df["date"] = (
        df["date"]
        .astype(str)
        .str.strip()
        .str.replace("/", "-", regex=False)
    )

    # ========================================================
    # CREATE SECONDS
    # ========================================================
    df["start_sec"] = df["start_time"].apply(hms_to_sec)
    df["end_sec"]   = df["end_time"].apply(hms_to_sec)

    df = df.dropna(subset=["start_sec", "end_sec"])

    # Broadcast day adjustment (02:00 → next day 01:59)
    df.loc[df["start_sec"] < 7200, "start_sec"] += 86400
    df.loc[df["end_sec"]   < 7200, "end_sec"]   += 86400

    # Fix midnight crossing
    df.loc[df["end_sec"] < df["start_sec"], "end_sec"] += 86400

    # ========================================================
    # DURATION
    # ========================================================
    df["duration_seconds"] = df["end_sec"] - df["start_sec"]
    df = df[df["duration_seconds"] > 0]

    # ========================================================
    # BROADCAST DATE
    # ========================================================
    real_date = pd.to_datetime(df["date"], errors="coerce")

    df["broadcast_date"] = real_date

    mask = df["start_sec"] >= 86400
    df.loc[mask, "broadcast_date"] = (
        df.loc[mask, "broadcast_date"] - pd.Timedelta(days=1)
    )

    df["date"] = df["broadcast_date"].dt.strftime("%Y-%m-%d")

    # ========================================================
    # CREATE Indi
    # ========================================================
    df["Indi"] = df["hhid"].astype(str) + df["member_id"].astype(str)

    # ========================================================
    # SORT
    # ========================================================
    df = df.sort_values(
        ["Indi", "date", "start_sec"],
        kind="mergesort"
    ).reset_index(drop=True)

    # ========================================================
    # MERGE CONTINUOUS SESSIONS
    # ========================================================
    merged_rows = []

    for indi, g in df.groupby("Indi", sort=False):

        g = g.sort_values("start_sec").reset_index(drop=True)
        current = g.iloc[0].copy()

        for i in range(1, len(g)):
            nxt = g.iloc[i]

            if (
                current["channelid"] == nxt["channelid"] and
                current["end_sec"] == nxt["start_sec"]
            ):
                current["end_sec"] = nxt["end_sec"]
                current["end_time"] = nxt["end_time"]

                dur = current["end_sec"] - current["start_sec"]
                current["duration_seconds"] = dur
                current["duration"] = duration_to_text(dur)

            else:
                merged_rows.append(current)
                current = nxt.copy()

        merged_rows.append(current)

    df = pd.DataFrame(merged_rows)

    # ========================================================
    # RULE C (MAX SESSION)
    # ========================================================
    long_sessions = df["duration_seconds"] > MAX_SESSION
    if long_sessions.any():
        print(f"Removing {long_sessions.sum()} sessions > 6 hours")

    df = df[~long_sessions]

    # ========================================================
    # APPLY RULE A + RULE B
    # ========================================================
    output_rows = []

    for indi, g in df.groupby("Indi", sort=False):

        g = g.sort_values("start_sec").reset_index(drop=True)

        total_used = 0
        cutoff = False

        for _, row in g.iterrows():

            if cutoff:
                break

            dur = row["duration_seconds"]
            row_copy = row.copy()

            # RULE B
            check_start = row["start_sec"] % 86400
            if (
                RULE_B_START_SEC <= check_start <= RULE_B_END_SEC
                and dur > RULE_B_LIMIT
            ):
                continue

            # RULE A
            if total_used + dur > TOTAL_LIMIT:

                allowed = TOTAL_LIMIT - total_used

                if allowed > 0:
                    row_copy["duration_seconds"] = allowed

                    new_end_sec = row["start_sec"] + allowed
                    row_copy["end_sec"] = new_end_sec
                    row_copy["end_time"] = sec_to_hms(new_end_sec)
                    row_copy["duration"] = duration_to_text(allowed)

                    output_rows.append(row_copy)

                cutoff = True
                break

            total_used += dur
            output_rows.append(row_copy)

    # ========================================================
    # FINAL OUTPUT
    # ========================================================
    final_df = pd.DataFrame(output_rows)

    final_df = final_df.drop(
        columns=["start_sec", "end_sec", "broadcast_date"],
        errors="ignore"
    )

    if not final_df.empty:
        date_str = str(final_df["date"].iloc[0])
    else:
        date_str = yesterday

    out_file = os.path.join(
        OUTPUT_DIR,
        f"{date_str}_ruled.csv"
    )

    final_df.to_csv(out_file, index=False)

    print(f"Processed: {os.path.basename(file_path)}")
    print(f"Original rows: {original_rows}")
    print(f"Final rows: {len(final_df)}")
    print(f"Output: {os.path.basename(out_file)}")

print("\n================================================")
print("BATCH PROCESS COMPLETED SUCCESSFULLY")
print("================================================")