import pandas as pd
from datetime import timedelta, datetime

import os

# ===============================
# CONFIG
# ===============================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_CSV  = os.path.join(SCRIPT_DIR, "output", "final_channel_member_sessions.csv")
yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
                
OUTPUT_CSV = os.path.join(SCRIPT_DIR, "output", f"{yesterday}_fp_sessions.csv")

# ===============================
# HELPERS
# ===============================
def to_dt(t):
    """Convert HH:MM:SS (including HH>=24) to timedelta"""
    try:
        hh, mm, ss = map(int, t.split(":"))
        return timedelta(hours=hh, minutes=mm, seconds=ss)
    except Exception as e:
        print(f"⚠️ Invalid time format: {t}")
        return None

def to_str(dt):
    """Convert timedelta back to HH:MM:SS, keeping hours >= 24"""
    total_seconds = int(dt.total_seconds())
    hh = total_seconds // 3600
    mm = (total_seconds % 3600) // 60
    ss = total_seconds % 60
    return f"{hh:02d}:{mm:02d}:{ss:02d}"

def sec_to_hms(sec):
    return str(timedelta(seconds=int(sec)))

# ===============================
# READ DATA
# ===============================
df = pd.read_csv(INPUT_CSV)

# normalize times
df["start_dt"] = df["start_time"].apply(to_dt)
df["end_dt"]   = df["end_time"].apply(to_dt)

# sort correctly using YOUR columns
df = df.sort_values(
    ["hhid", "s3_date", "member_id", "chname", "start_dt"]
).reset_index(drop=True)

# ===============================
# GROUP CONTIGUOUS SESSIONS
# ===============================
grouped_rows = []
current = None

for _, row in df.iterrows():

    key = (
        row["hhid"],
        row["s3_date"],
        row["member_id"],
        row["chname"]
    )

    if current is None:
        current = row.copy()
        continue

    prev_key = (
        current["hhid"],
        current["s3_date"],
        current["member_id"],
        current["chname"]
    )

    # merge if same member + channel and continuous
    if (
        key == prev_key and
        abs((row["start_dt"] - current["end_dt"]).total_seconds()) <= 1
    ):
        current["end_dt"] = row["end_dt"]
        current["duration_seconds"] += row["duration_seconds"]

    else:
        grouped_rows.append(current)
        current = row.copy()

# append last
if current is not None:
    grouped_rows.append(current)

# ===============================
# FINALIZE OUTPUT
# ===============================
final_df = pd.DataFrame(grouped_rows)

final_df["start_time"] = final_df["start_dt"].apply(to_str)
final_df["end_time"]   = final_df["end_dt"].apply(to_str)
final_df["duration"]   = final_df["duration_seconds"].apply(sec_to_hms)

final_df = final_df.drop(columns=["start_dt", "end_dt"])

# keep clean column order
final_df = final_df[
    [
        "hhid",
        "s3_date",
        "chid",
        "chname",
        "member_id",
        "start_time",
        "end_time",
        "duration",
        "duration_seconds",
        "start_secs",
        "type"
    ]
]

final_df.to_csv(OUTPUT_CSV, index=False)

print(f"✅ Member-grouped sessions written to {OUTPUT_CSV}")
