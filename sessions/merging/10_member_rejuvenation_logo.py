
# ============================================================
# FP MEMBER ATTRIBUTION ENGINE (AUTO D-1 VERSION)
# ============================================================

import pandas as pd
import os
from datetime import datetime, timedelta

# ============================================================
# PATH SETUP (UNCHANGED)
# ============================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))

FP_INPUT_PATH = os.path.join(BASE_DIR, "sessions", "logo", "household_viewership_memberwise_output")

PANEL_FILE = os.path.join(BASE_DIR, "sessions", "merging", "HHID_Mapping_Script.xlsx")
CVF_FILE   = os.path.join(BASE_DIR, "sessions", "merging", "cvf_table.csv")
DIST_FILE  = os.path.join(BASE_DIR, "sessions", "merging", "distribution_table_backoff_completed.csv")

OUTPUT_PATH = os.path.join(BASE_DIR, "sessions", "merging", "sessions_with_rejuvenation")

# ============================================================
# D-1 DATE (UNCHANGED)
# ============================================================

today = datetime.today()
d1_date = today - timedelta(days=1)
date_str = d1_date.strftime("%Y-%m-%d")

print("Processing D-1 date:", date_str)

# ============================================================
# FILE FETCH (UNCHANGED)
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
# OUTPUT SETUP (UNCHANGED)
# ============================================================

os.makedirs(OUTPUT_PATH, exist_ok=True)

OUTPUT_FILE = os.path.join(
    OUTPUT_PATH,
    f"{date_str}_Members_Updatedlogo.csv"
)

TXT_OUTPUT_FILE = OUTPUT_FILE.replace(".csv", ".txt")

# ============================================================
# TIME BAND FUNCTION (UNCHANGED)
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

        # =========================
        # LATE NIGHT
        # 00:00 → 05:59
        # =========================
        if current < day_start:

            band_end = min(day_start, end)
            band = "Late Night"

        # =========================
        # DAY
        # 06:00 → 17:59
        # =========================
        elif current < prime_start:

            band_end = min(prime_start, end)
            band = "Day"

        # =========================
        # PRIME
        # 18:00 → 23:59
        # =========================
        else:

            band_end = min(next_midnight, end)
            band = "Prime"

        bands.append((current, band_end, band))

        current = band_end

    return bands

# ============================================================
# LOAD DATA (UNCHANGED)
# ============================================================

df = pd.read_csv(INPUT_FILE)
panel = pd.read_excel(PANEL_FILE)
cvf = pd.read_csv(CVF_FILE)
dist = pd.read_csv(DIST_FILE)

df.columns = df.columns.str.strip().str.lower()

# ============================================================
# CLEAN LOOKUPS (FROM NEW LOGIC)
# ============================================================

cvf = cvf[['City_Group','HH_Size_Group','Time_Band','CVF']].drop_duplicates()

panel = panel.rename(columns={
    'member_code': 'member_id',
    'Family_Size_Group': 'HH_Size_Group'
})

panel = panel[['hhid','member_id','Age_Group','gender','HH_Size_Group','City_Group']]

# =========================
# CLEAN DATA (CRITICAL FIX)  INSERT HERE
# =========================

panel['Age_Group'] = panel['Age_Group'].astype(str).str.strip()
panel['gender'] = panel['gender'].astype(str).str.strip().str.capitalize()

dist = dist.rename(columns={'gende': 'gender'})

dist['Age_Group'] = dist['Age_Group'].astype(str).str.strip()
dist['gender'] = dist['gender'].astype(str).str.strip().str.capitalize()

# =========================
# TIME FIX
# =========================
df['start_time'] = pd.to_datetime(df['date'].astype(str) + ' ' + df['start_time'].astype(str))
df['end_time'] = pd.to_datetime(df['date'].astype(str) + ' ' + df['end_time'].astype(str))

df.loc[df['end_time'] < df['start_time'], 'end_time'] += pd.Timedelta(days=1)

df['duration_seconds'] = (df['end_time'] - df['start_time']).dt.total_seconds().astype(int)

# =========================
# SPLIT INTO TIME BANDS (NEW STEP)
# =========================
split_rows = []

for _, r in df.iterrows():

    start = r['start_time']
    end = r['end_time']

    splits = get_band_ranges(start, end)

    for s, e, band in splits:
        new_r = r.copy()
        new_r['start_time'] = s
        new_r['end_time'] = e
        new_r['duration_seconds'] = int((e - s).total_seconds())
        new_r['Time_Band'] = band

        split_rows.append(new_r)

df = pd.DataFrame(split_rows)

print(" After split rows:", len(df))

# =========================
# SPLIT HHIDs
# =========================
hh_missing_flag = df.groupby('hhid')['member_id'].apply(lambda x: x.isna().all())
missing_hhids = hh_missing_flag[hh_missing_flag].index

missing_df = df[df['hhid'].isin(missing_hhids)].copy()
valid_df = df[~df['hhid'].isin(missing_hhids)].copy()

print("Total HHIDs:", df['hhid'].nunique())
print("Fully Missing HHIDs:", len(missing_hhids))


