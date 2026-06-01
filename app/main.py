from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import sqlite3
from typing import Optional

DB_PATH = "/data/zuzulka.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS zuzulka_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            event_date TEXT NOT NULL,
            task_type TEXT NOT NULL,
            freq TEXT DEFAULT 'none',
            interval INTEGER DEFAULT 1
        )
    ''')
    conn.commit()
    conn.close()

app = FastAPI(title="Zuzulka Home Ops API")
init_db()

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.middleware("http")
async def add_ingress_prefix(request: Request, call_next):
    root_path = request.headers.get("X-Ingress-Path", "")
    if root_path: request.scope["root_path"] = root_path
    return await call_next(request)

class TaskCreate(BaseModel):
    title: str
    event_date: str
    task_type: str
    freq: Optional[str] = 'none'
    interval: Optional[int] = 1

@app.get("/api/tasks")
async def get_tasks():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM zuzulka_tasks ORDER BY event_date ASC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

@app.post("/api/tasks")
async def create_task(task: TaskCreate):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO zuzulka_tasks (title, event_date, task_type, freq, interval) VALUES (?, ?, ?, ?, ?)",
        (task.title, task.event_date, task.task_type, task.freq, task.interval)
    )
    conn.commit()
    conn.close()
    return {"status": "success"}

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    root_path = request.scope.get("root_path", "")
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <script src="https://cdn.jsdelivr.net/npm/fullcalendar@6.1.11/index.global.min.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/@fullcalendar/rrule@6.1.11/index.global.min.js"></script>
        <style>
            body {{ background: #121212; color: #e0e0e0; font-family: sans-serif; padding: 20px; }}
            .container {{ display: grid; grid-template-columns: 2fr 1fr; gap: 20px; max-width: 1400px; margin: auto; }}
            .card {{ background: #1e1e1e; padding: 20px; border-radius: 12px; }}
            input, select {{ width: 100%; padding: 10px; background: #252525; border: 1px solid #444; color: white; margin-bottom: 10px; border-radius: 6px; }}
            .btn {{ background: #03a9f4; color: white; padding: 10px; border: none; width: 100%; border-radius: 6px; cursor: pointer; }}
            .event-item {{ padding: 10px; margin-bottom: 8px; background: #252525; border-left: 5px solid #03a9f4; border-radius: 4px; }}
        </style>
    </head>
    <body>
        <h1>Zuzulka Log 🚀</h1>
        <div class="container">
            <div class="card"><div id="calendar"></div></div>
            <div class="card">
                <h2>➕ Додати задачу</h2>
                <form id="taskForm">
                    <input type="text" id="title" placeholder="Назва" required>
                    <input type="date" id="eventDate" required>
                    <select id="freq">
                        <option value="none">Одноразова</option>
                        <option value="daily">Щодня</option>
                        <option value="weekly">Щотижня</option>
                        <option value="monthly">Щомісяця</option>
                    </select>
                    <button type="submit" class="btn">Додати</button>
                </form>
                <div id="eventList"></div>
            </div>
        </div>
        <script>
            const apiBase = "{root_path}";
            let calendar;

            document.addEventListener('DOMContentLoaded', async function() {{
                calendar = new FullCalendar.Calendar(document.getElementById('calendar'), {{
                    initialView: 'dayGridMonth', locale: 'uk', plugins: [FullCalendar.rrulePlugin]
                }});
                calendar.render();
                loadTasks();
            }});

            async function loadTasks() {{
                const res = await fetch(`${{apiBase}}/api/tasks`);
                const data = await res.json();
                calendar.removeAllEvents();
                data.forEach(t => {{
                    if (t.freq !== 'none') {{
                        calendar.addEvent({{ title: t.title, rrule: {{ freq: t.freq, dtstart: t.event_date }} }});
                    }} else {{
                        calendar.addEvent({{ title: t.title, start: t.event_date }});
                    }});
                }});
                document.getElementById('eventList').innerHTML = data.map(t =>
                    `<div class="event-item">${{t.title}} - ${{t.event_date}}</div>`).join('');
            }}

            document.getElementById('taskForm').onsubmit = async (e) => {{
                e.preventDefault();
                await fetch(`${{apiBase}}/api/tasks`, {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{
                        title: document.getElementById('title').value,
                        event_date: document.getElementById('eventDate').value,
                        task_type: 'custom',
                        freq: document.getElementById('freq').value
                    }})
                }});
                loadTasks();
            }};
        </script>
    </body>
    </html>
    """
