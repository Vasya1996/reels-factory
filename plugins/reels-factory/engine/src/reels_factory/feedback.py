"""Пожелания пользователей к ещё не готовым функциям.

Отдельная база, а не таблица в billing.sqlite3: к деньгам эти записи
отношения не имеют, а руками их читать проще там, где ничего нельзя
испортить. SQLite как в jobs.py и billing.py — один процесс бота.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path


class FeedbackStore:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS wishes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    username TEXT,
                    topic TEXT NOT NULL,
                    text TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_wishes_topic ON wishes(topic)"
            )

    def add(self, chat_id: int, *, topic: str, text: str,
            username: str | None = None) -> int:
        """Записать пожелание. Возвращает id записи."""
        text = str(text or "").strip()
        if not text:
            raise ValueError("пустое пожелание не пишем")
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO wishes (chat_id, username, topic, text, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (int(chat_id), username or None, str(topic), text, time.time()),
            )
            return int(cur.lastrowid)

    def list(self, *, topic: str | None = None, limit: int = 100) -> list[dict]:
        """Пожелания, новые сверху — читать глазами, не для бота."""
        sql = "SELECT * FROM wishes"
        args: list = []
        if topic:
            sql += " WHERE topic = ?"
            args.append(topic)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(int(limit))
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(sql, args)]

    def count(self, *, topic: str | None = None) -> int:
        sql = "SELECT COUNT(*) FROM wishes"
        args: list = []
        if topic:
            sql += " WHERE topic = ?"
            args.append(topic)
        with self._connect() as conn:
            return int(conn.execute(sql, args).fetchone()[0])
