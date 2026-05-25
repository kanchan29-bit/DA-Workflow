from flask import Flask, jsonify, request, render_template, Response
import os
import json
import queue
from datetime import datetime, timedelta

# Adjust sys.path to find dashboard module
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dashboard.models import init_db, get_recent_runs, get_run_details, check_run_exists_for_date, create_run, get_successful_runs, is_any_run_running, delete_run_from_db
from dashboard.runner import run_pipeline, log_queues, stop_pipeline
from s3_utils import get_s3_client, S3_OUTPUT_BUCKET, S3_OUTPUT_PREFIX, S3_OUTPUT_REGION, parse_date_flex
from botocore.exceptions import ClientError

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
    if is_any_run_running():
        return jsonify({"error": "Another workflow run is currently active. You cannot run multiple workflows at the same time."}), 400

    data = request.get_json(silent=True) or {}
    requested_date = data.get('date')
    force = bool(data.get('force', False))

    if requested_date:
        try:
            requested_date_obj = parse_date_flex(requested_date).date()
        except Exception:
            return jsonify({"error": "Invalid date format. Use YYYY-MM-DD."}), 400
    else:
        # Default to processing date (yesterday) so pipeline and UI match
        requested_date_obj = (datetime.now() - timedelta(days=1)).date()

    min_date = datetime(2026, 1, 1).date()
    max_date = datetime.now().date()
    if requested_date_obj < min_date or requested_date_obj > max_date:
        return jsonify({"error": "Date must be between 2026-01-01 and today."}), 400

    date_str = requested_date_obj.strftime("%Y-%m-%d")
    if check_run_exists_for_date(date_str) and not force:
        return jsonify({"error": f"A run for {date_str} is already active or successful. Use force=true to override."}), 400

    run_id = create_run(date_str, trigger_type="manual")
    run_pipeline(run_id, date_str=date_str)
    return jsonify({"run_id": run_id, "status": "Started"}), 201

@app.route('/api/workflow/runs/<int:run_id>/retry', methods=['POST'])
def retry_run(run_id):
    if is_any_run_running():
        return jsonify({"error": "Another workflow run is currently active. You cannot run multiple workflows at the same time."}), 400

    run = get_run_details(run_id)
    if not run:
        return jsonify({"error": "Run not found"}), 404
        
    start_step_index = 0
    if "steps" in run:
        for i, step in enumerate(run["steps"]):
            if step["status"] in ["Failed", "Skipped"]:
                start_step_index = i
                break

    date_str = run.get('date') or datetime.now().strftime("%Y-%m-%d")
    new_run_id = create_run(date_str, trigger_type=f"retry_{run_id}")
    run_pipeline(new_run_id, start_step_index=start_step_index, date_str=date_str)
    return jsonify({"run_id": new_run_id, "status": "Retried"}), 201

@app.route('/api/workflow/runs/<int:run_id>/stop', methods=['POST'])
def stop_run(run_id):
    success = stop_pipeline(run_id)
    if not success:
        return jsonify({"error": "Run not found or not active"}), 404
    return jsonify({"status": "Stopping"}), 200

@app.route('/api/workflow/runs/<int:run_id>', methods=['DELETE'])
def delete_run(run_id):
    run = get_run_details(run_id)
    if not run:
        return jsonify({"error": "Run not found"}), 404
    if run.get("status") == "Running":
        return jsonify({"error": "Cannot delete a running workflow. Please stop it first."}), 400
    
    delete_run_from_db(run_id)
    return jsonify({"status": "Deleted"}), 200

ARTIFACT_FILE_MAP = [
    {"label": "Logo Sessions", "category": "logo", "filename": "logo_sessions.csv"},
    {"label": "FP Sessions", "category": "fp", "filename": "fp_sessions.csv"},
    {"label": "Sessions without Rejuvenation", "category": "merging", "filename": "Sessions_without_Rejuvenation.csv"},
    {"label": "Rejuvenated Sessions (Logo)", "category": "merging", "filename": "Sessions_with_rejuvenation_logo.csv"},
    {"label": "Rejuvenated Sessions (FP)", "category": "merging", "filename": "Sessions_with_rejuvenation_FP.csv"},
    {"label": "Final Merged Sessions", "category": "merging", "filename": "Sessions_final_merged.csv"},
    {"label": "Panel Cleaned File", "category": "for_panel", "filename": "cleaned.csv"},
    {"label": "Qualifier Ruled File", "category": "qualifier", "filename": "ruled.csv"},
    {"label": "Qualifier Ruled Processed", "category": "qualifier", "filename": "ruled_PROCESSED.csv"},
    {"label": "Statement File", "category": "statement", "filename": "statement.csv"},
]


def build_artifact_files(date_str):
    try:
        run_date_obj = parse_date_flex(date_str)
    except ValueError:
        run_date_obj = datetime.strptime(date_str, "%Y-%m-%d")

    # The upload pipeline stores outputs under yesterday's folder date.
    s3_date = (run_date_obj - timedelta(days=1)).strftime("%d-%m-%Y")

    files = []
    for item in ARTIFACT_FILE_MAP:
        key = f"{S3_OUTPUT_PREFIX}/{s3_date}/{item['category']}/{item['filename']}"
        url = f"https://{S3_OUTPUT_BUCKET}.s3.{S3_OUTPUT_REGION}.amazonaws.com/{key}"
        files.append({
            "label": item["label"],
            "category": item["category"],
            "filename": item["filename"],
            "key": key,
            "url": url,
        })
    return files

@app.route('/api/artifacts', methods=['GET'])
def list_artifacts():
    runs = get_successful_runs()
    for run in runs:
        run["files"] = build_artifact_files(run["date"])
    return jsonify(runs)

@app.route('/api/artifacts/<int:run_id>/download-file/<path:filename>', methods=['GET'])
def download_artifact_file(run_id, filename):
    from flask import Response, stream_with_context

    run = get_run_details(run_id)
    if not run:
        return jsonify({"error": "Run not found"}), 404

    files = build_artifact_files(run["date"])
    match = next((item for item in files if item["filename"] == filename), None)
    if not match:
        return jsonify({"error": "File not found"}), 404

    s3 = get_s3_client()
    try:
        obj = s3.get_object(Bucket=S3_OUTPUT_BUCKET, Key=match["key"])
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code")
        if code in ["NoSuchKey", "404"]:
            return jsonify({"error": "File not found"}), 404
        if code == "AccessDenied":
            return jsonify({"error": "Access denied"}), 403
        raise

    body = obj['Body']
    response = Response(
        stream_with_context(body.iter_chunks(chunk_size=8192)),
        mimetype=obj.get('ContentType', 'application/octet-stream'),
        headers={
            'Content-Disposition': f'attachment; filename="{filename}"'
        }
    )
    return response

@app.route('/api/artifacts/<int:run_id>/download', methods=['GET'])
def download_artifacts(run_id):
    import io
    import zipfile
    from flask import send_file

    run = get_run_details(run_id)
    if not run:
        return jsonify({"error": "Run not found"}), 404

    files = build_artifact_files(run["date"])
    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        s3 = get_s3_client()
        for item in files:
            try:
                obj = s3.get_object(Bucket=S3_OUTPUT_BUCKET, Key=item["key"])
                content = obj['Body'].read()
                zf.writestr(item["filename"], content)
            except ClientError as e:
                if e.response.get("Error", {}).get("Code") in ["NoSuchKey", "404", "NoSuchBucket"]:
                    continue
                raise

    memory_file.seek(0)
    return send_file(
        memory_file,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f"DA_Workflow_Artifacts_{run['date']}.zip"
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
