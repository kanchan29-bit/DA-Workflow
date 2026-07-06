# ============================================================
# STEP 1 – AUTO CITY PROCESSING (MINIMUM 5 INTAB RULE)
# ============================================================

import pandas as pd
import os
import random
from datetime import datetime
from datetime import datetime, timedelta
import psycopg2
import smtplib
from email.message import EmailMessage

# ============================================================
# DB CONFIG
# ============================================================

DB_HOST = "armenia-db-01.c960kiumy09x.ap-south-1.rds.amazonaws.com"
DB_PORT = "5432"
DB_NAME = "meter01"
DB_USER = "postgres"
DB_PASSWORD = "inditronics123"

# ============================================================
# INPUT / OUTPUT PATHS
# ============================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))

INPUT_FOLDER = os.path.join(BASE_DIR, "for_panel_files", "for_panel")
OUTPUT_FOLDER = os.path.join(BASE_DIR, "Panel", "Panel Files")


# ============================================================
# QUERY
# ============================================================


# QUERY = """
# SELECT
#     h.hhid,
#     m.member_code,
#     m.gender,
#     region,
#     DATE_PART('year', AGE(CURRENT_DATE, m.dob)) AS age
# FROM households h
# JOIN members m
#     ON h.id = m.household_id
# """

QUERY = """
 WITH latest_households AS (
    SELECT DISTINCT ON (household_id)
        household_id,
        assigned_by,
        assigned_at
    FROM (
        SELECT DISTINCT ON (ma.meter_id)
            h.hhid AS household_id,
            ma.assigned_by,
            ma.assigned_at
        FROM meter_assignments ma
        JOIN meters m
            ON ma.meter_id = m.id
        JOIN households h
            ON ma.household_id = h.id
        WHERE m.meter_id >= 'IM000101'
          AND m.meter_id <= 'IM000600'
        ORDER BY ma.meter_id, ma.assigned_at DESC
    ) latest_per_meter
    ORDER BY household_id, assigned_at DESC
)

SELECT
    h.hhid,
    m.member_code,
    m.gender,
    h.city,
    h.region,
    DATE_PART('year', AGE(CURRENT_DATE, m.dob)) AS age,
    lh.assigned_by,
    lh.assigned_at
FROM latest_households lh
JOIN households h
    ON h.hhid = lh.household_id
JOIN members m
    ON h.id = m.household_id
ORDER BY
    h.hhid,
    m.member_code;
"""
# ============================================================
# CONNECTION FUNCTION
# ============================================================

def load_master_from_db():

    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD
    )

    members_all = pd.read_sql(QUERY, conn)

    conn.close()

    members_all.columns = (
        members_all.columns
        .str.lower()
        .str.strip()
    )

    return members_all
# ============================================================
# AGE LOGIC
# ============================================================

def weighted_group(age):
    if age <= 17: return "3-17"
    elif age <= 20: return "18-20"
    elif age <= 29: return "21-29"
    elif age <= 39: return "30-39"
    elif age <= 49: return "40-49"
    elif age <= 59: return "50-59"
    else: return "60+"


def reporting_group(age):
    if age <= 17: return "3-17"
    elif age <= 20: return "18-20"
    elif age <= 29: return "21-29"
    elif age <= 39: return "30-39"
    elif age <= 49: return "40-49"
    elif age <= 59: return "50-59"
    else: return "60+"


# ============================================================
# MAIN FUNCTION
# ============================================================

