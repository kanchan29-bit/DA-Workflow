import subprocess
import sys
import os
from datetime import datetime

# ============================================================
# CONFIG: DEFINE YOUR PIPELINE ORDER HERE
# ============================================================
# Use relative paths from the project root
PIPELINE = [
    {
        "name": "Logo Sessions",
        "script": os.path.join("sessions", "logo", "01_sessions.py"),
        "check_file": None  # Optional: path to expected output
    },
    {
        "name": "FP files download",
        "script": os.path.join("sessions", "fp", "02_downloading_files.py"),
        "check_file": None  # Optional: path to expected output
    },
    {
        "name": "correcting the data",
        "script": os.path.join("sessions", "fp", "03_all_scripts_1.py"),
        "check_file": None
    },
    {
        "name": "mapping the data",
        "script": os.path.join("sessions", "fp", "04_automatic_mapping_2.py"),
        "check_file": None
    },
    {
        "name": "merging the member declaration and viewership data for fp",
        "script": os.path.join("sessions", "fp", "05_merging_3.py"),
        "check_file": None
    },
    {
        "name": "household sessions for fp",
        "script": os.path.join("sessions", "fp", "06_sessions_4.py"),
        "check_file": None
    },
    {
        "name": "member sessions for fp",
        "script": os.path.join("sessions", "fp", "07_member_level_sessions_5.py"),
        "check_file": None
    },
    {
        "name": "cleaning",
        "script": os.path.join("sessions", "fp", "08_data_cleaning_6.py"),
        "check_file": None
    },
    {
        "name": "merging sessions without rejuvenation for rejuvenation history file",
        "script": os.path.join("sessions", "merging", "09_merging_1.py"),
        "check_file": None
    },
    {
        "name": "cleaning for history file",
        "script": os.path.join("sessions", "merging", "10_data_cleaning.py"),
        "check_file": None
    },
    {
        "name": "member rejuvenation",
        "script": os.path.join("sessions", "merging", "11_member_rejuvenation.py"),
        "check_file": None
    },
    {
        "name": "now merging the rejuvenated logo and fp files",
        "script": os.path.join("sessions", "merging", "12_merging_after_rejuvenation.py"),
        "check_file": None
    },
    {
        "name": "cleaning for panel file",
        "script": os.path.join("for_panel_files", "13_data_cleaning.py"),
        "check_file": None
    },
    {
        "name": "3 rules",
        "script": os.path.join("statement_file", "14_qualifier_rules.py"),
        "check_file": None
    },
    {
        "name": "channel clipping",
        "script": os.path.join("statement_file", "15_channel_clipping.py"),
        "check_file": None
    },
    {
        "name": "statement file generation",
        "script": os.path.join("statement_file", "16_final_data_cleaning.py"),
        "check_file": None
    }
]

LOG_FILE = os.path.join("pipeline", "pipeline_log.txt")

# ============================================================
# FUNCTION: RUN SCRIPT
# ============================================================
def run_step(step):
    print(f"\nRunning: {step['name']}")
    start_time = datetime.now()

    # Ensure the script path is absolute or correctly relative to the project root
    script_path = os.path.abspath(step["script"])
    
    if not os.path.exists(script_path):
        raise Exception(f"Script not found: {script_path}")

    result = subprocess.run([sys.executable, script_path])

    end_time = datetime.now()
    duration = end_time - start_time

    log(f"{step['name']} | Start: {start_time} | End: {end_time} | Duration: {duration} | Code: {result.returncode}")

    if result.returncode != 0:
        raise Exception(f"Script failed: {script_path}")

    # Optional output validation
    if step["check_file"]:
        check_path = os.path.abspath(step["check_file"])
        if not os.path.exists(check_path):
            raise Exception(f"Expected output not found: {check_path}")

    print(f"Completed: {step['name']}")

# ============================================================
# FUNCTION: LOGGING
# ============================================================
def log(message):
    # Ensure the log directory exists
    log_dir = os.path.dirname(LOG_FILE)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir)
        
    # Specify utf-8 encoding to avoid UnicodeEncodeError on Windows
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(message + "\n")

# ============================================================
# MAIN EXECUTION
# ============================================================
if __name__ == "__main__":
    print("\nStarting Pipeline Execution\n")

    try:
        for step in PIPELINE:
            run_step(step)

        print("\nPipeline completed successfully!")

    except Exception as e:
        print(str(e))
        log(f"ERROR: {str(e)}")
        print("\nPipeline stopped due to error.")