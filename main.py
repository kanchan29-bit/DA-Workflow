import subprocess
import sys
import os
from datetime import datetime, timedelta

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
    },
    {
        "name": "upload outputs to S3",
        "script": os.path.join("pipeline", "17_upload_to_s3.py"),
        "check_file": None
    }
]

LOG_FILE = os.path.join("pipeline", "pipeline_log.txt")

# ============================================================
# FUNCTION: RUN SCRIPT
# ============================================================
def run_step(step, step_index, run_id, broadcast):
    broadcast(step_index, f"\nRunning: {step['name']}\n")
    start_time = datetime.now()

    from dashboard.models import create_step, update_step_status, append_step_log, update_run_status
    step_id = create_step(run_id, step_index, step["name"])

    # Ensure the script path is absolute or correctly relative to the project root
    script_path = os.path.abspath(step["script"])
    
    if not os.path.exists(script_path):
        msg = f"Script not found: {script_path}\n"
        append_step_log(step_id, msg)
        broadcast(step_index, msg, is_error=True)
        update_step_status(step_id, "Failed")
        update_run_status(run_id, "Failed", error_message=f"Script not found: {step['script']}")
        raise Exception(msg)

    env = os.environ.copy()
    run_date = os.environ.get("RUN_DATE") or os.environ.get("WORKFLOW_DATE")
    if not run_date:
        run_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    env["RUN_DATE"] = run_date
    env["WORKFLOW_DATE"] = run_date

    process = subprocess.Popen(
        [sys.executable, script_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        cwd=os.path.abspath(os.path.dirname(__file__)),
        env=env
    )

    for line in iter(process.stdout.readline, ''):
        append_step_log(step_id, line)
        broadcast(step_index, line)

    process.stdout.close()
    return_code = process.wait()

    end_time = datetime.now()
    duration = end_time - start_time

    log(f"{step['name']} | Start: {start_time} | End: {end_time} | Duration: {duration} | Code: {return_code}")

    if return_code != 0:
        msg = f"Step failed with exit code {return_code}\n"
        append_step_log(step_id, msg)
        broadcast(step_index, msg, is_error=True)
        update_step_status(step_id, "Failed")
        update_run_status(run_id, "Failed", error_message=f"Step '{step['name']}' failed.")
        raise Exception(f"Script failed: {script_path}")

    # Optional output validation
    if step["check_file"]:
        check_path = os.path.abspath(step["check_file"])
        if not os.path.exists(check_path):
            msg = f"Expected output not found: {check_path}\n"
            append_step_log(step_id, msg)
            broadcast(step_index, msg, is_error=True)
            update_step_status(step_id, "Failed")
            update_run_status(run_id, "Failed", error_message=f"Expected output missing for '{step['name']}'")
            raise Exception(msg)

    update_step_status(step_id, "Success")
    broadcast(step_index, f"Completed: {step['name']}\n")

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
    from dashboard.models import init_db, create_run, update_run_status, get_run_details
    import urllib.request
    import json
    
    # Adjust sys.path to find dashboard module
    sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
    init_db()
    
    # Determine date
    run_date = os.environ.get("RUN_DATE") or os.environ.get("WORKFLOW_DATE")
    if not run_date:
        run_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        
    run_id = create_run(run_date, trigger_type="cron")
    
    def broadcast(step_index, message, is_error=False):
        print(message, end="")
        sys.stdout.flush()
        
        payload = json.dumps({
            "run_id": run_id,
            "step_index": step_index,
            "message": message,
            "is_error": is_error
        }).encode('utf-8')
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:5000/api/workflow/broadcast",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=0.5) as res:
                pass
        except Exception:
            pass

    broadcast(-1, "\nStarting Pipeline Execution\n")

    try:
        for i, step in enumerate(PIPELINE):
            run_step(step, i, run_id, broadcast)

        update_run_status(run_id, "Success")
        broadcast(-1, "\nPipeline completed successfully!")

    except Exception as e:
        run_details = get_run_details(run_id)
        if run_details and run_details.get("status") == "Running":
            update_run_status(run_id, "Failed", error_message=str(e))
        
        broadcast(-1, f"\nPipeline stopped due to error: {str(e)}\n")