def run_step1(process_date, selected_cities):

    print(f"\nRunning Step-1 for {process_date}")

    folder_date = datetime.strptime(
        process_date, "%d-%m-%Y"
    ).strftime("%Y-%m-%d")

    raw_folder = INPUT_FOLDER

    # --------------------------------------------------------
    # RAW FILE DETECTION
    # --------------------------------------------------------

    expected_file = f"{folder_date}_cleaned.csv"

    raw_file_path = os.path.join(
        INPUT_FOLDER,
        expected_file
    )

    if not os.path.exists(raw_file_path):
        raise Exception(
            f"File not found: {expected_file}"
        )

    print(f"Using raw file: {expected_file}")

    raw = pd.read_csv(raw_file_path)
    raw.columns = raw.columns.str.lower().str.strip()

    raw_unique_hhids = set(raw["hhid"].drop_duplicates())

    # --------------------------------------------------------
    # LOAD MASTER FROM DATA BASE
    # --------------------------------------------------------

    members_all = load_master_from_db()

    # --------------------------------------------------------
    # OUTPUT DIRECTORY
    # --------------------------------------------------------

    output_dir = OUTPUT_FOLDER
    os.makedirs(output_dir, exist_ok=True)

    summary_table = []

    # ========================================================
    # PROCESS EACH CITY
    # ========================================================

    YEREVAN_CITY = ["Yerevan"]

    REST_CITIES = [
        "Vanadzor",
        "Artashat",
        "Hrazdan",
        "Gavar",
        "Gyumri",
        "Ashtarak",
        "Vagharshapat",
        "Ijevan",
        "Kapan",
        "Yeghegnadzor"
    ]

    CITY_GROUPS = {
        "Yerevan": YEREVAN_CITY,
        "Rest_of_Armenia": REST_CITIES
    }

    for group_name, cities in CITY_GROUPS.items():

        region_master = members_all[
            members_all["region"].isin(cities)
        ].copy()

        region_master_hhids = set(region_master["hhid"])
        region_raw_hhids = raw_unique_hhids & region_master_hhids

        # ================= VIEWERSHIP =================

        viewership_df = raw[
            raw["hhid"].isin(region_raw_hhids)
        ]

        viewership_hh_count = len(region_raw_hhids)

        viewership_member_count = (
            viewership_df[["hhid", "member_id"]]
            .drop_duplicates()
            .shape[0]
        )

        # ================= INTAB (MINIMUM 5 RULE) =================

        intab_hhids = set()

        for city in cities:

            city_master = region_master[
                region_master["region"] == city
            ]

            city_master_hhids = set(city_master["hhid"])

            city_raw_hhids = raw_unique_hhids & city_master_hhids

            city_intab_hhids = set(city_raw_hhids)

            target_intab = min(
                max(5, len(city_raw_hhids)),
                len(city_master_hhids)
            )

            remaining_pool = list(
                city_master_hhids - city_intab_hhids
            )

            while len(city_intab_hhids) < target_intab and remaining_pool:
                extra_hhid = random.choice(remaining_pool)
                city_intab_hhids.add(extra_hhid)
                remaining_pool.remove(extra_hhid)

            intab_hhids.update(city_intab_hhids)

        raw_hh_count = len(region_raw_hhids)
        intab_hh_count = len(intab_hhids)
        intab_members_df = region_master[
            region_master["hhid"].isin(intab_hhids)
        ].copy()

        intab_member_count = (
            intab_members_df[["hhid", "member_code"]]
            .drop_duplicates()
            .shape[0]
        )

        # ================= AGE + GROUP =================

        intab_members_df["Date"] = process_date
        intab_members_df["Sex"] = intab_members_df["gender"]
        intab_members_df["Actual_age"] = intab_members_df["age"]

        intab_members_df["City_Group"] = (
            "Yerevan"
            if group_name == "Yerevan"
            else "Rest of Armenia"
        )

        intab_members_df["Weighted_Age_Group"] = (
            intab_members_df["Actual_age"]
            .apply(weighted_group)
        )

        intab_members_df["Reporting_Age_Group"] = \
            intab_members_df["Actual_age"].apply(reporting_group)

        intab_members_df["HH_City"] = intab_members_df["region"]

        final_df = intab_members_df[
            [
                "Date", "hhid", "member_code", "Sex",
                "Actual_age", "Weighted_Age_Group",
                "Reporting_Age_Group",
                "City_Group", "HH_City"
            ]
        ]

        # ====================================================
        # CITY WISE SUMMARY FOR GOOGLE SHEET
        # ====================================================

        if group_name == "Rest_of_Armenia":

            for city in cities:

                city_master = region_master[
                    region_master["region"] == city
                ]

                city_intab = intab_members_df[
                    intab_members_df["HH_City"] == city
                ]

                city_master_hhids = set(city_master["hhid"])

                city_raw_hhids = (
                    raw_unique_hhids &
                    city_master_hhids
                )

                city_viewership_df = raw[
                    raw["hhid"].isin(city_raw_hhids)
                ]

                city_intab_hh_count = city_intab["hhid"].nunique()

                city_intab_member_count = (
                    city_intab[
                        ["hhid", "member_code"]
                    ]
                    .drop_duplicates()
                    .shape[0]
                )

                city_viewership_hh_count = len(city_raw_hhids)

                city_viewership_member_count = (
                    city_viewership_df[
                        ["hhid", "member_id"]
                    ]
                    .drop_duplicates()
                    .shape[0]
                )

                city_master = members_all[
                    members_all["region"] == city
                ]

                installed_hh = city_master["hhid"].nunique()

                installed_members = (
                    city_master[
                        ["hhid", "member_code"]
                    ]
                    .drop_duplicates()
                    .shape[0]
                )

                summary_table.append([
                    city,
                    installed_hh,
                    installed_members,
                    city_intab_hh_count,
                    city_intab_member_count,
                    city_viewership_hh_count,
                    city_viewership_member_count
                ])
        
        final_df.to_csv(
            os.path.join(
                output_dir,
                f"{process_date}_{group_name}.csv"
            ),
            index=False
        )


        if group_name == "Yerevan":

            

            installed_hh = region_master["hhid"].nunique()

            installed_members = (
                region_master[
                    ["hhid", "member_code"]
                ]
                .drop_duplicates()
                .shape[0]
            )

            summary_table.append([
                group_name,
                installed_hh,
                installed_members,
                intab_hh_count,
                intab_member_count,
                viewership_hh_count,
                viewership_member_count
            ])

        print(f"{group_name}  RAW:{raw_hh_count} | INTAB:{intab_hh_count}")

    print("\nSUMMARY TABLE")
    print(summary_table)

    summary_df = pd.DataFrame(
    summary_table,
    columns=[
        "Region",
        "Installed_HH",
        "Installed_Members",
        "Intab_HH",
        "Intab_Members",
        "Viewership_HH",
        "Viewership_Members"
    ]
    )

    desired_order = [
        "Artashat",
        "Ashtarak",
        "Gavar",
        "Gyumri",
        "Hrazdan",
        "Ijevan",
        "Kapan",
        "Vagharshapat",
        "Vanadzor",
        "Yeghegnadzor",
        "Yerevan"
    ]

    summary_df["Region"] = pd.Categorical(
        summary_df["Region"],
        categories=desired_order,
        ordered=True
    )

    summary_df = summary_df.sort_values("Region")
    summary_df = summary_df.reset_index(drop=True)

    # ==========================================
    # GRAND TOTAL
    # ==========================================

    grand_total = pd.DataFrame([{
        "Region": "Grand Total",
        "Installed_HH": summary_df["Installed_HH"].sum(),
        "Installed_Members": summary_df["Installed_Members"].sum(),
        "Intab_HH": summary_df["Intab_HH"].sum(),
        "Intab_Members": summary_df["Intab_Members"].sum(),
        "Viewership_HH": summary_df["Viewership_HH"].sum(),
        "Viewership_Members": summary_df["Viewership_Members"].sum()
    }])


    summary_df = pd.concat(
        [summary_df, grand_total],
        ignore_index=True
    )

    summary_df.to_csv(
        os.path.join(
            output_dir,
            f"{process_date}_summary.csv"
        ),
        index=False
    )

    print("\nSTEP-1 COMPLETED SUCCESSFULLY")

