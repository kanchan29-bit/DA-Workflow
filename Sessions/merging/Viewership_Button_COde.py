# ============================================================
# TV Household Member Backfill Engine (EXCEL VERSION)
# MULTI-FILE VERSION
# ============================================================

import pandas as pd
import os
import re
from datetime import datetime, timedelta

# ============================================================
# INPUT RAW FILES (ADD AS MANY AS YOU WANT)
# ============================================================
yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
RAW_FILES = [
    rf"C:\Users\kanch\Desktop\statement\Sessions\logo\household_viewership_memberwise_output\{yesterday}_logo_sessions.csv",
    rf"C:\Users\kanch\Desktop\statement\Sessions\fp\output\{yesterday}_fp_sessions.csv"
]

# ============================================================
# EXCEL REFERENCE
# ============================================================

REF_FILE = r"C:\Users\kanch\Desktop\statement\Sessions\merging\main_reference.xlsx"
REF_SHEET = "Sheet1"

# ============================================================
# OUTPUT BASE PATH
# ============================================================

BASE_OUTPUT = r"C:\Users\kanch\Desktop\statement\Sessions\merging\sessions_with_rejuvenation"

# ============================================================
# USER INPUT
# ============================================================

print("Select Reference Pool:")
print("1 = Weekday")
print("2 = Weekend")

choice = input("Enter 1 or 2: ").strip()
day_filter = "Weekday" if choice == "1" else "Weekend"

print("\nSelect Type:")
print("29 = LOGO")
print("42 = FP")

type_filter = input("Enter 29 or 42: ").strip()

if type_filter == "29":
    TYPE_FOLDER = "Logo"
    TYPE_TAG = "logo"
elif type_filter == "42":
    TYPE_FOLDER = "FP"
    TYPE_TAG = "FP"
else:
    raise ValueError("Invalid type")

# ============================================================
# TIME FUNCTIONS
# ============================================================

def sec(t):
    if t == "" or pd.isna(t):
        return None
    h, m, s = map(int, str(t).split(":"))
    return h*3600 + m*60 + s

