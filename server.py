"""
DON v3.0 web server — FastAPI + WebSockets.

Serves the JARVIS dashboard and connects it to the SAME working
Assistant used by the CLI, so the brain, tools, and memory behave identically.

Endpoints:
  GET  /                 -> dashboard page
  POST /api/chat         -> {text} -> {reply}
  POST /api/chat_stream  -> streamed plain-text reply
  GET  /api/status       -> model / brain-ready / uptime
  GET  /api/reminders    -> pending reminders
  WS   /ws               -> live system stats (CPU/memory/uptime)
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import json
import traceback

import config

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
    from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
    from fastapi.staticfiles import StaticFiles
    from fastapi.templating import Jinja2Templates
    from fastapi.concurrency import run_in_threadpool
except Exception as exc:  # pragma: no cover
    raise SystemExit(
        "FastAPI is required. Install: pip install -r requirements.txt\n"
        f"(import error: {exc})"
    )

from assistant import Assistant

app = FastAPI(title="DON", version="3.0")

_here = config.BASE_DIR / "web"
templates = Jinja2Templates(directory=str(_here / "templates"))
app.mount("/static", StaticFiles(directory=str(_here / "static")), name="static")

assistant = Assistant()
_started_at = _dt.datetime.now()


def _uptime() -> str:
    d = _dt.datetime.now() - _started_at
    s = int(d.total_seconds())
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _stats() -> dict:
    try:
        import psutil
        return {"cpu": psutil.cpu_percent(interval=None),
                "memory": psutil.virtual_memory().percent}
    except Exception:
        return {"cpu": 0, "memory": 0}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        request=request, name="index.html",
        context={"model": assistant.brain.model if assistant.brain_ready else config.GEMINI_MODEL},
    )


@app.post("/api/chat")
async def api_chat(request: Request):
    """Non-streaming fallback: send text, get full reply."""
    try:
        data = await request.json()
        text = (data or {}).get("text", "")
        reply = await run_in_threadpool(assistant.handle, text)
        return JSONResponse({"reply": reply})
    except Exception as exc:
        traceback.print_exc()
        return JSONResponse({"reply": f"Server error: {exc}"}, status_code=200)


@app.post("/api/chat_stream")
async def api_chat_stream(request: Request):
    """Stream the reply as plain-text chunks."""
    import queue as _queue
    import threading

    try:
        data = await request.json()
    except Exception:
        data = {}
    text = (data or {}).get("text", "")

    q: _queue.Queue = _queue.Queue()
    SENTINEL = object()

    def worker():
        try:
            for piece in assistant.handle_stream(text):
                q.put(piece)
        except Exception as exc:
            traceback.print_exc()
            q.put(f"Apologies sir, I encountered an error: {exc}")
        finally:
            q.put(SENTINEL)

    threading.Thread(target=worker, daemon=True).start()

    async def gen():
        while True:
            try:
                piece = await asyncio.to_thread(q.get, timeout=60)
            except Exception:
                break
            if piece is SENTINEL:
                break
            yield piece

    return StreamingResponse(gen(), media_type="text/plain")


@app.get("/api/status")
async def api_status():
    return {
        "model": assistant.brain.model if assistant.brain_ready else config.GEMINI_MODEL,
        "brain_ready": assistant.brain_ready,
        "uptime": _uptime(),
        "network": "cloud (Gemini)",
    }


@app.get("/api/reminders")
async def api_reminders():
    try:
        return {"reminders": assistant.memory.pending_reminders()}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.websocket("/ws")
async def ws(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            s = _stats()
            await ws.send_text(json.dumps({
                "cpu": s["cpu"], "memory": s["memory"], "uptime": _uptime(),
            }))
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
