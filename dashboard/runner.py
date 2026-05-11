import threading
import queue
import subprocess
import os
import sys
from datetime import datetime
from dashboard.models import create_run, update_run_status, create_step, update_step_status, append_step_log

# Import PIPELINE from main
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))
from main import PIPELINE

# Global list of queues for SSE clients
log_queues = []

def broadcast_log(run_id, step_index, message, is_error=False):
    event = {
        "run_id": run_id,
        "step_index": step_index,
        "message": message,
        "is_error": is_error
    }
    # Append to DB log if it's tied to a step
    # (Actually we do this before calling broadcast, so just send to clients here)
    for q in list(log_queues):
        try:
            q.put_nowait(event)
        except queue.Full:
            pass

def run_pipeline(run_id, start_step_index=0):
    def target():
        try:
            for i, step in enumerate(PIPELINE):
                # Skip steps before start_step_index
                if i < start_step_index:
                    step_id = create_step(run_id, i, step["name"])
                    update_step_status(step_id, "Skipped", log_output="Skipped during retry.\n")
                    continue
                
                step_id = create_step(run_id, i, step["name"])
                broadcast_log(run_id, i, f"Starting step: {step['name']}\n")
                
                script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", step["script"]))
                if not os.path.exists(script_path):
                    msg = f"Script not found: {script_path}\n"
                    append_step_log(step_id, msg)
                    broadcast_log(run_id, i, msg, is_error=True)
                    update_step_status(step_id, "Failed")
                    update_run_status(run_id, "Failed", error_message=f"Script not found: {step['script']}")
                    return

                process = subprocess.Popen(
                    [sys.executable, script_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    cwd=os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
                )
                
                for line in iter(process.stdout.readline, ''):
                    append_step_log(step_id, line)
                    broadcast_log(run_id, i, line)
                
                process.stdout.close()
                return_code = process.wait()
                
                if return_code != 0:
                    msg = f"Step failed with exit code {return_code}\n"
                    append_step_log(step_id, msg)
                    broadcast_log(run_id, i, msg, is_error=True)
                    update_step_status(step_id, "Failed")
                    update_run_status(run_id, "Failed", error_message=f"Step '{step['name']}' failed.")
                    return
                
                # Check file
                if step.get("check_file"):
                    check_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", step["check_file"]))
                    if not os.path.exists(check_path):
                        msg = f"Expected output not found: {check_path}\n"
                        append_step_log(step_id, msg)
                        broadcast_log(run_id, i, msg, is_error=True)
                        update_step_status(step_id, "Failed")
                        update_run_status(run_id, "Failed", error_message=f"Expected output missing for '{step['name']}'")
                        return

                update_step_status(step_id, "Success")
                broadcast_log(run_id, i, f"Completed step: {step['name']}\n")

            update_run_status(run_id, "Success")
            broadcast_log(run_id, -1, "Workflow completed successfully.\n")
            
        except Exception as e:
            msg = f"Workflow exception: {str(e)}\n"
            broadcast_log(run_id, -1, msg, is_error=True)
            update_run_status(run_id, "Failed", error_message=str(e))

    thread = threading.Thread(target=target)
    thread.daemon = True
    thread.start()
