from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from contextlib import contextmanager
from datetime import date, timedelta
import sqlite3

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


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS zuzulka_tasks (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                title          TEXT    NOT NULL,
                event_date     TEXT    NOT NULL,
                freq           TEXT    DEFAULT 'none',
                interval_days  INTEGER DEFAULT 0,
                done           INTEGER DEFAULT 0
            )
        """)
        # migrate: add `done` column if it doesn't exist yet
        try:
            conn.execute("ALTER TABLE zuzulka_tasks ADD COLUMN done INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # column already exists
        conn.commit()


# ─────────────────────────────────────────────
#  App
# ─────────────────────────────────────────────
app = FastAPI()
init_db()


@app.middleware("http")
async def ingress_path_middleware(request: Request, call_next):
    root_path = request.headers.get("X-Ingress-Path", "")
    request.scope["root_path"] = root_path
    return await call_next(request)


# ─────────────────────────────────────────────
#  Models
# ─────────────────────────────────────────────
class TaskCreate(BaseModel):
    title: str
    event_date: str
    freq: str = "none"
    interval_days: int = 0


# ─────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────
def advance_recurring_task(conn: sqlite3.Connection, task: dict) -> None:
    """Bump event_date forward and clear done flag for recurring tasks."""
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
        # approximate — add 30 days
        delta = timedelta(days=30)
    elif freq == "custom":
        days = task["interval_days"] or 1
        delta = timedelta(days=days)
    else:
        return

    # Advance until the next occurrence is in the future
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
@app.get("/api/tasks")
async def get_tasks():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM zuzulka_tasks ORDER BY done ASC, event_date ASC"
        ).fetchall()
        return [dict(r) for r in rows]


@app.post("/api/tasks", status_code=201)
async def create_task(task: TaskCreate):
    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO zuzulka_tasks (title, event_date, freq, interval_days) VALUES (?, ?, ?, ?)",
            (task.title, task.event_date, task.freq, task.interval_days),
        )
        conn.commit()
        return {"id": cursor.lastrowid, "status": "created"}


@app.put("/api/tasks/{task_id}")
async def update_task(task_id: int, task: TaskCreate):
    with get_db() as conn:
        result = conn.execute(
            "UPDATE zuzulka_tasks SET title=?, event_date=?, freq=?, interval_days=? WHERE id=?",
            (task.title, task.event_date, task.freq, task.interval_days, task_id),
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Task not found")
        conn.commit()
        return {"status": "updated"}


@app.post("/api/tasks/{task_id}/done")
async def complete_task(task_id: int):
    """Mark a task done. Recurring tasks get their date advanced automatically."""
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
            conn.execute(
                "UPDATE zuzulka_tasks SET done=1 WHERE id=?", (task_id,)
            )
            conn.commit()
        return {"status": "done"}


@app.delete("/api/tasks/{task_id}", status_code=204)
async def delete_task(task_id: int):
    with get_db() as conn:
        result = conn.execute(
            "DELETE FROM zuzulka_tasks WHERE id=?", (task_id,)
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Task not found")
        conn.commit()


# ─────────────────────────────────────────────
#  Frontend
# ─────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    root_path = request.scope.get("root_path", "")
    return HTMLResponse(content=HTML_PAGE.replace("__ROOT_PATH__", root_path))


# ─────────────────────────────────────────────
#  HTML / CSS / JS  (single-file SPA)
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
/* ── Reset & Variables ──────────────────────── */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg:        #0a0c10;
  --surface:   #111318;
  --surface2:  #181b22;
  --border:    #252933;
  --accent:    #4fffb0;
  --accent2:   #ff4f81;
  --amber:     #ffd166;
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
  font-size: 13px;
  line-height: 1.6;
  min-height: 100vh;
  overflow-x: hidden;
}

/* ── Noise texture overlay ──────────────────── */
body::before {
  content: '';
  position: fixed; inset: 0;
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.04'/%3E%3C/svg%3E");
  pointer-events: none; z-index: 0;
}

/* ── Layout ─────────────────────────────────── */
.shell {
  position: relative; z-index: 1;
  max-width: 980px; margin: 0 auto;
  padding: 28px 20px 60px;
}

/* ── Header ─────────────────────────────────── */
header {
  display: flex; align-items: baseline; gap: 14px;
  margin-bottom: 32px;
  border-bottom: 1px solid var(--border);
  padding-bottom: 18px;
}
.logo {
  font-family: var(--font-head);
  font-weight: 900; font-size: 22px;
  letter-spacing: -0.5px;
  background: linear-gradient(135deg, var(--accent), #00e5ff);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
}
.logo-sub {
  font-family: var(--font-mono);
  font-size: 11px; color: var(--muted);
  letter-spacing: 2px; text-transform: uppercase;
}
.badge {
  margin-left: auto;
  background: var(--surface2); border: 1px solid var(--border);
  border-radius: 40px; padding: 4px 12px;
  font-size: 11px; color: var(--muted);
  letter-spacing: 1px;
}

/* ── Grid ────────────────────────────────────── */
.grid { display: grid; grid-template-columns: 1fr 360px; gap: 18px; }
@media (max-width: 720px) { .grid { grid-template-columns: 1fr; } }

/* ── Cards ───────────────────────────────────── */
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 22px;
  animation: fadeUp .35s ease both;
}
.card + .card { margin-top: 18px; }
.card-title {
  font-family: var(--font-head);
  font-size: 10px; font-weight: 600;
  letter-spacing: 3px; text-transform: uppercase;
  color: var(--muted); margin-bottom: 16px;
}

@keyframes fadeUp {
  from { opacity: 0; transform: translateY(12px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* ── Calendar overrides ──────────────────────── */
.fc { --fc-border-color: var(--border) !important; }
.fc .fc-toolbar-title {
  font-family: var(--font-head) !important;
  font-size: 15px !important; font-weight: 600 !important;
  color: var(--text) !important;
}
.fc .fc-button {
  background: var(--surface2) !important;
  border: 1px solid var(--border) !important;
  border-radius: 8px !important;
  font-family: var(--font-mono) !important;
  font-size: 11px !important; color: var(--text) !important;
  padding: 4px 10px !important; box-shadow: none !important;
}
.fc .fc-button:hover { background: var(--border) !important; }
.fc .fc-daygrid-day { background: transparent !important; }
.fc .fc-daygrid-day-number { color: var(--muted) !important; font-size: 11px !important; }
.fc .fc-daygrid-day.fc-day-today { background: rgba(79,255,176,.06) !important; }
.fc .fc-event {
  background: var(--accent) !important; border: none !important;
  color: #000 !important; border-radius: 4px !important;
  font-size: 10px !important; font-family: var(--font-mono) !important;
  padding: 1px 4px !important;
}
.fc .fc-col-header-cell-cushion { color: var(--muted) !important; font-size: 10px !important; }

/* ── Form ────────────────────────────────────── */
.field { margin-bottom: 12px; }
.field label {
  display: block; font-size: 10px; letter-spacing: 2px;
  text-transform: uppercase; color: var(--muted); margin-bottom: 5px;
}
input[type=text], input[type=date], input[type=number], select {
  width: 100%; padding: 10px 12px;
  background: var(--surface2); border: 1px solid var(--border);
  color: var(--text); border-radius: 8px;
  font-family: var(--font-mono); font-size: 13px;
  outline: none; transition: border-color .2s;
  -webkit-appearance: none;
}
input:focus, select:focus { border-color: var(--accent); }
select option { background: var(--surface2); }
input[type=date]::-webkit-calendar-picker-indicator { filter: invert(0.6); cursor: pointer; }

.btn {
  cursor: pointer; border: none; border-radius: 8px;
  font-family: var(--font-mono); font-weight: 700;
  font-size: 12px; padding: 10px 16px;
  transition: opacity .15s, transform .1s;
  white-space: nowrap;
}
.btn:hover { opacity: .85; }
.btn:active { transform: scale(.97); }
.btn-primary { background: var(--accent); color: #000; width: 100%; padding: 12px; }
.btn-icon { padding: 7px 10px; font-size: 13px; line-height: 1; }
.btn-edit  { background: rgba(255,209,102,.15); color: var(--amber); border: 1px solid rgba(255,209,102,.25); }
.btn-done  { background: rgba(79,255,176,.12);  color: var(--accent); border: 1px solid rgba(79,255,176,.25); }
.btn-del   { background: rgba(255,79,129,.12);  color: var(--accent2); border: 1px solid rgba(255,79,129,.25); }

/* ── Task list ───────────────────────────────── */
.task-item {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 12px;
  background: var(--surface2); border: 1px solid var(--border);
  border-radius: 10px; margin-bottom: 8px;
  transition: border-color .2s;
  animation: fadeUp .25s ease both;
}
.task-item:hover { border-color: #333b4a; }
.task-item.done-item { opacity: .4; }
.task-item.done-item .task-title { text-decoration: line-through; }

.task-info { flex: 1; min-width: 0; }
.task-title {
  font-size: 13px; color: var(--text);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.task-meta {
  display: flex; gap: 8px; margin-top: 3px; flex-wrap: wrap;
}
.tag {
  font-size: 10px; padding: 2px 7px; border-radius: 20px;
  letter-spacing: .5px;
}
.tag-date { background: rgba(0,229,255,.08); color: #00e5ff; border: 1px solid rgba(0,229,255,.2); }
.tag-freq { background: rgba(255,209,102,.08); color: var(--amber); border: 1px solid rgba(255,209,102,.2); }
.tag-overdue { background: rgba(255,79,129,.12); color: var(--accent2); border: 1px solid rgba(255,79,129,.3); }
.tag-today { background: rgba(79,255,176,.1); color: var(--accent); border: 1px solid rgba(79,255,176,.3); }

.task-actions { display: flex; gap: 6px; flex-shrink: 0; }

/* ── Empty state ──────────────────────────────── */
.empty {
  text-align: center; padding: 40px 20px;
  color: var(--muted); font-size: 12px; letter-spacing: 1px;
}
.empty-icon { font-size: 32px; display: block; margin-bottom: 10px; }

/* ── Stats row ───────────────────────────────── */
.stats {
  display: flex; gap: 12px; margin-bottom: 18px; flex-wrap: wrap;
}
.stat {
  flex: 1; min-width: 80px;
  background: var(--surface2); border: 1px solid var(--border);
  border-radius: 10px; padding: 12px 14px;
  text-align: center;
}
.stat-val {
  font-family: var(--font-head); font-size: 22px; font-weight: 900;
  line-height: 1;
}
.stat-val.green  { color: var(--accent); }
.stat-val.red    { color: var(--accent2); }
.stat-val.yellow { color: var(--amber); }
.stat-label { font-size: 10px; color: var(--muted); margin-top: 4px; letter-spacing: 1px; text-transform: uppercase; }

/* ── Scrollbar ────────────────────────────────── */
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

  <!-- Stats -->
  <div class="stats">
    <div class="stat"><div class="stat-val green" id="st-total">0</div><div class="stat-label">Всього</div></div>
    <div class="stat"><div class="stat-val red"   id="st-over">0</div><div class="stat-label">Прострочено</div></div>
    <div class="stat"><div class="stat-val yellow" id="st-today">0</div><div class="stat-label">Сьогодні</div></div>
    <div class="stat"><div class="stat-val green"  id="st-rec">0</div><div class="stat-label">Регулярних</div></div>
  </div>

  <div class="grid">
    <!-- Left column -->
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

    <!-- Right column: form -->
    <div>
      <div class="card" style="animation-delay:.15s; position: sticky; top: 20px;">
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
        <button class="btn" id="cancelBtn"
          style="display:none; width:100%; margin-top:8px; background:transparent; border:1px solid var(--border); color:var(--muted);"
          onclick="cancelEdit()">Скасувати</button>
      </div>
    </div>
  </div>
</div>

<script>
const ROOT = "__ROOT_PATH__";
let calendar;
let allTasks = [];

// ── Clock ────────────────────────────────────────
function updateClock() {
  const now = new Date();
  document.getElementById('clock').textContent =
    now.toLocaleDateString('uk-UA', { day:'2-digit', month:'short', year:'numeric' }) +
    '  ' + now.toTimeString().slice(0,5);
}
updateClock(); setInterval(updateClock, 30000);

// ── Init ─────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  calendar = new FullCalendar.Calendar(document.getElementById('calendar'), {
    initialView: 'dayGridMonth',
    locale: 'uk',
    height: 'auto',
    headerToolbar: { left: 'prev', center: 'title', right: 'next' },
    eventClick: info => { info.jsEvent.preventDefault(); }
  });
  calendar.render();

  // set today as default date
  document.getElementById('eventDate').value = new Date().toISOString().slice(0,10);

  loadTasks();
});

// ── Data helpers ──────────────────────────────────
const todayStr = new Date().toISOString().slice(0,10);

function isOverdue(dateStr) { return dateStr < todayStr; }
function isToday(dateStr)   { return dateStr === todayStr; }

const FREQ_LABELS = {
  none: null, daily: 'щодня', weekly: 'щотижня',
  monthly: 'щомісяця', custom: 'кастом'
};

// ── Load tasks ────────────────────────────────────
async function loadTasks() {
  try {
    const res = await fetch(ROOT + '/api/tasks');
    if (!res.ok) throw new Error('HTTP ' + res.status);
    allTasks = await res.json();
    renderCalendar();
    renderList();
    renderStats();
  } catch(e) {
    console.error('loadTasks error:', e);
  }
}

function renderCalendar() {
  calendar.removeAllEvents();
  allTasks.forEach(t => {
    if (t.done) return;
    calendar.addEvent({
      title: t.title,
      start: t.event_date,
      color: isOverdue(t.event_date) ? 'var(--accent2)' :
             isToday(t.event_date)   ? 'var(--accent)'  : '#4fa8ff'
    });
  });
}

function renderStats() {
  const active = allTasks.filter(t => !t.done);
  document.getElementById('st-total').textContent = active.length;
  document.getElementById('st-over').textContent  = active.filter(t => isOverdue(t.event_date)).length;
  document.getElementById('st-today').textContent = active.filter(t => isToday(t.event_date)).length;
  document.getElementById('st-rec').textContent   = active.filter(t => t.freq !== 'none').length;
}

function renderList() {
  const list = document.getElementById('taskList');
  if (!allTasks.length) {
    list.innerHTML = `<div class="empty"><span class="empty-icon">🛸</span>Завдань поки немає</div>`;
    return;
  }

  list.innerHTML = '';
  allTasks.forEach(t => {
    const overdue = !t.done && isOverdue(t.event_date);
    const today   = !t.done && isToday(t.event_date);
    const freqLabel = FREQ_LABELS[t.freq];

    const dateTag = `<span class="tag ${overdue ? 'tag-overdue' : today ? 'tag-today' : 'tag-date'}">${t.event_date}</span>`;
    const freqTag = freqLabel
      ? `<span class="tag tag-freq">${freqLabel}${t.freq==='custom' ? ' ('+t.interval_days+'д)' : ''}</span>`
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
        ${!t.done ? `<button class="btn btn-icon btn-done" title="Виконано" onclick="doneTask(${t.id})">✓</button>` : ''}
        <button class="btn btn-icon btn-edit" title="Редагувати" onclick="editTask(${t.id})">✎</button>
        <button class="btn btn-icon btn-del"  title="Видалити"   onclick="deleteTask(${t.id})">✕</button>
      </div>`;
    list.appendChild(item);
  });
}

function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Form helpers ──────────────────────────────────
function toggleInterval() {
  const show = document.getElementById('freq').value === 'custom';
  document.getElementById('intervalField').style.display = show ? 'block' : 'none';
}

function cancelEdit() {
  document.getElementById('taskId').value = '';
  document.getElementById('title').value = '';
  document.getElementById('eventDate').value = todayStr;
  document.getElementById('freq').value = 'none';
  document.getElementById('interval').value = '';
  document.getElementById('intervalField').style.display = 'none';
  document.getElementById('formMode').textContent = 'Нове завдання';
  document.getElementById('cancelBtn').style.display = 'none';
}

function editTask(id) {
  const t = allTasks.find(x => x.id === id);
  if (!t) return;
  document.getElementById('taskId').value    = t.id;
  document.getElementById('title').value     = t.title;
  document.getElementById('eventDate').value = t.event_date;
  document.getElementById('freq').value      = t.freq;
  document.getElementById('interval').value  = t.interval_days;
  document.getElementById('intervalField').style.display = t.freq === 'custom' ? 'block' : 'none';
  document.getElementById('formMode').textContent = 'Редагувати завдання';
  document.getElementById('cancelBtn').style.display = 'block';
  document.querySelector('.card:last-child').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ── API actions ───────────────────────────────────
async function submitForm() {
  const id    = document.getElementById('taskId').value;
  const title = document.getElementById('title').value.trim();
  const date  = document.getElementById('eventDate').value;
  if (!title || !date) { alert('Заповніть назву та дату'); return; }

  const payload = {
    title,
    event_date: date,
    freq: document.getElementById('freq').value,
    interval_days: parseInt(document.getElementById('interval').value || 0)
  };

  try {
    const url    = ROOT + (id ? '/api/tasks/' + id : '/api/tasks');
    const method = id ? 'PUT' : 'POST';
    const res    = await fetch(url, {
      method, headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    cancelEdit();
    await loadTasks();
  } catch(e) {
    console.error('submitForm error:', e);
    alert('Помилка збереження');
  }
}

async function doneTask(id) {
  try {
    const res = await fetch(ROOT + '/api/tasks/' + id + '/done', { method: 'POST' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    await loadTasks();
  } catch(e) { console.error('doneTask error:', e); }
}

async function deleteTask(id) {
  if (!confirm('Видалити завдання?')) return;
  try {
    const res = await fetch(ROOT + '/api/tasks/' + id, { method: 'DELETE' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    await loadTasks();
  } catch(e) { console.error('deleteTask error:', e); }
}
</script>
</body>
</html>
"""
