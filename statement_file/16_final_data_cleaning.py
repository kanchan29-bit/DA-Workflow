import pandas as pd
import os
from datetime import datetime, timedelta

# ===============================
# FILE PATHS
# ===============================
# Get project root directory
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))

yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
INPUT_FILE = os.path.join(BASE_DIR, "statement_file", "qualifier_output", f"{yesterday}_ruled_PROCESSED.csv")
OUTPUT_FOLDER = os.path.join(BASE_DIR, "statement_file", "statement")
OUTPUT_FILE_NAME = f"{yesterday}_statement.csv"

os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# ===============================
# CHANNEL MAPPING
# ===============================
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

# ===============================
# FUNCTION: TIME → SECONDS
# ===============================
def convert_time_to_seconds(time_str):
    h, m, s = map(int, time_str.split(":"))
    seconds = h * 3600 + m * 60 + s

    # If hour is 00 or 01 → next day continuation
    if h in [0, 1]:
        seconds += 86400

    return seconds

# ===============================
# READ FILE
# ===============================
df = pd.read_csv(INPUT_FILE)

# ===============================
# START TIME → SECONDS
# ===============================
if "start_time_secs" in df.columns:
    df = df.drop(columns=["start_time_secs"])

df["start_time_secs"] = df["start_time"].apply(convert_time_to_seconds)

print("Start time converted to seconds.")

# ===============================
# CLEAN + MAP CHANNEL
# ===============================
df["channel"] = df["channel"].astype(str).str.strip()

df["channelid"] = df["channel"].map(CHANNEL_MAP)

# Fill unknown as 99
df["channelid"] = df["channelid"].fillna(99).astype(int)

print("Channel mapping completed.")

# ===============================
# REMOVE UNWANTED CHANNELIDS
# ===============================
initial_rows = len(df)

df = df[~df["channelid"].isin([10, 13, 14,15, 99])]

print(f"Rows removed: {initial_rows - len(df)}")

# ===============================
# REMOVE SHORT SESSIONS (ZERO SECONDS)
# ===============================
if "duration_seconds" in df.columns:
    before_filter = len(df)
    df = df[df["duration_seconds"] != 0]
    print(f"Rows removed (duration != 0 sec): {before_filter - len(df)}")
# else:
#     print("Warning: 'duration_secs' column not found!")


# ===============================
# DATE FORMAT CONVERSION
# ===============================
df["date"] = pd.to_datetime(df["date"], errors="coerce")
df["date"] = df["date"].dt.strftime("%-m/%-d/%Y")

print("Date format conversion complete.")

# ===============================
# SAVE OUTPUT
# ===============================
output_path = os.path.join(OUTPUT_FOLDER, OUTPUT_FILE_NAME)
df.to_csv(output_path, index=False)

print("Final file saved at:", output_path)