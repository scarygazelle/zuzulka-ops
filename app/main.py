from __future__ import annotations  # enables list[str] on Python 3.8

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, validator
from contextlib import contextmanager
from datetime import date, timedelta
from typing import List, Optional
import sqlite3
import logging
import traceback

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("zuzulka")

# ─────────────────────────────────────────────
#  Database
# ─────────────────────────────────────────────
DB_PATH = "/data/zuzulka.db"


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def get_columns(conn) -> set:
    rows = conn.execute("PRAGMA table_info(zuzulka_tasks)").fetchall()
    return {row["name"] for row in rows}


def init_db():
    with get_db() as conn:
        # Create table with all known columns (only runs on a fresh DB)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS zuzulka_tasks (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                title          TEXT    NOT NULL,
                event_date     TEXT    NOT NULL,
                freq           TEXT    DEFAULT 'none',
                interval_days  INTEGER DEFAULT 0,
                done           INTEGER DEFAULT 0,
                task_type      TEXT    DEFAULT 'task'
            )
        """)
        # Migrate existing DB: safely add any missing columns
        existing = get_columns(conn)
        migrations = [
            ("freq",          "TEXT    DEFAULT 'none'"),
            ("interval_days", "INTEGER DEFAULT 0"),
            ("done",          "INTEGER DEFAULT 0"),
            ("task_type",     "TEXT    DEFAULT 'task'"),
        ]
        for col, definition in migrations:
            if col not in existing:
                conn.execute(f"ALTER TABLE zuzulka_tasks ADD COLUMN {col} {definition}")
                log.info("Migration: added column '%s'", col)
        conn.commit()


# ─────────────────────────────────────────────
#  App
# ─────────────────────────────────────────────
app = FastAPI()
init_db()


# ── Global error handlers — always return JSON, never a blank 500 ──
@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    log.error("Validation error: %s", exc.errors())
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception):
    log.error("Unhandled exception:\n%s", traceback.format_exc())
    return JSONResponse(status_code=500, content={"detail": str(exc)})


@app.middleware("http")
async def ingress_path_middleware(request: Request, call_next):
    # Store ingress path in state — never mutate scope["root_path"]
    # Mutating scope breaks Starlette routing and causes 405 errors
    request.state.ingress_path = request.headers.get("X-Ingress-Path", "")
    return await call_next(request)


# ─────────────────────────────────────────────
#  Models
# ─────────────────────────────────────────────
class TaskCreate(BaseModel):
    title: str
    event_date: str
    freq: str = "none"
    interval_days: int = 0

    @validator("interval_days", pre=True, always=True)
    def coerce_interval(cls, v):
        try:
            return int(v or 0)
        except (ValueError, TypeError):
            return 0

    @validator("freq", pre=True, always=True)
    def coerce_freq(cls, v):
        allowed = {"none", "daily", "weekly", "monthly", "custom"}
        return v if v in allowed else "none"


# ─────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────
def next_occurrences(task: dict, months_ahead: int = 3) -> List[str]:
    """
    Return all future occurrence dates for a recurring task,
    from today up to `months_ahead` months from now.
    For 'none' tasks returns just the original event_date.
    """
    freq = task["freq"]
    start = date.fromisoformat(task["event_date"])
    today = date.today()
    cutoff = today + timedelta(days=months_ahead * 31)

    if freq == "none":
        return [task["event_date"]]

    if freq == "daily":
        delta = timedelta(days=1)
    elif freq == "weekly":
        delta = timedelta(weeks=1)
    elif freq == "monthly":
        delta = timedelta(days=30)
    elif freq == "custom":
        delta = timedelta(days=max(task["interval_days"] or 1, 1))
    else:
        return [task["event_date"]]

    # Advance start to first occurrence >= today
    current = start
    while current < today:
        current += delta

    dates = []
    while current <= cutoff:
        dates.append(current.isoformat())
        current += delta
    return dates


def advance_recurring_task(conn: sqlite3.Connection, task: dict) -> None:
    """Bump event_date to next future occurrence after marking done."""
    freq = task["freq"]
    if freq == "none":
        return

    today = date.today()
    event = date.fromisoformat(task["event_date"])

    if freq == "daily":
        delta = timedelta(days=1)
    elif freq == "weekly":
        delta = timedelta(weeks=1)
    elif freq == "monthly":
        delta = timedelta(days=30)
    elif freq == "custom":
        delta = timedelta(days=max(task["interval_days"] or 1, 1))
    else:
        return

    while event <= today:
        event += delta

    conn.execute(
        "UPDATE zuzulka_tasks SET event_date=?, done=0 WHERE id=?",
        (event.isoformat(), task["id"]),
    )
    conn.commit()


# ─────────────────────────────────────────────
#  API Routes
# ─────────────────────────────────────────────
@app.get("/debug")
async def debug():
    """Quick health-check — open in browser to verify the API is alive."""
    import sys
    with get_db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM zuzulka_tasks").fetchone()[0]
    return {"status": "ok", "python": sys.version, "task_count": count}



@app.get("/tasks")
async def get_tasks():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM zuzulka_tasks ORDER BY done ASC, event_date ASC"
        ).fetchall()
        return [dict(r) for r in rows]


@app.post("/tasks", status_code=201)
async def create_task(task: TaskCreate):
    log.info("CREATE: %s", task.dict())
    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO zuzulka_tasks (title, event_date, freq, interval_days, task_type) VALUES (?, ?, ?, ?, ?)",
            (task.title, task.event_date, task.freq, task.interval_days, "task"),
        )
        conn.commit()
        return {"id": cursor.lastrowid, "status": "created"}


@app.put("/tasks/{task_id}")
async def update_task(task_id: int, task: TaskCreate):
    log.info("UPDATE %s: %s", task_id, task.dict())
    with get_db() as conn:
        result = conn.execute(
            "UPDATE zuzulka_tasks SET title=?, event_date=?, freq=?, interval_days=?, done=0 WHERE id=?",
            (task.title, task.event_date, task.freq, task.interval_days, task_id),  # task_type unchanged
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
        if task["freq"] != "none":
            advance_recurring_task(conn, task)
        else:
            conn.execute("UPDATE zuzulka_tasks SET done=1 WHERE id=?", (task_id,))
            conn.commit()
        return {"status": "done"}


@app.delete("/tasks/{task_id}", status_code=204)
async def delete_task(task_id: int):
    with get_db() as conn:
        result = conn.execute("DELETE FROM zuzulka_tasks WHERE id=?", (task_id,))
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Task not found")
        conn.commit()


# New endpoint: return calendar events (expands recurring tasks)
@app.get("/calendar-events")
async def get_calendar_events():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM zuzulka_tasks WHERE done=0 ORDER BY event_date ASC"
        ).fetchall()
    events = []
    for row in rows:
        t = dict(row)
        for d in next_occurrences(t):
            events.append({"id": t["id"], "title": t["title"], "date": d, "freq": t["freq"]})
    return events


# ─────────────────────────────────────────────
#  Frontend
# ─────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    root_path = getattr(request.state, "ingress_path", "")
    return HTMLResponse(content=HTML_PAGE.replace("__ROOT_PATH__", root_path))


# ─────────────────────────────────────────────
#  HTML / CSS / JS
# ─────────────────────────────────────────────
HTML_PAGE = r"""<!DOCTYPE html>
<html lang="uk">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Зузулька 🚀</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Unbounded:wght@300;600;900&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/fullcalendar@6.1.11/index.global.min.js"></script>
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg:        #0a0c10;
  --surface:   #111318;
  --surface2:  #181b22;
  --border:    #252933;
  --accent:    #4fffb0;
  --accent2:   #ff4f81;
  --amber:     #ffd166;
  --blue:      #4fa8ff;
  --text:      #e8eaf0;
  --muted:     #606878;
  --radius:    14px;
  --font-head: 'Unbounded', sans-serif;
  --font-mono: 'Space Mono', monospace;
}

