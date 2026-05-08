import pandas as pd
from datetime import datetime, timedelta
import os
from openpyxl import Workbook
from openpyxl.utils.dataframe import dataframe_to_rows

# =========================
# FILE PATHS
# =========================
yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))

input_file = os.path.join(BASE_DIR, "sessions", "merging", "sessions_without_rejuvenation", f"{yesterday}_Sessions.csv")
main_file = os.path.join(BASE_DIR, "sessions", "merging", "main_reference.xlsx")
output_file = os.path.join(BASE_DIR, "sessions", "merging", "main_reference.xlsx")

# =========================
# LOAD FILES
# =========================
print(f"Reading input file: {input_file}")
df_input = pd.read_csv(input_file)

print(f"Reading main reference file: {main_file}")
if not os.path.exists(main_file):
    print(f"Warning: Main reference file not found at {main_file}. Creating a new one.")
    df_main = pd.DataFrame()
else:
    try:
        df_main = pd.read_excel(main_file)
    except Exception as e:
        print(f"Warning: Could not read {main_file} ({e}). Starting with fresh data.")
        df_main = pd.DataFrame()

# =========================
# DATE PROCESSING
# =========================
# Convert to datetime FIRST
df_input['date'] = pd.to_datetime(df_input['date'], errors='coerce')

# Now .dt works
df_input['Day_Wise'] = df_input['date'].dt.day_name()

df_input['Day'] = df_input['Day_Wise'].apply(
    lambda x: 'Weekend' if x in ['Saturday', 'Sunday'] else 'Weekday'
)

# AFTER all operations -> convert to clean string
df_input['date'] = df_input['date'].dt.strftime('%Y-%m-%d')

# =========================
# ALIGN INPUT TO MAIN STRUCTURE
# =========================

# Align columns with the main reference file if it exists
if df_main.empty:
    df_updated = df_input
else:
    # This adds missing columns as NaN and ensures the same order
    df_input = df_input.reindex(columns=df_main.columns)
    df_updated = pd.concat([df_main, df_input], ignore_index=True)

print(f"Combined data shape: {df_updated.shape}")

# =========================
# SAVE OUTPUT
# =========================
def save_excel_memory_efficient(df, path):
    """
    Saves a DataFrame to Excel using openpyxl's write_only mode to minimize memory usage.
    """
    wb = Workbook(write_only=True)
    ws = wb.create_sheet("Sheet1")
    
    # dataframe_to_rows is slower but uses significantly less memory with write_only=True
    for r in dataframe_to_rows(df, index=False, header=True):
        ws.append(r)
    
    wb.save(path)

print(f"Attempting to save to {output_file}...")
try:
    # Try memory-efficient save first
    save_excel_memory_efficient(df_updated, output_file)
    print(" Data appended successfully using memory-efficient engine.")
except MemoryError:
    print(" Error: Memory limit reached even with efficient engine.")
    csv_fallback = output_file.replace(".xlsx", "_fallback.csv")
    df_updated.to_csv(csv_fallback, index=False)
    print(f" Saved CSV fallback instead: {csv_fallback}")
except Exception as e:
    print(f" Error saving to Excel: {e}")
    csv_fallback = output_file.replace(".xlsx", "_fallback.csv")
    df_updated.to_csv(csv_fallback, index=False)
    print(f" Saved CSV fallback instead: {csv_fallback}")

print(" Data appended successfully (no header duplication)")
print(f"Final rows: {len(df_updated)}")