import pandas as pd
import ast
from datetime import datetime, timedelta

import os

# ===============================
# CONFIG
# ===============================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CHANNEL_CSV = os.path.join(SCRIPT_DIR, "output", "sessions_output.csv")     # channel-level sessions (already sessionized)
MEMBER_CSV  = os.path.join(SCRIPT_DIR, "output", "merged_timeline.csv")     # type=3 member declarations
OUTPUT_CSV  = os.path.join(SCRIPT_DIR, "output", "final_channel_member_sessions.csv")

# ===============================
# TIME HELPERS
# ===============================
def to_dt(t):
    return datetime.strptime(t, "%H:%M:%S")

def to_str(dt):
    return dt.strftime("%H:%M:%S")

def seconds_to_hms(sec):
    return str(timedelta(seconds=int(sec)))

# ===============================
# PARSE MEMBER DECLARATIONS
# ===============================
def parse_members(details):
    try:
        data = ast.literal_eval(details)
        return data.get("members", [])
    except:
        return []

# ===============================
# READ FILES
# ===============================
channel_df = pd.read_csv(CHANNEL_CSV)
member_df  = pd.read_csv(MEMBER_CSV)

# Normalize time
member_df["decl_dt"] = member_df["start_time"].apply(to_dt)

# ===============================
# BUILD MEMBER SESSIONS
# ===============================
member_sessions = []

# group strictly by household
for hhid, hh_df in member_df.sort_values("decl_dt").groupby("hhid"):

    # track active state per member inside this household
    state = {}  # member_id -> session_start_dt

    for _, row in hh_df.iterrows():
        decl_time = row["decl_dt"]
        members = parse_members(row["details"])

        for m in members:
            mid = m.get("member_id")

            # skip invalid / guest / malformed entries
            if not mid:
                continue

            active = m.get("active", False)


            # ACTIVE → start if not already active
            if active:
                if mid not in state:
                    state[mid] = decl_time

            # INACTIVE → close if currently active
            else:
                if mid in state:
                    member_sessions.append({
                        "hhid": hhid,
                        "member_id": mid,
                        "start_dt": state[mid],
                        "end_dt": decl_time
                    })
                    del state[mid]

    # open-ended sessions (no inactive later)
    for mid, start_dt in state.items():
        member_sessions.append({
            "hhid": hhid,
            "member_id": mid,
            "start_dt": start_dt,
            "end_dt": None
        })

member_sess_df = pd.DataFrame(member_sessions)

# ===============================
# OVERLAY MEMBER SESSIONS ON CHANNEL SESSIONS
# ===============================
final_rows = []

for _, ch in channel_df.iterrows():

    ch_start = to_dt(ch["start_time"])
    ch_end   = to_dt(ch["end_time"])
    hhid     = ch["hhid"]

    matched = False

    relevant_members = member_sess_df[
        (member_sess_df["hhid"] == hhid)
    ]

    for _, ms in relevant_members.iterrows():

        ms_start = ms["start_dt"]
        ms_end   = ms["end_dt"] or ch_end

        overlap_start = max(ch_start, ms_start)
        overlap_end   = min(ch_end, ms_end)

        if overlap_start < overlap_end:
            matched = True
            row = ch.copy()
            row["member_id"] = ms["member_id"]
            row["start_time"] = to_str(overlap_start)
            row["end_time"]   = to_str(overlap_end)

            dur_sec = int((overlap_end - overlap_start).total_seconds())
            row["duration_seconds"] = dur_sec
            row["duration"] = seconds_to_hms(dur_sec)

            final_rows.append(row)

    # no active members → keep channel session as-is
    if not matched:
        row = ch.copy()
        row["member_id"] = ""
        dur_sec = int((ch_end - ch_start).total_seconds())
        row["duration_seconds"] = dur_sec
        row["duration"] = seconds_to_hms(dur_sec)
        final_rows.append(row)

# ===============================
# OUTPUT
# ===============================
final_df = pd.DataFrame(final_rows)

# ensure original column order + appended fields
base_cols = list(channel_df.columns)
extra_cols = [c for c in final_df.columns if c not in base_cols]
final_df = final_df[base_cols + extra_cols]

final_df.to_csv(OUTPUT_CSV, index=False)

print(f"✅ Final channel-member sessions written to {OUTPUT_CSV}")
