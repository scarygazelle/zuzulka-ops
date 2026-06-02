from __future__ import annotations

import logging
import os
import traceback
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, field_validator

from .database import get_db, init_db
from .scheduler import recalculate_next_date, get_occurrences

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("zuzulka")

# Initialize database and run migrations
init_db()

app = FastAPI()

# ── Error Handlers ──
@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    log.error("Validation error: %s", exc.errors())
    return JSONResponse(status_code=422, content={"detail": exc.errors()})

@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception):
    log.error("Unhandled exception:\n%s", traceback.format_exc())
    return JSONResponse(status_code=500, content={"detail": str(exc)})

# ── Middleware for Home Assistant Ingress ──
@app.middleware("http")
async def ingress_path_middleware(request: Request, call_next):
    # Store ingress path in state — never mutate scope["root_path"]
    # Mutating scope breaks Starlette routing and causes 405 errors
    request.state.ingress_path = request.headers.get("X-Ingress-Path", "")
    return await call_next(request)

# ── Models ──
class TaskCreate(BaseModel):
    title: str
    event_date: str
    freq: str = "none"
    interval_days: int = 0
    is_floating: int = 1
    performer: str = ""
    category: str = "general"
    description: str = ""
    cost: float = 0.0

    @field_validator("interval_days", mode="before")
    @classmethod
    def coerce_interval(cls, v):
        try:
            return int(v or 0)
        except (ValueError, TypeError):
            return 0

    @field_validator("freq", mode="before")
    @classmethod
    def coerce_freq(cls, v):
        allowed = {"none", "daily", "weekly", "monthly", "custom"}
        return v if v in allowed else "none"

# ── API Routes ──

@app.get("/debug")
async def debug():
    """Quick health-check and DB status."""
    import sys
    with get_db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM zuzulka_tasks").fetchone()[0]
        history_count = conn.execute("SELECT COUNT(*) FROM event_log").fetchone()[0]
    return {
        "status": "ok",
        "python": sys.version,
        "task_count": count,
        "history_count": history_count
    }

@app.get("/tasks")
async def get_tasks():
    """Fetch all tasks."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM zuzulka_tasks ORDER BY done ASC, event_date ASC"
        ).fetchall()
        return [dict(r) for r in rows]

@app.post("/tasks", status_code=201)
async def create_task(task: TaskCreate):
    log.info("CREATE: %s", task.model_dump())
    with get_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO zuzulka_tasks 
            (title, event_date, freq, interval_days, is_floating, performer, category, description, cost, done)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                task.title,
                task.event_date,
                task.freq,
                task.interval_days,
                task.is_floating,
                task.performer,
                task.category,
                task.description,
                task.cost
            ),
        )
        conn.commit()
        return {"id": cursor.lastrowid, "status": "created"}

@app.put("/tasks/{task_id}")
async def update_task(task_id: int, task: TaskCreate):
    log.info("UPDATE %s: %s", task_id, task.model_dump())
    with get_db() as conn:
        result = conn.execute(
            """
            UPDATE zuzulka_tasks 
            SET title=?, event_date=?, freq=?, interval_days=?, is_floating=?, performer=?, category=?, description=?, cost=?, done=0
            WHERE id=?
            """,
            (
                task.title,
                task.event_date,
                task.freq,
                task.interval_days,
                task.is_floating,
                task.performer,
                task.category,
                task.description,
                task.cost,
                task_id
            ),
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Task not found")
        conn.commit()
        return {"status": "updated"}

@app.post("/tasks/{task_id}/done")
async def complete_task(task_id: int):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM zuzulka_tasks WHERE id=?", (task_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Task not found")
        task = dict(row)
        
        # 1. Log completion in event history log
        timestamp = datetime.utcnow().isoformat() + "Z"
        conn.execute(
            """
            INSERT INTO event_log (task_id, timestamp, event_date, category, performer, title, description, cost)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task["id"],
                timestamp,
                task["event_date"],
                task["category"],
                task["performer"],
                task["title"],
                task["description"],
                task["cost"]
            )
        )
        
        # 2. Recalculate next occurrence if recurring
        if task["freq"] != "none":
            next_date = recalculate_next_date(
                task["freq"],
                task["interval_days"],
                bool(task["is_floating"]),
                task["event_date"]
            )
            conn.execute(
                "UPDATE zuzulka_tasks SET event_date=?, done=0 WHERE id=?",
                (next_date, task_id)
            )
            conn.commit()
            return {"status": "done", "next_date": next_date}
        else:
            conn.execute(
                "UPDATE zuzulka_tasks SET done=1 WHERE id=?",
                (task_id,)
            )
            conn.commit()
            return {"status": "done", "next_date": None}

@app.delete("/tasks/{task_id}", status_code=204)
async def delete_task(task_id: int):
    with get_db() as conn:
        result = conn.execute("DELETE FROM zuzulka_tasks WHERE id=?", (task_id,))
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Task not found")
        conn.commit()

@app.get("/calendar-events")
async def get_calendar_events():
    """Generate calendar events for the next 3 months, expanding recurring events."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM zuzulka_tasks WHERE done=0"
        ).fetchall()
    events = []
    for row in rows:
        t = dict(row)
        for d in get_occurrences(t, months_ahead=3):
            events.append({
                "id": t["id"],
                "title": t["title"],
                "date": d,
                "freq": t["freq"]
            })
    return events

@app.get("/history")
async def get_history():
    """Fetch completed task history."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM event_log ORDER BY timestamp DESC LIMIT 100"
        ).fetchall()
        return [dict(r) for r in rows]

# ── Frontend Ingress Delivery ──
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    root_path = getattr(request.state, "ingress_path", "")
    html_file = os.path.join(os.path.dirname(__file__), "index.html")
    try:
        with open(html_file, "r", encoding="utf-8") as f:
            content = f.read()
        return HTMLResponse(content=content.replace("__ROOT_PATH__", root_path))
    except Exception as e:
        log.error("Failed to read index.html: %s", e)
        raise HTTPException(status_code=500, detail="Frontend template index.html not found.")