html, body { height: 100%; }

body {
  background: var(--bg);
  color: var(--text);
  font-family: var(--font-mono);
  font-size: 15px;          /* ↑ was 13px */
  line-height: 1.65;
  min-height: 100vh;
  overflow-x: hidden;
}

body::before {
  content: '';
  position: fixed; inset: 0;
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.04'/%3E%3C/svg%3E");
  pointer-events: none; z-index: 0;
}

.shell {
  position: relative; z-index: 1;
  max-width: 1060px; margin: 0 auto;
  padding: 30px 24px 70px;
}

/* ── Header ─────────────────── */
header {
  display: flex; align-items: center; gap: 16px;
  margin-bottom: 28px;
  border-bottom: 1px solid var(--border);
  padding-bottom: 20px;
}
.logo {
  font-family: var(--font-head);
  font-weight: 900; font-size: 26px;
  letter-spacing: -0.5px;
  background: linear-gradient(135deg, var(--accent), #00e5ff);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
}
.logo-sub {
  font-size: 12px; color: var(--muted);
  letter-spacing: 2px; text-transform: uppercase;
  margin-top: 2px;
}
.badge {
  margin-left: auto;
  background: var(--surface2); border: 1px solid var(--border);
  border-radius: 40px; padding: 6px 16px;
  font-size: 13px; color: var(--muted);
  letter-spacing: 1px;
}

/* ── Grid ────────────────────── */
.grid { display: grid; grid-template-columns: 1fr 400px; gap: 20px; }
@media (max-width: 780px) { .grid { grid-template-columns: 1fr; } }

/* ── Cards ───────────────────── */
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 24px;
  animation: fadeUp .35s ease both;
}
.card + .card { margin-top: 20px; }
.card-title {
  font-family: var(--font-head);
  font-size: 11px; font-weight: 600;
  letter-spacing: 3px; text-transform: uppercase;
  color: var(--muted); margin-bottom: 18px;
}

