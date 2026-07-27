"""Деньги фабрики: перевод в микродоллары, журнал трат и балансы пользователей.

Все суммы — целые микродоллары (1 USD = 1_000_000). Float для денег не
используется: вызов Клода стоит доли цента, в центах он схлопнется в ноль, а
float на тысячах записей накопит дрейф.

SQLite намеренно простой, как в jobs.py: один процесс бота и один worker.
Атомарность списания даёт BEGIN IMMEDIATE — журнал и баланс меняются вместе
либо не меняются вовсе.
"""
from __future__ import annotations

import json
import math
import sqlite3
import time
from pathlib import Path

MICRO = 1_000_000


def to_micro(usd: float) -> int:
    """Доллары -> микродоллары, всегда вверх.

    Вверх, а не арифметически: округление вниз на копеечных вызовах Клода
    сделало бы их бесплатными.
    """
    return int(math.ceil(float(usd) * MICRO - 1e-9))


def from_micro(micro: int) -> float:
    return int(micro) / MICRO


class LedgerStore:
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
                CREATE TABLE IF NOT EXISTS balances (
                    chat_id INTEGER PRIMARY KEY,
                    balance_micro INTEGER NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS spend_log (
                    entry_id TEXT PRIMARY KEY,
                    chat_id INTEGER NOT NULL,
                    job_id TEXT,
                    provider TEXT NOT NULL,
                    unit TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    unit_price_micro INTEGER NOT NULL,
                    cost_micro INTEGER NOT NULL,
                    charged_micro INTEGER NOT NULL,
                    refunded_at REAL,
                    created_at REAL NOT NULL,
                    meta_json TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_spend_job ON spend_log(job_id)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS topups (
                    purchase_id TEXT PRIMARY KEY,
                    chat_id INTEGER NOT NULL,
                    amount_minor INTEGER NOT NULL,
                    currency TEXT NOT NULL,
                    credited_micro INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    raw_json TEXT
                )
                """
            )

    def balance(self, chat_id: int) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT balance_micro FROM balances WHERE chat_id = ?",
                (int(chat_id),),
            ).fetchone()
        return int(row["balance_micro"]) if row else 0

    @staticmethod
    def _bump(conn: sqlite3.Connection, chat_id: int, delta_micro: int, now: float) -> None:
        conn.execute(
            """
            INSERT INTO balances (chat_id, balance_micro, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE
            SET balance_micro = balance_micro + excluded.balance_micro,
                updated_at = excluded.updated_at
            """,
            (int(chat_id), int(delta_micro), now),
        )

    def charge(
        self,
        chat_id: int,
        *,
        entry_id: str,
        job_id: str | None,
        provider: str,
        unit: str,
        quantity: float,
        unit_price_micro: int,
        cost_micro: int,
        charged_micro: int,
        meta: dict | None = None,
    ) -> bool:
        """Записать трату и списать её. False — если запись уже была.

        Баланс может уйти в минус: деньги у провайдера уже потрачены, и не
        записать это хуже, чем показать отрицательный баланс.
        """
        now = time.time()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            exists = conn.execute(
                "SELECT 1 FROM spend_log WHERE entry_id = ?", (entry_id,)
            ).fetchone()
            if exists:
                conn.rollback()
                return False
            conn.execute(
                """
                INSERT INTO spend_log
                (entry_id, chat_id, job_id, provider, unit, quantity,
                 unit_price_micro, cost_micro, charged_micro, created_at, meta_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry_id, int(chat_id), job_id, provider, unit, float(quantity),
                    int(unit_price_micro), int(cost_micro), int(charged_micro), now,
                    json.dumps(meta, ensure_ascii=False) if meta else None,
                ),
            )
            self._bump(conn, chat_id, -int(charged_micro), now)
            conn.commit()
            return True
        finally:
            conn.close()

    def credit(
        self,
        chat_id: int,
        micro: int,
        *,
        purchase_id: str,
        amount_minor: int,
        currency: str,
        raw: dict | None = None,
    ) -> bool:
        """Зачислить пополнение. False — если этот purchase_id уже зачислен.

        Вебхуки Tribute ретраятся сутки, поэтому ключ обязателен.
        """
        now = time.time()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            exists = conn.execute(
                "SELECT 1 FROM topups WHERE purchase_id = ?", (purchase_id,)
            ).fetchone()
            if exists:
                conn.rollback()
                return False
            conn.execute(
                """
                INSERT INTO topups
                (purchase_id, chat_id, amount_minor, currency, credited_micro,
                 created_at, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    purchase_id, int(chat_id), int(amount_minor), currency,
                    int(micro), now,
                    json.dumps(raw, ensure_ascii=False) if raw else None,
                ),
            )
            self._bump(conn, chat_id, int(micro), now)
            conn.commit()
            return True
        finally:
            conn.close()

    def refund_job(self, job_id: str) -> int:
        """Вернуть на баланс всё списанное за сборку. Возвращает сумму.

        Сборка упала по нашей вине — пользователь за это не платит.
        Уже возвращённые строки помечены refunded_at и повторно не считаются.
        """
        now = time.time()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                """
                SELECT entry_id, chat_id, charged_micro FROM spend_log
                WHERE job_id = ? AND refunded_at IS NULL
                """,
                (job_id,),
            ).fetchall()
            if not rows:
                conn.rollback()
                return 0
            total = 0
            for row in rows:
                self._bump(conn, int(row["chat_id"]), int(row["charged_micro"]), now)
                total += int(row["charged_micro"])
            conn.execute(
                "UPDATE spend_log SET refunded_at = ? WHERE job_id = ? AND refunded_at IS NULL",
                (now, job_id),
            )
            conn.commit()
            return total
        finally:
            conn.close()

    def job_breakdown(self, job_id: str) -> dict[str, int]:
        """Сколько списано за сборку по каждому провайдеру."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT provider, SUM(charged_micro) AS total FROM spend_log
                WHERE job_id = ? AND refunded_at IS NULL
                GROUP BY provider
                """,
                (job_id,),
            ).fetchall()
        return {row["provider"]: int(row["total"]) for row in rows}
