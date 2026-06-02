import sqlite3
import os
import logging
from contextlib import contextmanager

log = logging.getLogger("zuzulka.database")

# Setup dynamic database path with local fallback
DB_PATH = os.getenv("DB_PATH", "/data/zuzulka.db")

if not os.path.exists("/data") and DB_PATH == "/data/zuzulka.db":
    DB_PATH = "zuzulka.db"

@contextmanager
def get_db():
    # Ensure database folder exists
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
        
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def get_columns(conn, table_name: str) -> set:
    try:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return {row["name"] for row in rows}
    except Exception:
        return set()

def init_db():
    with get_db() as conn:
        # 1. Create tasks table
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
        
        # 2. Run migrations to safely add any missing columns
        existing = get_columns(conn, "zuzulka_tasks")
        migrations = [
            ("freq",          "TEXT    DEFAULT 'none'"),
            ("interval_days", "INTEGER DEFAULT 0"),
            ("done",          "INTEGER DEFAULT 0"),
            ("task_type",     "TEXT    DEFAULT 'task'"),
            ("is_floating",   "INTEGER DEFAULT 1"),
            ("performer",     "TEXT    DEFAULT ''"),
            ("category",      "TEXT    DEFAULT 'general'"),
            ("description",   "TEXT    DEFAULT ''"),
            ("cost",          "REAL    DEFAULT 0.0"),
        ]
        
        for col, definition in migrations:
            if col not in existing:
                conn.execute(f"ALTER TABLE zuzulka_tasks ADD COLUMN {col} {definition}")
                log.info("Migration: added column '%s' to zuzulka_tasks", col)
                
        # 3. Create event_log table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS event_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id     INTEGER,
                timestamp   TEXT NOT NULL,
                event_date  TEXT NOT NULL,
                category    TEXT,
                performer   TEXT,
                title       TEXT,
                description TEXT,
                cost        REAL DEFAULT 0.0
            )
        """)
        
        # Seed initial tasks if the table is completely empty
        count = conn.execute("SELECT COUNT(*) FROM zuzulka_tasks").fetchone()[0]
        if count == 0:
            from datetime import date
            today = date.today().isoformat()
            initial_tasks = [
                ("Міняти фільтр осмосу", today, "custom", 180, 1, "Денис", "фільтри", "Заміна картриджів фільтра питної води", 800.0),
                ("Підсипати бактерії у септик", today, "monthly", 0, 1, "Денис", "септик", "Додати одну дозу бактерій в унітаз", 150.0),
                ("Вивозити сміття", today, "custom", 14, 0, "Денис", "загальне", "Виставити бак на вулицю ввечері", 0.0),
                ("Зняти показники лічильників", today, "monthly", 0, 0, "Денис", "рахунки", "Записати газ, світло, воду", 0.0)
            ]
            conn.executemany("""
                INSERT INTO zuzulka_tasks (title, event_date, freq, interval_days, is_floating, performer, category, description, cost)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, initial_tasks)
            log.info("Database seeded with default home ops tasks")
            
        conn.commit()