@keyframes fadeUp {
  from { opacity: 0; transform: translateY(12px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* ── Stats ───────────────────── */
.stats { display: flex; gap: 14px; margin-bottom: 20px; flex-wrap: wrap; }
.stat {
  flex: 1; min-width: 90px;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; padding: 16px 18px; text-align: center;
}
.stat-val {
  font-family: var(--font-head); font-size: 28px; font-weight: 900; line-height: 1;
}
.stat-val.green  { color: var(--accent); }
.stat-val.red    { color: var(--accent2); }
.stat-val.yellow { color: var(--amber); }
.stat-val.blue   { color: var(--blue); }
.stat-label { font-size: 11px; color: var(--muted); margin-top: 5px; letter-spacing: 1px; text-transform: uppercase; }

/* ── Calendar overrides ──────── */
.fc { --fc-border-color: var(--border) !important; }

.fc .fc-toolbar-title {
  font-family: var(--font-head) !important;
  font-size: 17px !important; font-weight: 600 !important;
  color: var(--text) !important;
}
.fc .fc-button {
  background: var(--surface2) !important;
  border: 1px solid var(--border) !important;
  border-radius: 8px !important;
  font-family: var(--font-mono) !important;
  font-size: 13px !important; color: var(--text) !important;
  padding: 5px 12px !important; box-shadow: none !important;
}
.fc .fc-button:hover { background: var(--border) !important; }
.fc .fc-daygrid-day { background: transparent !important; }
.fc .fc-daygrid-day-number {
  color: var(--muted) !important; font-size: 13px !important;
}
.fc .fc-daygrid-day.fc-day-today { background: rgba(79,255,176,.07) !important; }

/* ── Calendar event chips — DARK TEXT for readability ── */
.fc .fc-event {
  border: none !important;
  border-radius: 4px !important;
  font-size: 11px !important;
  font-family: var(--font-mono) !important;
  font-weight: 700 !important;
  padding: 2px 5px !important;
  color: #0a0c10 !important;   /* always dark text on colored bg */
}
.fc .fc-event.ev-overdue { background: #ff4f81 !important; }
.fc .fc-event.ev-today   { background: #4fffb0 !important; }
.fc .fc-event.ev-future  { background: #4fa8ff !important; }
.fc .fc-event.ev-recurr  { background: var(--amber) !important; }

.fc .fc-col-header-cell-cushion { color: var(--muted) !important; font-size: 12px !important; }
.fc .fc-daygrid-more-link { color: var(--muted) !important; font-size: 11px !important; }

/* ── Form ────────────────────── */
.field { margin-bottom: 14px; }
.field label {
  display: block; font-size: 11px; letter-spacing: 2px;
  text-transform: uppercase; color: var(--muted); margin-bottom: 6px;
}
input[type=text], input[type=date], input[type=number], select {
  width: 100%; padding: 12px 14px;
  background: var(--surface2); border: 1px solid var(--border);
  color: var(--text); border-radius: 10px;
  font-family: var(--font-mono); font-size: 15px;
  outline: none; transition: border-color .2s;
  -webkit-appearance: none;
}
input:focus, select:focus { border-color: var(--accent); }
select option { background: var(--surface2); }
input[type=date]::-webkit-calendar-picker-indicator { filter: invert(0.6); cursor: pointer; }

.btn {
  cursor: pointer; border: none; border-radius: 8px;
  font-family: var(--font-mono); font-weight: 700;
  font-size: 14px; padding: 11px 18px;
  transition: opacity .15s, transform .1s;
  white-space: nowrap;
}
.btn:hover  { opacity: .85; }
.btn:active { transform: scale(.97); }

.btn-primary {
  background: var(--accent); color: #000;
  width: 100%; padding: 14px; font-size: 15px;
}
.btn-cancel {
  display: none; width: 100%; margin-top: 10px;
  background: transparent;
  border: 1px solid var(--border); color: var(--muted);
}
.btn-icon { padding: 8px 11px; font-size: 15px; line-height: 1; }
.btn-edit  { background: rgba(255,209,102,.15); color: var(--amber);  border: 1px solid rgba(255,209,102,.3); }
.btn-done  { background: rgba(79,255,176,.12);  color: var(--accent); border: 1px solid rgba(79,255,176,.3); }
.btn-del   { background: rgba(255,79,129,.12);  color: var(--accent2);border: 1px solid rgba(255,79,129,.3); }

/* ── Task list ───────────────── */
.task-item {
  display: flex; align-items: center; gap: 12px;
  padding: 14px 16px;
  background: var(--surface2); border: 1px solid var(--border);
  border-radius: 12px; margin-bottom: 10px;
  transition: border-color .2s;
  animation: fadeUp .25s ease both;
}
.task-item:hover { border-color: #333b4a; }
.task-item.done-item { opacity: .38; }
.task-item.done-item .task-title { text-decoration: line-through; }

.task-info { flex: 1; min-width: 0; }
.task-title {
  font-size: 15px; color: var(--text);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.task-meta { display: flex; gap: 8px; margin-top: 5px; flex-wrap: wrap; }

.tag {
  font-size: 11px; padding: 3px 9px; border-radius: 20px; letter-spacing: .5px;
}
.tag-date   { background: rgba(79,168,255,.1);  color: var(--blue);   border: 1px solid rgba(79,168,255,.25); }
.tag-freq   { background: rgba(255,209,102,.1); color: var(--amber);  border: 1px solid rgba(255,209,102,.25); }
.tag-overdue{ background: rgba(255,79,129,.14); color: var(--accent2);border: 1px solid rgba(255,79,129,.35); }
.tag-today  { background: rgba(79,255,176,.12); color: var(--accent); border: 1px solid rgba(79,255,176,.35); }

.task-actions { display: flex; gap: 8px; flex-shrink: 0; }

/* ── Empty state ─────────────── */
.empty {
  text-align: center; padding: 44px 20px;
  color: var(--muted); font-size: 13px; letter-spacing: 1px;
}
.empty-icon { font-size: 34px; display: block; margin-bottom: 12px; }

/* ── Toast ───────────────────── */
#toast {
  position: fixed; bottom: 28px; left: 50%; transform: translateX(-50%) translateY(20px);
  background: var(--surface2); border: 1px solid var(--border);
  color: var(--text); padding: 12px 24px; border-radius: 40px;
  font-size: 14px; pointer-events: none;
  opacity: 0; transition: opacity .25s, transform .25s;
  z-index: 999;
}
#toast.show { opacity: 1; transform: translateX(-50%) translateY(0); }
#toast.err  { border-color: var(--accent2); color: var(--accent2); }

::-webkit-scrollbar { width: 5px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }
</style>
</head>
<body>
<div class="shell">

  <header>
    <div>
      <div class="logo">Зузулька 🚀</div>
      <div class="logo-sub">Бортовий журнал</div>
    </div>
    <div class="badge" id="clock">──</div>
  </header>

  <div class="stats">
    <div class="stat"><div class="stat-val green"  id="st-total">–</div><div class="stat-label">Всього</div></div>
    <div class="stat"><div class="stat-val red"    id="st-over">–</div><div class="stat-label">Прострочено</div></div>
    <div class="stat"><div class="stat-val yellow" id="st-today">–</div><div class="stat-label">Сьогодні</div></div>
    <div class="stat"><div class="stat-val blue"   id="st-rec">–</div><div class="stat-label">Регулярних</div></div>
  </div>

  <div class="grid">

    <!-- Left: calendar + task list -->
    <div>
      <div class="card" style="animation-delay:.05s">
        <div class="card-title">Календар</div>
        <div id="calendar"></div>
      </div>
      <div class="card" style="animation-delay:.1s">
        <div class="card-title">Завдання</div>
        <div id="taskList"></div>
      </div>
    </div>

    <!-- Right: sticky form -->
    <div>
      <div class="card" style="animation-delay:.15s; position:sticky; top:20px;">
        <div class="card-title" id="formMode">Нове завдання</div>

        <input type="hidden" id="taskId">

        <div class="field">
          <label>Назва</label>
          <input type="text" id="title" placeholder="Що треба зробити?">
        </div>
        <div class="field">
          <label>Дата</label>
          <input type="date" id="eventDate">
        </div>
        <div class="field">
          <label>Повторення</label>
          <select id="freq" onchange="toggleInterval()">
            <option value="none">Одноразова</option>
            <option value="daily">Щодня</option>
            <option value="weekly">Щотижня</option>
            <option value="monthly">Щомісяця</option>
            <option value="custom">Кожні Х днів</option>
          </select>
        </div>
        <div class="field" id="intervalField" style="display:none">
          <label>Інтервал (днів)</label>
          <input type="number" id="interval" placeholder="напр. 14" min="1">
        </div>

        <button class="btn btn-primary" onclick="submitForm()">Зберегти завдання</button>
        <button class="btn btn-cancel" id="cancelBtn" onclick="cancelEdit()">Скасувати</button>
      </div>
    </div>

  </div>
</div>

<div id="toast"></div>

<script>
const ROOT = "__ROOT_PATH__";
let calendar;
let allTasks = [];

// ── Toast ─────────────────────────────────────────
let toastTimer;
function toast(msg, isErr = false) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = 'show' + (isErr ? ' err' : '');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.className = ''; }, 2800);
}

// ── Clock ─────────────────────────────────────────
function updateClock() {
  const now = new Date();
  document.getElementById('clock').textContent =
    now.toLocaleDateString('uk-UA', { day:'2-digit', month:'short', year:'numeric' }) +
    '  ' + now.toTimeString().slice(0,5);
}
updateClock(); setInterval(updateClock, 30000);

// ── Init ──────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  calendar = new FullCalendar.Calendar(document.getElementById('calendar'), {
    initialView: 'dayGridMonth',
    locale: 'uk',
    height: 'auto',
    headerToolbar: { left: 'prev', center: 'title', right: 'next' },
    eventClassNames: info => [info.event.extendedProps.evClass],
    eventClick: info => info.jsEvent.preventDefault()
  });
  calendar.render();
  document.getElementById('eventDate').value = todayStr;
  loadTasks();
});

