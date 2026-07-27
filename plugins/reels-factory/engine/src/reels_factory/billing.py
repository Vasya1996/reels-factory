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
import sys
import threading
import time
from pathlib import Path
from uuid import uuid4

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


def heygen_cost_micro(seconds: float, rates: dict, *, twin: bool = False) -> int:
    """Стоимость рендера HeyGen.

    Ветка бота шлёт type:"image" (Photo Avatar) — она дешевле. Digital Twin
    включается, только когда в конфиге клиента задан heygen_look_id.
    """
    key = "heygen_twin_usd_per_second" if twin else "heygen_usd_per_second"
    return to_micro(float(seconds) * float(rates[key]))


def billable_seconds(path) -> float:
    """Длительность готового mp4 — то, за что HeyGen берёт деньги.

    Меряем факт, а не оценку: цена привязана к секундам выданного видео, а не
    к запрошенным. Сбой замера не должен ронять сборку — она уже оплачена,
    просто не учтётся.

    Общий помощник для block-by-block ветки (pipeline.py) и avatar islands
    (avatar_islands.py); живёт здесь, а не в pipeline.py, чтобы избежать
    цикла импорта (pipeline импортирует avatar_islands).
    """
    from reels_factory.render import media_dur
    try:
        return float(media_dur(path))
    except Exception as e:
        # Сборка уже оплачена — не роняем её, но и не молчим: без лога
        # оператор не узнает, что HeyGen списал деньги, а метр этого не увидел.
        print(f"[billing] billable_seconds: не удалось измерить {path}: {e}",
              file=sys.stderr)
        return 0.0


def elevenlabs_cost_micro(chars: int, rates: dict) -> int:
    return to_micro(int(chars) / 1000.0 * float(rates["elevenlabs_usd_per_1k_chars"]))


def claude_cost_micro(usd: float) -> int:
    """Claude Code сам сообщает стоимость вызова в долларах."""
    return to_micro(usd)


def apply_markup(cost_micro: int, markup: float) -> int:
    return int(math.ceil(int(cost_micro) * float(markup) - 1e-9))


def estimate_micro(chars: int, rates: dict, markup: float, *, twin: bool = False) -> int:
    """Грубая оценка до первого платного шага.

    Задача оценки — не угадать цену, а не пустить в рендер с пустым балансом,
    поэтому Клод учитывается плоской добавкой, а секунды считаются из символов.
    """
    seconds = int(chars) / float(rates["chars_per_second"])
    cost = (
        heygen_cost_micro(seconds, rates, twin=twin)
        + elevenlabs_cost_micro(chars, rates)
        + to_micro(rates["claude_flat_usd_per_reel"])
    )
    return apply_markup(cost, markup)


class JobMeter:
    """Учёт трат одной сборки: считает стоимость и сразу списывает.

    Списание идёт по факту каждого платного шага, а не одной суммой в конце:
    если конвейер упадёт посередине, деньги у провайдера уже потрачены и это
    должно остаться в журнале. Возврат за упавшую сборку делает refund_job.
    """

    def __init__(self, store: LedgerStore, *, chat_id: int, job_id: str,
                 rates: dict, markup: float, run_id: str | None = None):
        self.store = store
        self.chat_id = int(chat_id)
        self.job_id = job_id
        self.rates = rates
        self.markup = float(markup)
        # Метка конкретного запуска сборки: у повторного ручного запуска того
        # же job_id она другая, поэтому entry_id не совпадёт с прошлым
        # запуском и второй расход не потеряется как «дубль».
        self.run_id = run_id if run_id is not None else uuid4().hex[:8]
        self._step = 0
        self._charged = 0
        # avatar_islands рендерит шоты параллельно (ThreadPoolExecutor), и
        # несколько потоков могут звать _record одновременно — лок держится
        # ровно вокруг выдачи номера шага и изменения self._charged.
        self._lock = threading.Lock()

    def _record(self, provider: str, unit: str, quantity: float,
                unit_price_micro: int, cost_micro: int) -> None:
        charged = apply_markup(cost_micro, self.markup)
        with self._lock:
            entry_id = f"{self.job_id}:{self.run_id}:{provider}:{self._step}"
            self._step += 1
        if self.store.charge(
            self.chat_id, entry_id=entry_id, job_id=self.job_id,
            provider=provider, unit=unit, quantity=quantity,
            unit_price_micro=unit_price_micro, cost_micro=cost_micro,
            charged_micro=charged,
        ):
            with self._lock:
                self._charged += charged

    def heygen(self, seconds: float, *, cached: bool = False, twin: bool = False) -> None:
        # Попадание в кэш денег не стоит — фрагмент уже отрендерен раньше.
        if cached or seconds <= 0:
            return
        key = "heygen_twin_usd_per_second" if twin else "heygen_usd_per_second"
        self._record(
            "heygen", "seconds", seconds,
            to_micro(self.rates[key]),
            heygen_cost_micro(seconds, self.rates, twin=twin),
        )

    def elevenlabs(self, chars: int) -> None:
        if chars <= 0:
            return
        self._record(
            "elevenlabs", "chars", chars,
            to_micro(self.rates["elevenlabs_usd_per_1k_chars"] / 1000.0),
            elevenlabs_cost_micro(chars, self.rates),
        )

    def claude(self, usd: float) -> None:
        if not usd or usd <= 0:
            return
        self._record("claude", "usd", float(usd), 0, claude_cost_micro(usd))

    def total_charged(self) -> int:
        return self._charged
