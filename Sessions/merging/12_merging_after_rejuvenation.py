import pandas as pd
from datetime import datetime, timedelta

# ===============================
# CONFIG
# ===============================
yesterday = (datetime.now() - timedelta(days=1)).strftime("%d-%m-%Y")
file1_csv = rf"C:\Users\kanch\Desktop\statement\Sessions\merging\sessions_with_rejuvenation\{yesterday}Members_Updatedlogo.csv"   # primary file
file2_csv = rf"C:\Users\kanch\Desktop\statement\Sessions\merging\sessions_with_rejuvenation\{yesterday}Members_UpdatedFP.csv"   # secondary file (rows removed if hhid exists in file1)

output_csv = rf"C:\Users\kanch\Desktop\statement\Sessions\merging\Final_merged_file\{yesterday}_Sessions.csv"

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


