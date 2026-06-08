# ============================================================
# FP MEMBER ATTRIBUTION ENGINE (AUTO D-1 VERSION)
# ============================================================

import pandas as pd
import os
from datetime import datetime, timedelta

# ============================================================
# PATH SETUP (MATCH BACKFILL SCRIPT)
# ============================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))

FP_INPUT_PATH = os.path.join(BASE_DIR, "sessions", "fp", "output")

PANEL_FILE = os.path.join(BASE_DIR, "sessions", "merging", "HHID_Mapping_Script.xlsx")
CVF_FILE   = os.path.join(BASE_DIR, "sessions", "merging", "cvf_table.csv")
DIST_FILE  = os.path.join(BASE_DIR, "sessions", "merging", "distribution_table_backoff_completed.csv")

OUTPUT_PATH = os.path.join(BASE_DIR, "sessions", "merging", "sessions_with_rejuvenation")

# ============================================================
# D-1 DATE
# ============================================================

today = datetime.today()
d1_date = today - timedelta(days=1)

date_str = d1_date.strftime("%Y-%m-%d")

print("Processing D-1 date:", date_str)

# ============================================================
# FILE FETCH
# ============================================================

def get_file_from_folder(folder_path):
    if not os.path.exists(folder_path):
        raise ValueError(f"Folder not found: {folder_path}")

    for f in os.listdir(folder_path):
        if date_str in f:
            return os.path.join(folder_path, f)
    return None

INPUT_FILE = get_file_from_folder(FP_INPUT_PATH)

if not INPUT_FILE:
    raise ValueError(f"FP file not found for {date_str}")

# ============================================================
# OUTPUT SETUP
# ============================================================

os.makedirs(OUTPUT_PATH, exist_ok=True)

OUTPUT_FILE = os.path.join(
    OUTPUT_PATH,
    f"{date_str}_Members_UpdatedFP.csv"
)

TXT_OUTPUT_FILE = OUTPUT_FILE.replace(".csv", ".txt")

# ============================================================
# TIME BAND SPLIT FUNCTION
# ============================================================

def get_band_ranges(start, end):

    bands = []
    current = start

    while current < end:

        date = current.date()

        day_start = pd.Timestamp(f"{date} 06:00:00")
        prime_start = pd.Timestamp(f"{date} 18:00:00")

        next_midnight = (
            pd.Timestamp(f"{date} 23:59:59")
            + pd.Timedelta(seconds=1)
        )

        if current < day_start:
            band_end = min(day_start, end)
            band = "Late Night"

        elif current < prime_start:
            band_end = min(prime_start, end)
            band = "Day"

        else:
            band_end = min(next_midnight, end)
            band = "Prime"

        bands.append((current, band_end, band))
        current = band_end

    return bands

# ============================================================
# LOAD DATA
# ============================================================

df = pd.read_csv(INPUT_FILE)
panel = pd.read_excel(PANEL_FILE)
cvf = pd.read_csv(CVF_FILE)
dist = pd.read_csv(DIST_FILE)

df.columns = df.columns.str.strip().str.lower()

# ============================================================
# CLEAN LOOKUPS
# ============================================================

cvf = cvf[['City_Group','HH_Size_Group','Time_Band','CVF']].drop_duplicates()

panel = panel.rename(columns={
    'member_code': 'member_id',
    'Family_Size_Group': 'HH_Size_Group'
})

panel = panel[['hhid','member_id','Age_Group','gender','HH_Size_Group','City_Group']]

panel['Age_Group'] = panel['Age_Group'].astype(str).str.strip()
panel['gender'] = panel['gender'].astype(str).str.strip().str.capitalize()

dist = dist.rename(columns={'gende': 'gender'})
dist['Age_Group'] = dist['Age_Group'].astype(str).str.strip()
dist['gender'] = dist['gender'].astype(str).str.strip().str.capitalize()

# ============================================================
# TIME FIX
# ============================================================

df['start_time'] = pd.to_datetime(df['s3_date'].astype(str) + ' ' + df['start_time'].astype(str))
df['end_time'] = pd.to_datetime(df['s3_date'].astype(str) + ' ' + df['end_time'].astype(str))

df.loc[df['end_time'] < df['start_time'], 'end_time'] += pd.Timedelta(days=1)

