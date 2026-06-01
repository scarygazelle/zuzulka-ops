from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import sqlite3

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
            freq TEXT DEFAULT 'none',
            interval_days INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

app = FastAPI()
init_db()

# Middleware для коректної обробки Ingress шляху
@app.middleware("http")
async def add_ingress_path(request: Request, call_next):
    root_path = request.headers.get("X-Ingress-Path", "")
    request.scope["root_path"] = root_path
    return await call_next(request)

class TaskCreate(BaseModel):
    title: str
    event_date: str
    freq: str = 'none'
    interval_days: int = 0

@app.get("/api/tasks")
async def get_tasks():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM zuzulka_tasks ORDER BY event_date ASC")
    tasks = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return tasks

@app.post("/api/tasks")
async def create_task(task: TaskCreate):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO zuzulka_tasks (title, event_date, freq, interval_days) VALUES (?, ?, ?, ?)",
                   (task.title, task.event_date, task.freq, task.interval_days))
    conn.commit()
    conn.close()
    return {"status": "ok"}

@app.put("/api/tasks/{task_id}")
async def update_task(task_id: int, task: TaskCreate):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE zuzulka_tasks SET title=?, event_date=?, freq=?, interval_days=? WHERE id=?",
                   (task.title, task.event_date, task.freq, task.interval_days, task_id))
    conn.commit()
    conn.close()
    return {"status": "ok"}

@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM zuzulka_tasks WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()
    return {"status": "ok"}

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    root_path = request.scope.get("root_path", "")
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <script src="https://cdn.jsdelivr.net/npm/fullcalendar@6.1.11/index.global.min.js"></script>
        <style>
            body {{ background: #121212; color: white; font-family: sans-serif; padding: 20px; }}
            .container {{ max-width: 900px; margin: auto; }}
            .card {{ background: #1e1e1e; padding: 20px; border-radius: 12px; margin-bottom: 20px; }}
            .task-item {{ display: flex; justify-content: space-between; align-items: center; padding: 10px; background: #252525; margin-bottom: 5px; border-radius: 6px; }}
            input, select {{ width: 100%; padding: 10px; background: #333; border: 1px solid #555; color: white; margin-bottom: 10px; border-radius: 6px; box-sizing: border-box; }}
            .btn {{ cursor: pointer; padding: 10px; border: none; border-radius: 6px; color: white; font-weight: bold; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Бортовий Журнал "Зузулька" 🚀</h1>
            <div class="card"><div id="calendar"></div></div>
            <div class="card">
                <form id="taskForm">
                    <input type="hidden" id="taskId">
                    <input type="text" id="title" placeholder="Назва" required>
                    <input type="date" id="eventDate" required>
                    <select id="freq" onchange="document.getElementById('interval').style.display = (this.value === 'custom' ? 'block' : 'none')">
                        <option value="none">Одноразова</option>
                        <option value="daily">Щодня</option>
                        <option value="custom">Кожні Х днів</option>
                    </select>
                    <input type="number" id="interval" placeholder="Кількість днів" style="display:none;">
                    <button type="submit" class="btn" style="background:#03a9f4; width:100%;">Зберегти</button>
                </form>
            </div>
            <div class="card" id="taskList"></div>
        </div>
        <script>
            const rootPath = "{root_path}";
            let calendar;
            document.addEventListener('DOMContentLoaded', () => {{
                calendar = new FullCalendar.Calendar(document.getElementById('calendar'), {{ initialView: 'dayGridMonth', locale: 'uk' }});
                calendar.render();
                loadTasks();
            }});

            async function loadTasks() {{
                const res = await fetch(rootPath + '/api/tasks');
                const tasks = await res.json();
                calendar.removeAllEvents();
                const list = document.getElementById('taskList');
                list.innerHTML = '<h3>Список задач</h3>';
                tasks.forEach(t => {{
                    calendar.addEvent({{ title: t.title, start: t.event_date }});
                    list.innerHTML += `<div class="task-item">
                        <span>${{t.title}} (${{t.event_date}})</span>
                        <div>
                            <button class="btn" style="background:#ff9800" onclick="editTask(${{t.id}})">✎</button>
                            <button class="btn" style="background:#f44336" onclick="deleteTask(${{t.id}})">🗑️</button>
                        </div>
                    </div>`;
                }});
            }}

            async function editTask(id) {{
                const res = await fetch(rootPath + '/api/tasks');
                const tasks = await res.json();
                const t = tasks.find(x => x.id == id);
                document.getElementById('taskId').value = t.id;
                document.getElementById('title').value = t.title;
                document.getElementById('eventDate').value = t.event_date;
                document.getElementById('freq').value = t.freq;
                document.getElementById('interval').style.display = (t.freq === 'custom' ? 'block' : 'none');
                document.getElementById('interval').value = t.interval_days;
            }}

            document.getElementById('taskForm').onsubmit = async (e) => {{
                e.preventDefault();
                const id = document.getElementById('taskId').value;
                const url = rootPath + (id ? '/api/tasks/' + id : '/api/tasks');
                await fetch(url, {{
                    method: id ? 'PUT' : 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{
                        title: document.getElementById('title').value,
                        event_date: document.getElementById('eventDate').value,
                        freq: document.getElementById('freq').value,
                        interval_days: parseInt(document.getElementById('interval').value || 0)
                    }})
                }});
                document.getElementById('taskForm').reset();
                document.getElementById('taskId').value = '';
                loadTasks();
            }};

            async function deleteTask(id) {{
                if(confirm("Видалити?")) {{
                    await fetch(rootPath + '/api/tasks/' + id, {{ method: 'DELETE' }});
                    loadTasks();
                }}
            }}
        </script>
    </body>
    </html>
    """
