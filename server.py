import os
import sys
import subprocess
import asyncio
import threading
import json
from datetime import datetime
from typing import List, Dict, Optional
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Add current directory to path so we can import main.py
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from main import PIPELINE, LOG_FILE

app = FastAPI(title="DA Workflow UI")

# --- Pipeline State Manager ---

class StepStatus(BaseModel):
    name: str
    script: str
    status: str = "idle"  # idle, running, success, failed
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    duration: Optional[str] = None
    return_code: Optional[int] = None
    output_files: List[str] = []

class PipelineState:
    def __init__(self):
        self.steps: List[StepStatus] = [
            StepStatus(name=s["name"], script=s["script"]) for s in PIPELINE
        ]
        self.current_step_index: int = -1
        self.is_running: bool = False
        self.logs: List[str] = []
        self._log_queue = asyncio.Queue()
        self.lock = threading.Lock()

    def reset(self):
        with self.lock:
            for step in self.steps:
                step.status = "idle"
                step.start_time = None
                step.end_time = None
                step.duration = None
                step.return_code = None
                step.output_files = []
            self.current_step_index = -1
            self.is_running = False
            self.logs = []
            # Clear queue (asyncio.Queue doesn't have clear, so we just replace it)
            self._log_queue = asyncio.Queue()

    def add_log(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted_message = f"[{timestamp}] {message}"
        self.logs.append(formatted_message)
        # Add to queue for streaming
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.call_soon_threadsafe(self._log_queue.put_nowait, formatted_message)
        except Exception:
            pass

    def update_step(self, index: int, **kwargs):
        with self.lock:
            step = self.steps[index]
            for key, value in kwargs.items():
                setattr(step, key, value)

state = PipelineState()

# --- Execution Logic ---

async def run_pipeline():
    if state.is_running:
        return
    
    state.reset()
    state.is_running = True
    state.add_log("Starting Pipeline Execution...")

    try:
        for i, step_config in enumerate(PIPELINE):
            state.current_step_index = i
            step = state.steps[i]
            
            state.update_step(i, status="running", start_time=datetime.now().isoformat())
            state.add_log(f"Running Step {i+1}/{len(PIPELINE)}: {step.name}")

            script_path = os.path.abspath(step_config["script"])
            if not os.path.exists(script_path):
                error_msg = f"Script not found: {script_path}"
                state.add_log(f"ERROR: {error_msg}")
                state.update_step(i, status="failed", end_time=datetime.now().isoformat())
                raise Exception(error_msg)

            # Run the script
            start_t = datetime.now()
            process = await asyncio.create_subprocess_exec(
                sys.executable, script_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=os.path.dirname(os.path.abspath(__file__))
            )

            try:
                # Read logs in real-time
                try:
                    async for line in process.stdout:
                        try:
                            msg = line.decode('utf-8', errors='replace').strip()
                            if msg:
                                state.add_log(msg)
                        except Exception as e:
                            print(f"Error decoding log line: {e}")
                except Exception as e:
                    state.add_log(f"Error reading process output: {e}")

                state.add_log(f"Waiting for process to finish...")
                return_code = await process.wait()
                end_t = datetime.now()
                duration = str(end_t - start_t).split(".")[0]

                state.update_step(i, 
                    status="success" if return_code == 0 else "failed",
                    end_time=end_t.isoformat(),
                    duration=duration,
                    return_code=return_code
                )

                if return_code != 0:
                    state.add_log(f"Step failed with return code {return_code}. Stopping pipeline.")
                    state.is_running = False
                    return

                state.add_log(f"Step completed: {step.name} (Duration: {duration})")
                state.add_log("--- Preparing next step ---")
            except Exception as e:
                state.add_log(f"Unexpected error in loop for step {step.name}: {str(e)}")
                state.update_step(i, status="failed")
                state.is_running = False
                return

        state.add_log("Pipeline completed successfully!")
    except Exception as e:
        state.add_log(f"Pipeline stopped due to error: {str(e)}")
    finally:
        state.is_running = False

# --- API Endpoints ---

@app.get("/api/pipeline")
async def get_pipeline():
    return {
        "steps": state.steps,
        "is_running": state.is_running,
        "current_step_index": state.current_step_index
    }

@app.post("/api/execute")
async def execute_pipeline(background_tasks: BackgroundTasks):
    if state.is_running:
        raise HTTPException(status_code=400, detail="Pipeline is already running")
    
    background_tasks.add_task(run_pipeline)
    return {"message": "Pipeline started"}

@app.get("/api/logs")
async def stream_logs():
    async def log_generator():
        # First send all existing logs
        for log in state.logs:
            yield f"data: {json.dumps({'message': log})}\n\n"
        
        # Then stream new logs
        while True:
            log = await state._log_queue.get()
            yield f"data: {json.dumps({'message': log})}\n\n"

    return StreamingResponse(log_generator(), media_type="text/event-stream")

# --- Artifacts Logic ---

OUTPUT_DIRS = [
    "household_viewership_memberwise_output",
    "sessions/logo/household_viewership_memberwise_output",
    "sessions/fp/output",
    "sessions/merging/sessions_without_rejuvenation",
    "sessions/merging/sessions_with_rejuvenation",
    "sessions/merging/Final_merged_file",
    "statement_file/qualifier_output",
    "pipeline"
]

@app.get("/api/outputs")
async def get_outputs():
    artifacts = []
    base_path = os.path.dirname(os.path.abspath(__file__))
    
    for rel_dir in OUTPUT_DIRS:
        full_dir = os.path.join(base_path, rel_dir)
        if os.path.exists(full_dir) and os.path.isdir(full_dir):
            for file in os.listdir(full_dir):
                if file.endswith((".csv", ".txt", ".xlsx")):
                    file_path = os.path.join(full_dir, file)
                    stats = os.stat(file_path)
                    artifacts.append({
                        "name": file,
                        "path": os.path.relpath(file_path, base_path),
                        "size": f"{stats.st_size / 1024:.1f} KB",
                        "modified": datetime.fromtimestamp(stats.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                        "category": rel_dir.split("/")[-1]
                    })
    
    return sorted(artifacts, key=lambda x: x["modified"], reverse=True)

# Serve UI
os.makedirs("ui", exist_ok=True)
app.mount("/", StaticFiles(directory="ui", html=True), name="ui")

if __name__ == "__main__":
    import uvicorn
    print("\nStarting DA Workflow Server on http://localhost:8000\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)
