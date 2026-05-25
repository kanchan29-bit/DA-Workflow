import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'workflow.db')

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS workflow_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        status TEXT NOT NULL,
        started_at TEXT,
        finished_at TEXT,
        duration_seconds REAL,
        trigger_type TEXT,
        error_message TEXT
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS workflow_steps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER,
        step_index INTEGER,
        name TEXT,
        status TEXT,
        started_at TEXT,
        finished_at TEXT,
        duration_seconds REAL,
        log_output TEXT,
        FOREIGN KEY (run_id) REFERENCES workflow_runs(id)
    )
    ''')
    conn.commit()
    conn.close()

def create_run(date_str, trigger_type="manual"):
    conn = get_db()
    cursor = conn.cursor()
    started_at = datetime.now().isoformat()
    cursor.execute('''
        INSERT INTO workflow_runs (date, status, started_at, trigger_type)
        VALUES (?, ?, ?, ?)
    ''', (date_str, "Running", started_at, trigger_type))
    run_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return run_id

def update_run_status(run_id, status, error_message=None):
    conn = get_db()
    cursor = conn.cursor()
    
    if status in ["Success", "Failed", "Stopped"]:
        cursor.execute("SELECT started_at FROM workflow_runs WHERE id=?", (run_id,))
        started_at_str = cursor.fetchone()["started_at"]
        started_at = datetime.fromisoformat(started_at_str) if started_at_str else datetime.now()
        finished_at = datetime.now()
        duration = (finished_at - started_at).total_seconds()
        
        cursor.execute('''
            UPDATE workflow_runs 
            SET status=?, finished_at=?, duration_seconds=?, error_message=?
            WHERE id=?
        ''', (status, finished_at.isoformat(), duration, error_message, run_id))
    else:
        cursor.execute('''
            UPDATE workflow_runs SET status=? WHERE id=?
        ''', (status, run_id))
        
    conn.commit()
    conn.close()

def create_step(run_id, step_index, name):
    conn = get_db()
    cursor = conn.cursor()
    started_at = datetime.now().isoformat()
    cursor.execute('''
        INSERT INTO workflow_steps (run_id, step_index, name, status, started_at, log_output)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (run_id, step_index, name, "Running", started_at, ""))
    step_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return step_id

def update_step_status(step_id, status, log_output=None):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT started_at, log_output FROM workflow_steps WHERE id=?", (step_id,))
    row = cursor.fetchone()
    started_at_str = row["started_at"]
    current_log = row["log_output"] or ""
    
    if log_output is not None:
        current_log += log_output
        
    if status in ["Success", "Failed", "Skipped", "Stopped"]:
        started_at = datetime.fromisoformat(started_at_str) if started_at_str else datetime.now()
        finished_at = datetime.now()
        duration = (finished_at - started_at).total_seconds()
        
        cursor.execute('''
            UPDATE workflow_steps 
            SET status=?, finished_at=?, duration_seconds=?, log_output=?
            WHERE id=?
        ''', (status, finished_at.isoformat(), duration, current_log, step_id))
    else:
        cursor.execute('''
            UPDATE workflow_steps SET status=?, log_output=? WHERE id=?
        ''', (status, current_log, step_id))
        
    conn.commit()
    conn.close()

def append_step_log(step_id, log_output):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT log_output FROM workflow_steps WHERE id=?", (step_id,))
    row = cursor.fetchone()
    current_log = row["log_output"] or ""
    current_log += log_output
    cursor.execute("UPDATE workflow_steps SET log_output=? WHERE id=?", (current_log, step_id))
    conn.commit()
    conn.close()

def get_recent_runs(limit=10):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM workflow_runs ORDER BY id DESC LIMIT ?
    ''', (limit,))
    runs = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return runs

def get_run_details(run_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM workflow_runs WHERE id=?", (run_id,))
    run = dict(cursor.fetchone() or {})
    if run:
        cursor.execute("SELECT * FROM workflow_steps WHERE run_id=? ORDER BY step_index", (run_id,))
        run["steps"] = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return run

def check_run_exists_for_date(date_str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM workflow_runs WHERE date=? AND status IN ('Success', 'Running')", (date_str,))
    row = cursor.fetchone()
    conn.close()
    return row is not None

def get_successful_runs():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM workflow_runs WHERE status='Success' ORDER BY date DESC")
    runs = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return runs

def is_any_run_running():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM workflow_runs WHERE status='Running'")
    row = cursor.fetchone()
    conn.close()
    return row is not None

def delete_run_from_db(run_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM workflow_steps WHERE run_id=?", (run_id,))
    cursor.execute("DELETE FROM workflow_runs WHERE id=?", (run_id,))
    conn.commit()
    conn.close()