// ── Helpers ───────────────────────────────────────
const todayStr = new Date().toISOString().slice(0,10);
function isOverdue(d) { return d < todayStr; }
function isToday(d)   { return d === todayStr; }

const FREQ_LABELS = {
  none: null, daily: 'щодня', weekly: 'щотижня',
  monthly: 'щомісяця', custom: 'кастом'
};

function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Load ──────────────────────────────────────────
async function loadTasks() {
  try {
    const [tasksRes, eventsRes] = await Promise.all([
      fetch(ROOT + '/tasks'),
      fetch(ROOT + '/calendar-events')
    ]);
    if (!tasksRes.ok) throw new Error('tasks HTTP ' + tasksRes.status);
    if (!eventsRes.ok) throw new Error('events HTTP ' + eventsRes.status);
    allTasks = await tasksRes.json();
    const calEvents = await eventsRes.json();
    renderCalendar(calEvents);
    renderList();
    renderStats();
  } catch(e) {
    console.error('loadTasks:', e);
    toast('Помилка завантаження', true);
  }
}

// ── Calendar ──────────────────────────────────────
function renderCalendar(events) {
  calendar.removeAllEvents();
  events.forEach(ev => {
    const overdue = isOverdue(ev.date);
    const today   = isToday(ev.date);
    const recurr  = ev.freq !== 'none';
    const evClass = overdue ? 'ev-overdue' : today ? 'ev-today' : recurr ? 'ev-recurr' : 'ev-future';
    calendar.addEvent({ title: ev.title, start: ev.date, extendedProps: { evClass } });
  });
}