# ============================================================
# STEP 2 – AUTO CITY-BASED RAKING (PRODUCTION VERSION)
# ============================================================

import pandas as pd
import os
from datetime import datetime

# ============================================================
# CITY BENCHMARKS
# ============================================================

CITY_BENCHMARKS = {

    "Yerevan": {
    "POP_TOTAL": 1136300,
    "GENDER_TARGETS": {
        "Male": 0.44785,
        "Female": 0.55215
    },
    "POP_AGE_GENDER": {
        "3-17_Male": 0.07380,
        "18-20_Male": 0.01500,
        "21-29_Male": 0.04860,
        "30-39_Male": 0.06935,
        "40-49_Male": 0.06599,
        "50-59_Male": 0.05110,
        "60+_Male": 0.12401,

        "3-17_Female": 0.09099,
        "18-20_Female": 0.01849,
        "21-29_Female": 0.05992,
        "30-39_Female": 0.08550,
        "40-49_Female": 0.08136,
        "50-59_Female": 0.06300,
        "60+_Female": 0.15289
    }
 },


    "Rest_of_Armenia": {
    "POP_TOTAL": 1931100,
    "GENDER_TARGETS": {
        "Male": 0.48477,
        "Female": 0.51523
    },
    "POP_AGE_GENDER": {
        "3-17_Male": 0.10247,
        "18-20_Male": 0.01804,
        "21-29_Male": 0.04965,
        "30-39_Male": 0.07660,
        "40-49_Male": 0.06445,
        "50-59_Male": 0.05609,
        "60+_Male": 0.11748,

        "3-17_Female": 0.10890,
        "18-20_Female": 0.01917,
        "21-29_Female": 0.05277,
        "30-39_Female": 0.08141,
        "40-49_Female": 0.06850,
        "50-59_Female": 0.05961,
        "60+_Female": 0.12486
    }
 }
}


