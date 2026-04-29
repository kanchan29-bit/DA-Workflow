import subprocess
import sys
import os
from datetime import datetime

# ============================================================
# CONFIG: DEFINE YOUR PIPELINE ORDER HERE
# ============================================================
PIPELINE = [
    {
        "name": "Logo Sessions",
        "script": r"C:\Users\kanch\Desktop\statement\Sessions\logo\01_sessions.py",
        "check_file": None  # Optional: path to expected output
    },
    {
        "name": "FP files download",
        "script": r"C:\Users\kanch\Desktop\statement\Sessions\fp\02_downloading_files.py",
        "check_file": None  # Optional: path to expected output
    },
    {
        "name": "correcting the data",
        "script": r"C:\Users\kanch\Desktop\statement\Sessions\fp\03_all scripts_1.py",
        "check_file": None
    },
    {
        "name": "mapping the data",
        "script": r"C:\Users\kanch\Desktop\statement\Sessions\fp\04_Automatic mapping_2.py",
        "check_file": None
    },
    {
        "name": "merging the member declaration and viewership data for fp",
        "script": r"C:\Users\kanch\Desktop\statement\Sessions\fp\05_merging_3.py",
        "check_file": None
    },
    {
        "name": "household sessions for fp",
        "script": r"C:\Users\kanch\Desktop\statement\Sessions\fp\06_sessions_4.py",
        "check_file": None
    },
    {
        "name": "member sessions for fp",
        "script": r"C:\Users\kanch\Desktop\statement\Sessions\fp\07_member_level sessions_5.py",
        "check_file": None
    },
    {
        "name": "cleaning",
        "script": r"C:\Users\kanch\Desktop\statement\Sessions\fp\08_Data cleaning_6.py",
        "check_file": None
    },
    {
        "name": "merging sessions without rejuvenation for rejuvenation history file",
        "script": r"C:\Users\kanch\Desktop\statement\Sessions\merging\09_merging_1.py",
        "check_file": None
    },
    {
        "name": "cleaning for history file",
        "script": r"C:\Users\kanch\Desktop\statement\Sessions\merging\10_Data Cleaning.py",
        "check_file": None
    },
    {
        "name": "member rejuvenation",
        "script": r"C:\Users\kanch\Desktop\statement\Sessions\merging\11_member_rejuvination.py",
        "check_file": None
    },
    {
        "name": "now merging the rejuvenated logo and fp files",
        "script": r"C:\Users\kanch\Desktop\statement\Sessions\merging\12_merging_after_rejuvenation.py",
        "check_file": None
    },
    {
        "name": "cleaning for panel file",
        "script": r"C:\Users\kanch\Desktop\statement\For Panel Files\13_Data CLeaning.py",
        "check_file": None
    },
    {
        "name": "3 rules",
        "script": r"C:\Users\kanch\Desktop\statement\Statement File\14_Qualifier_rules.py",
        "check_file": None
    },
    {
        "name": "channel clipping",
        "script": r"C:\Users\kanch\Desktop\statement\Statement File\15_Channel_clippling.py",
        "check_file": None
    },
    {
        "name": "statement file generation",
        "script": r"C:\Users\kanch\Desktop\statement\Statement File\16_Final_data_cleaning.py",
        "check_file": None
    }
]

LOG_FILE = r"C:\Users\kanch\Desktop\statement\Pipeline\pipeline_log.txt"

# ============================================================
# FUNCTION: RUN SCRIPT
# ============================================================
def run_step(step):
    print(f"\n▶ Running: {step['name']}")
    start_time = datetime.now()

    result = subprocess.run([sys.executable, step["script"]])

    end_time = datetime.now()
    duration = end_time - start_time

    log(f"{step['name']} | Start: {start_time} | End: {end_time} | Duration: {duration} | Code: {result.returncode}")

    if result.returncode != 0:
        raise Exception(f"❌ Script failed: {step['script']}")

    # Optional output validation
    if step["check_file"]:
        if not os.path.exists(step["check_file"]):
            raise Exception(f"❌ Expected output not found: {step['check_file']}")

    print(f"✅ Completed: {step['name']}")

# ============================================================
# FUNCTION: LOGGING
# ============================================================
def log(message):
    with open(LOG_FILE, "a") as f:
        f.write(message + "\n")

# ============================================================
# MAIN EXECUTION
# ============================================================
if __name__ == "__main__":
    print("\n🚀 Starting Pipeline Execution\n")

    try:
        for step in PIPELINE:
            run_step(step)

        print("\n🎯 Pipeline completed successfully!")

    except Exception as e:
        print(str(e))
        log(f"ERROR: {str(e)}")
        print("\n🛑 Pipeline stopped due to error.")