def day_night(s, e):
    if s is None or e is None:
        return 0, 0
    if e < s:
        e += 86400
    day = night = 0
    for t in range(int(s), int(e)):
        hr = (t // 3600) % 24
        if 6 <= hr < 18:
            day += 1
        else:
            night += 1
    return day, night

# ============================================================
# DATE EXTRACTION
# ============================================================

def extract_date(filepath):
    filename = os.path.basename(filepath)

    patterns = [
        r"(\d{4}-\d{2}-\d{2})",
        r"(\d{2}-\d{2}-\d{4})",
        r"(\d{4}\d{2}\d{2})",
        r"(\d{2}_\d{2}_\d{4})",
        r"(\d{2}\d{2}\d{4})"
    ]

    for pattern in patterns:
        match = re.search(pattern, filename)
        if match:
            raw_date = match.group(1)

            for fmt in [
                "%Y-%m-%d",
                "%d-%m-%Y",
                "%Y%m%d",
                "%d_%m_%Y",
                "%d%m%Y"
            ]:
                try:
                    dt = datetime.strptime(raw_date, fmt)
                    return dt.strftime("%d-%m-%Y")
                except:
                    continue

    return None

# ============================================================
# LOAD EXCEL REFERENCE (ONCE, OUTSIDE THE LOOP)
# ============================================================

ref_master = pd.read_excel(
    REF_FILE,
    sheet_name=REF_SHEET,
    usecols=[
        "hhid",
        "member_id",
        "start_time",
        "end_time",
        "date",
        "Day",
        "type"
    ]
).fillna("")

# STRONG NORMALIZATION
ref_master["hhid"] = ref_master["hhid"].astype(str).str.strip().str.lstrip("0")
ref_master["member_id"] = ref_master["member_id"].astype(str).str.strip()
ref_master["type"] = ref_master["type"].astype(str).str.strip().str.replace(".0", "", regex=False)
ref_master["Day"] = ref_master["Day"].astype(str).str.strip().str.lower()

day_filter = day_filter.lower()

# FIX DATE
ref_master["date"] = pd.to_datetime(ref_master["date"], errors="coerce")
ref_master["date"] = ref_master["date"].dt.strftime("%Y-%m-%d")

# FILTER
ref_master = ref_master[
    (ref_master["Day"] == day_filter) &
    (ref_master["type"] == type_filter)
]

ref_master = ref_master[ref_master["member_id"] != ""]

# TIME CONVERSION
ref_master["s"] = ref_master["start_time"].apply(sec)
ref_master["e"] = ref_master["end_time"].apply(sec)

# GROUP BY DATE
refs = {
    date: df
    for date, df in ref_master.groupby("date")
}

# ============================================================
# PROCESS EACH FILE SEPARATELY
# ============================================================

for RAW_FILE in RAW_FILES:

    print(f"\n{'='*60}")
    print(f"Processing: {os.path.basename(RAW_FILE)}")
    print(f"{'='*60}")

    # --------------------------------------------------------
    # LOAD RAW
    # --------------------------------------------------------

    raw = pd.read_csv(RAW_FILE, dtype=str).fillna("")

    raw["hhid"] = raw["hhid"].astype(str).str.strip().str.lstrip("0")
    raw["s"] = raw["start_time"].apply(sec)
    raw["e"] = raw["end_time"].apply(sec)

    # --------------------------------------------------------
    # FIND BLANK HHIDs
    # --------------------------------------------------------

    blank_hhids = (
        raw.groupby("hhid")["member_id"]
           .apply(lambda x: (x == "").all())
    )
    blank_hhids = set(blank_hhids[blank_hhids].index)

    # --------------------------------------------------------
    # RAW PROFILE
    # --------------------------------------------------------

    raw_profile = {}

    for hhid, g in raw[raw["hhid"].isin(blank_hhids)].groupby("hhid"):
        d = n = 0
        for _, r in g.iterrows():
            dd, nn = day_night(r["s"], r["e"])
            d += dd
            n += nn
        raw_profile[hhid] = (d, n)

    # --------------------------------------------------------
    # MATCHING
    # --------------------------------------------------------

    hhid_members = {}
    audit = []

    for hhid in blank_hhids:

        best_score = 0
        best_date = None
        best_members = None

        for date, df in refs.items():

            pool = df[df["hhid"] == hhid]
            if pool.empty:
                continue

            d = n = 0
            for _, r in pool.iterrows():
                dd, nn = day_night(r["s"], r["e"])
                d += dd
                n += nn

            score = min(d, raw_profile[hhid][0]) + min(n, raw_profile[hhid][1])
            members = sorted(pool["member_id"].unique())

            if score > best_score and len(members) > 0:
                best_score = score
                best_date = date
                best_members = members

        if best_members:
            hhid_members[hhid] = best_members
            audit.append(f"{hhid} -> {best_date} -> {','.join(best_members)}")

    # --------------------------------------------------------
    # EXPANSION
    # --------------------------------------------------------

    raw["__order"] = range(len(raw))
    out = []

    for hhid, g in raw.groupby("hhid", sort=False):
        g = g.sort_values("__order")

        if hhid in hhid_members:
            for m in hhid_members[hhid]:
                for _, r in g.iterrows():
                    new = r.copy()
                    new["member_id"] = m
                    out.append(new)
        else:
            for _, r in g.iterrows():
                out.append(r)

    out_df = pd.DataFrame(out).drop(columns=["__order", "s", "e"], errors="ignore")

    # --------------------------------------------------------
    # DATE EXTRACTION & OUTPUT PATH (PER FILE)
    # --------------------------------------------------------

    formatted_date = extract_date(RAW_FILE)

    if not formatted_date:
        print("⚠️ Date not found in filename, using today's date")
        formatted_date = datetime.today().strftime("%d-%m-%Y")

    print("Using date:", formatted_date)

    final_dir = os.path.join(BASE_OUTPUT, TYPE_FOLDER, formatted_date)
    os.makedirs(final_dir, exist_ok=True)

    csv_path = os.path.join(final_dir, f"{formatted_date}_Members_Updated_{TYPE_TAG}.csv")
    txt_path = os.path.join(final_dir, f"{formatted_date}_Audit_{TYPE_TAG}.txt")

    # --------------------------------------------------------
    # SAVE
    # --------------------------------------------------------

    out_df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    with open(txt_path, "w", encoding="utf-8") as f:

        f.write("HHIDs 100% blank BEFORE:\n")
        for h in sorted(blank_hhids):
            f.write(h + "\n")
        f.write(f"Total blank BEFORE = {len(blank_hhids)}\n\n")

        f.write("HHID -> Chosen Reference -> Members\n")
        for l in audit:
            f.write(l + "\n")

        f.write("\nHHIDs FILLED:\n")
        for h in sorted(hhid_members.keys()):
            f.write(h + "\n")
        f.write(f"Total filled = {len(hhid_members)}\n\n")

        still_blank = blank_hhids - set(hhid_members.keys())

        f.write("HHIDs STILL BLANK:\n")
        for h in sorted(still_blank):
            f.write(h + "\n")
        f.write(f"Total still blank = {len(still_blank)}\n")

    # --------------------------------------------------------
    # DEBUG OUTPUT
    # --------------------------------------------------------

    print("PROCESS COMPLETED")
    print("Raw rows    :", len(raw))
    print("Output rows :", len(out_df))
    print("HHIDs filled:", len(hhid_members))
    print("CSV  :", csv_path)
    print("AUDIT:", txt_path)

print(f"\n{'='*60}")
print("ALL FILES PROCESSED")
print(f"{'='*60}")