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
            freq TEXT DEFAULT 'none'
        )
    ''')
    conn.commit()
    conn.close()

app = FastAPI()
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
    cursor.execute("INSERT INTO zuzulka_tasks (title, event_date, task_type, freq) VALUES (?, ?, ?, ?)",
                   (task.title, task.event_date, task.task_type, task.freq))
    conn.commit()
    conn.close()
    return {"status": "success"}

@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM zuzulka_tasks WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()
    return {"status": "deleted"}

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    root_path = request.scope.get("root_path", "")
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <script src="https://cdn.jsdelivr.net/npm/fullcalendar@6.1.11/index.global.min.js"></script>
        <style>
            body {{ background: #121212; color: #e0e0e0; font-family: sans-serif; padding: 20px; }}
            .container {{ display: grid; grid-template-columns: 2fr 1fr; gap: 20px; max-width: 1400px; margin: auto; }}
            .card {{ background: #1e1e1e; padding: 20px; border-radius: 12px; margin-bottom: 20px; }}
            .task-item {{ display: flex; justify-content: space-between; align-items: center; padding: 10px; background: #252525; margin-bottom: 5px; border-radius: 6px; }}
            input, select {{ width: 100%; padding: 10px; background: #333; border: 1px solid #555; color: white; margin-bottom: 10px; }}
            .btn {{ cursor: pointer; padding: 10px; border: none; border-radius: 6px; color: white; width: 100%; background: #03a9f4; }}
            .btn-del {{ background: #f44336; width: auto; padding: 5px 10px; }}
        </style>
    </head>
    <body>
        <h1>Zuzulka Log 🚀</h1>
        <div class="container">
            <div class="card"><div id="calendar"></div></div>
            <div class="card">
                <h3>➕ Додати задачу</h3>
                <form id="taskForm">
                    <input type="text" id="title" placeholder="Назва" required>
                    <input type="date" id="eventDate" required>
                    <select id="freq"><option value="none">Одноразова</option></select>
                    <button type="submit" class="btn">Додати</button>
                </form>
                <hr style="border:0; border-top:1px solid #444; margin: 20px 0;">
                <h3>Список задач</h3>
                <div id="taskList"></div>
            </div>
        </div>
        <script>
            const apiBase = "{root_path}";
            let calendar;

            document.addEventListener('DOMContentLoaded', function() {{
                calendar = new FullCalendar.Calendar(document.getElementById('calendar'), {{ initialView: 'dayGridMonth', locale: 'uk' }});
                calendar.render();
                loadTasks();
            }});

            async function loadTasks() {{
                const res = await fetch(`${{apiBase}}/api/tasks`);
                const tasks = await res.json();
                calendar.removeAllEvents();
                const list = document.getElementById('taskList');
                list.innerHTML = '';
                tasks.forEach(t => {{
                    calendar.addEvent({{ id: t.id, title: t.title, start: t.event_date }});
                    const div = document.createElement('div');
                    div.className = 'task-item';
                    div.innerHTML = `<span>${{t.title}} (${{t.event_date}})</span>
                                     <button class="btn btn-del" onclick="deleteTask(${{t.id}})">🗑️</button>`;
                    list.appendChild(div);
                }});
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
                document.getElementById('taskForm').reset();
                loadTasks();
            }};

            async function deleteTask(id) {{
                if(!confirm("Видалити задачу?")) return;
                await fetch(`${{apiBase}}/api/tasks/${{id}}`, {{ method: 'DELETE' }});
                loadTasks();
            }}
        </script>
    </body>
    </html>
    """
