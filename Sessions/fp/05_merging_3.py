import pandas as pd

# ===============================
# CONFIG
# ===============================
file1_csv = r"C:\Users\kanch\Desktop\statement\Sessions\fp\output\mapping.csv"
file2_csv = r"C:\Users\kanch\Desktop\statement\Sessions\fp\New folder\filtered.csv"
output_csv = r"C:\Users\kanch\Desktop\statement\Sessions\fp\output\merged_timeline.csv"

# ===============================
# READ FILES
# ===============================
df1 = pd.read_csv(file1_csv)
df2 = pd.read_csv(file2_csv)

# ===============================
# CLEAN FILE 1
# ===============================
df1 = df1.drop(columns=[c for c in ["id", "createdAt"] if c in df1.columns])

# ===============================
# ADD SOURCE PRIORITY
# File 1 must come first if timestamps match
# ===============================
df1["_source_priority"] = 0
df2["_source_priority"] = 1

# ===============================
# ALIGN SCHEMAS (UNION)
# ===============================
all_columns = sorted(set(df1.columns).union(set(df2.columns)))

df1 = df1.reindex(columns=all_columns)
df2 = df2.reindex(columns=all_columns)

# ===============================
# COMBINE
# ===============================
df = pd.concat([df1, df2], ignore_index=True)

# ===============================
# TYPE SAFETY
# ===============================
df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")

# ===============================
# SORT TIMELINE
# ===============================
df = df.sort_values(
    by=["device_id", "timestamp", "_source_priority"],
    ascending=[True, True, True]
)

# ===============================
# CONTEXT FILL (PER DEVICE)
# ===============================
context_columns = ["chid", "chname", "s3_date", "hhid"]

df[context_columns] = (
    df.groupby("device_id")[context_columns]
      .ffill()
      .bfill()
)

# ===============================
# ADD start_time COLUMN
# ===============================
# Convert timestamp (assumed to be in seconds) to datetime with UTC+4
df["start_time"] = pd.to_datetime(df["timestamp"], unit='s', utc=True) \
                     .dt.tz_convert("Etc/GMT-4") \
                     .dt.strftime("%H:%M:%S")

# ===============================
# CLEAN UP
# ===============================
df = df.drop(columns=["_source_priority"])

# ===============================
# WRITE OUTPUT
# ===============================
df.to_csv(output_csv, index=False)

print("✅ Merge completed successfully")
print(f"📁 Output file: {output_csv}")
print(f"🧾 Final columns: {list(df.columns)}")
print(f"📊 Total rows: {len(df)}")
