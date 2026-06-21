"""
Pipeline control API routes — start/stop/progress/logs
"""
import json
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from config import PROJECTS_DIR
from routes.project_names import project_dir, safe_project_name
from services.colmap_pipeline import run_pipeline

router = APIRouter()

# In-memory state for active runs
_pipeline_state: dict[str, dict] = {}
_state_lock = threading.Lock()
_MAX_LOGS = 1000


def _idle_progress(message: str = "已停止") -> dict:
    return {
        "phase": "idle",
        "overall": 0,
        "stageMessage": message,
        "extractProgress": 0,
        "alignProgress": 0,
        "exportProgress": 0,
    }


def _terminate_process_tree(proc):
    if not proc or proc.poll() is not None:
        return
    try:
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        else:
            proc.kill()
        proc.wait(timeout=2)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _terminate_active_processes(state: dict):
    lock = state.get("lock")
    if lock:
        with lock:
            processes = list(state.get("processes", set()))
    else:
        processes = list(state.get("processes", set()))
    for proc in processes:
        _terminate_process_tree(proc)


def shutdown_pipelines():
    for state in list(_pipeline_state.values()):
        state["running"] = False
        _terminate_active_processes(state)


def _load_project_config(name: str) -> dict:
    config_path = project_dir(PROJECTS_DIR, name) / "config.json"
    if not config_path.exists():
        raise HTTPException(404, f"Project '{name}' not found")
    return json.loads(config_path.read_text(encoding="utf-8"))


@router.post("/pipeline/{name}/start")
async def start_pipeline(name: str, request: Request):
    """Start the pipeline for a project"""
    name = safe_project_name(name)
    config = _load_project_config(name)

    with _state_lock:
        if name in _pipeline_state and _pipeline_state[name].get("running"):
            raise HTTPException(409, "Pipeline already running")

        # Initialize state
        _pipeline_state[name] = {
            "running": True,
            "progress": {
                "phase": "extracting",
                "overall": 0,
                "stageMessage": "初始化...",
                "extractProgress": 0,
                "alignProgress": 0,
                "exportProgress": 0,
            },
            "logs": [],
            "processes": set(),
            "lock": threading.Lock(),
        }

    pm = request.app.state.progress_manager

    def update_progress(phase, overall, stage_message, extract=0, align=0, export_p=0):
        state = _pipeline_state.get(name)
        if not state:
            return
        if not state.get("running") and phase != "idle":
            return
        data = {
            "phase": phase,
            "overall": overall,
            "stageMessage": stage_message,
            "extractProgress": extract,
            "alignProgress": align,
            "exportProgress": export_p,
        }
        state["progress"] = data
        pm.broadcast(name, "progress", data)

    def add_log(level, message):
        state = _pipeline_state.get(name)
        if not state:
            return
        entry = {"timestamp": datetime.now().isoformat(), "level": level, "message": message}
        state["logs"].append(entry)
        if len(state["logs"]) > _MAX_LOGS:
            state["logs"] = state["logs"][-_MAX_LOGS:]
        pm.broadcast(name, "log", entry)

    def is_stopped():
        return not _pipeline_state.get(name, {}).get("running", False)

    def register_process(proc):
        state = _pipeline_state.get(name)
        if not state or not proc:
            return
        with state["lock"]:
            state["processes"].add(proc)

    def unregister_process(proc):
        state = _pipeline_state.get(name)
        if not state or not proc:
            return
        with state["lock"]:
            state["processes"].discard(proc)

    def run():
        try:
            run_pipeline(
                config=config,
                update_progress=update_progress,
                add_log=add_log,
                is_stopped=is_stopped,
                register_process=register_process,
                unregister_process=unregister_process,
            )
            phase = _pipeline_state.get(name, {}).get("progress", {}).get("phase")
            if is_stopped():
                update_progress("idle", 0, "已停止", 0, 0, 0)
            elif phase not in {"done", "error", "idle"}:
                update_progress("done", 100, "处理完成", 100, 100, 100)
        except Exception as exc:
            if is_stopped():
                add_log("warn", "重建已停止")
                update_progress("idle", 0, "已停止", 0, 0, 0)
            else:
                add_log("error", str(exc))
                progress = _pipeline_state.get(name, {}).get("progress", _idle_progress(""))
                update_progress(
                    "error",
                    progress.get("overall", 0),
                    f"错误: {exc}",
                    progress.get("extractProgress", 0),
                    progress.get("alignProgress", 0),
                    progress.get("exportProgress", 0),
                )
        finally:
            if name in _pipeline_state:
                _terminate_active_processes(_pipeline_state[name])
                _pipeline_state[name]["running"] = False
            request.app.state.active_pipelines.pop(name, None)

    thread = threading.Thread(target=run, daemon=True)
    request.app.state.active_pipelines[name] = thread
    thread.start()

    return {"success": True, "data": None}


@router.post("/pipeline/{name}/stop")
async def stop_pipeline(name: str, request: Request):
    """Request pipeline stop (graceful)"""
    name = safe_project_name(name)
    if name in _pipeline_state:
        state = _pipeline_state[name]
        state["running"] = False
        state["progress"] = _idle_progress()
        entry = {
            "timestamp": datetime.now().isoformat(),
            "level": "warn",
            "message": "已请求停止重建，正在终止后台进程...",
        }
        state["logs"].append(entry)
        if len(state["logs"]) > _MAX_LOGS:
            state["logs"] = state["logs"][-_MAX_LOGS:]
        pm = request.app.state.progress_manager
        pm.broadcast(name, "log", entry)
        pm.broadcast(name, "progress", state["progress"])
        _terminate_active_processes(state)
    return {"success": True, "data": None}


@router.post("/pipeline/{name}/reset")
async def reset_pipeline(name: str, request: Request):
    """Clear a finished/failed pipeline state so the setup screen can be shown."""
    name = safe_project_name(name)
    with _state_lock:
        state = _pipeline_state.get(name)
        if state is None:
            state = {
                "running": False,
                "progress": _idle_progress(""),
                "logs": [],
                "processes": set(),
                "lock": threading.Lock(),
            }
            _pipeline_state[name] = state
        state["running"] = False

    _terminate_active_processes(state)
    with state["lock"]:
        state["processes"] = set()
    state["progress"] = _idle_progress("")
    state["logs"] = []
    request.app.state.active_pipelines.pop(name, None)

    pm = request.app.state.progress_manager
    pm.broadcast(name, "progress", state["progress"])
    return {"success": True, "data": None}


@router.get("/pipeline/{name}/progress")
async def get_progress(name: str):
    """Get current pipeline progress"""
    name = safe_project_name(name)
    state = _pipeline_state.get(name, {})
    return {
        "success": True,
        "data": state.get("progress", {
            "phase": "idle",
            "overall": 0,
            "stageMessage": "",
            "extractProgress": 0,
            "alignProgress": 0,
            "exportProgress": 0,
        }),
    }


@router.get("/pipeline/{name}/logs")
async def get_logs(name: str):
    """Get pipeline logs"""
    name = safe_project_name(name)
    state = _pipeline_state.get(name, {})
    return {"success": True, "data": state.get("logs", [])}