GENDER_COL = "Sex"
AGE_COL = "Reporting_Age_Group"

TOLERANCE = 0.0001
MAX_ITER = 50


# ============================================================
# RAKING FUNCTION
# ============================================================

def rake_dataframe(df, city):

    bench = CITY_BENCHMARKS[city]

    POP_TOTAL = bench["POP_TOTAL"]
    POP_AGE_GENDER = bench["POP_AGE_GENDER"]

    df = df.copy()
    df["weight"] = 1.0

    df["AGE_GENDER"] = (
    df["Reporting_Age_Group"].astype(str)
    + "_"
    + df["Sex"].astype(str)
    )

    iterations_used = 0

    for it in range(MAX_ITER):

        iterations_used = it + 1

        # ---------------- Age x Gender ----------------

        ag_dist = df.groupby("AGE_GENDER")["weight"].sum()
        ag_dist = ag_dist / ag_dist.sum()

        for cell, target in POP_AGE_GENDER.items():

            if cell in ag_dist:

                df.loc[
                    df["AGE_GENDER"] == cell,
                    "weight"
                ] *= target / ag_dist[cell]


        # ---------------- Convergence ----------------
        ag_check = (
            df.groupby("AGE_GENDER")["weight"]
            .sum()
        )

        ag_check = ag_check / ag_check.sum()

        if all(
            abs(ag_check.get(cell, 0) - target)
            <= TOLERANCE
            for cell, target in POP_AGE_GENDER.items()
        ):
            break

    df["final_weight"] = df["weight"]
    df["final_weight_scaled"] = (
    df["final_weight"] *
    (POP_TOTAL / df["final_weight"].sum())
    )

    df["final_weight"] = (
    df["final_weight"]
    .round(5)
    )

    df["final_weight_scaled"] = (
        df["final_weight_scaled"]
        .round(5)
    )

    # ====================================================
    # GENDER VALIDATION
    # ====================================================

    gender_targets = bench["GENDER_TARGETS"]

    gender_check = (
        df.groupby("Sex")["final_weight_scaled"]
        .sum()
    )

    gender_check = gender_check / gender_check.sum()

    print("\nGender Validation")

    for sex in ["Male", "Female"]:

        actual = gender_check.get(sex, 0)
        target = gender_targets[sex]
        diff = abs(actual - target)

        status = "PASS" if diff <= 0.0001 else "FAIL"

        print(
            f"{sex} | "
            f"Actual={actual:.5f} | "
            f"Target={target:.5f} | "
            f"Diff={diff:.5f} | "
            f"{status}"
        )
    df["raking_iterations"] = iterations_used

    df = df.drop(columns=["weight"])

    return df


# ============================================================
# MAIN FUNCTION
# ============================================================

