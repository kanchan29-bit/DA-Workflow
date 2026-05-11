from flask import Flask, jsonify, request, render_template, Response
import os
import json
import queue
from datetime import datetime

# Adjust sys.path to find dashboard module
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dashboard.models import init_db, get_recent_runs, get_run_details, check_run_exists_for_date, create_run, get_successful_runs
from dashboard.runner import run_pipeline, log_queues

app = Flask(__name__)

# Initialize DB on startup
with app.app_context():
    init_db()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/workflow/runs', methods=['GET'])
def list_runs():
    limit = int(request.args.get('limit', 10))
    runs = get_recent_runs(limit)
    return jsonify(runs)

@app.route('/api/workflow/runs/<int:run_id>', methods=['GET'])
def get_run(run_id):
    run = get_run_details(run_id)
    if not run:
        return jsonify({"error": "Run not found"}), 404
    return jsonify(run)

@app.route('/api/workflow/run', methods=['POST'])
def start_run():
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    if check_run_exists_for_date(today_str):
        return jsonify({"error": f"A run for {today_str} is already active or successful."}), 400
        
    run_id = create_run(today_str, trigger_type="manual")
    run_pipeline(run_id)
    return jsonify({"run_id": run_id, "status": "Started"}), 201

@app.route('/api/workflow/runs/<int:run_id>/retry', methods=['POST'])
def retry_run(run_id):
    run = get_run_details(run_id)
    if not run:
        return jsonify({"error": "Run not found"}), 404
        
    start_step_index = 0
    if "steps" in run:
        for i, step in enumerate(run["steps"]):
            if step["status"] in ["Failed", "Skipped"]:
                start_step_index = i
                break
                
    today_str = datetime.now().strftime("%Y-%m-%d")
    new_run_id = create_run(today_str, trigger_type=f"retry_{run_id}")
    run_pipeline(new_run_id, start_step_index=start_step_index)
    return jsonify({"run_id": new_run_id, "status": "Retried"}), 201

@app.route('/api/artifacts', methods=['GET'])
def list_artifacts():
    runs = get_successful_runs()
    return jsonify(runs)

@app.route('/api/artifacts/<int:run_id>/download', methods=['GET'])
def download_artifacts(run_id):
    import io
    import zipfile
    from flask import send_file
    
    run = get_run_details(run_id)
    if not run:
        return jsonify({"error": "Run not found"}), 404
        
    date_str = run["date"]
    
    # Parse dates from the run date string (YYYY-MM-DD format from DB)
    try:
        run_date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        date_ymd = run_date_obj.strftime("%Y-%m-%d")
        date_dmy = run_date_obj.strftime("%d-%m-%Y")
    except ValueError:
        return jsonify({"error": "Invalid run date format"}), 500

    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    
    # Define files to include based on 17_upload_to_s3.py structure
    files_to_zip = [
        os.path.join("sessions", "logo", "household_viewership_memberwise_output", f"{date_ymd}_logo_sessions.csv"),
        os.path.join("sessions", "fp", "output", f"{date_ymd}_fp_sessions.csv"),
        os.path.join("sessions", "merging", "sessions_without_rejuvenation", f"{date_ymd}_Sessions.csv"),
        os.path.join("sessions", "merging", "sessions_with_rejuvenation", f"{date_ymd}Members_Updatedlogo.csv"),
        os.path.join("sessions", "merging", "sessions_with_rejuvenation", f"{date_ymd}Members_UpdatedFP.csv"),
        os.path.join("sessions", "merging", "Final_merged_file", f"{date_ymd}_Sessions.csv"),
        os.path.join("for_panel_files", "for_panel", f"{date_dmy}_cleaned.csv"),
        os.path.join("statement_file", "qualifier_output", f"{date_dmy}_ruled.csv"),
        os.path.join("statement_file", "qualifier_output", f"{date_dmy}_ruled_PROCESSED.csv"),
        os.path.join("statement_file", "statement", f"{date_dmy}_statement.csv")
    ]
    
    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        for rel_path in files_to_zip:
            abs_path = os.path.join(base_dir, rel_path)
            if os.path.exists(abs_path):
                zf.write(abs_path, arcname=os.path.basename(abs_path))
                
    memory_file.seek(0)
    return send_file(
        memory_file,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f"DA_Workflow_Artifacts_{date_str}.zip"
    )

@app.route('/api/workflow/stream')

def stream_logs():
    def event_stream():
        q = queue.Queue(maxsize=200)
        log_queues.append(q)
        try:
            while True:
                event = q.get()
                yield f"data: {json.dumps(event)}\n\n"
        except GeneratorExit:
            pass
        finally:
            if q in log_queues:
                log_queues.remove(q)
            
    return Response(event_stream(), mimetype="text/event-stream")

if __name__ == '__main__':
    app.run(port=5000, debug=True)
