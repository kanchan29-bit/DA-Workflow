import pandas as pd
from datetime import datetime, timedelta

import os

# ===============================
# CONFIG
# ===============================
yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))

file1_csv = os.path.join(BASE_DIR, "sessions", "merging", "sessions_with_rejuvenation", f"{yesterday}Members_Updatedlogo.csv")
file2_csv = os.path.join(BASE_DIR, "sessions", "merging", "sessions_with_rejuvenation", f"{yesterday}Members_UpdatedFP.csv")

output_csv = os.path.join(BASE_DIR, "sessions", "merging", "Final_merged_file", f"{yesterday}_Sessions.csv")

# Ensure output directory exists
os.makedirs(os.path.dirname(output_csv), exist_ok=True)

HHID_COL = "hhid"         # change if your column name is different

# ===============================
# READ FILES
# ===============================
df1 = pd.read_csv(file1_csv)
df2 = pd.read_csv(file2_csv)

# ===============================
# REMOVE DUPLICATE HHIDs FROM FILE 2
# ===============================
df2_filtered = df2[~df2[HHID_COL].isin(df1[HHID_COL])]

# ===============================
# MERGE FILES
# ===============================
merged_df = pd.concat([df1, df2_filtered], ignore_index=True)

# ===============================
# FILL TYPE COLUMN (NEW LOGIC)
# ===============================
if "type" in merged_df.columns:
    merged_df["type"] = (
        merged_df["type"]
        .replace("", pd.NA)
        .fillna(29)
        .astype(int)
    )
else:
    print("⚠️ 'type' column not found in merged data")

# ===============================
# SAVE OUTPUT
# ===============================
merged_df.to_csv(output_csv, index=False)

print(f"Merge complete. Output saved to: {output_csv}")
print(f"Rows in file1        : {len(df1)}")
print(f"Rows kept from file2 : {len(df2_filtered)}")
print(f"Total rows merged    : {len(merged_df)}")


