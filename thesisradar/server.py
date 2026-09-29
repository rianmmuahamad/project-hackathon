"""HTTP API for the dashboard.

The server owns one background job at a time. A check spends API credits and
model tokens, so a second request is refused with the reason rather than queued
silently — the same rule the CLI follows.
"""

from __future__ import annotations

import json
import threading
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import engines
from .config import REPO_ROOT, settings
from .jev import describe as jev_describe
from .service import JobBusy, Service


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """The server owns the clock: the schedule runs exactly as long as it does.

    A misconfigured schedule must not stop the dashboard from serving, so the
    failure is printed once and the timer is simply left off.
    """
    try:
        state = SERVICE.start_schedule()
        print(f"schedule: {state['when']} on {state['days']} ({state['tz']}) — "
              f"next {state['next']}", flush=True)
    except Exception as err:  # noqa: BLE001 — a bad THESISRADAR_SCHEDULE_AT is not fatal
        print(f"schedule: disabled — {type(err).__name__}: {err}", flush=True)
    try:
        yield
    finally:
        SERVICE.stop_schedule()


app = FastAPI(title="Thesis Radar", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SERVICE = Service()
STATIC_DIR = REPO_ROOT / "web" / "dist"
_started = time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _guard(fn, *args, **kwargs) -> Any:
    """Run a service call, mapping expected failures onto honest HTTP codes."""
    try:
        return fn(*args, **kwargs)
    except JobBusy as err:
        raise HTTPException(status_code=409, detail=str(err)) from err
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    except Exception as err:  # noqa: BLE001 — surfaced verbatim, not swallowed
        raise HTTPException(status_code=500, detail=f"{type(err).__name__}: {err}") from err


# --------------------------------------------------------------------------
# reads
# --------------------------------------------------------------------------
@app.get("/api/health")
def health() -> dict[str, Any]:
    jev = jev_describe()
    return {
        "ok": True,
        "started_at": _started,
        "has_key": settings().has_key,
        "engine": engines.describe(),
        "jev": {"available": jev["available"], "model": jev["model"],
                "detail": jev["detail"]},
    }


@app.get("/api/stats")
def stats() -> dict[str, Any]:
    out = SERVICE.stats()
    out["schedule"] = SERVICE.schedule_state()
    return out


@app.get("/api/queue")
def queue() -> dict[str, Any]:
    return {"theses": SERVICE.queue()}


@app.get("/api/thesis/{thesis_id}")
def thesis_detail(thesis_id: str) -> dict[str, Any]:
    detail = SERVICE.thesis_detail(thesis_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"no thesis {thesis_id}")
    return detail


@app.get("/api/check/{check_id}")
def check_detail(check_id: str) -> dict[str, Any]:
    detail = SERVICE.check_detail(check_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"no check {check_id}")
    return detail


@app.get("/api/notifications")
def notifications(unread_only: bool = False) -> dict[str, Any]:
    return {"notifications": SERVICE.notifications(unread_only=unread_only)}


@app.get("/api/credits")
def credits() -> dict[str, Any]:
    return SERVICE.store.credits()


@app.get("/api/job")
def job() -> dict[str, Any]:
    return {"job": SERVICE.current_job()}


@app.get("/api/events")
def events() -> StreamingResponse:
    """Server-sent events: the live transcript of the running job."""
    def stream():
        last = 0
        idle = 0
        while idle < 900:  # ~15 min of silence ends the stream
            current = SERVICE.current_job()
            if current is None:
                yield "event: idle\ndata: {}\n\n"
                idle += 1
            else:
                events = current.get("events") or []
                for index in range(last, len(events)):
                    yield ("event: step\ndata: "
                           + json.dumps({**events[index], "index": index},
                                        ensure_ascii=False, default=str) + "\n\n")
                last = len(events)
                if current.get("state") != "running":
                    yield ("event: finished\ndata: "
                           + json.dumps({"state": current.get("state"),
                                         "error": current.get("error"),
                                         "result": current.get("result")},
                                        default=str) + "\n\n")
                    last = 0
                    idle = 0
                else:
                    idle = 0
            time.sleep(1)
    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# --------------------------------------------------------------------------
# writes
# --------------------------------------------------------------------------
def _background(kind: str, fn, *args, **kwargs) -> None:
    def runner() -> None:
        try:
            fn(*args, **kwargs)
        except Exception:  # noqa: BLE001 — recorded on the job by the service
            pass
    threading.Thread(target=runner, name=f"thesisradar-{kind}", daemon=True).start()


@app.post("/api/thesis")
def create_thesis(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return _guard(
        SERVICE.create_thesis,
        text=str(payload.get("statement") or payload.get("text") or ""),
        symbol=payload.get("symbol"),
        statement=payload.get("statement"),
        company_name=payload.get("company_name"),
        horizon=payload.get("horizon"),
        capture_baselines=payload.get("capture_baselines", True),
    )


@app.put("/api/thesis/{thesis_id}/claims")
def update_claims(thesis_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return _guard(SERVICE.update_claims, thesis_id, payload.get("claims") or [])


@app.post("/api/thesis/{thesis_id}/check")
def check_thesis(thesis_id: str, payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    thesis = SERVICE.store.get_thesis(thesis_id)
    if thesis is None:
        raise HTTPException(status_code=404, detail=f"no thesis {thesis_id}")
    if SERVICE.current_job() and SERVICE.current_job().get("state") == "running":
        raise HTTPException(status_code=409,
                            detail=f"a {SERVICE.current_job()['kind']} job is already running")
    _background("check", SERVICE.check_thesis, thesis_id,
                engine_override=payload.get("engine"), budget=payload.get("budget"))
    return {"started": True, "thesis_id": thesis_id,
            "job": SERVICE.current_job()}


@app.post("/api/check-all")
def check_all(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    if SERVICE.current_job() and SERVICE.current_job().get("state") == "running":
        raise HTTPException(status_code=409,
                            detail=f"a {SERVICE.current_job()['kind']} job is already running")
    # With email on (the default) the button runs the same sweep the timer runs,
    # so a manual click and a scheduled run produce the same digest. Turning it
    # off keeps the old behaviour with no mailer in the path at all.
    if payload.get("email", True):
        _background("check-all", SERVICE.scheduled_check, email=True)
    else:
        _background("check-all", SERVICE.check_all,
                    watch_only=not payload.get("all", False),
                    limit=payload.get("limit"),
                    engine_override=payload.get("engine"))
    return {"started": True, "job": SERVICE.current_job()}


@app.post("/api/watch")
def watch(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return _guard(SERVICE.watchlist, symbol=payload.get("symbol"),
                  action=str(payload.get("action") or "list"))


@app.post("/api/notifications/read")
def mark_read(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    SERVICE.store.mark_read(payload.get("id"))
    return {"ok": True}


@app.get("/api/draft")
def draft(subsector: str = "banks", count: int = 3) -> dict[str, Any]:
    return _guard(SERVICE.suggest_theses, sub_sector=subsector, count=count)


# --------------------------------------------------------------------------
# static dashboard
# --------------------------------------------------------------------------
if STATIC_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str) -> Any:
        candidate = STATIC_DIR / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        index = STATIC_DIR / "index.html"
        if index.is_file():
            return FileResponse(index)
        return JSONResponse({"detail": "dashboard build missing"}, status_code=404)
else:
    @app.get("/")
    def placeholder() -> dict[str, Any]:
        return {
            "detail": "the dashboard has not been built",
            "build": "cd web && npm install && npm run build",
            "api": "/api/queue",
        }