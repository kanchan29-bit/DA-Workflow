# ============================================================
# TV Household Member Backfill Engine (AUTO VERSION - FINAL)
# ============================================================

import pandas as pd
import os
from datetime import datetime, timedelta

# ============================================================
# PATHS
# ============================================================

# Get project root directory
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))

LOGO_INPUT_PATH = os.path.join(BASE_DIR, "sessions", "logo", "household_viewership_memberwise_output")
FP_INPUT_PATH   = os.path.join(BASE_DIR, "sessions", "fp", "output")

OUTPUT_PATH = os.path.join(BASE_DIR, "sessions", "merging", "sessions_with_rejuvenation")

REF_FILE = os.path.join(BASE_DIR, "sessions", "merging", "main_reference.xlsx")
REF_SHEET = "Sheet1"

# ============================================================
# D-1 DATE LOGIC
# ============================================================

today = datetime.today()
d1_date = today - timedelta(days=1)

date_str1 = d1_date.strftime("%Y-%m-%d")   # filename match
date_str2 = d1_date.strftime("%Y-%m-%d")   # output naming

print("Processing D-1 date:", date_str1)

# ============================================================
# DAY TYPE DETECTION
# ============================================================

def get_day_type(dt):
    return "weekday" if dt.weekday() < 5 else "weekend"

day_filter = get_day_type(d1_date)

# ============================================================
# FILE FETCH FROM FOLDER
# ============================================================

def get_file_from_folder(folder_path):
    if not os.path.exists(folder_path):
        raise ValueError(f"Folder not found: {folder_path}")

    for f in os.listdir(folder_path):
        if date_str1 in f:
            return os.path.join(folder_path, f)
    return None

# ============================================================
# TIME FUNCTIONS
# ============================================================

def sec(t):
    if t == "" or pd.isna(t):
        return None
    h, m, s = map(int, str(t).split(":"))
    return h * 3600 + m * 60 + s

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
# CORE PROCESS FUNCTION
# ============================================================

def process_file(RAW_FILE, type_filter, TYPE_TAG):

    print(f"\nProcessing {TYPE_TAG.upper()} file:", RAW_FILE)

    formatted_date = date_str2

    input_dt = datetime.strptime(formatted_date, "%Y-%m-%d")

    # 🔥 exact 30-day window
    start_dt = input_dt - pd.Timedelta(days=29)
    end_dt = input_dt

    print("Window:", start_dt.date(), "to", end_dt.date())
    print("Day Type:", day_filter)

    # ============================================================
    # LOAD RAW
    # ============================================================

    raw = pd.read_csv(RAW_FILE, dtype=str).fillna("")
    raw["hhid"] = raw["hhid"].astype(str).str.strip().str.lstrip("0")

    raw["s"] = raw["start_time"].apply(sec)
    raw["e"] = raw["end_time"].apply(sec)

    # ============================================================
    # FIND BLANK HHIDs
    # ============================================================

    blank_hhids = (
        raw.groupby("hhid")["member_id"]
           .apply(lambda x: (x == "").all())
    )

    blank_hhids = set(blank_hhids[blank_hhids].index)

    # ============================================================
    # RAW PROFILE
    # ============================================================

    raw_profile = {}

    for hhid, g in raw[raw["hhid"].isin(blank_hhids)].groupby("hhid"):
        d = n = 0
        for _, r in g.iterrows():
            dd, nn = day_night(r["s"], r["e"])
            d += dd
            n += nn
        raw_profile[hhid] = (d, n)

    # ============================================================
    # LOAD REFERENCE
    # ============================================================

    ref_master = pd.read_excel(
        REF_FILE,
        sheet_name=REF_SHEET,
        usecols=[
            "hhid","member_id","start_time",
            "end_time","date","Day","type"
        ]
    ).fillna("")

    ref_master["hhid"] = ref_master["hhid"].astype(str).str.strip().str.lstrip("0")
    ref_master["member_id"] = ref_master["member_id"].astype(str).str.strip()

    ref_master["type"] = ref_master["type"].astype(str).str.strip()
    ref_master["type"] = ref_master["type"].str.replace(".0", "", regex=False)

    ref_master["Day"] = ref_master["Day"].astype(str).str.strip().str.lower()
    ref_master["date"] = pd.to_datetime(ref_master["date"], errors="coerce")

    # ============================================================
    # FILTER
    # ============================================================

    ref_master = ref_master[
        (ref_master["Day"] == day_filter) &
        (ref_master["type"] == type_filter)
    ]

    ref_master = ref_master[
        (ref_master["date"] >= start_dt) &
        (ref_master["date"] <= end_dt)
    ]

    ref_master = ref_master[ref_master["member_id"] != ""]

    # ============================================================
    # TIME CONVERSION
    # ============================================================

    ref_master["s"] = ref_master["start_time"].apply(sec)
    ref_master["e"] = ref_master["end_time"].apply(sec)

    # ============================================================
    # GROUP BY DATE
    # ============================================================

    ref_master["date_str"] = ref_master["date"].dt.strftime("%Y-%m-%d")

    refs = {date: df for date, df in ref_master.groupby("date_str")}

    # ============================================================
    # MATCHING
    # ============================================================

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

    # ============================================================
    # EXPANSION
    # ============================================================

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

    out_df = pd.DataFrame(out).drop(columns=["__order","s","e"], errors="ignore")

    # ============================================================
    # OUTPUT
    # ============================================================

    os.makedirs(OUTPUT_PATH, exist_ok=True)

    csv_path = os.path.join(
        OUTPUT_PATH,
        f"{formatted_date}Members_Updated{TYPE_TAG}.csv"
    )

    txt_path = os.path.join(
        OUTPUT_PATH,
        f"{formatted_date}Audit{TYPE_TAG}.txt"
    )

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

    print("DONE:", TYPE_TAG.upper())
    print("Rows IN:", len(raw))
    print("Rows OUT:", len(out_df))
    print("HHIDs filled:", len(hhid_members))

# ============================================================
# MAIN EXECUTION
# ============================================================

logo_file = get_file_from_folder(LOGO_INPUT_PATH)
fp_file   = get_file_from_folder(FP_INPUT_PATH)

# LOGO FIRST
if logo_file:
    process_file(logo_file, "29", "logo")
else:
    print("❌ Logo file not found for", date_str1)

# FP NEXT
if fp_file:
    process_file(fp_file, "42", "FP")
else:
    print("❌ FP file not found for", date_str1)