def run_step2(process_date):

    folder_date = datetime.strptime(
        process_date, "%d-%m-%Y"
    ).strftime("%Y-%m-%d")

    input_dir = OUTPUT_FOLDER
    output_dir = OUTPUT_FOLDER

    os.makedirs(output_dir, exist_ok=True)

    files = [
    f for f in os.listdir(input_dir)
    if f.endswith(".csv")
    and process_date in f
    and "summary" not in f.lower()
    ]
    if not files:
        raise Exception("No Step1 files found")

    for fname in files:

        df = pd.read_csv(os.path.join(input_dir, fname))
        df["Weighted_Age_Group"] = (
            df["Weighted_Age_Group"]
            .astype(str)
            .replace({
                "14-Mar": "3-14",
                "Mar-14": "3-14"
            })
        )

        city_group = (
            df["City_Group"]
            .dropna()
            .astype(str)
            .iloc[0]
        )

        if city_group == "Yerevan":
            benchmark_key = "Yerevan"

        elif city_group == "Rest of Armenia":
            benchmark_key = "Rest_of_Armenia"

        else:
            raise Exception(
                f"Unknown City_Group: {city_group}"
            )

        print(
            f"Processing: {fname} | "
            f"Benchmark: {benchmark_key}"
        )

        print(f"Records : {len(df):,}")
        print(f"HHIDs   : {df['hhid'].nunique():,}")
        df_out = rake_dataframe(df, benchmark_key)

        # Add empty cols
        for col in ["SEC","HH_Income","HH_Education", "With_Child", "HH_Size"]:
            if col not in df_out.columns:
                df_out[col] = ""

        final_columns = [
            "Date","hhid","member_code","Sex","Actual_age",
            "Weighted_Age_Group","Reporting_Age_Group",
            "City_Group","HH_City",
            "final_weight","final_weight_scaled",
            "raking_iterations",
            "SEC","HH_Income","HH_Education", "With_Child", "HH_Size"
        ]

        df_out = df_out[final_columns]

        out_name = f"Raked_{fname.replace('.csv','.xlsx')}"

        df_out.to_excel(
            os.path.join(output_dir, out_name),
            index=False
        )

        print("Saved:", out_name)

    print("STEP 2 COMPLETED SUCCESSFULLY")

# ============================================================
# STEP 3 – COMBINE ALL STEP-2 FILES (PRODUCTION VERSION)
# ============================================================

import pandas as pd
import os
import re
from datetime import datetime


# ============================================================
# AGE FIX FUNCTION (EXCEL SAFE)
# ============================================================

def clean_age(val):

    if pd.isna(val):
        return val

    # If Excel auto-converted to datetime
    if isinstance(val, pd.Timestamp):
        if val.month == 3:
            return "'3-" + str(val.day)

    val_str = str(val).strip()

    # If string like 14-Mar
    match = re.match(r"^(\d{1,2})-Mar", val_str, re.IGNORECASE)
    if match:
        day = match.group(1)
        return "'3-" + day

    return val_str


# ============================================================
# MAIN FUNCTION
# ============================================================

def run_step3(process_date):

    print(f"\nRunning Step-3 Combine for {process_date}")

    input_dir = OUTPUT_FOLDER
    output_dir = OUTPUT_FOLDER

    if not os.path.exists(input_dir):
        raise Exception("Step-2 folder not found")

    files = [
        f"Raked_{process_date}_Yerevan.xlsx",
        f"Raked_{process_date}_Rest_of_Armenia.xlsx"
    ]

    files = [
        f for f in files
        if os.path.exists(os.path.join(input_dir, f))
    ]

    print("\nFILES USED FOR COMBINATION:")
    for f in files:
        print(f)

    if len(files) != 2:
        raise Exception(
            f"Expected 2 Step-2 files but found {len(files)}: {files}"
        )

    all_dfs = []

    for fname in files:

        file_path = os.path.join(input_dir, fname)

        print("Reading:", fname)

        if fname.lower().endswith(".csv"):
            df = pd.read_csv(file_path)
        else:
            df = pd.read_excel(file_path)

        all_dfs.append(df)

    # =========================================================
    # COMBINE
    # =========================================================

    final_df = pd.concat(all_dfs, ignore_index=True)
    print("\nCOMBINED SUMMARY")
    print(f"Rows  : {len(final_df):,}")
    print(f"HHIDs : {final_df['hhid'].nunique():,}")

    # =========================================================
    # FORCE AGE FIX
    # =========================================================

    columns_to_fix = ["Weighted_Age_Group", "Reporting_Age_Group"]

    for col in columns_to_fix:
        if col in final_df.columns:
            final_df[col] = final_df[col].apply(clean_age)

    # =========================================================
    # SAVE FILE
    # =========================================================

    output_file = os.path.join(
        output_dir,
        f"{process_date}_combined_weighted.csv"
    )

    final_df.to_csv(output_file, index=False)
    print("\nFILES USED FOR COMBINATION:")
    for f in files:
        print(f)

    print("\nSTEP-3 COMPLETED")
    print("Total Rows:", len(final_df))
    print("Saved:", output_file)

    return {
    "csv": output_file,
    }

