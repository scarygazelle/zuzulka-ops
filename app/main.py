from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional
import os
import sqlite3

# Імпортуємо коннект та ініціалізацію з нашого сусіднього файлу
from app.database import get_db_connection, init_db

app = FastAPI(title="Zuzulka Home Ops API", description="Бортовий журнал для Home Assistant")

# Налаштування CORS, щоб інтерфейс міг спокійно спілкуватися з API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Автоматична ініціалізація БД при старті контейнера
@app.on_event("startup")
def on_startup():
    init_db()

# Middleware для динамічного підхоплення префіксу Home Assistant Ingress
@app.middleware("http")
async def add_ingress_prefix(request: Request, call_next):
    root_path = request.headers.get("X-Ingress-Path", "")
    if root_path:
        request.scope["root_path"] = root_path
    response = await call_next(request)
    return response

# Pydantic моделі для валідації даних, що приходять в API
class EventLogCreate(BaseModel):
    event_date: str
    category: str
    performer: str
    title: str
    description: Optional[str] = None
    cost: Optional[float] = 0.0

class TaskUpdate(BaseModel):
    next_due_date: str

# --- МАРШРУТИ (ENDPOINTS) ---

# 1. Головна сторінка, яка тепер відкриється в боковій панелі замість помилки 404
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    root_path = request.scope.get("root_path", "")
    return f"""
    <html>
        <head>
            <title>Зузулька</title>
            <meta charset="utf-8">
            <style>
                body {{ font-family: sans-serif; text-align: center; padding-top: 50px; background-color: #1a1a1a; color: #e0e0e0; }}
                h1 {{ color: #03a9f4; }}
                .card {{ background: #2a2a2a; padding: 20px; border-radius: 8px; display: inline-block; margin-top: 20px; box-shadow: 0 4px 8px rgba(0,0,0,0.3); }}
                a {{ color: #ff9800; text-decoration: none; font-weight: bold; }}
                a:hover {{ text-decoration: underline; }}
            </style>
        </head>
        <body>
            <h1>Бортовий Журнал "Зузулька" 🚀</h1>
            <p>Бекенд успішно запущений та інтегрований в Home Assistant Ingress!</p>
            <div class="card">
                <p>Бажаєш протестувати ендпоінти або надіслати запит?</p>
                <p>👉 <a href="{root_path}/docs">Перейти до інтерактивної документації Swagger API</a></p>
            </div>
        </body>
    </html>
    """

# 2. Отримати список усіх періодичних завдань
@app.get("/api/tasks")
def get_tasks():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM recurring_tasks ORDER BY next_due_date ASC")
    tasks = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return tasks

# 3. Оновити дату наступного виконання для таски (наприклад, посунули плаваючу дату)
@app.put("/api/tasks/{task_id}")
def update_task_date(task_id: int, task: TaskUpdate):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE recurring_tasks SET next_due_date = ? WHERE id = ?",
        (task.next_due_date, task_id)
    )
    conn.commit()
    conn.close()
    return {"status": "success", "message": f"Task {task_id} updated"}

# 4. Отримати весь журнал подій
@app.get("/api/logs")
def get_logs():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM event_log ORDER BY event_date DESC, id DESC")
    logs = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return logs

# 5. Додати новий запис у журнал подій (витрати, роботи тощо)
@app.post("/api/logs")
def create_log_entry(entry: EventLogCreate):
    from datetime import datetime
    current_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO event_log (timestamp, event_date, category, performer, title, description, cost)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        current_timestamp,
        entry.event_date,
        entry.category,
        entry.performer,
        entry.title,
        entry.description,
        entry.cost
    ))
    conn.commit()
    conn.close()
    return {"status": "success", "message": "Log entry created"}