df['duration_seconds'] = (df['end_time'] - df['start_time']).dt.total_seconds().astype(int)

# ============================================================
# SPLIT INTO TIME BANDS
# ============================================================

split_rows = []

for _, r in df.iterrows():

    splits = get_band_ranges(r['start_time'], r['end_time'])

    for s, e, band in splits:
        new_r = r.copy()
        new_r['start_time'] = s
        new_r['end_time'] = e
        new_r['duration_seconds'] = int((e - s).total_seconds())
        new_r['Time_Band'] = band

        split_rows.append(new_r)

df = pd.DataFrame(split_rows)

print("After split rows:", len(df))

# ============================================================
# IDENTIFY MISSING HHIDs
# ============================================================

hh_missing_flag = df.groupby('hhid')['member_id'].apply(lambda x: x.isna().all())
missing_hhids = hh_missing_flag[hh_missing_flag].index

missing_df = df[df['hhid'].isin(missing_hhids)].copy()
valid_df = df[~df['hhid'].isin(missing_hhids)].copy()

print("Total HHIDs:", df['hhid'].nunique())
print("Fully Missing HHIDs:", len(missing_hhids))

# ============================================================
# ATTRIBUTION
# ============================================================

output = []
member_time_tracker = {}

for _, r in missing_df.iterrows():

    start = r['start_time']
    end_time = r['end_time']
    hh = r['hhid']

    members = panel[panel['hhid'] == hh]

    if len(members) == 0:
        output.append(r)
        continue

    city = members['City_Group'].iloc[0]
    size = members['HH_Size_Group'].iloc[0]
    base_total = int(r['duration_seconds'])
    band = r['Time_Band']

    # CVF
    cvf_row = cvf[
        (cvf['City_Group'] == city) &
        (cvf['HH_Size_Group'] == size) &
        (cvf['Time_Band'] == band)
    ]

    cvf_val = float(cvf_row.iloc[0]['CVF']) if len(cvf_row) > 0 else 1.0
    expanded_total = int(base_total * cvf_val)

    # DISTRIBUTION
    d = dist[
        (dist.City_Group == city) &
        (dist.HH_Size_Group == size) &
        (dist.Time_Band == band)
    ]

    if len(d) == 0:
        fallback = r.copy()
        m = members.iloc[0]

        fallback['member_id'] = m['member_id']
        fallback['gender'] = m['gender']
        fallback['Age_Group'] = m['Age_Group']
        fallback['HH_Size_Group'] = m['HH_Size_Group']
        fallback['City_Group'] = m['City_Group']

        output.append(fallback)
        continue

    d = d.copy()
    d['New_Share'] = d['New_Share'] / d['New_Share'].sum()

    member_list = []
    share_list = []
    new_share_list = []

    for _, row_d in d.iterrows():
        seg_members = members[
            (members['Age_Group'] == row_d['Age_Group']) &
            (members['gender'] == row_d['gender'])
        ]

        for _, m in seg_members.iterrows():
            member_list.append(m)
            share_list.append(row_d.get('Share', row_d['New_Share']))
            new_share_list.append(row_d['New_Share'])

    if len(member_list) == 0:
        fallback = r.copy()
        m = members.iloc[0]

        fallback['member_id'] = m['member_id']
        fallback['gender'] = m['gender']
        fallback['Age_Group'] = m['Age_Group']
        fallback['HH_Size_Group'] = m['HH_Size_Group']
        fallback['City_Group'] = m['City_Group']

        output.append(fallback)
        continue

    temp_df = pd.DataFrame({
        'member': member_list,
        'share': share_list,
        'new_share': new_share_list
    })

    temp_df = temp_df[temp_df['new_share'] > 0].copy()

    if len(temp_df) == 0:
        continue

    positive_count = (temp_df['new_share'] > 0).sum()
    active_count = max(1, int(round(cvf_val)))
    active_count = min(active_count, positive_count)

    try:
        temp_df = temp_df.sample(
            n=active_count,
            weights='new_share',
            replace=False,
            random_state=42
        )
    except:
        temp_df = temp_df.nlargest(active_count, 'new_share')

    member_list = temp_df['member'].tolist()
    share_list = temp_df['share'].tolist()
    new_share_list = temp_df['new_share'].tolist()

    alloc = pd.Series(new_share_list)
    alloc = (alloc / alloc.sum()) * expanded_total
    alloc = alloc.round().astype(int).tolist()

    diff = expanded_total - sum(alloc)
    alloc[-1] += diff

    rank_order = sorted(range(len(new_share_list)), key=lambda x: new_share_list[x], reverse=True)
    session_duration = int((end_time - start).total_seconds())

    for i in range(len(alloc)):

        dur = alloc[i]
        if dur <= 0:
            continue

        m = member_list[i]
        key = (hh, m['member_id'])

        current_total = member_time_tracker.get(key, 0)
        remaining_allowed = 86400 - current_total

        if remaining_allowed <= 0:
            continue

        final_sec = min(dur, remaining_allowed, session_duration)
        member_time_tracker[key] = current_total + final_sec

        rank = rank_order.index(i)

        if rank == 0:
            member_start = start
            member_end = end_time
        else:
            max_shift = 60
            shift_seed = hash(str(m['member_id'])) % max_shift
            direction = -1 if (hash(str(m['member_id'])) % 2 == 0) else 1
            shift = direction * shift_seed

            center = start + timedelta(seconds=(session_duration / 2) + shift)

            member_start = center - timedelta(seconds=final_sec / 2)
            member_end = member_start + timedelta(seconds=final_sec)

            if member_start < start:
                member_start = start
                member_end = start + timedelta(seconds=final_sec)

            if member_end > end_time:
                member_end = end_time
                member_start = end_time - timedelta(seconds=final_sec)

        new_row = r.copy()

        new_row['start_time'] = member_start
        new_row['end_time'] = member_end
        actual_sec = int((member_end - member_start).total_seconds())

        new_row['duration_seconds'] = actual_sec
        new_row['duration'] = str(timedelta(seconds=actual_sec))

        new_row['member_id'] = m['member_id']
        new_row['gender'] = m['gender']
        new_row['Age_Group'] = m['Age_Group']
        new_row['HH_Size_Group'] = size
        new_row['City_Group'] = city
        new_row['Time_Band'] = band
        new_row['CVF'] = cvf_val
        new_row['Share'] = share_list[i]
        new_row['New_Share'] = new_share_list[i]

        output.append(new_row)