// ── Stats ─────────────────────────────────────────
function renderStats() {
  const active = allTasks.filter(t => !t.done);
  document.getElementById('st-total').textContent = active.length;
  document.getElementById('st-over').textContent  = active.filter(t => isOverdue(t.event_date)).length;
  document.getElementById('st-today').textContent = active.filter(t => isToday(t.event_date)).length;
  document.getElementById('st-rec').textContent   = active.filter(t => t.freq !== 'none').length;
}

// ── Task list ─────────────────────────────────────
function renderList() {
  const list = document.getElementById('taskList');
  if (!allTasks.length) {
    list.innerHTML = `<div class="empty"><span class="empty-icon">🛸</span>Завдань поки немає</div>`;
    return;
  }
  list.innerHTML = '';
  allTasks.forEach(t => {
    const overdue    = !t.done && isOverdue(t.event_date);
    const today      = !t.done && isToday(t.event_date);
    const freqLabel  = FREQ_LABELS[t.freq];
    const dateTag    = `<span class="tag ${overdue ? 'tag-overdue' : today ? 'tag-today' : 'tag-date'}">${t.event_date}</span>`;
    const freqTag    = freqLabel
      ? `<span class="tag tag-freq">${freqLabel}${t.freq==='custom' ? ' ('+t.interval_days+'д)':''}</span>`
      : '';

    const item = document.createElement('div');
    item.className = 'task-item' + (t.done ? ' done-item' : '');
    item.dataset.id = t.id;
    item.innerHTML = `
      <div class="task-info">
        <div class="task-title">${escHtml(t.title)}</div>
        <div class="task-meta">${dateTag}${freqTag}</div>
      </div>
      <div class="task-actions">
        ${!t.done
          ? `<button class="btn btn-icon btn-done" title="Виконано"   onclick="doneTask(${t.id})">✓</button>`
          : ''}
        <button class="btn btn-icon btn-edit" title="Редагувати" onclick="editTask(${t.id})">✎</button>
        <button class="btn btn-icon btn-del"  title="Видалити"   onclick="deleteTask(${t.id})">✕</button>
      </div>`;
    list.appendChild(item);
  });
}

