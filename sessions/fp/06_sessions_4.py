import pandas as pd

import os

# ===============================
# CONFIG
# ===============================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_CSV = os.path.join(SCRIPT_DIR, "output", "merged_timeline.csv")
OUTPUT_CSV = os.path.join(SCRIPT_DIR, "output", "sessions_output.csv")

SESSION_GAP_SEC = 300   # 5 minutes
SINGLE_EVENT_PADDING = 10
SINGLE_EVENT_NEXT_LIMIT = 20

# ===============================
# HELPER FUNCTIONS
# ===============================
def hhmmss_to_seconds(t):
    h, m, s = map(int, t.split(":"))
    sec = h * 3600 + m * 60 + s
    if sec < 2*3600:  # Before 02:00:00
        sec += 24*3600
    return sec




def seconds_to_hhmmss(sec):
    sec = int(sec) % (24*3600)
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


# ===============================
# READ DATA
# ===============================
df = pd.read_csv(INPUT_CSV)

# Keep only channel recognition events
df = df[df["type"] == 42].copy()

# Sort correctly
df = df.sort_values(["hhid", "timestamp"]).reset_index(drop=True)

# Convert start_time to seconds
df["start_secs"] = df["start_time"].apply(hhmmss_to_seconds)

# ===============================
# SESSION IDENTIFICATION
# ===============================
df["prev_timestamp"] = df.groupby("hhid")["timestamp"].shift(1)
df["prev_chname"] = df.groupby("hhid")["chname"].shift(1)

df["time_diff"] = df["timestamp"] - df["prev_timestamp"]

df["new_session"] = (
    (df["chname"] != df["prev_chname"]) |
    (df["time_diff"] > SESSION_GAP_SEC) |
    (df["prev_timestamp"].isna())
)

df["session_id"] = df.groupby("hhid")["new_session"].cumsum()

# ===============================
# BUILD SESSIONS
# ===============================
sessions = []

for (hhid, session_id), grp in df.groupby(["hhid", "session_id"]):
    grp = grp.sort_values("timestamp")

    first = grp.iloc[0]
    last = grp.iloc[-1]

    start_secs = first["start_secs"]
    start_time = first["start_time"]
    s3_date = first["s3_date"]

    # Determine end_time
    if len(grp) == 1:
        next_idx = first.name + 1
        if next_idx in df.index:
            next_event = df.loc[next_idx]
            if next_event["timestamp"] - first["timestamp"] <= SINGLE_EVENT_NEXT_LIMIT:
                end_secs = next_event["start_secs"]
            else:
                end_secs = start_secs + SINGLE_EVENT_PADDING
        else:
            end_secs = start_secs + SINGLE_EVENT_PADDING
    else:
        next_session = df[
            (df["hhid"] == hhid) &
            (df["session_id"] == session_id + 1)
        ]

        if not next_session.empty:
            gap = next_session.iloc[0]["timestamp"] - last["timestamp"]
            if gap <= SESSION_GAP_SEC:
                end_secs = next_session.iloc[0]["start_secs"]
            else:
                end_secs = last["start_secs"]
        else:
            end_secs = last["start_secs"]

    end_time = seconds_to_hhmmss(end_secs)
    duration = end_secs - start_secs

    sessions.append({
        "hhid": hhid,
        "s3_date": s3_date,
        "chid": first["chid"],
        "chname": first["chname"],
        "start_time": start_time,
        "end_time": end_time,
        "duration": duration,
        "member_id": "",
        "start_secs": start_secs,
        "type": 42
    })

# ===============================
# OUTPUT
# ===============================
sessions_df = pd.DataFrame(sessions)
sessions_df.to_csv(OUTPUT_CSV, index=False)

print(f"Sessionization complete. Output written to {OUTPUT_CSV}")