# =========================
# ATTRIBUTION
# =========================
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

    # =========================
    # GET CVF
    # =========================
    cvf_row = cvf[
        (cvf['City_Group'] == city) &
        (cvf['HH_Size_Group'] == size) &
        (cvf['Time_Band'] == band)
    ]

    cvf_val = float(cvf_row.iloc[0]['CVF']) if len(cvf_row) > 0 else 1.0
    expanded_total = int(base_total * cvf_val)

    # =========================
    # GET DISTRIBUTION
    # =========================
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

    # =========================
    # BUILD MEMBER LIST
    # =========================
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

    # =========================
    # CVF FILTERING
    # =========================
    temp_df = pd.DataFrame({
        'member': member_list,
        'share': share_list,
        'new_share': new_share_list
    })
# Remove zero-weight rows
    temp_df = temp_df[temp_df['new_share'] > 0].copy()

    if len(temp_df) == 0:
        print(f"No valid distribution for HHID {hh}")
        continue

    positive_count = (temp_df['new_share'] > 0).sum()

    active_count = int(round(cvf_val))
    active_count = max(1, active_count)

    # Cannot sample more than positive-weight rows
    active_count = min(active_count, positive_count)

    print("HHID:", hh)
    print("CVF:", cvf_val)
    print("active_count:", active_count)
    print("rows available:", len(temp_df))
    print("positive weights:", positive_count)

    try:
        temp_df = temp_df.sample(
            n=active_count,
            weights='new_share',
            replace=False,
            random_state=42
        )
    except ValueError:
        print(f"Fallback used for HHID {hh}")
        temp_df = temp_df.nlargest(active_count, 'new_share')
    except Exception as e:
        print(f"Sampling error for HHID {hh}")
        print(temp_df[['new_share']])
        raise

    member_list = temp_df['member'].tolist()
    share_list = temp_df['share'].tolist()
    new_share_list = temp_df['new_share'].tolist()

    # =========================
    # ALLOCATION
    # =========================
    alloc = pd.Series(new_share_list)
    alloc = (alloc / alloc.sum()) * expanded_total
    alloc = alloc.round().astype(int).tolist()

    diff = expanded_total - sum(alloc)
    alloc[-1] += diff

    # =========================
    # SORT FOR RANKING
    # =========================
    rank_order = sorted(range(len(new_share_list)), key=lambda x: new_share_list[x], reverse=True)

    session_duration = int((end_time - start).total_seconds())

    # =========================
    # ASSIGN WINDOWS
    # =========================
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

        final_sec = min(dur, remaining_allowed)
        #  FIX 4: Ensure member duration never exceeds session
        session_duration = int((end_time - start).total_seconds())
        final_sec = min(final_sec, session_duration)
        member_time_tracker[key] = current_total + final_sec

        rank = rank_order.index(i)

        # =========================
        # SAFE PROPORTIONAL WINDOW (STRICT SESSION BOUND)
        # =========================

        if rank == 0:
            # MAIN MEMBER → full session
            member_start = start
            member_end = end_time
        else:
            member_duration = final_sec

            session_duration = int((end_time - start).total_seconds())

            # If member duration >= session → clamp to session
            if member_duration >= session_duration:
                member_start = start
                member_end = end_time
            else:
                # =========================
                # ADD SMALL SHIFT FOR SAME DEMO MEMBERS
                # =========================
                max_shift = 60  # max 60 seconds difference

                # deterministic shift using member_id
                shift_seed = hash(str(m['member_id'])) % max_shift

                # alternate left/right
                direction = -1 if (hash(str(m['member_id'])) % 2 == 0) else 1
                shift = direction * shift_seed

                center_point = start + timedelta(seconds=(session_duration / 2) + shift)

                member_start = center_point - timedelta(seconds=member_duration / 2)
                member_end = member_start + timedelta(seconds=member_duration)
                # STRICT CLAMP
                if member_start < start:
                    member_start = start
                    member_end = start + timedelta(seconds=member_duration)

                if member_end > end_time:
                    member_end = end_time
                    member_start = end_time - timedelta(seconds=member_duration)
        new_row = r.copy()

        new_row['start_time'] = member_start
        new_row['end_time'] = member_end
        #  FIX 5: VALIDATION CHECK
        if not (member_start >= start and member_end <= end_time):
            print("ERROR:",
                "HH:", hh,
                "Member:", m['member_id'],
                "Session:", start, "→", end_time,
                "Member:", member_start, "→", member_end)
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
# FINAL OUTPUT (UNCHANGED)
# ============================================================

final_missing = pd.DataFrame(output)
final = pd.concat([valid_df, final_missing], ignore_index=True)

final['duration'] = final['duration_seconds'].apply(
    lambda x: str(timedelta(seconds=int(x)))
)

final['start_time'] = final['start_time'].dt.strftime('%H:%M:%S')
final['end_time'] = final['end_time'].dt.strftime('%H:%M:%S')

final.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")

print("FINAL DONE:", final.shape)