// ── Form ──────────────────────────────────────────
function toggleInterval() {
  document.getElementById('intervalField').style.display =
    document.getElementById('freq').value === 'custom' ? 'block' : 'none';
}

function cancelEdit() {
  document.getElementById('taskId').value    = '';
  document.getElementById('title').value     = '';
  document.getElementById('eventDate').value = todayStr;
  document.getElementById('freq').value      = 'none';
  document.getElementById('interval').value  = '';
  document.getElementById('intervalField').style.display = 'none';
  document.getElementById('formMode').textContent        = 'Нове завдання';
  document.getElementById('cancelBtn').style.display     = 'none';
}

function editTask(id) {
  const t = allTasks.find(x => x.id === id);
  if (!t) return;
  document.getElementById('taskId').value    = t.id;
  document.getElementById('title').value     = t.title;
  document.getElementById('eventDate').value = t.event_date;
  document.getElementById('freq').value      = t.freq;
  document.getElementById('interval').value  = t.interval_days || '';
  document.getElementById('intervalField').style.display = t.freq === 'custom' ? 'block' : 'none';
  document.getElementById('formMode').textContent        = 'Редагувати завдання';
  document.getElementById('cancelBtn').style.display     = 'block';
  // scroll to form on mobile
  document.getElementById('cancelBtn').closest('.card').scrollIntoView({ behavior:'smooth', block:'start' });
}

