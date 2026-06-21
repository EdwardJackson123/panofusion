import os
import shutil
import sys
from pathlib import Path

# Ensure the backend directory is on sys.path so relative imports work
_backend_dir = Path(__file__).resolve().parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from config import PROJECTS_DIR, find_metashape_exe
from routes.project import router as project_router
from routes.pipeline import router as pipeline_router, shutdown_pipelines
from routes.viewer import router as viewer_router
from ws.progress import ProgressManager

def _metashape_available() -> bool:
    exe = find_metashape_exe()
    return Path(exe).exists() or shutil.which(exe) is not None

app = FastAPI(
    title="PanoFusion Backend",
    version="0.1.0",
    description="Automated panoramic reconstruction pipeline with Metashape",
)

# CORS — allow Electron/Vite dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:8765",
        "http://localhost:8766",
        "http://localhost:8767",
        "http://localhost:8768",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8765",
        "http://127.0.0.1:8766",
        "http://127.0.0.1:8767",
        "http://127.0.0.1:8768",
        "app://.",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Shared state
progress_manager = ProgressManager()
app.state.progress_manager = progress_manager
app.state.active_pipelines: dict = {}  # project_name -> thread

# Register routes
app.include_router(project_router, prefix="/api")
app.include_router(pipeline_router, prefix="/api")
app.include_router(viewer_router, prefix="/api")


# ── Health check ──
@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "edition": "metashape",
        "metashape_available": _metashape_available(),
        "timestamp": datetime.now().isoformat(),
    }


# ── WebSocket for real-time progress ──
@app.websocket("/ws/{project_name}")
async def websocket_endpoint(websocket: WebSocket, project_name: str):
    await progress_manager.connect(websocket, project_name)
    try:
        while True:
            data = await websocket.receive_text()
            if data == 'ping':
                await websocket.send_text('pong')
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        progress_manager.disconnect(websocket, project_name)


@app.on_event("startup")
async def startup_event():
    # Store event loop for thread-safe WebSocket broadcasting
    import asyncio
    progress_manager.set_loop(asyncio.get_running_loop())
    print(f"[PanoFusion] Backend starting on port {os.environ.get('PANOFUSION_ACTUAL_PORT', os.environ.get('PANOFUSION_PORT', '8765'))}")
    print(f"[PanoFusion] Metashape available: {_metashape_available()}")
    print(f"[PanoFusion] Projects dir: {PROJECTS_DIR}")


@app.on_event("shutdown")
async def shutdown_event():
    print("[PanoFusion] Backend shutting down")
    shutdown_pipelines()
    app.state.active_pipelines.clear()


def _port_free(port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def main():
    preferred = int(os.environ.get("PANOFUSION_PORT", "8765"))
    port = preferred
    if not _port_free(port):
        for fallback in (8766, 8767, 8768):
            if _port_free(fallback):
                port = fallback
                break
    os.environ["PANOFUSION_ACTUAL_PORT"] = str(port)
    print(f"[PanoFusion] Starting backend on http://127.0.0.1:{port}" +
          (f" (preferred {preferred} was busy)" if port != preferred else ""))
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=port,
        log_level="info",
        reload=False,
    )


if __name__ == "__main__":
    main()
