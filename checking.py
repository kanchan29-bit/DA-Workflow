import pandas as pd
import hashlib
import os

# ===================================
# FILE PATH
# ===================================
FILE = r"C:\current-da-workflow-20260630T092527Z-3-001\current-da-workflow\sessions\fp\output\merged_timeline.csv"

# ===================================
# READ
# ===================================
df = pd.read_csv(FILE)

print("=" * 60)
print("SESSION INPUT CHECK - VS CODE")
print("=" * 60)

print("Rows                :", len(df))
print("Columns             :", len(df.columns))
print("Unique HHIDs        :", df["hhid"].nunique())
print("Unique Device IDs   :", df["device_id"].nunique())
print("Unique Channels     :", df["chname"].nunique())
print("Timestamp Min       :", df["timestamp"].min())
print("Timestamp Max       :", df["timestamp"].max())

# ===================================
# DETERMINISTIC SORT
# ===================================
df = df.sort_values(
    by=[
        "hhid",
        "timestamp",
        "start_time",
        "chid",
        "device_id",
        "details"
    ],
    kind="mergesort"
).reset_index(drop=True)

# ===================================
# FINGERPRINT
# ===================================
fingerprint = hashlib.md5(
    pd.util.hash_pandas_object(df, index=False).values.tobytes()
).hexdigest()

print("\nFingerprint :", fingerprint)

print("=" * 60)