# ============================================================
# STEP 4 – FULL VALIDATION (CITY + GENDER + AGE BENCHMARKS)
# ============================================================

import pandas as pd
import os
from datetime import datetime

TOLERANCE = 0.0001  

# ============================================================
# OFFICIAL POPULATION TOTALS
# ============================================================

CITY_TOTAL_POP = {
    "Yerevan": 1136300,
    "Rest_of_Armenia": 1931100
}

# ============================================================
# BENCHMARK DISTRIBUTIONS
# ============================================================

CITY_BENCHMARKS = {

    "Yerevan": {
    "POP_TOTAL": 1136300,
    "GENDER_TARGETS": {
        "Male": 0.44785,
        "Female": 0.55215
    },
    "POP_AGE_GENDER": {
        "3-17_Male": 0.07380,
        "18-20_Male": 0.01500,
        "21-29_Male": 0.04860,
        "30-39_Male": 0.06935,
        "40-49_Male": 0.06599,
        "50-59_Male": 0.05110,
        "60+_Male": 0.12401,

        "3-17_Female": 0.09099,
        "18-20_Female": 0.01849,
        "21-29_Female": 0.05992,
        "30-39_Female": 0.08550,
        "40-49_Female": 0.08136,
        "50-59_Female": 0.06300,
        "60+_Female": 0.15289
    }
 },


    "Rest_of_Armenia": {
    "POP_TOTAL": 1931100,
    "GENDER_TARGETS": {
        "Male": 0.48477,
        "Female": 0.51523
    },
    "POP_AGE_GENDER": {
        "3-17_Male": 0.10247,
        "18-20_Male": 0.01804,
        "21-29_Male": 0.04965,
        "30-39_Male": 0.07660,
        "40-49_Male": 0.06445,
        "50-59_Male": 0.05609,
        "60+_Male": 0.11748,

        "3-17_Female": 0.10890,
        "18-20_Female": 0.01917,
        "21-29_Female": 0.05277,
        "30-39_Female": 0.08141,
        "40-49_Female": 0.06850,
        "50-59_Female": 0.05961,
        "60+_Female": 0.12486
    }
 }
}

# ============================================================
# MAIN FUNCTION
# ============================================================

