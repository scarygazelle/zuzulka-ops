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
    # Додаємо колонку interval_days для довільного циклу
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

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.middleware("http")
async def add_ingress_prefix(request: Request, call_next):
    root_path = request.headers.get("X-Ingress-Path", "")
    if root_path: request.scope["root_path"] = root_path
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
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

@app.post("/api/tasks")
async def create_task(task: TaskCreate):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO zuzulka_tasks (title, event_date, freq, interval_days) VALUES (?, ?, ?, ?)",
                   (task.title, task.event_date, task.freq, task.interval_days))
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
            body {{ background: #121212; color: white; font-family: sans-serif; padding: 20px; }}
            .container {{ max-width: 1000px; margin: auto; }}
            .card {{ background: #1e1e1e; padding: 20px; border-radius: 12px; margin-bottom: 20px; }}
            .task-item {{ display: flex; justify-content: space-between; align-items: center; padding: 10px; background: #252525; margin-bottom: 5px; border-radius: 6px; }}
            .btns-group {{ display: flex; gap: 5px; }}
            .btn-icon {{ cursor: pointer; padding: 5px 8px; border: none; border-radius: 4px; color: white; font-size: 14px; }}
            .btn-edit {{ background: #ff9800; }}
            .btn-del {{ background: #f44336; }}
            input, select {{ width: 100%; padding: 10px; background: #333; border: 1px solid #555; color: white; margin-bottom: 10px; border-radius: 6px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Бортовий Журнал "Зузулька" 🚀</h1>
            <div class="card"><div id="calendar"></div></div>
            <div class="card">
                <h3>➕ Нова задача</h3>
                <form id="taskForm">
                    <input type="text" id="title" placeholder="Назва" required>
                    <input type="date" id="eventDate" required>
                    <select id="freq" onchange="toggleInterval(this.value)">
                        <option value="none">Одноразова</option>
                        <option value="custom">Кожні Х днів</option>
                    </select>
                    <input type="number" id="interval" placeholder="Кількість днів" style="display:none;">
                    <button type="submit" class="btn" style="background:#03a9f4; border:none; padding:10px; width:100%; border-radius:6px; color:white;">Додати</button>
                </form>
            </div>
            <div class="card">
                <h3>📜 Хронологічний список</h3>
                <div id="taskList"></div>
            </div>
        </div>
        <script>
            const apiBase = "{root_path}";
            function toggleInterval(val) {{ document.getElementById('interval').style.display = val === 'custom' ? 'block' : 'none'; }}

            async function loadTasks() {{
                const res = await fetch(`${{apiBase}}/api/tasks`);
                const tasks = await res.json();
                const list = document.getElementById('taskList');
                list.innerHTML = '';
                tasks.forEach(t => {{
                    const div = document.createElement('div');
                    div.className = 'task-item';
                    div.innerHTML = `<span><b>${{t.title}}</b> (${{t.event_date}})</span>
                        <div class="btns-group">
                            <button class="btn-icon btn-edit" onclick="alert('Редагування ID: ${{t.id}} - скоро буде!')">✎</button>
                            <button class="btn-icon btn-del" onclick="deleteTask(${{t.id}})">🗑️</button>
                        </div>`;
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
                        freq: document.getElementById('freq').value,
                        interval_days: parseInt(document.getElementById('interval').value || 0)
                    }})
                }});
                loadTasks();
            }};

            async function deleteTask(id) {{ if(confirm("Видалити?")) {{ await fetch(`${{apiBase}}/api/tasks/${{id}}`, {{ method: 'DELETE' }}); loadTasks(); }} }}
            loadTasks();
        </script>
    </body>
    </html>
    """
