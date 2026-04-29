import pandas as pd
from datetime import datetime, timedelta

# =========================
# FILE PATHS
# =========================
yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
input_file = rf"C:\Users\kanch\Desktop\statement\Sessions\merging\sessions_without_rejuvenation\{yesterday}_Sessions.csv"
main_file = r'C:\Users\kanch\Desktop\statement\Sessions\merging\main_reference.xlsx'
output_file = r'C:\Users\kanch\Desktop\statement\Sessions\merging\main_reference.xlsx'

# =========================
# LOAD FILES
# =========================
df_input = pd.read_csv(input_file)
df_main = pd.read_excel(main_file)

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

# AFTER all operations → convert to clean string
df_input['date'] = df_input['date'].dt.strftime('%Y-%m-%d')

# =========================
# ALIGN INPUT TO MAIN STRUCTURE
# =========================

# Add missing columns in input (based on main file)
for col in df_main.columns:
    if col not in df_input.columns:
        df_input[col] = None

# Ensure same column order as main file
df_input = df_input[df_main.columns]

# =========================
# APPEND DATA (NO HEADER ISSUE)
# =========================
df_updated = pd.concat([df_main, df_input], ignore_index=True)


# =========================
# SAVE OUTPUT
# =========================
df_updated.to_excel(output_file, index=False)

print("✅ Data appended successfully (no header duplication)")
print(f"Final rows: {len(df_updated)}")