# ============================================================
# FINAL OUTPUT
# ============================================================

final_missing = pd.DataFrame(output)
final = pd.concat([valid_df, final_missing], ignore_index=True)

final['duration'] = final['duration_seconds'].apply(
    lambda x: str(timedelta(seconds=int(x)))
)

final['start_time'] = final['start_time'].dt.strftime('%H:%M:%S')
final['end_time'] = final['end_time'].dt.strftime('%H:%M:%S')

final.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")

# ============================================================
# AUDIT FILE
# ============================================================

with open(TXT_OUTPUT_FILE, "w", encoding="utf-8") as f:

    f.write("HHIDs 100% blank BEFORE:\n")
    for h in sorted(missing_hhids):
        f.write(str(h) + "\n")

    f.write(f"Total blank BEFORE = {len(missing_hhids)}\n\n")

    filled_hhids = set(final_missing['hhid'].unique())

    f.write("HHIDs FILLED:\n")
    for h in sorted(filled_hhids):
        f.write(str(h) + "\n")

    f.write(f"Total filled = {len(filled_hhids)}\n\n")

    final_blank_check = final.groupby('hhid')['member_id'].apply(lambda x: x.isna().all())
    still_blank = set(final_blank_check[final_blank_check].index)

    f.write("HHIDs STILL BLANK:\n")
    for h in sorted(still_blank):
        f.write(str(h) + "\n")

    f.write(f"Total still blank = {len(still_blank)}\n")

# ============================================================
# VALIDATION
# ============================================================

check = final.groupby(['hhid', 'member_id'])['duration_seconds'].sum()
violations = check[check > 86400]

if len(violations) > 0:
    print("\n HHIDs exceeding 24 hrs:\n")
    for (hhid, member_id), total_sec in violations.items():
        print(hhid, member_id, total_sec)
else:
    print("\n No HHIDs exceed 24 hrs")

print(" FINAL DONE:", final.shape)