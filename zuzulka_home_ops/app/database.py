import sqlite3
import os
from datetime import datetime

DB_PATH = os.getenv("DB_PATH", "data/zuzulka.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS recurring_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            interval_days INTEGER NOT NULL,
            is_floating BOOLEAN NOT NULL,
            performer TEXT NOT NULL,
            next_due_date TEXT NOT NULL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS event_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            event_date TEXT NOT NULL,
            category TEXT NOT NULL,
            performer TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            cost REAL DEFAULT 0.0
        )
    ''')

    cursor.execute("SELECT COUNT(*) FROM recurring_tasks")
    if cursor.fetchone()[0] == 0:
        today = datetime.now().strftime("%Y-%m-%d")
        initial_tasks = [
            ("Міняти фільтр осмосу", 180, 1, "Денис", today),
            ("Підсипати бактерії у септик", 30, 1, "Денис", today),
            ("Вивозити сміття", 14, 0, "Денис", today),
            ("Зняти показники лічильників", 30, 0, "Денис", today)
        ]
        cursor.executemany('''
            INSERT INTO recurring_tasks (name, interval_days, is_floating, performer, next_due_date)
            VALUES (?, ?, ?, ?, ?)
        ''', initial_tasks)

    conn.commit()
    conn.close()