def run_full_validation(process_date):

    print(f"\nRunning Full Validation for {process_date}")

    folder_date = datetime.strptime(
        process_date, "%d-%m-%Y"
    ).strftime("%Y-%m-%d")

    combined_path = os.path.join(
    OUTPUT_FOLDER,
    f"{process_date}_combined_weighted.csv"
    )

    if not os.path.exists(combined_path):
        raise Exception("Combined file not found.")

    df = pd.read_csv(combined_path)

    # =========================================================
    # CITY TOTAL VALIDATION
    # =========================================================

    city_results = []
    present_cities = set(df["City_Group"].str.replace(" ", "_"))

    for city, pop in CITY_TOTAL_POP.items():

        if city not in present_cities:
            city_results.append({
                "City": city,
                "Expected_Population": pop,
                "Weighted_Sum": 0,
                "Difference": -pop,
                "Difference_%": -100,
                "Status": "MISSING"
            })
            continue

        city_df = df[
            df["City_Group"]
            .str.replace(" ", "_")
            == city
        ].copy()

        city_sum = city_df["final_weight_scaled"].sum()

        diff = city_sum - pop
        pct_diff = (diff / pop) * 100

        status = "PASS" if abs(diff) <= 1 else "FAIL"

        city_results.append({
            "City": city,
            "Expected_Population": pop,
            "Weighted_Sum": round(city_sum, 2),
            "Difference": round(diff, 2),
            "Difference_%": round(pct_diff, 4),
            "Status": status
        })

    city_validation_df = pd.DataFrame(city_results)

        

    # =========================================================
    # GENDER + AGE BENCHMARK VALIDATION
    # =========================================================

    benchmark_results = []

    for city in CITY_TOTAL_POP.keys():

        city_df = df[
            df["City_Group"]
            .str.replace(" ", "_")
            == city
        ].copy()

        if len(city_df) == 0:
            continue

        city_df["Weighted_Age_Group"] = (
        city_df["Weighted_Age_Group"]
        .astype(str)
        .replace({
            "14-Mar": "3-14",
            "Mar-14": "3-14"
        })
        )

        total_weight = city_df["final_weight_scaled"].sum()

        # =========================================================
        # GENDER VALIDATION
        # =========================================================

        gender_dist = (
            city_df.groupby("Sex")["final_weight_scaled"]
            .sum()
        )

        gender_dist = gender_dist / total_weight

        for gender, expected in CITY_BENCHMARKS[city]["GENDER_TARGETS"].items():

            observed = gender_dist.get(gender, 0)

            diff = observed - expected

            status = (
                "PASS"
                if abs(diff) <= TOLERANCE
                else "FAIL"
            )

            benchmark_results.append({
                "City": city,
                "Dimension": "Gender",
                "Category": gender,
                "Expected": round(expected, 5),
                "Observed": round(observed, 5),
                "Difference": round(diff, 5),
                "Status": status
            })

        city_df["AGE_GENDER"] = (
        city_df["Reporting_Age_Group"].astype(str)
        + "_"
        + city_df["Sex"].astype(str)
        )

        ag_dist = (
            city_df.groupby("AGE_GENDER")["final_weight_scaled"]
            .sum()
        )

        ag_dist = ag_dist / total_weight

        for cell, expected in CITY_BENCHMARKS[city]["POP_AGE_GENDER"].items():

            observed = ag_dist.get(cell, 0)

            diff = observed - expected

            status = (
                "PASS"
                if abs(diff) <= TOLERANCE
                else "FAIL"
            )

            benchmark_results.append({
                "City": city,
                "Dimension": "Age_Gender",
                "Category": cell,
                "Expected": round(expected, 5),
                "Observed": round(observed, 5),
                "Difference": round(diff, 5),
                "Status": status
            })

    benchmark_validation_df = pd.DataFrame(benchmark_results)

    overall_status = "PASS"

    if (
        (city_validation_df["Status"] != "PASS").any()
        or
        (benchmark_validation_df["Status"] != "PASS").any()
    ):
        overall_status = "FAIL"

    # =========================================================
    # SAVE TXT REPORT
    # =========================================================

    validation_dir = OUTPUT_FOLDER

    os.makedirs(validation_dir, exist_ok=True)

    txt_path = os.path.join(
        validation_dir,
        f"{process_date}_full_validation_report.txt"
    )

    with open(txt_path, "w", encoding="utf-8") as f:

        f.write("=============================================\n")
        f.write("RIM ENGINE – FULL VALIDATION REPORT\n")
        f.write("=============================================\n\n")
        f.write(f"Process Date : {process_date}\n")
        f.write(f"Generated On : {datetime.now()}\n\n")

        f.write("===== CITY TOTAL VALIDATION =====\n\n")
        f.write(city_validation_df.to_string(index=False))
        f.write("\n\n")

        f.write("===== GENDER + AGE BENCHMARK VALIDATION =====\n\n")
        f.write(benchmark_validation_df.to_string(index=False))
        f.write("\n\n")

    print("Validation report saved:", txt_path)

    return {
        "overall_status": overall_status,
        "city_validation": city_validation_df,
        "benchmark_validation": benchmark_validation_df
    }