// ── API ───────────────────────────────────────────
async function submitForm() {
  const id    = document.getElementById('taskId').value;
  const title = document.getElementById('title').value.trim();
  const dt    = document.getElementById('eventDate').value;
  if (!title || !dt) { toast('Заповніть назву та дату', true); return; }

  // FIX: always send a valid integer — never NaN
  const intervalRaw = document.getElementById('interval').value;
  const interval_days = intervalRaw === '' ? 0 : (parseInt(intervalRaw, 10) || 0);

  const payload = {
    title,
    event_date: dt,
    freq: document.getElementById('freq').value,
    interval_days          // guaranteed integer
  };

  try {
    const url    = ROOT + (id ? '/tasks/' + id : '/tasks');
    const method = id ? 'PUT' : 'POST';
    const res    = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!res.ok) {
      const body = await res.text();
      throw new Error(`HTTP ${res.status}: ${body}`);
    }
    toast(id ? 'Завдання оновлено ✓' : 'Завдання додано ✓');
    cancelEdit();
    await loadTasks();
  } catch(e) {
    console.error('submitForm:', e);
    toast('Помилка збереження: ' + e.message, true);
  }
}

async function doneTask(id) {
  try {
    const res = await fetch(ROOT + '/tasks/' + id + '/done', { method:'POST' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    toast('Виконано! 🎉');
    await loadTasks();
  } catch(e) {
    console.error('doneTask:', e);
    toast('Помилка', true);
  }
}

async function deleteTask(id) {
  if (!confirm('Видалити завдання?')) return;
  try {
    const res = await fetch(ROOT + '/tasks/' + id, { method:'DELETE' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    toast('Видалено');
    await loadTasks();
  } catch(e) {
    console.error('deleteTask:', e);
    toast('Помилка видалення', true);
  }
}
</script>
</body>
</html>
"""
