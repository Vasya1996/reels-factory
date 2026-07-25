"""Постоянная очередь сборок Telegram-бота.

SQLite здесь намеренно простой: один bot process и один render worker достаточно
для первых десятков пользователей, а транзакционный claim не даст двум
процессам одновременно забрать одну job. Тяжёлые и платные стадии этот модуль
не запускает — он только хранит состояние и пути.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path


ACTIVE_STATUSES = ("queued", "running")
TERMINAL_STATUSES = ("completed", "qa_failed", "failed", "interrupted", "delivery_failed")


@dataclass(frozen=True)
class BuildJob:
    job_id: str
    chat_id: int
    workdir: Path
    status: str
    created_at: float
    updated_at: float
    attempts: int = 0
    stage: str | None = None
    error: str | None = None
    result: dict | None = None


class JobStore:
    """Durable FIFO-очередь с атомарным захватом задания одним worker."""

    def __init__(self, db_path: Path | str, jobs_root: Path | str):
        self.db_path = Path(db_path)
        self.jobs_root = Path(jobs_root)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.jobs_root.mkdir(parents=True, exist_ok=True)
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
                CREATE TABLE IF NOT EXISTS build_jobs (
                    job_id TEXT PRIMARY KEY,
                    chat_id INTEGER NOT NULL,
                    workdir TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    started_at REAL,
                    finished_at REAL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    stage TEXT,
                    error TEXT,
                    result_json TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_build_jobs_status_created
                ON build_jobs(status, created_at)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_build_jobs_chat_created
                ON build_jobs(chat_id, created_at DESC)
                """
            )

    @staticmethod
    def new_id() -> str:
        return uuid.uuid4().hex

    def workdir_for(self, job_id: str) -> Path:
        return self.jobs_root / job_id

    def enqueue(self, chat_id: int, *, job_id: str | None = None) -> BuildJob:
        job_id = job_id or self.new_id()
        workdir = self.workdir_for(job_id)
        workdir.mkdir(parents=True, exist_ok=False)
        try:
            return self.enqueue_prepared(chat_id, job_id=job_id, workdir=workdir)
        except Exception:
            # Папка пуста на этом этапе; оставлять её как будто job существует
            # хуже, чем аккуратно откатить создание.
            workdir.rmdir()
            raise

    def enqueue_prepared(
        self, chat_id: int, *, job_id: str, workdir: Path | str
    ) -> BuildJob:
        """Поставить в очередь уже полностью подготовленную папку job.

        Bot сначала атомарно пишет scenario.json и лишь затем делает job
        видимой worker — так worker не может забрать полуподготовленную сборку.
        """
        workdir = Path(workdir)
        if not workdir.is_dir():
            raise FileNotFoundError(workdir)
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO build_jobs
                (job_id, chat_id, workdir, status, created_at, updated_at)
                VALUES (?, ?, ?, 'queued', ?, ?)
                """,
                (job_id, int(chat_id), str(workdir.resolve()), now, now),
            )
        return self.get(job_id)

    def _row_to_job(self, row: sqlite3.Row | None) -> BuildJob | None:
        if row is None:
            return None
        raw = row["result_json"]
        result = json.loads(raw) if raw else None
        return BuildJob(
            job_id=row["job_id"],
            chat_id=int(row["chat_id"]),
            workdir=Path(row["workdir"]),
            status=row["status"],
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
            attempts=int(row["attempts"]),
            stage=row["stage"],
            error=row["error"],
            result=result,
        )

    def get(self, job_id: str) -> BuildJob | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM build_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return self._row_to_job(row)

    def latest_for_chat(self, chat_id: int) -> BuildJob | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM build_jobs
                WHERE chat_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (int(chat_id),),
            ).fetchone()
        return self._row_to_job(row)

    def active_for_chat(self, chat_id: int) -> BuildJob | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM build_jobs
                WHERE chat_id = ? AND status IN ('queued', 'running')
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (int(chat_id),),
            ).fetchone()
        return self._row_to_job(row)

    def queued_ahead(self, job_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT created_at FROM build_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if row is None:
                return 0
            count = conn.execute(
                """
                SELECT COUNT(*) AS n FROM build_jobs
                WHERE status = 'queued' AND created_at < ?
                """,
                (float(row["created_at"]),),
            ).fetchone()["n"]
        return int(count)

    def claim_next(self) -> BuildJob | None:
        """Атомарно взять самую старую queued job.

        BEGIN IMMEDIATE сериализует claim даже если позже появится второй bot
        process. Долгая сборка идёт уже после commit и не держит DB-lock.
        """
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT job_id FROM build_jobs
                WHERE status = 'queued'
                ORDER BY created_at
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                conn.commit()
                return None
            now = time.time()
            cur = conn.execute(
                """
                UPDATE build_jobs
                SET status = 'running', updated_at = ?, started_at = ?,
                    attempts = attempts + 1, stage = 'build', error = NULL
                WHERE job_id = ? AND status = 'queued'
                """,
                (now, now, row["job_id"]),
            )
            if cur.rowcount != 1:
                conn.rollback()
                return None
            conn.commit()
            return self.get(row["job_id"])
        finally:
            conn.close()

    def finish(
        self,
        job_id: str,
        status: str,
        *,
        result: dict | None = None,
        stage: str | None = None,
        error: str | None = None,
    ) -> BuildJob:
        if status not in TERMINAL_STATUSES:
            raise ValueError(f"неизвестный terminal status: {status}")
        now = time.time()
        result_json = (
            json.dumps(result, ensure_ascii=False, separators=(",", ":"), default=str)
            if result is not None
            else None
        )
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE build_jobs
                SET status = ?, updated_at = ?, finished_at = ?,
                    stage = ?, error = ?, result_json = ?
                WHERE job_id = ?
                """,
                (status, now, now, stage, (error or "")[:1000] or None, result_json, job_id),
            )
            if cur.rowcount != 1:
                raise KeyError(job_id)
        return self.get(job_id)

    def mark_running_interrupted(self) -> list[BuildJob]:
        """Безопасно остановить осиротевшие jobs после рестарта.

        Автоматически повторять paid pipeline пока нельзя: старый HeyGen-клиент
        ещё не сохраняет provider job id и idempotency key, поэтому повтор может
        списать деньги второй раз. Queued jobs остаются queued и будут взяты
        новым worker; только реально исполнявшиеся переводятся в interrupted.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT job_id FROM build_jobs WHERE status = 'running'"
            ).fetchall()
            if not rows:
                return []
            now = time.time()
            ids = [row["job_id"] for row in rows]
            conn.execute(
                """
                UPDATE build_jobs
                SET status = 'interrupted', updated_at = ?, finished_at = ?,
                    stage = 'restart',
                    error = 'worker был остановлен; автоповтор отключён во избежание повторной оплаты'
                WHERE status = 'running'
                """,
                (now, now),
            )
        return [self.get(job_id) for job_id in ids]