# ==========================================
# Email Config
# ==========================================
SENDER_EMAIL = "senthil.inditronics@gmail.com"
APP_PASSWORD = "ytnp tetz uixs jprs"
RECEIVER_EMAILS = [
    "senthil.inditronics@gmail.com"
]

# =========================================================
# E-MAIL FUNCTION
# =========================================================

def send_email(process_date):

    summary_file = os.path.join(
        OUTPUT_FOLDER,
        f"{process_date}_summary.csv"
    )

    combined_file = os.path.join(
        OUTPUT_FOLDER,
        f"{process_date}_combined_weighted.csv"
    )

    if not os.path.exists(summary_file):
        raise Exception(
            f"Summary file not found: {summary_file}"
        )

    if not os.path.exists(combined_file):
        raise Exception(
            f"Combined file not found: {combined_file}"
        )

    msg = EmailMessage()

    msg["Subject"] = (
        f"Panel Output - {process_date}"
    )

    msg["From"] = SENDER_EMAIL

    msg["To"] = ", ".join(RECEIVER_EMAILS)

    msg.set_content(
        f"""
Hi Senthil,

Please find attached files for {process_date}

1. {process_date}_summary.csv
2. {process_date}_combined_weighted.csv

Regards,
Panel Automation
"""
    )

    # =====================================
    # Attach Summary CSV
    # =====================================

    with open(summary_file, "rb") as f:

        msg.add_attachment(
            f.read(),
            maintype="text",
            subtype="csv",
            filename=os.path.basename(summary_file)
        )

    # =====================================
    # Attach Combined CSV
    # =====================================

    with open(combined_file, "rb") as f:

        msg.add_attachment(
            f.read(),
            maintype="text",
            subtype="csv",
            filename=os.path.basename(combined_file)
        )

    with smtplib.SMTP_SSL(
        "smtp.gmail.com",
        465
    ) as smtp:

        smtp.login(
            SENDER_EMAIL,
            APP_PASSWORD
        )

        smtp.send_message(msg)

    print("\n EMAIL SENT SUCCESSFULLY")

# ============================================================
# MAIN FUNCTION
# ============================================================

if __name__ == "__main__":

    print("\nRIM ENGINE AUTOMATION")
    print("-" * 50)

    # ==========================================
    # ALWAYS PROCESS D-1 DATE
    # ==========================================

    process_date = (
        datetime.now() - timedelta(days=1)
    ).strftime("%d-%m-%Y")

    print(
        f"\nProcessing D-1 Date : {process_date}"
    )

    folder_date = datetime.strptime(
        process_date,
        "%d-%m-%Y"
    ).strftime("%Y-%m-%d")

    # ==========================================
    # INPUT FILE CHECK
    # ==========================================

    expected_file = f"{folder_date}_cleaned.csv"

    raw_file_path = os.path.join(
        INPUT_FOLDER,
        expected_file
    )

    if not os.path.exists(raw_file_path):
        raise Exception(
            f"\nInput file not found:\n{raw_file_path}"
        )

    print(f"\nUsing Input File : {expected_file}")


    # ==========================================
    # CITYS
    # ==========================================

    selected_cities = [
        "Yerevan",
        "Rest_of_Armenia"
    ]

    # ==========================================
    # STEP 1
    # ==========================================

    run_step1(
        process_date,
        selected_cities
    )

    print("\nSTEP 1 DONE")

    # ==========================================
    # STEP 2
    # ==========================================

    run_step2(
        process_date
    )

    print("\nSTEP 2 DONE")

    # ==========================================
    # STEP 3
    # ==========================================

    run_step3(
        process_date
    )

    print("\nSTEP 3 DONE")

    # ==========================================
    # STEP 4
    # ==========================================

    validation_result = run_full_validation(
        process_date
    )

    print("\nSTEP 4 DONE")

    print(
        f"\nFINAL STATUS : "
        f"{validation_result['overall_status']}"
    )

    send_email(
        process_date
    )

    print(
        "\nPIPELINE COMPLETED SUCCESSFULLY"
    )

