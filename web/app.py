import os
import sys
from pathlib import Path

# Add project root to sys.path to allow importing from 'src'
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

import uuid
import shutil
import threading
import asyncio
import json
from typing import Dict, Any, Optional
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.runner import run_search, SearchConfig

app = FastAPI()

# Directory for uploads
UPLOADS_DIR = Path("uploads")
UPLOADS_DIR.mkdir(exist_ok=True)

class RunState:
    def __init__(self):
        self.lock = threading.Lock()
        self.current_run_id: Optional[str] = None
        self.events_queue: Optional[asyncio.Queue] = None
        self.last_results: Optional[Dict[str, Any]] = None
        self.last_error: Optional[str] = None
        self.cancel_event = threading.Event()
        self.loop: Optional[asyncio.AbstractEventLoop] = None

state = RunState()
app.mount("/static", StaticFiles(directory="web/static"), name="static")

@app.get("/")
async def get_index():
    return FileResponse("web/static/index.html")

def emit_to_queue(event_type: str, data: Dict[str, Any]):
    if state.loop and state.events_queue:
        event = {"type": event_type, "payload": data}
        state.loop.call_soon_threadsafe(state.events_queue.put_nowait, event)

@app.post("/api/run")
async def start_run(
    request: Request,
    resume: UploadFile = File(...),
    skills: str = Form(...),
    remote: str = Form("false"),
    max_pages: str = Form("2"),
    min_skill_match: str = Form(""),
    model: str = Form("llama3.1"),
    no_llm: str = Form("false"),
    headless: str = Form("false"),
    captcha_wait_s: str = Form("120"),
    google_domain: str = Form("google.com"),
    output: str = Form("results.json")
):
    if not state.lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A search is already in progress.")

    run_id = str(uuid.uuid4())
    state.current_run_id = run_id
    state.events_queue = asyncio.Queue()
    state.cancel_event.clear()
    state.loop = asyncio.get_running_loop()
    
    # Save uploaded resume
    upload_path = UPLOADS_DIR / f"{run_id}_{resume.filename}"
    with open(upload_path, "wb") as buffer:
        shutil.copyfileobj(resume.file, buffer)
    
    # Parsing args
    try:
        min_match_val = int(min_skill_match) if min_skill_match else 0
        config = SearchConfig(
            resume_path=str(upload_path.absolute()),
            skills=[s.strip() for s in skills.split(",")],
            remote=remote.lower() == "true",
            max_pages=int(max_pages),
            min_skill_match=min_match_val,
            model=model,
            no_llm=no_llm.lower() == "true",
            headless=headless.lower() == "true",
            captcha_wait_s=int(captcha_wait_s),
            google_domain=google_domain,
            output_path=output
        )
    except Exception as e:
        state.lock.release()
        upload_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Invalid parameters: {e}")

    def thread_target():
        try:
            def emit(event_type, data):
                emit_to_queue(event_type, data)
            
            def cancel_check():
                return state.cancel_event.is_set()

            results = run_search(config, emit, cancel_check=cancel_check)
            state.last_results = results
            emit_to_queue("finish", {"results": results, "matches": [r["url"] for r in results if r.get("status") == "match"]})
        except Exception as e:
            state.last_error = str(e)
            emit_to_queue("error", {"message": str(e)})
        finally:
            state.lock.release()
            state.current_run_id = None
            if upload_path.exists():
                upload_path.unlink()

    thread = threading.Thread(target=thread_target, daemon=True)
    thread.start()

    return {"run_id": run_id}

@app.get("/api/stream/{run_id}")
async def stream_events(run_id: str):
    if state.current_run_id != run_id:
        raise HTTPException(status_code=404, detail="Run ID not found or not active")
    
    async def event_generator():
        while True:
            try:
                event = await asyncio.wait_for(state.events_queue.get(), timeout=20.0)
                yield f"data: {json.dumps(event)}\n\n"
            except asyncio.TimeoutError:
                yield "data: {\"type\": \"ping\"}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'data': {'message': str(e)}})}\n\n"
                break

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/api/status/{run_id}")
async def get_status(run_id: str):
    if state.current_run_id != run_id:
        return {"state": "done" if state.last_results else "error"}
    return {"state": "running"}

@app.post("/api/cancel/{run_id}")
async def cancel_run(run_id: str):
    if state.current_run_id == run_id:
        state.cancel_event.set()
        return {"message": "Cancellation requested"}
    raise HTTPException(status_code=404, detail="Run ID not found")

@app.get("/api/result")
async def get_result():
    if state.last_results is None:
        raise HTTPException(status_code=404, detail="No results available")
    return state.last_results

@app.get("/api/query")
async def get_query(skills: str, remote: str = "false"):
    from src.search import build_query
    skill_list = [s.strip() for s in skills.split(",")]
    query = build_query(skill_list, remote.lower() == "true")
    return {"query": query}
