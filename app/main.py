from fastapi import FastAPI, HTTPException, Body
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import Optional
import app.database as db
from app.scheduler import recalculate_next_date

app = FastAPI(title="Бортовий Журнал Зузулька API")

db.init_db()

class WebhookPayload(BaseModel):
    category: str
    performer: str
    title: str
    description: Optional[str] = None
    cost: Optional[float] = 0.0

class TaskCompletePayload(BaseModel):
    cost: Optional[float] = 0.0
    description: Optional[str] = None

@app.get("/api/health")
def health_check():
    return {"status": "online", "system": "Zuzulka Core"}

@app.get("/api/ha-tasks")
def get_tasks_for_ha(days: int = 10):
    conn = db.get_db_connection()
    cursor = conn.cursor()
    max_date = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")

    cursor.execute('''
        SELECT id, name, next_due_date, performer, interval_days
        FROM recurring_tasks
        WHERE next_due_date <= ?
        ORDER BY next_due_date ASC
    ''', (max_date,))

    tasks = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return {"count": len(tasks), "days_horizon": days, "tasks": tasks}

@app.post("/api/webhook")
def receive_webhook(payload: WebhookPayload):
    conn = db.get_db_connection()
    cursor = conn.cursor()
    now = datetime.now()

    cursor.execute('''
        INSERT INTO event_log (timestamp, event_date, category, performer, title, description, cost)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (now.strftime("%Y-%m-%d %H:%M:%S"), now.strftime("%Y-%m-%d"), payload.category, payload.performer, payload.title, payload.description, payload.cost))

    conn.commit()
    conn.close()
    return {"status": "logged", "title": payload.title}

@app.post("/api/tasks/{task_id}/complete")
def complete_task(task_id: int, payload: TaskCompletePayload = Body(...)):
    conn = db.get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM recurring_tasks WHERE id = ?", (task_id,))
    task = cursor.fetchone()
    if not task:
        conn.close()
        raise HTTPException(status_code=404, detail="Task not found")

    new_due_date = recalculate_next_date(task["interval_days"], task["is_floating"], task["next_due_date"])
    cursor.execute("UPDATE recurring_tasks SET next_due_date = ? WHERE id = ?", (new_due_date, task_id))

    now = datetime.now()
    cursor.execute('''
        INSERT INTO event_log (timestamp, event_date, category, performer, title, description, cost)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (now.strftime("%Y-%m-%d %H:%M:%S"), now.strftime("%Y-%m-%d"), "#Побут", task["performer"], f"Виконано: {task['name']}", payload.description, payload.cost))

    conn.commit()
    conn.close()
    return {"status": "success", "next_due_date": new_due_date}
