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

@app.put("/api/tasks/{task_id}")
async def update_task(task_id: int, task: TaskCreate):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE zuzulka_tasks SET title=?, event_date=?, freq=?, interval_days=? WHERE id=?",
                   (task.title, task.event_date, task.freq, task.interval_days, task_id))
    conn.commit()
    conn.close()
    return {"status": "updated"}

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
        <meta charset="utf-8">
        <script src="https://cdn.jsdelivr.net/npm/fullcalendar@6.1.11/index.global.min.js"></script>
        <style>
            body {{ background: #121212; color: white; font-family: sans-serif; padding: 20px; }}
            .container {{ max-width: 1000px; margin: auto; }}
            .card {{ background: #1e1e1e; padding: 20px; border-radius: 12px; margin-bottom: 20px; }}
            .task-item {{ display: flex; justify-content: space-between; align-items: center; padding: 12px; margin-bottom: 8px; border-radius: 8px; border-left: 6px solid #444; }}
            .past {{ background: #2c2c2c; border-color: #777; color: #aaa; }}
            .today {{ background: #1b3a1b; border-color: #4caf50; color: #fff; }}
            .future {{ background: #3a2b1b; border-color: #ff9800; color: #fff; }}
            .btns-group {{ display: flex; gap: 5px; }}
            .btn-icon {{ cursor: pointer; padding: 6px 10px; border: none; border-radius: 4px; color: white; font-size: 14px; }}
            input, select {{ width: 100%; padding: 10px; background: #333; border: 1px solid #555; color: white; margin-bottom: 10px; border-radius: 6px; box-sizing: border-box; }}
            .btn-submit {{ background: #03a9f4; border:none; padding:10px; width:100%; border-radius:6px; color:white; font-weight:bold; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Бортовий Журнал "Зузулька" 🚀</h1>
            <div class="card"><div id="calendar"></div></div>
            <div class="card">
                <h3 id="formTitle">➕ Нова задача</h3>
                <form id="taskForm">
                    <input type="hidden" id="taskId">
                    <input type="text" id="title" placeholder="Назва" required>
                    <input type="date" id="eventDate" required>
                    <select id="freq" onchange="toggleInterval(this.value)">
                        <option value="none">Одноразова</option>
                        <option value="daily">Щодня</option>
                        <option value="weekly">Щотижня</option>
                        <option value="monthly">Щомісяця</option>
                        <option value="custom">Кожні Х днів</option>
                    </select>
                    <input type="number" id="interval" placeholder="Кількість днів" style="display:none;">
                    <button type="submit" class="btn-submit">Зберегти</button>
                    <button type="button" id="cancelBtn" class="btn-submit" style="display:none; background:#555; margin-top:5px;" onclick="resetForm()">Скасувати</button>
                </form>
            </div>
            <div class="card">
                <h3>📜 Хронологічний список</h3>
                <div id="taskList"></div>
            </div>
        </div>
        <script>
            const apiBase = "{root_path}";
            let calendar, currentTasks = [];

            document.addEventListener('DOMContentLoaded', function() {{
                calendar = new FullCalendar.Calendar(document.getElementById('calendar'), {{
                    initialView: 'dayGridMonth',
                    locale: 'uk',
                    eventDidMount: function(info) {{
                        const today = new Date().toISOString().split('T')[0];
                        const d = info.event.startStr;
                        info.el.style.backgroundColor = d < today ? '#777' : (d === today ? '#4caf50' : '#ff9800');
                    }}
                }});
                calendar.render();
                loadTasks();
            }});

            function isTaskActiveOnDate(t, dStr) {{
                let tDate = new Date(t.event_date);
                let cDate = new Date(dStr);
                if (cDate < tDate) return false;
                if (t.freq === 'none') return dStr === t.event_date;
                let diff = Math.floor((cDate - tDate) / (1000 * 60 * 60 * 24));
                if (t.freq === 'daily') return true;
                if (t.freq === 'weekly') return diff % 7 === 0;
                if (t.freq === 'monthly') return cDate.getDate() === tDate.getDate();
                if (t.freq === 'custom') return diff % t.interval_days === 0;
                return false;
            }}

            async function loadTasks() {{
                const res = await fetch(`${{apiBase}}/api/tasks`);
                currentTasks = await res.json();
                calendar.removeAllEvents();
                const list = document.getElementById('taskList');
                list.innerHTML = '';
                const today = new Date().toISOString().split('T')[0];

                // Динамічне додавання подій на 3 місяці вперед
                let start = new Date();
                let end = new Date(); end.setMonth(end.getMonth() + 3);
                for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {{
                    let dStr = d.toISOString().split('T')[0];
                    currentTasks.forEach(t => {{
                        if (isTaskActiveOnDate(t, dStr)) calendar.addEvent({{ title: t.title, start: dStr, id: t.id }});
                    }});
                }}

                currentTasks.forEach(t => {{
                    let status = t.event_date < today ? 'past' : (t.event_date === today ? 'today' : 'future');
                    const div = document.createElement('div');
                    div.className = `task-item ${{status}}`;
                    div.innerHTML = `<span><b>${{t.title}}</b> (${{t.event_date}})</span>
                        <div class="btns-group">
                            <button class="btn-icon" style="background:#ff9800" onclick="editTask(${{t.id}})">✎</button>
                            <button class="btn-icon" style="background:#f44336" onclick="deleteTask(${{t.id}})">🗑️</button>
                        </div>`;
                    list.appendChild(div);
                }});
            }}

            function toggleInterval(val) {{ document.getElementById('interval').style.display = val === 'custom' ? 'block' : 'none'; }}

            function resetForm() {{
                document.getElementById('taskForm').reset();
                document.getElementById('taskId').value = '';
                document.getElementById('formTitle').innerText = '➕ Нова задача';
                document.getElementById('cancelBtn').style.display = 'none';
                toggleInterval('none');
            }}

            function editTask(id) {{
                const t = currentTasks.find(x => x.id === id);
                document.getElementById('taskId').value = t.id;
                document.getElementById('title').value = t.title;
                document.getElementById('eventDate').value = t.event_date;
                document.getElementById('freq').value = t.freq;
                if(t.freq === 'custom') {{ document.getElementById('interval').value = t.interval_days; toggleInterval('custom'); }}
                document.getElementById('formTitle').innerText = '✏️ Редагувати задачу';
                document.getElementById('cancelBtn').style.display = 'block';
            }}

            document.getElementById('taskForm').onsubmit = async (e) => {{
                e.preventDefault();
                const id = document.getElementById('taskId').value;
                const data = {{
                    title: document.getElementById('title').value,
                    event_date: document.getElementById('eventDate').value,
                    freq: document.getElementById('freq').value,
                    interval_days: parseInt(document.getElementById('interval').value || 0)
                }};
                await fetch(id ? `${{apiBase}}/api/tasks/${{id}}` : `${{apiBase}}/api/tasks`, {{
                    method: id ? 'PUT' : 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify(data)
                }});
                resetForm(); loadTasks();
            }};

            async function deleteTask(id) {{ if(confirm("Видалити?")) {{ await fetch(`${{apiBase}}/api/tasks/${{id}}`, {{ method: 'DELETE' }}); loadTasks(); }} }}
        </script>
    </body>
    </html>
    """
