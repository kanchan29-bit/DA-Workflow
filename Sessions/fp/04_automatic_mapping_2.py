import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
import pytz

# -------------------------------
# DB CONFIG
# -------------------------------
db_config = {
    'host': 'armenia-db-01.c960kiumy09x.ap-south-1.rds.amazonaws.com',
    'port': 5432,
    'dbname': 'meter01',
    'user': 'postgres',
    'password': 'inditronics123'
}

# -------------------------------
# AUTO DATE (D-1)
# -------------------------------
yesterday = datetime.now() - timedelta(days=1)
start_date_str = yesterday.strftime("%Y-%m-%d")
end_date_str = yesterday.strftime("%Y-%m-%d")

print(f"Auto Date Selected (D-1): {start_date_str}")

import os

# -------------------------------
# HARD CODED FILE PATHS
# -------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
device_csv_path = os.path.join(SCRIPT_DIR, "input_data", "filtered.csv")
output_csv_path = os.path.join(SCRIPT_DIR, "output", "mapping.csv")

# Ensure output directory exists
os.makedirs(os.path.dirname(output_csv_path), exist_ok=True)

# -------------------------------
# LOAD DEVICE IDs FROM CSV
# -------------------------------
device_df = pd.read_csv(device_csv_path)

if 'device_id' not in device_df.columns:
    raise ValueError("CSV must contain a 'device_id' column")

device_list = device_df['device_id'].astype(str).unique().tolist()

print(f"Loaded {len(device_list)} unique device_ids from CSV")

# -------------------------------
# CONVERT LOCAL TIME TO UTC TIMESTAMP
# -------------------------------
tz_erevan = pytz.timezone('Asia/Yerevan')

start_dt_local = tz_erevan.localize(
    datetime.strptime(f"{start_date_str} 02:00:00", "%Y-%m-%d %H:%M:%S")
)

end_dt_local = tz_erevan.localize(
    datetime.strptime(f"{end_date_str} 01:59:59", "%Y-%m-%d %H:%M:%S") + timedelta(days=1)
)

start_ts = int(start_dt_local.astimezone(pytz.UTC).timestamp())
end_ts = int(end_dt_local.astimezone(pytz.UTC).timestamp())

print(f"UTC Timestamp Range: {start_ts} to {end_ts}")

# -------------------------------
# SQL QUERY
# -------------------------------
device_ids_str = ",".join([f"'{d}'" for d in device_list])

query = f"""
SELECT *
FROM events
WHERE type IN ('42','23','3','4')
  AND timestamp BETWEEN {start_ts} AND {end_ts}
  AND device_id IN ({device_ids_str})
ORDER BY device_id ASC, timestamp ASC;
"""

# -------------------------------
# QUERY DATABASE
# -------------------------------
print("Connecting to database...")
conn = psycopg2.connect(**db_config)

try:
    df = pd.read_sql_query(query, conn)
finally:
    conn.close()

print(f"Retrieved {len(df)} rows from DB.")

# -------------------------------
# FINAL FILTER CHECK
# -------------------------------
df = df[df['device_id'].isin(device_list)]
print(f"Rows after device_id filtering: {len(df)}")

# -------------------------------
# SAVE TO CSV
# -------------------------------
df.to_csv(output_csv_path, index=False)
print(f"Saved output to: {output_csv_path}")