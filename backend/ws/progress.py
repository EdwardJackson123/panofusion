"""
WebSocket progress manager — broadcasts pipeline progress to connected clients.
Thread-safe: uses asyncio.run_coroutine_threadsafe for cross-thread broadcasting.
"""
import json
import asyncio
from fastapi import WebSocket


class ProgressManager:
    def __init__(self):
        self._connections: dict[str, set[WebSocket]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        """Store the main event loop for thread-safe broadcasting."""
        self._loop = loop

    async def connect(self, websocket: WebSocket, project_name: str):
        await websocket.accept()
        if project_name not in self._connections:
            self._connections[project_name] = set()
        self._connections[project_name].add(websocket)
        print(f"[WS] Client connected to {project_name} (total: {len(self._connections[project_name])})")

    def disconnect(self, websocket: WebSocket, project_name: str):
        if project_name in self._connections:
            self._connections[project_name].discard(websocket)
            print(f"[WS] Client disconnected from {project_name}")
            if not self._connections[project_name]:
                del self._connections[project_name]

    async def _broadcast_async(self, project_name: str, msg_type: str, data: dict):
        """Internal async broadcast implementation."""
        if project_name not in self._connections:
            return
        message = json.dumps({"type": msg_type, "data": data}, ensure_ascii=False)
        dead = set()
        for ws in self._connections.get(project_name, set()):
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self.disconnect(ws, project_name)

    def broadcast(self, project_name: str, msg_type: str, data: dict):
        """
        Thread-safe broadcast — can be called from any thread.
        Schedules the async broadcast on the main event loop via run_coroutine_threadsafe.
        """
        if not self._loop:
            # Try to get the running loop
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                pass

        if not self._loop:
            return

        coro = self._broadcast_async(project_name, msg_type, data)
        asyncio.run_coroutine_threadsafe(coro, self._loop)


# Singleton
progress_manager = ProgressManager()
