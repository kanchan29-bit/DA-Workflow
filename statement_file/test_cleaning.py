import pandas as pd
import os

# ===============================
# FILE PATHS
# ===============================
INPUT_FILE = "/content/cleaned/01-07-2026_ruled_PROCESSED.csv"
OUTPUT_FOLDER = "output_folder"
OUTPUT_FILE_NAME = "01-07-2026_statement.csv"

os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# ===============================
# CHANNEL MAPPING
# ===============================
CHANNEL_MAP = {
    "Shant TV": 3, "ShantTV": 3,
    "MIR TV": 8, "MirTV": 8,
    "Boon Tv": 11, "BoonTV": 11,
    "Nur TV": 98, "NurTV": 98,
    "Shoghakat TV": 98,
    "1st TV channel": 2,
    "FirstNewsChannel": 1,
    "Nor Hayastan": 98, "NorHayastan": 98,
    "First News Channel": 1,
    "Public TV": 2, "PublicTV": 2,
    "Fast Sports": 98, "FastSports": 98,
    "Kentron Tv HD": 5, "KentronTVHD": 5,
    "Free News": 98, "FreeNews": 98,
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

df = df[~df["channelid"].isin([ ])]

print(f"Rows removed: {initial_rows - len(df)}")

# ===============================
# REMOVE SESSIONS LESS THAN 5 SEC
# ===============================
if "duration_seconds" in df.columns:

    before_rows = len(df)

    df = df[df["duration_seconds"].fillna(0) >= 5]

    print(
        f"Rows removed (duration_seconds < 5 sec): "
        f"{before_rows - len(df):,}"
    )

else:
    print("duration_seconds column not found. Skipping filter.")


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