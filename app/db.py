"""SQLite 연결. Flask 요청 안에서는 get_db(), 그 밖(CLI·스크립트)에서는 connect()를 쓴다."""
import sqlite3
from pathlib import Path

from flask import current_app, g

SCHEMA = Path(__file__).with_name("schema.sql")


def connect(db_path):
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


NEW_ATT_COLUMNS = [("text_body", "TEXT"), ("text_status", "TEXT"), ("text_at", "TEXT")]


def _migrate(conn):
    """이전 버전 DB 에 새 열을 붙인다(스키마 파일의 CREATE TABLE IF NOT EXISTS 는 기존 표를 바꾸지 않으므로)."""
    for table, cols in (("attachments", NEW_ATT_COLUMNS),):
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if have:
            for name, typ in cols:
                if name not in have:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")
            conn.commit()


def init_schema(conn):
    _migrate(conn)
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.commit()


def get_db():
    if "db" not in g:
        g.db = connect(current_app.config["DB_PATH"])
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_app(app):
    app.teardown_appcontext(close_db)
    conn = connect(app.config["DB_PATH"])
    try:
        init_schema(conn)
    finally:
        conn.close()
