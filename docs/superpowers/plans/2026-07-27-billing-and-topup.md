# Биллинг и пополнение баланса — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Считать себестоимость рилса по каждому провайдеру, списывать её с наценкой из виртуального баланса пользователя, блокировать рендер при нехватке и принимать пополнение через Tribute без ручного участия.

**Architecture:** Новый модуль `billing.py` хранит балансы и журнал трат в `work/billing.sqlite3` (тот же паттерн, что `jobs.py`: WAL, connection-per-call, `BEGIN IMMEDIATE`). Точки учёта врезаются в существующие вызовы провайдеров; каждая записывает строку журнала и меняет баланс одной транзакцией. Пополнение приходит вебхуком Tribute на `ThreadingHTTPServer` внутри процесса бота, снаружи его терминирует уже установленный Caddy.

**Tech Stack:** Python 3.11+, стандартные `sqlite3`/`hmac`/`http.server` (новых зависимостей нет), pytest, Caddy на сервере.

## Global Constraints

- Деньги — **только целые микродоллары** (1 USD = 1_000_000). Float для денег запрещён.
- Каждая запись в журнал и изменение баланса — **одна транзакция**, ключ идемпотентности обязателен.
- Файлы Юли не трогать: `compose.py`, `render.py`, `captions.py`, `edit.py`, `zoom.py`, `revideo_*`, `twin.py`, `engine/revideo/`. Читать и импортировать из них можно (Task 5 берёт `render.media_dur`), менять — нет.
- **`pipeline.py` править МОЖНО — Вася дал добро 2026-07-27.** Файл числился спорным (в передаточном документе от 2026-07-24 он в зоне Юли, в дорожной карте — в зоне Васи), вопрос закрыт: Вася сам предупредит Юлю, чтобы она синхронизировала свою локальную копию с GitHub. Правку держать минимальной — один параметр `meter=None` в сигнатуру `run_make` и два вызова колбэка; без `meter` поведение не меняется. Ничего сверх учёта в этом файле не трогать.
- Ветка `feat/vasya-billing` от `main`, вливать через PR. Показать дифф словами и дождаться «ок» перед push.
- Тесты на русском, как в существующих (`def test_баланс_не_уходит_в_минус`).
- Команда тестов: `.venv\Scripts\python.exe -m pytest -q` из `plugins/reels-factory/engine`.
- Ставки: HeyGen Photo Avatar `$0.05/сек`, HeyGen Digital Twin `$0.0667/сек`, ElevenLabs `$0.10/1000 симв`, наценка `2.0`.
- Ключ Tribute читается из env `TRIBUTE_API_KEY`; в код и в git не попадает.

## File Structure

| Файл | Ответственность |
|---|---|
| `src/reels_factory/billing.py` | создать — деньги: перевод в микродоллары, расчёт стоимости по ставкам, `LedgerStore` (балансы, журнал, пополнения) |
| `src/reels_factory/tribute.py` | создать — вебхук Tribute: проверка подписи, разбор события, зачисление |
| `src/reels_factory/config.py` | изменить — читатель секции `billing` из `factory/config.yaml` |
| `src/reels_factory/llm.py` | изменить — `--output-format json`, отдать фактическую стоимость вызова |
| `src/reels_factory/tts.py` | изменить — вернуть число символов синтеза наружу |
| `src/reels_factory/pipeline.py` | изменить — врезать учёт HeyGen и ElevenLabs |
| `src/reels_factory/__main__.py` | изменить — создать учёт трат в `_cmd_make`: сборка идёт отдельным процессом, объект учёта живёт там |
| `src/reels_factory/bot.py` | изменить — оценка до рендера, возврат при сбое, экраны баланса и пополнения, запуск слушателя |
| `templates/config.example.yaml` | изменить — секция `billing` с дефолтами |
| `tests/test_billing.py` | создать |
| `tests/test_tribute.py` | создать |

---

### Task 1: Деньги и журнал — `billing.py`

**Files:**
- Create: `plugins/reels-factory/engine/src/reels_factory/billing.py`
- Test: `plugins/reels-factory/engine/tests/test_billing.py`

**Interfaces:**
- Consumes: ничего (первая задача)
- Produces: `to_micro(usd: float) -> int`, `from_micro(micro: int) -> float`, `LedgerStore(db_path)` с методами `balance(chat_id) -> int`, `charge(chat_id, *, entry_id, job_id, provider, unit, quantity, unit_price_micro, cost_micro, charged_micro, meta=None) -> bool`, `credit(chat_id, micro, *, purchase_id, amount_minor, currency, raw=None) -> bool`, `refund_job(job_id) -> int`, `job_breakdown(job_id) -> dict[str, int]`

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_billing.py`:

```python
import pytest

from reels_factory.billing import LedgerStore, from_micro, to_micro


@pytest.fixture
def store(tmp_path):
    return LedgerStore(tmp_path / "billing.sqlite3")


def test_микродоллары_округляются_вверх():
    # $0.0000005 не должен схлопнуться в ноль: иначе дешёвые вызовы Клода
    # будут бесплатными и баланс поедет.
    assert to_micro(0.0000005) == 1
    assert to_micro(1.0) == 1_000_000
    assert from_micro(1_500_000) == 1.5


def test_баланс_нового_пользователя_ноль(store):
    assert store.balance(777) == 0


def test_списание_уменьшает_баланс(store):
    store.credit(777, 10_000_000, purchase_id="p1", amount_minor=1000, currency="usd")
    ok = store.charge(
        777, entry_id="job1:heygen:0", job_id="job1", provider="heygen",
        unit="seconds", quantity=30.0, unit_price_micro=50_000,
        cost_micro=1_500_000, charged_micro=3_000_000,
    )
    assert ok is True
    assert store.balance(777) == 7_000_000


def test_повторное_списание_с_тем_же_ключом_игнорируется(store):
    store.credit(777, 10_000_000, purchase_id="p1", amount_minor=1000, currency="usd")
    kw = dict(
        entry_id="job1:heygen:0", job_id="job1", provider="heygen",
        unit="seconds", quantity=30.0, unit_price_micro=50_000,
        cost_micro=1_500_000, charged_micro=3_000_000,
    )
    assert store.charge(777, **kw) is True
    assert store.charge(777, **kw) is False
    assert store.balance(777) == 7_000_000


def test_повторное_пополнение_с_тем_же_purchase_id_игнорируется(store):
    assert store.credit(777, 10_000_000, purchase_id="p1", amount_minor=1000, currency="usd") is True
    assert store.credit(777, 10_000_000, purchase_id="p1", amount_minor=1000, currency="usd") is False
    assert store.balance(777) == 10_000_000


def test_баланс_уходит_в_минус_но_списание_проходит(store):
    # Платный шаг уже случился у провайдера — не записать его нельзя.
    store.charge(
        777, entry_id="job1:tts:0", job_id="job1", provider="elevenlabs",
        unit="chars", quantity=500, unit_price_micro=100,
        cost_micro=50_000, charged_micro=100_000,
    )
    assert store.balance(777) == -100_000


def test_возврат_за_упавшую_сборку(store):
    store.credit(777, 10_000_000, purchase_id="p1", amount_minor=1000, currency="usd")
    store.charge(
        777, entry_id="job1:tts:0", job_id="job1", provider="elevenlabs",
        unit="chars", quantity=500, unit_price_micro=100,
        cost_micro=50_000, charged_micro=100_000,
    )
    store.charge(
        777, entry_id="job1:heygen:0", job_id="job1", provider="heygen",
        unit="seconds", quantity=30.0, unit_price_micro=50_000,
        cost_micro=1_500_000, charged_micro=3_000_000,
    )
    returned = store.refund_job("job1")
    assert returned == 3_100_000
    assert store.balance(777) == 10_000_000


def test_повторный_возврат_ничего_не_меняет(store):
    store.credit(777, 10_000_000, purchase_id="p1", amount_minor=1000, currency="usd")
    store.charge(
        777, entry_id="job1:tts:0", job_id="job1", provider="elevenlabs",
        unit="chars", quantity=500, unit_price_micro=100,
        cost_micro=50_000, charged_micro=100_000,
    )
    assert store.refund_job("job1") == 100_000
    assert store.refund_job("job1") == 0
    assert store.balance(777) == 10_000_000


def test_разбивка_по_провайдерам(store):
    store.charge(
        777, entry_id="job1:tts:0", job_id="job1", provider="elevenlabs",
        unit="chars", quantity=500, unit_price_micro=100,
        cost_micro=50_000, charged_micro=100_000,
    )
    store.charge(
        777, entry_id="job1:heygen:0", job_id="job1", provider="heygen",
        unit="seconds", quantity=30.0, unit_price_micro=50_000,
        cost_micro=1_500_000, charged_micro=3_000_000,
    )
    assert store.job_breakdown("job1") == {"elevenlabs": 100_000, "heygen": 3_000_000}
```

- [ ] **Step 2: Запустить тест, убедиться что падает**

Run: `.venv\Scripts\python.exe -m pytest tests/test_billing.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'reels_factory.billing'`

- [ ] **Step 3: Написать минимальную реализацию**

Создать `src/reels_factory/billing.py`:

```python
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
```

- [ ] **Step 4: Запустить тесты, убедиться что проходят**

Run: `.venv\Scripts\python.exe -m pytest tests/test_billing.py -q`
Expected: PASS, 9 passed

- [ ] **Step 5: Коммит**

```bash
git add plugins/reels-factory/engine/src/reels_factory/billing.py plugins/reels-factory/engine/tests/test_billing.py
git commit -m "feat(billing): add ledger store with balances and spend log"
```

---

### Task 2: Ставки в конфиге и расчёт стоимости

**Files:**
- Modify: `plugins/reels-factory/engine/src/reels_factory/config.py` (добавить в конец файла)
- Modify: `plugins/reels-factory/engine/src/reels_factory/billing.py` (добавить функции стоимости)
- Modify: `plugins/reels-factory/templates/config.example.yaml`
- Test: `plugins/reels-factory/engine/tests/test_billing.py` (дописать)

**Interfaces:**
- Consumes: `to_micro` из Task 1
- Produces: `config.load_billing_config() -> dict`; в `billing.py` — `heygen_cost_micro(seconds, rates, *, twin=False) -> int`, `elevenlabs_cost_micro(chars, rates) -> int`, `claude_cost_micro(usd) -> int`, `apply_markup(cost_micro, markup) -> int`, `estimate_micro(chars, rates, markup, *, twin=False) -> int`

- [ ] **Step 1: Написать падающий тест**

Дописать в `tests/test_billing.py`:

```python
from reels_factory.billing import (
    apply_markup, claude_cost_micro, elevenlabs_cost_micro,
    estimate_micro, heygen_cost_micro,
)
from reels_factory.config import load_billing_config

RATES = {
    "heygen_usd_per_second": 0.05,
    "heygen_twin_usd_per_second": 0.0667,
    "elevenlabs_usd_per_1k_chars": 0.10,
    "chars_per_second": 14.0,
    "claude_flat_usd_per_reel": 0.05,
}


def test_стоимость_heygen_по_секундам():
    # 30 секунд Photo Avatar по $0.05/сек = $1.50
    assert heygen_cost_micro(30.0, RATES) == 1_500_000


def test_стоимость_heygen_digital_twin_дороже():
    assert heygen_cost_micro(30.0, RATES, twin=True) == 2_001_000


def test_стоимость_elevenlabs_по_символам():
    # 1000 символов по $0.10/1000 = $0.10
    assert elevenlabs_cost_micro(1000, RATES) == 100_000


def test_стоимость_клода_из_долларов():
    assert claude_cost_micro(0.0342) == 34_200


def test_наценка_удваивает():
    assert apply_markup(1_500_000, 2.0) == 3_000_000


def test_оценка_рилса_включает_обоих_провайдеров_и_наценку():
    # 420 символов -> 30 секунд; heygen $1.50 + eleven $0.042 + claude $0.05
    # = $1.592, с наценкой 2.0 -> $3.184
    assert estimate_micro(420, RATES, 2.0) == 3_184_000


def test_конфиг_биллинга_отдаёт_дефолты_без_файла(tmp_path, monkeypatch):
    # Подменяем сам CONFIG_PATH, а не cwd: путь вычисляется один раз при
    # импорте модуля, и monkeypatch.chdir на него уже не влияет — тест
    # молча читал бы реальный конфиг машины.
    import reels_factory.config as cfg_mod
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", tmp_path / "config.yaml")

    cfg = load_billing_config()
    assert cfg["markup"] == 2.0
    assert cfg["rates"]["heygen_usd_per_second"] == 0.05
    assert cfg["enabled"] is True


def test_конфиг_биллинга_накладывает_значения_поверх_дефолтов(tmp_path, monkeypatch):
    import reels_factory.config as cfg_mod
    path = tmp_path / "config.yaml"
    path.write_text(
        "billing:\n  markup: 3.0\n  rates:\n    heygen_usd_per_second: 0.07\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", path)

    cfg = load_billing_config()
    assert cfg["markup"] == 3.0
    assert cfg["rates"]["heygen_usd_per_second"] == 0.07
    # не заданное в файле остаётся дефолтным
    assert cfg["rates"]["elevenlabs_usd_per_1k_chars"] == 0.10
    assert cfg["fx"]["rub"] == 0.011
```

- [ ] **Step 2: Запустить тест, убедиться что падает**

Run: `.venv\Scripts\python.exe -m pytest tests/test_billing.py -q -k "стоимость or наценка or оценка or конфиг_биллинга"`
Expected: FAIL — `ImportError: cannot import name 'heygen_cost_micro'`

- [ ] **Step 3: Написать реализацию**

Дописать в конец `src/reels_factory/billing.py`:

```python
def heygen_cost_micro(seconds: float, rates: dict, *, twin: bool = False) -> int:
    """Стоимость рендера HeyGen.

    Ветка бота шлёт type:"image" (Photo Avatar) — она дешевле. Digital Twin
    включается, только когда в конфиге клиента задан heygen_look_id.
    """
    key = "heygen_twin_usd_per_second" if twin else "heygen_usd_per_second"
    return to_micro(float(seconds) * float(rates[key]))


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
```

Дописать в конец `src/reels_factory/config.py`:

```python
# Биллинг: ставки провайдеров и наценка. Обновляются руками при смене прайса
# провайдера — автоматического источника цен для HeyGen/ElevenLabs не существует.
BILLING_DEFAULTS = {
    "enabled": True,
    "markup": 2.0,
    "rates": {
        "heygen_usd_per_second": 0.05,
        "heygen_twin_usd_per_second": 0.0667,
        "elevenlabs_usd_per_1k_chars": 0.10,
        "chars_per_second": 14.0,
        "claude_flat_usd_per_reel": 0.05,
    },
    "fx": {"usd": 1.0, "eur": 1.08, "rub": 0.011},
}


def load_billing_config() -> dict:
    """Секция billing из factory/config.yaml поверх дефолтов.

    Отсутствие файла — не ошибка: биллинг должен работать и на чистой машине.
    """
    merged = {
        "enabled": BILLING_DEFAULTS["enabled"],
        "markup": BILLING_DEFAULTS["markup"],
        "rates": dict(BILLING_DEFAULTS["rates"]),
        "fx": dict(BILLING_DEFAULTS["fx"]),
    }
    try:
        raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return merged
    section = raw.get("billing") or {}
    if "enabled" in section:
        merged["enabled"] = bool(section["enabled"])
    if "markup" in section:
        merged["markup"] = float(section["markup"])
    merged["rates"].update(section.get("rates") or {})
    merged["fx"].update(section.get("fx") or {})
    return merged
```

Дописать в конец `templates/config.example.yaml`:

```yaml
# Биллинг: себестоимость рилса и наценка на пользователя.
# Ставки сверять с прайсом провайдера при изменении — автообновления нет.
billing:
  enabled: true
  markup: 2.0            # 2.0 = наценка 100%
  rates:
    heygen_usd_per_second: 0.05        # Avatar IV Photo Avatar (ветка бота)
    heygen_twin_usd_per_second: 0.0667 # Digital Twin (когда задан look_id)
    elevenlabs_usd_per_1k_chars: 0.10  # pay-as-you-go Multilingual v2/v3
    chars_per_second: 14.0             # для оценки длительности до рендера
    claude_flat_usd_per_reel: 0.05     # плоская добавка в оценку
  fx:                    # курсы для зачисления пополнений, приходящих не в USD
    usd: 1.0
    eur: 1.08
    rub: 0.011
```

- [ ] **Step 4: Запустить тесты**

Run: `.venv\Scripts\python.exe -m pytest tests/test_billing.py -q`
Expected: PASS, 17 passed

- [ ] **Step 5: Коммит**

```bash
git add plugins/reels-factory/engine/src/reels_factory/billing.py plugins/reels-factory/engine/src/reels_factory/config.py plugins/reels-factory/templates/config.example.yaml plugins/reels-factory/engine/tests/test_billing.py
git commit -m "feat(billing): add provider rates config and cost calculators"
```

---

### Task 3: Клод отдаёт стоимость вызова

**Files:**
- Modify: `plugins/reels-factory/engine/src/reels_factory/llm.py:82-97`
- Test: `plugins/reels-factory/engine/tests/test_llm.py`

**Interfaces:**
- Consumes: ничего
- Produces: `ClaudeSkillRunner.run_skill(skill, payload_path) -> str` (контракт прежний — возвращает текст результата); новые атрибуты `ClaudeSkillRunner.last_cost_usd: float | None` (стоимость последнего вызова) и `ClaudeSkillRunner.total_cost_usd: float` (сумма всех вызовов этого runner — именно её списывают)

- [ ] **Step 1: Написать падающий тест**

Дописать в `tests/test_llm.py`:

```python
import json
from types import SimpleNamespace

from reels_factory.llm import ClaudeSkillRunner


def test_скилл_возвращает_текст_из_json(monkeypatch, tmp_path):
    payload = json.dumps({
        "type": "result", "subtype": "success", "is_error": False,
        "result": "готовый текст сценария",
        "total_cost_usd": 0.0342,
    })
    monkeypatch.setattr(
        "reels_factory.llm.subprocess.run",
        lambda *a, **kw: SimpleNamespace(returncode=0, stdout=payload, stderr=""),
    )
    runner = ClaudeSkillRunner(config_dir=tmp_path / "profile")
    assert runner.run_skill("script", "payload.json") == "готовый текст сценария"
    assert runner.last_cost_usd == 0.0342


def test_скилл_просит_json_формат(monkeypatch, tmp_path):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"result": "ок", "total_cost_usd": 0.01}),
            stderr="",
        )

    monkeypatch.setattr("reels_factory.llm.subprocess.run", fake_run)
    ClaudeSkillRunner(config_dir=tmp_path / "profile").run_skill("script", "p.json")
    assert "--output-format" in seen["cmd"]
    assert seen["cmd"][seen["cmd"].index("--output-format") + 1] == "json"


def test_шум_перед_json_не_ломает_разбор(monkeypatch, tmp_path):
    # node и прочие подпроцессы пишут в тот же stdout; берём последний
    # JSON-объект, а не весь поток целиком.
    noisy = 'npm warn something\n' + json.dumps({"result": "ок", "total_cost_usd": 0.02})
    monkeypatch.setattr(
        "reels_factory.llm.subprocess.run",
        lambda *a, **kw: SimpleNamespace(returncode=0, stdout=noisy, stderr=""),
    )
    runner = ClaudeSkillRunner(config_dir=tmp_path / "profile")
    assert runner.run_skill("script", "p.json") == "ок"
    assert runner.last_cost_usd == 0.02


def test_стоимость_нескольких_вызовов_суммируется(monkeypatch, tmp_path):
    # Один runner обслуживает генерацию, хуманизатор и судью подряд —
    # по last_cost_usd видно только последний вызов.
    monkeypatch.setattr(
        "reels_factory.llm.subprocess.run",
        lambda *a, **kw: SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"result": "ок", "total_cost_usd": 0.01}),
            stderr="",
        ),
    )
    runner = ClaudeSkillRunner(config_dir=tmp_path / "profile")
    runner.run_skill("script", "p.json")
    runner.run_skill("humanizing-speech", "p.json")
    runner.run_skill("judge", "p.json")
    assert runner.last_cost_usd == 0.01
    assert round(runner.total_cost_usd, 4) == 0.03


def test_невалидный_json_падает_понятной_ошибкой(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "reels_factory.llm.subprocess.run",
        lambda *a, **kw: SimpleNamespace(returncode=0, stdout="не json вовсе", stderr=""),
    )
    runner = ClaudeSkillRunner(config_dir=tmp_path / "profile")
    try:
        runner.run_skill("script", "p.json")
    except RuntimeError as exc:
        assert "JSON" in str(exc)
    else:
        raise AssertionError("ожидали RuntimeError")
```

- [ ] **Step 2: Запустить тест, убедиться что падает**

Run: `.venv\Scripts\python.exe -m pytest tests/test_llm.py -q -k "json"`
Expected: FAIL — `run_skill` возвращает весь stdout, `last_cost_usd` не существует

- [ ] **Step 3: Написать реализацию**

В `src/reels_factory/llm.py` добавить импорт `json` в начало файла (после `import os`) и заменить класс `ClaudeSkillRunner` целиком на:

```python
class ClaudeSkillRunner:
    """Вызов скилла плагина: claude -p "/reels-factory:<skill> <payload>".

    Скилл разворачивается в промпт детерминированно (headless-механизм
    Claude Code); --plugin-dir гарантирует загрузку локального плагина.

    Изоляция: свой CLAUDE_CONFIG_DIR + --setting-sources "" (ни user, ни
    project, ни local настроек) + --strict-mcp-config (ноль MCP) + выключенная
    авто-память. ANTHROPIC_API_KEY/ANTHROPIC_AUTH_TOKEN вычищаются: они
    приоритетнее подписки и молча перевели бы вызовы на платный API.

    Формат ответа — json, а не text: только так CLI сообщает стоимость вызова,
    без которой Клода нечем учитывать в себестоимости рилса. Наружу отдаётся
    поле result, поэтому вызывающий код не меняется.
    """

    def __init__(self, plugin_dir=None, timeout_s: int = 600, config_dir=None):
        from reels_factory.config import PLUGIN_DIR
        if plugin_dir is not None:
            # Preserve path format: use as_posix() for Path objects to avoid Windows backslash conversion
            self.plugin_dir = plugin_dir.as_posix() if hasattr(plugin_dir, 'as_posix') else str(plugin_dir)
        else:
            self.plugin_dir = str(PLUGIN_DIR)
        self.config_dir = Path(config_dir) if config_dir else SKILL_PROFILE_DIR
        self.timeout_s = timeout_s
        self.exe = shutil.which("claude") or "claude"
        self.last_cost_usd: float | None = None
        # Один runner обслуживает несколько скиллов подряд (генерация,
        # хуманизатор, судья), поэтому нужна и сумма: по last_cost_usd
        # видно только последний вызов, и остальные потерялись бы.
        self.total_cost_usd: float = 0.0

    def _env(self) -> dict:
        env = dict(os.environ)
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("ANTHROPIC_AUTH_TOKEN", None)
        env["CLAUDE_CONFIG_DIR"] = str(self.config_dir)
        env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
        return env

    @staticmethod
    def _extract_json(stdout: str) -> dict:
        """Последний JSON-объект из потока.

        Подпроцессы (node и прочие) пишут в тот же stdout, поэтому просто
        json.loads(stdout) ненадёжен.
        """
        text = (stdout or "").strip()
        for start in range(len(text)):
            if text[start] != "{":
                continue
            try:
                obj = json.loads(text[start:])
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                return obj
        raise RuntimeError(f"claude -p вернул не JSON: {text[:300]}")

    def run_skill(self, skill: str, payload_path) -> str:
        prompt = f"/reels-factory:{skill} {payload_path}"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        p = subprocess.run(
            [self.exe, "-p", "--output-format", "json",
             "--plugin-dir", self.plugin_dir,
             "--setting-sources", "", "--strict-mcp-config"],
            input=prompt, capture_output=True, text=True, encoding="utf-8",
            timeout=self.timeout_s, env=self._env(),
        )
        if p.returncode != 0:
            # ошибки входа CLI печатает в stdout, поэтому берём оба потока
            err = (p.stderr or "").strip() or (p.stdout or "").strip()
            raise RuntimeError(
                f"claude -p /{skill} failed (code {p.returncode}): {err[:500]}")
        obj = self._extract_json(p.stdout)
        cost = obj.get("total_cost_usd")
        self.last_cost_usd = float(cost) if cost is not None else None
        if self.last_cost_usd:
            self.total_cost_usd += self.last_cost_usd
        return obj.get("result", "")
```

- [ ] **Step 4: Починить два существующих теста — они сломаются, и это ожидаемо**

Оба подсовывают в `stdout` не-JSON и ждут его обратно дословно. Теперь `run_skill`
возвращает поле `result`, поэтому заглушки надо привести к настоящему формату CLI.

В `tests/test_llm.py::test_claude_skill_runner_builds_command` было:

```python
    class P:
        returncode = 0
        stdout = '{"ok": true}'
        stderr = ""
...
    assert out == '{"ok": true}'
```

стало:

```python
    class P:
        returncode = 0
        stdout = '{"result": "{\\"ok\\": true}", "total_cost_usd": 0.01}'
        stderr = ""
...
    assert out == '{"ok": true}'
```

В `tests/test_llm.py::test_скилл_зовётся_в_изоляции` было:

```python
        stdout = "ok"
```

стало:

```python
        stdout = '{"result": "ok", "total_cost_usd": 0.01}'
```

Остальные проверки в обоих тестах (флаги команды, env, изоляция) не трогать —
они про другое и остаются валидными.

- [ ] **Step 5: Запустить тесты модуля**

Run: `.venv\Scripts\python.exe -m pytest tests/test_llm.py -q`
Expected: PASS — и новые, и оба починенных

- [ ] **Step 6: Прогнать весь набор — контракт run_skill не должен сломать вызывающих**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: PASS. Если падает что-то в `test_scenario.py` или `test_pipeline.py` —
значит там тоже подсовывали сырой stdout: поправить заглушку теста на формат
`{"result": ..., "total_cost_usd": ...}`, реализацию не менять.

- [ ] **Step 7: Коммит**

```bash
git add plugins/reels-factory/engine/src/reels_factory/llm.py plugins/reels-factory/engine/tests/test_llm.py
git commit -m "feat(llm): switch skill runner to json output and expose call cost"
```

---

### Task 4: Учёт ElevenLabs

**Files:**
- Modify: `plugins/reels-factory/engine/src/reels_factory/tts.py:170-213` (`synth_voice`)
- Test: `plugins/reels-factory/engine/tests/test_tts.py`

**Interfaces:**
- Consumes: ничего
- Produces: `tts.synth_voice(...)` дополнительно принимает `meter=None` — вызываемое `meter(chars: int) -> None`, куда передаётся число синтезированных символов

- [ ] **Step 1: Написать падающий тест**

Дописать в `tests/test_tts.py`:

`synth_voice` не ходит через `ElevenLabsClient` — он сам делает `http.post`,
а `http` и `run_cmd` принимает параметрами. Поэтому подменяем их, как это уже
делают существующие тесты в этом файле (`_FakeHttp` объявлен там же, строка 24).

```python
def test_synth_voice_сообщает_число_символов(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    seen = []
    text = "Привет, это тестовая фраза для озвучки."

    synth_voice(text, tmp_path / "g.wav", voice_id="v1", http=_FakeHttp(),
                run_cmd=lambda *a, **kw: None, meter=seen.append)

    assert seen == [len(text)]


def test_synth_voice_без_meter_работает_как_раньше(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    # meter необязателен: движок зовут и вручную, там учёта нет.
    out = synth_voice("текст", tmp_path / "g.wav", voice_id="v1",
                      http=_FakeHttp(), run_cmd=lambda *a, **kw: None)
    assert out == tmp_path / "g.wav"
```

- [ ] **Step 2: Запустить тест, убедиться что падает**

Run: `.venv\Scripts\python.exe -m pytest tests/test_tts.py -q -k "meter or символов"`
Expected: FAIL — `synth_voice() got an unexpected keyword argument 'meter'`

- [ ] **Step 3: Реализация**

В `src/reels_factory/tts.py` сигнатуру `synth_voice` (строка 170) дополнить
последним параметром:

```python
def synth_voice(text: str, out_wav: Path, voice_id: str | None = None,
                model_id: str | None = None, stability: float | None = None,
                http=None, run_cmd=None, meter=None) -> Path:
```

и вставить учёт сразу после `resp.raise_for_status()` (строка ~205), до
`mp3_tmp.write_bytes(...)`:

```python
    resp.raise_for_status()
    # Считаем ровно то, за что берёт деньги ElevenLabs — символы запроса.
    # После raise_for_status: за упавший запрос платить не за что.
    if meter is not None:
        meter(len(text))
```

- [ ] **Step 4: Запустить тесты**

Run: `.venv\Scripts\python.exe -m pytest tests/test_tts.py -q`
Expected: PASS

- [ ] **Step 5: Коммит**

```bash
git add plugins/reels-factory/engine/src/reels_factory/tts.py plugins/reels-factory/engine/tests/test_tts.py
git commit -m "feat(tts): report synthesized character count for metering"
```

---

### Task 5: Учёт HeyGen и сведение трат в конвейере

**Files:**
- Modify: `plugins/reels-factory/engine/src/reels_factory/pipeline.py:74-81` (сигнатура `run_make`), `:240` (вызов синтеза речи), `:255-276` (ветка avatar islands — предохранитель), `:277-292` (цикл по блокам — учёт HeyGen), `:60` (вспомогательная `_billable_seconds`)
- Test: `plugins/reels-factory/engine/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `tts.synth_voice(..., meter=...)` из Task 4
- Produces: `run_make(...)` дополнительно принимает `meter=None` — объект с методами `heygen(seconds: float, *, cached: bool = False, twin: bool = False)` и `elevenlabs(chars: int)`. Возвращаемый `dict` **не меняется**: траты уходят в журнал, а не в ответ конвейера — иначе их пришлось бы тащить через границу процессов.

- [ ] **Step 1: Написать падающий тест**

Дописать в `tests/test_pipeline.py`:

```python
class _FakeMeter:
    def __init__(self):
        self.heygen_calls = []
        self.eleven_calls = []

    def heygen(self, seconds, *, cached=False, twin=False):
        self.heygen_calls.append((seconds, cached, twin))

    def elevenlabs(self, chars):
        self.eleven_calls.append(chars)


def test_кэшированный_фрагмент_не_тарифицируется():
    meter = _FakeMeter()
    meter.heygen(12.0, cached=True, twin=False)
    meter.heygen(30.0, cached=False, twin=False)
    billable = [s for s, cached, _ in meter.heygen_calls if not cached]
    assert billable == [30.0]


def test_run_make_принимает_meter():
    import inspect
    from reels_factory.pipeline import run_make
    assert "meter" in inspect.signature(run_make).parameters
```

- [ ] **Step 2: Запустить тест, убедиться что падает**

Run: `.venv\Scripts\python.exe -m pytest tests/test_pipeline.py -q -k "meter"`
Expected: FAIL — `assert "meter" in ...` не проходит

- [ ] **Step 3: Реализация**

В `src/reels_factory/pipeline.py`:

1. В сигнатуру `run_make` (строка 74) добавить последним параметром `meter=None`.

2. Пробросить в синтез речи. Строка ~240 — было:

```python
                synth_fn(text, wav, voice_id=voice_id)
```

стало:

```python
                synth_fn(
                    text, wav, voice_id=voice_id,
                    meter=(meter.elevenlabs if meter is not None else None),
                )
```

3. Врезать учёт в цикл по блокам (строки ~278–292). **В этом цикле три ветки, и
платная из них только две** — `covered_block_fn` рендерит локально через ffmpeg,
HeyGen там не участвует и денег не стоит. Кэш есть только у роли `cta`.

Было:

```python
            for i, (b, wav) in enumerate(zip(scenario["blocks"], block_wavs)):
                if fmt in ("split", "avatar"):
                    role = b.get("role")
                    if role == "cta":
                        mp4 = cached_generate(
                            avatar_client, wav, cache_dir, role=role
                        )
                    elif i in covered_blocks:
                        mp4 = covered_block_fn(wav, wd / f"avatar_{i}.mp4")
                    else:
                        # role задаёт пластику: хук энергичный, payoff спокойный
                        mp4 = avatar_client.generate(
                            wav, wd / f"avatar_{i}.mp4", role=role
                        )
                    avatar_mp4s.append(mp4)
```

Стало:

```python
            for i, (b, wav) in enumerate(zip(scenario["blocks"], block_wavs)):
                if fmt in ("split", "avatar"):
                    role = b.get("role")
                    billable = True
                    if role == "cta":
                        # Попадание в кэш проверяем ДО вызова: сам
                        # cached_generate возвращает путь одинаково в обоих
                        # случаях, и по нему хит от промаха не отличить.
                        key = avatar_cache_key(avatar_client, wav, role=role)
                        billable = not (cache_dir / f"{key}.mp4").exists()
                        mp4 = cached_generate(
                            avatar_client, wav, cache_dir, role=role
                        )
                    elif i in covered_blocks:
                        # Локальный ffmpeg, HeyGen не вызывается — не платно.
                        billable = False
                        mp4 = covered_block_fn(wav, wd / f"avatar_{i}.mp4")
                    else:
                        # role задаёт пластику: хук энергичный, payoff спокойный
                        mp4 = avatar_client.generate(
                            wav, wd / f"avatar_{i}.mp4", role=role
                        )
                    if meter is not None and billable:
                        meter.heygen(
                            _billable_seconds(mp4),
                            twin=bool(getattr(avatar_client, "look_id", None)),
                        )
                    avatar_mp4s.append(mp4)
```

Импорт `avatar_cache_key` добавить к существующему импорту из `avatar` (строка 27):

```python
from reels_factory.avatar import (
    HeyGenClient, avatar_cache_key, cached_generate, render_covered_block,
)
```

4. **Ветка `use_avatar_islands` (строки ~255–276) в этом плане НЕ учитывается —
её нужно закрыть предохранителем, а не догадками.** Она рендерит аватара через
`_render_avatar_islands` внутри `avatar_islands.py` (30 КБ), и точки вызова
HeyGen там свои. Ветка включается только при `master_audio.enabled: true`, а это
`false` по умолчанию — то есть сейчас она выключена. Чтобы её нельзя было
включить и незаметно рендерить бесплатно, сразу после `avatar_mp4s = list(...)`
в этой ветке добавить:

```python
            if meter is not None:
                raise RuntimeError(
                    "учёт трат не поддерживает ветку avatar islands: "
                    "включите master_audio.enabled=false или снимите биллинг"
                )
```

Учёт для этой ветки — отдельная задача: разобрать `rendered.manifest` и брать
секунды оттуда. В этот план она не входит.

4. Длительность мерить **уже существующей** `render.media_dur` — своего пробника
не писать, он в проекте уже есть (`render.py:33`). Добавить рядом с `_log`
(строка 60) только обёртку, гасящую сбой замера:

```python
def _billable_seconds(path) -> float:
    """Длительность готового mp4 — то, за что HeyGen берёт деньги.

    Меряем факт, а не оценку: цена привязана к секундам выданного видео.
    Сбой замера не должен ронять сборку — она уже оплачена, просто не учтётся.
    """
    from reels_factory.render import media_dur
    try:
        return float(media_dur(path))
    except Exception:
        return 0.0
```

В коде пункта 3 она уже вызывается — определить её нужно **выше** по файлу, чтобы
на момент вызова функция существовала.

- [ ] **Step 4: Запустить тесты**

Run: `.venv\Scripts\python.exe -m pytest tests/test_pipeline.py -q`
Expected: PASS

- [ ] **Step 5: Коммит**

```bash
git add plugins/reels-factory/engine/src/reels_factory/pipeline.py plugins/reels-factory/engine/tests/test_pipeline.py
git commit -m "feat(pipeline): meter heygen seconds and elevenlabs characters"
```

---

### Task 6: Сборщик трат — связать конвейер с журналом

**Files:**
- Modify: `plugins/reels-factory/engine/src/reels_factory/billing.py` (добавить класс)
- Modify: `plugins/reels-factory/engine/src/reels_factory/__main__.py:59-88` (`_cmd_make` — создание meter, Step 5)
- Test: `plugins/reels-factory/engine/tests/test_billing.py` (дописать)

**Interfaces:**
- Consumes: `LedgerStore`, функции стоимости из Task 1-2
- Produces: `JobMeter(store, *, chat_id, job_id, rates, markup)` с методами `heygen(seconds, *, cached=False, twin=False)`, `elevenlabs(chars)`, `claude(usd)`, `total_charged() -> int`; `__main__._build_meter(wd) -> JobMeter | None`

- [ ] **Step 1: Написать падающий тест**

Дописать в `tests/test_billing.py`:

```python
from reels_factory.billing import JobMeter


def test_meter_списывает_с_наценкой(store):
    store.credit(777, 20_000_000, purchase_id="p1", amount_minor=2000, currency="usd")
    meter = JobMeter(store, chat_id=777, job_id="job1", rates=RATES, markup=2.0)
    meter.heygen(30.0)
    # $1.50 себестоимость -> $3.00 списано
    assert store.balance(777) == 17_000_000
    assert meter.total_charged() == 3_000_000


def test_meter_не_тарифицирует_кэш(store):
    meter = JobMeter(store, chat_id=777, job_id="job1", rates=RATES, markup=2.0)
    meter.heygen(30.0, cached=True)
    assert store.balance(777) == 0
    assert meter.total_charged() == 0


def test_meter_нумерует_шаги_и_не_схлопывает_одинаковые(store):
    meter = JobMeter(store, chat_id=777, job_id="job1", rates=RATES, markup=2.0)
    meter.heygen(30.0)
    meter.heygen(30.0)
    assert meter.total_charged() == 6_000_000


def test_meter_считает_все_три_провайдера(store):
    meter = JobMeter(store, chat_id=777, job_id="job1", rates=RATES, markup=2.0)
    meter.heygen(30.0)
    meter.elevenlabs(1000)
    meter.claude(0.02)
    assert store.job_breakdown("job1") == {
        "heygen": 3_000_000,
        "elevenlabs": 200_000,
        "claude": 40_000,
    }
```

- [ ] **Step 2: Запустить тест, убедиться что падает**

Run: `.venv\Scripts\python.exe -m pytest tests/test_billing.py -q -k meter`
Expected: FAIL — `ImportError: cannot import name 'JobMeter'`

- [ ] **Step 3: Реализация**

Дописать в конец `src/reels_factory/billing.py`:

```python
class JobMeter:
    """Учёт трат одной сборки: считает стоимость и сразу списывает.

    Списание идёт по факту каждого платного шага, а не одной суммой в конце:
    если конвейер упадёт посередине, деньги у провайдера уже потрачены и это
    должно остаться в журнале. Возврат за упавшую сборку делает refund_job.
    """

    def __init__(self, store: LedgerStore, *, chat_id: int, job_id: str,
                 rates: dict, markup: float):
        self.store = store
        self.chat_id = int(chat_id)
        self.job_id = job_id
        self.rates = rates
        self.markup = float(markup)
        self._step = 0
        self._charged = 0

    def _record(self, provider: str, unit: str, quantity: float,
                unit_price_micro: int, cost_micro: int) -> None:
        charged = apply_markup(cost_micro, self.markup)
        entry_id = f"{self.job_id}:{provider}:{self._step}"
        self._step += 1
        if self.store.charge(
            self.chat_id, entry_id=entry_id, job_id=self.job_id,
            provider=provider, unit=unit, quantity=quantity,
            unit_price_micro=unit_price_micro, cost_micro=cost_micro,
            charged_micro=charged,
        ):
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
```

- [ ] **Step 4: Запустить тесты**

Run: `.venv\Scripts\python.exe -m pytest tests/test_billing.py -q`
Expected: PASS, 21 passed

- [ ] **Step 5: Создать meter ВНУТРИ процесса сборки**

**Важно, иначе всё развалится:** бот не вызывает `run_make` напрямую. Он
запускает отдельный процесс — `run_build` (bot.py:574) делает
`subprocess.run([sys.executable, "-m", "reels_factory", "make", ...])`. Поэтому
передать объект учёта из бота физически нельзя: это разные процессы. Meter
создаётся там, где реально зовётся конвейер — в `_cmd_make`.

Общая база при этом не проблема: `LedgerStore` работает в режиме WAL с
`busy_timeout`, а `entry_id` защищает от двойной записи. SQLite для того и нужен.

В `src/reels_factory/__main__.py`, функция `_cmd_make` (строка 59), заменить
строку 84:

```python
    result = run_make(cfg, args.broll, offset, wd, broll_plan=broll_plan)
```

на:

```python
    result = run_make(cfg, args.broll, offset, wd, broll_plan=broll_plan,
                      meter=_build_meter(wd))
```

и добавить рядом с `_cmd_make`:

```python
def _build_meter(wd):
    """Учёт трат для этой сборки — или None, если считать не для кого.

    chat_id и job_id лежат в job.input.json, который бот кладёт в workdir перед
    постановкой в очередь (bot.py:enqueue_build). Ручной прогон движка из
    консоли этого файла не имеет — там учёта нет, и это правильно: платит
    разработчик, а не пользователь.
    """
    from reels_factory.billing import JobMeter, LedgerStore
    from reels_factory.config import load_billing_config
    # WORK_ROOT уже импортирован в __main__.py на уровне модуля (строка 11).

    billing = load_billing_config()
    if not billing["enabled"]:
        return None
    try:
        doc = json.loads((Path(wd) / "job.input.json").read_text(encoding="utf-8"))
        chat_id = int(doc["user_id"])
        job_id = str(doc["job_id"])
    except (OSError, KeyError, ValueError, json.JSONDecodeError):
        return None
    return JobMeter(
        LedgerStore(WORK_ROOT / "billing.sqlite3"),
        chat_id=chat_id, job_id=job_id,
        rates=billing["rates"], markup=billing["markup"],
    )
```

`json` и `Path` в `__main__.py` уже импортированы.

- [ ] **Step 6: Проверить, что ручной прогон без job.input.json не падает**

Run: `.venv\Scripts\python.exe -c "from reels_factory.__main__ import _build_meter; print(_build_meter('.'))"`
Expected: `None` — без файла задания учёт молча выключается.

- [ ] **Step 7: Коммит**

```bash
git add plugins/reels-factory/engine/src/reels_factory/billing.py plugins/reels-factory/engine/src/reels_factory/__main__.py plugins/reels-factory/engine/tests/test_billing.py
git commit -m "feat(billing): add per-job meter and wire it into the make command"
```

---

### Task 7: Оценка до рендера и блокировка

**Files:**
- Modify: `plugins/reels-factory/engine/src/reels_factory/bot.py` — `:249-262` (кэш стора), `:352-372` (списание Клода в трёх `step_*`), `:489-570` (`enqueue_build` — оценка и блокировка), `:1046-1145` (`_process_job` — чек после выдачи)
- Test: `plugins/reels-factory/engine/tests/test_bot.py`

**Interfaces:**
- Consumes: `LedgerStore`, `estimate_micro`, `apply_markup`, `claude_cost_micro`, `load_billing_config`, `ClaudeSkillRunner.total_cost_usd` из Task 3 (без `JobMeter` — он живёт в процессе сборки)
- Produces: `bot._ledger() -> LedgerStore`, `bot._billing() -> dict`, `bot.format_usd(micro: int) -> str`, `bot._charge_claude(chat_id, runner) -> None`, `bot.InsufficientBalance`

- [ ] **Step 1: Написать падающий тест**

Дописать в `tests/test_bot.py`:

```python
def test_форматирование_баланса():
    from reels_factory.bot import format_usd
    assert format_usd(3_184_000) == "$3.18"
    assert format_usd(0) == "$0.00"
    assert format_usd(-100_000) == "-$0.10"


def test_ledger_переиспользуется_между_вызовами(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import importlib
    from reels_factory import bot as bot_mod
    importlib.reload(bot_mod)
    assert bot_mod._ledger() is bot_mod._ledger()


def test_нехватки_баланса_достаточно_чтобы_не_создавать_job(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import importlib
    from reels_factory import bot as bot_mod
    importlib.reload(bot_mod)
    cfg = bot_mod._billing()
    from reels_factory.billing import estimate_micro
    need = estimate_micro(500, cfg["rates"], cfg["markup"])
    assert bot_mod._ledger().balance(777) < need
```

- [ ] **Step 2: Запустить тест, убедиться что падает**

Run: `.venv\Scripts\python.exe -m pytest tests/test_bot.py -q -k "баланс or ledger"`
Expected: FAIL — `cannot import name 'format_usd'`

- [ ] **Step 3: Реализация**

В `src/reels_factory/bot.py` рядом с `_job_store()` (строка ~256) добавить:

```python
_ledger_cache: tuple[Path, LedgerStore] | None = None


def _ledger() -> LedgerStore:
    """Журнал трат и балансов. Кэшируем как _job_store: путь зависит от cwd."""
    global _ledger_cache
    db_path = (WORK_ROOT / "billing.sqlite3").resolve()
    if _ledger_cache is None or _ledger_cache[0] != db_path:
        _ledger_cache = (db_path, LedgerStore(db_path))
    return _ledger_cache[1]


def _billing() -> dict:
    return load_billing_config()


def format_usd(micro: int) -> str:
    """Микродоллары -> строка для пользователя."""
    sign = "-" if micro < 0 else ""
    return f"{sign}${abs(micro) / 1_000_000:.2f}"
```

Импорты в `bot.py`. Строку 30 расширить, строку с `billing` добавить рядом:

```python
import uuid                      # нового импорта в bot.py нет, добавить

from reels_factory.billing import (
    LedgerStore, apply_markup, claude_cost_micro, estimate_micro,
)
from reels_factory.config import (
    OUT_H, OUT_W, WORK_ROOT, load_billing_config, load_config,
)
```

`JobMeter` в `bot.py` не нужен — он используется только в `__main__.py`.

`os`, `json` и `Path` уже импортированы в `bot.py` — повторно не добавлять.

В функции `enqueue_build(chat_id, scenario: dict, *, language=None, voice_id=None)`
(строка ~489) — **в самом начале, до `workdir.mkdir`**, чтобы при нехватке баланса
не создавалась пустая папка сборки:

```python
    billing = _billing()
    if billing["enabled"]:
        # Оценка ДО первого платного шага: после него деньги уже не вернуть.
        # Символы берём из тех же блоков, что уйдут в синтез речи
        # (pipeline.run_make озвучивает scenario["blocks"][i]["speech"]).
        chars = sum(
            len(b.get("speech") or "") for b in (scenario.get("blocks") or [])
        )
        need = estimate_micro(chars, billing["rates"], billing["markup"])
        have = _ledger().balance(chat_id)
        if have < need:
            raise InsufficientBalance(need=need, have=have)
```

Рядом с другими исключениями модуля добавить:

```python
class InsufficientBalance(Exception):
    """Баланса не хватает на оценку сборки — платный рендер не начинаем."""

    def __init__(self, *, need: int, have: int):
        super().__init__(f"нужно {need}, есть {have}")
        self.need = need
        self.have = have
```

**Списание Клода.** Скиллы зовутся при подготовке сценария — то есть в процессе
бота и ДО того, как появится сборка, поэтому `JobMeter` тут не применим и
`job_id` ещё не существует. Пишем в журнал напрямую, с `job_id=None`.

Добавить рядом с `_ledger()`:

```python
def _charge_claude(chat_id: int, runner: ClaudeSkillRunner) -> None:
    """Списать стоимость вызовов Клода за подготовку сценария.

    Списываем сумму по runner, а не последний вызов: за один проход скиллов
    отрабатывают генерация, хуманизатор и судья.

    job_id=None — сборки ещё нет и может не быть вовсе (человек передумает).
    Деньги при этом уже потрачены, поэтому запись всё равно нужна.
    entry_id случайный: каждое нажатие — новая генерация, склеивать нечего.
    """
    billing = _billing()
    if not billing["enabled"] or not runner.total_cost_usd:
        return
    cost = claude_cost_micro(runner.total_cost_usd)
    _ledger().charge(
        chat_id,
        entry_id=f"claude:{uuid.uuid4().hex}",
        job_id=None,
        provider="claude",
        unit="usd",
        quantity=runner.total_cost_usd,
        unit_price_micro=0,
        cost_micro=cost,
        charged_micro=apply_markup(cost, billing["markup"]),
    )
```

Во всех трёх функциях, которые зовут скиллы (`step_verbatim` — строка ~353,
`step_ideas` — ~359, `step_scenario` — ~368), вынести runner в переменную и
списать после вызова. Пример для первой, остальные две — по образцу:

```python
def step_verbatim(chat_id: int, text: str, language: str) -> dict:
    runner = ClaudeSkillRunner()
    res = run_verbatim_path(session_dir(chat_id), text, runner,
                            language=normalize_profile_language(language))
    _charge_claude(chat_id, runner)
    return res["scenario"]
```

Добавить `import uuid` к импортам `bot.py` (его там нет), а к импорту из
`billing` — `apply_markup` и `claude_cost_micro`.

Побочный эффект, принятый осознанно: пользователь с нулевым балансом успеет
потратить на Клода до того, как упрётся в блокировку рендера. Это копейки, а
переносить блокировку на генерацию сценария означало бы не дать человеку даже
посмотреть, что мы умеем.

Перехват — **в обёртке `_enqueue_build` (строка ~999), не в обработчике кнопки**.
Там уже стоит `except Exception`, который иначе проглотит наше исключение и
покажет человеку сырой текст вместо кнопок пополнения. Новая ветка обязана идти
**выше** общей.

Было:

```python
    try:
        job = enqueue_build(
            chat_id,
            s["scenario"],
            language=_reel_language(s),
            voice_id=s.get("voice_id"),
        )
    except Exception as e:
        await msg.reply_text(f"Не удалось поставить ролик в очередь: {str(e)[:200]}")
        return None
```

стало:

```python
    try:
        job = enqueue_build(
            chat_id,
            s["scenario"],
            language=_reel_language(s),
            voice_id=s.get("voice_id"),
        )
    except InsufficientBalance as exc:
        # Раньше общего except: иначе нехватка баланса покажется как
        # техническая ошибка, без кнопок пополнения.
        await _show_topup(msg, chat_id, need=exc.need, have=exc.have)
        return None
    except Exception as e:
        await msg.reply_text(f"Не удалось поставить ролик в очередь: {str(e)[:200]}")
        return None
```

Шаг сессии при этом **не меняется** — человек остаётся на экране готовности и
после пополнения жмёт «Создать ролик» снова.

**`JobMeter` в `bot.py` НЕ создаётся** — сборка идёт отдельным процессом, meter
живёт там (Task 6, Step 5). Бот только читает журнал: база одна и та же
(`work/billing.sqlite3`), процессы разные.

В `_process_job`, после успешной выдачи ролика — рядом со
`store.finish(job.job_id, "completed", ...)` (строка ~1145) — показать чек:

```python
    breakdown = _ledger().job_breakdown(job.job_id)
    if breakdown:
        parts = ", ".join(
            f"{name} {format_usd(value)}" for name, value in sorted(breakdown.items())
        )
        total = sum(breakdown.values())
        await context.bot.send_message(
            job.chat_id,
            f"Списано {format_usd(total)} ({parts}).\n"
            f"Остаток баланса: {format_usd(_ledger().balance(job.chat_id))}",
        )
```

- [ ] **Step 4: Запустить тесты**

Run: `.venv\Scripts\python.exe -m pytest tests/test_bot.py -q`
Expected: PASS

- [ ] **Step 5: Прогнать весь набор**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: PASS

- [ ] **Step 6: Коммит**

```bash
git add plugins/reels-factory/engine/src/reels_factory/bot.py plugins/reels-factory/engine/tests/test_bot.py
git commit -m "feat(bot): estimate cost before paid render and block on empty balance"
```

---

### Task 8: Вебхук Tribute — подпись, разбор, зачисление

**Files:**
- Create: `plugins/reels-factory/engine/src/reels_factory/tribute.py`
- Test: `plugins/reels-factory/engine/tests/test_tribute.py`

**Interfaces:**
- Consumes: `LedgerStore.credit`, `to_micro` из Task 1
- Produces: `verify_signature(raw: bytes, signature: str, api_key: str) -> bool`, `credited_micro(amount_minor: int, currency: str, fx: dict) -> int`, `handle_webhook(store, raw: bytes, signature: str, *, api_key: str, fx: dict) -> dict`

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_tribute.py`:

```python
import hashlib
import hmac
import json

import pytest

from reels_factory.billing import LedgerStore
from reels_factory.tribute import credited_micro, handle_webhook, verify_signature

KEY = "test-api-key"


def sign(raw: bytes) -> str:
    return hmac.new(KEY.encode(), raw, hashlib.sha256).hexdigest()


@pytest.fixture
def store(tmp_path):
    return LedgerStore(tmp_path / "billing.sqlite3")


FX = {"usd": 1.0, "eur": 1.08, "rub": 0.011}


def body(**over) -> bytes:
    payload = {
        "product_id": 456, "amount": 1000, "currency": "usd",
        "telegram_user_id": 777, "purchase_id": "pur_1",
        "transaction_id": "tx_1",
    }
    payload.update(over)
    return json.dumps(
        {"name": "new_digital_product", "created_at": "2026-07-27T00:00:00Z",
         "payload": payload}
    ).encode()


def test_подпись_верная(store):
    raw = body()
    assert verify_signature(raw, sign(raw), KEY) is True


def test_подпись_чужим_ключом_не_проходит(store):
    raw = body()
    assert verify_signature(raw, sign(raw), "другой-ключ") is False


def test_подпись_подменённого_тела_не_проходит():
    raw = body()
    assert verify_signature(body(amount=999999), sign(raw), KEY) is False


def test_доллары_зачисляются_один_к_одному():
    # 1000 минимальных единиц = $10.00
    assert credited_micro(1000, "usd", FX) == 10_000_000


def test_рубли_конвертируются_по_курсу():
    # 100000 копеек = 1000 ₽ -> $11.00 при курсе 0.011
    assert credited_micro(100_000, "rub", FX) == 11_000_000


def test_вебхук_зачисляет_на_баланс(store):
    raw = body()
    res = handle_webhook(store, raw, sign(raw), api_key=KEY, fx=FX)
    assert res["credited"] is True
    assert store.balance(777) == 10_000_000


def test_повторная_доставка_не_зачисляет_дважды(store):
    raw = body()
    handle_webhook(store, raw, sign(raw), api_key=KEY, fx=FX)
    res = handle_webhook(store, raw, sign(raw), api_key=KEY, fx=FX)
    assert res["credited"] is False
    assert store.balance(777) == 10_000_000


def test_плохая_подпись_отвергается_до_зачисления(store):
    raw = body()
    with pytest.raises(PermissionError):
        handle_webhook(store, raw, "deadbeef", api_key=KEY, fx=FX)
    assert store.balance(777) == 0


def test_событие_без_telegram_id_не_зачисляется(store):
    # Оплата через веб без входа по Telegram: зачислять некому.
    raw = body(telegram_user_id=None)
    res = handle_webhook(store, raw, sign(raw), api_key=KEY, fx=FX)
    assert res["credited"] is False
    assert res["reason"] == "no_telegram_user_id"


def test_чужое_событие_игнорируется(store):
    raw = json.dumps({"name": "new_subscription", "payload": {}}).encode()
    res = handle_webhook(store, raw, sign(raw), api_key=KEY, fx=FX)
    assert res["credited"] is False
    assert res["reason"] == "ignored_event"
```

- [ ] **Step 2: Запустить тест, убедиться что падает**

Run: `.venv\Scripts\python.exe -m pytest tests/test_tribute.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'reels_factory.tribute'`

- [ ] **Step 3: Реализация**

Создать `src/reels_factory/tribute.py`:

```python
"""Приём вебхуков Tribute: пополнение баланса пользователя.

Tribute шлёт new_digital_product на каждую покупку инфопродукта и ретраит
доставку около суток, поэтому обработчик обязан быть идемпотентным — ключ
идемпотентности purchase_id.

Сумма берётся из полей события (amount в минимальных единицах + currency), а не
из таблицы соответствия товаров: так новые номиналы заработают без правки кода.
"""
from __future__ import annotations

import hashlib
import hmac
import json

from reels_factory.billing import LedgerStore, to_micro

TOPUP_EVENT = "new_digital_product"


def verify_signature(raw: bytes, signature: str, api_key: str) -> bool:
    """HMAC-SHA256 тела запроса ключом API, заголовок trbt-signature.

    Сравнение постоянного времени: обычное == утекает побайтово.
    """
    expected = hmac.new(api_key.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, (signature or "").strip().lower())


def credited_micro(amount_minor: int, currency: str, fx: dict) -> int:
    """Сумма события -> микродоллары.

    amount приходит в минимальных единицах (центы, копейки), поэтому делим
    на 100 и умножаем на курс к доллару.
    """
    rate = float(fx.get((currency or "usd").lower(), 1.0))
    return to_micro(int(amount_minor) / 100.0 * rate)


def handle_webhook(store: LedgerStore, raw: bytes, signature: str, *,
                   api_key: str, fx: dict) -> dict:
    """Проверить подпись, разобрать событие, зачислить пополнение.

    PermissionError — единственный случай, когда отвечать не-2xx: всё
    остальное Tribute будет ретраить сутки без всякой пользы.
    """
    if not verify_signature(raw, signature, api_key):
        raise PermissionError("bad signature")
    event = json.loads(raw.decode("utf-8"))
    if event.get("name") != TOPUP_EVENT:
        return {"credited": False, "reason": "ignored_event"}
    payload = event.get("payload") or {}
    chat_id = payload.get("telegram_user_id")
    if not chat_id:
        # Покупка через веб без входа по Telegram — не знаем, кому зачислять.
        return {"credited": False, "reason": "no_telegram_user_id"}
    purchase_id = str(payload.get("purchase_id") or payload.get("transaction_id") or "")
    if not purchase_id:
        return {"credited": False, "reason": "no_purchase_id"}
    micro = credited_micro(payload.get("amount") or 0, payload.get("currency") or "usd", fx)
    credited = store.credit(
        int(chat_id), micro, purchase_id=purchase_id,
        amount_minor=int(payload.get("amount") or 0),
        currency=str(payload.get("currency") or "usd"), raw=event,
    )
    return {
        "credited": credited,
        "reason": "ok" if credited else "duplicate",
        "chat_id": int(chat_id),
        "micro": micro,
    }
```

- [ ] **Step 4: Запустить тесты**

Run: `.venv\Scripts\python.exe -m pytest tests/test_tribute.py -q`
Expected: PASS, 10 passed

- [ ] **Step 5: Коммит**

```bash
git add plugins/reels-factory/engine/src/reels_factory/tribute.py plugins/reels-factory/engine/tests/test_tribute.py
git commit -m "feat(tribute): verify webhook signature and credit balance idempotently"
```

---

### Task 9: HTTP-слушатель вебхука и Caddy

**Files:**
- Modify: `plugins/reels-factory/engine/src/reels_factory/tribute.py` (дописать сервер)
- Modify: `plugins/reels-factory/engine/src/reels_factory/bot.py` (запуск при старте)
- Test: `plugins/reels-factory/engine/tests/test_tribute.py` (дописать)

**Interfaces:**
- Consumes: `handle_webhook` из Task 8
- Produces: `start_webhook_server(store, *, api_key, fx, port, on_credit=None) -> ThreadingHTTPServer`

- [ ] **Step 1: Написать падающий тест**

Дописать в `tests/test_tribute.py`:

```python
import urllib.error
import urllib.request


def test_сервер_принимает_подписанный_вебхук(store):
    from reels_factory.tribute import start_webhook_server

    got = []
    srv = start_webhook_server(
        store, api_key=KEY, fx=FX, port=0, on_credit=lambda ev: got.append(ev)
    )
    try:
        port = srv.server_address[1]
        raw = body()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/tribute",
            data=raw, method="POST",
            headers={"trbt-signature": sign(raw), "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200
        assert store.balance(777) == 10_000_000
        assert got and got[0]["chat_id"] == 777
    finally:
        srv.shutdown()


def test_сервер_отвергает_плохую_подпись(store):
    from reels_factory.tribute import start_webhook_server

    srv = start_webhook_server(store, api_key=KEY, fx=FX, port=0)
    try:
        port = srv.server_address[1]
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/tribute",
            data=body(), method="POST",
            headers={"trbt-signature": "deadbeef"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=5)
        assert exc.value.code == 401
        assert store.balance(777) == 0
    finally:
        srv.shutdown()
```

- [ ] **Step 2: Запустить тест, убедиться что падает**

Run: `.venv\Scripts\python.exe -m pytest tests/test_tribute.py -q -k сервер`
Expected: FAIL — `cannot import name 'start_webhook_server'`

- [ ] **Step 3: Реализация**

В `src/reels_factory/tribute.py` **импорты добавить в шапку файла**, к
существующим (не в конец — там они будут посреди кода):

```python
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
```

Остальное дописать в конец файла:

```python
WEBHOOK_PATH = "/tribute"
MAX_BODY_BYTES = 1_000_000


def start_webhook_server(store: LedgerStore, *, api_key: str, fx: dict,
                         port: int, on_credit=None) -> ThreadingHTTPServer:
    """Поднять слушатель вебхука в демон-потоке.

    ThreadingHTTPServer из стандартной библиотеки, а не веб-фреймворк: новых
    зависимостей ради одного эндпоинта не вводим, а SQLite потокобезопасен при
    connection-per-call. Снаружи HTTPS терминирует Caddy.
    """

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 — имя задано базовым классом
            if self.path.rstrip("/") != WEBHOOK_PATH:
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY_BYTES:
                self.send_error(400)
                return
            raw = self.rfile.read(length)
            signature = self.headers.get("trbt-signature", "")
            try:
                result = handle_webhook(
                    store, raw, signature, api_key=api_key, fx=fx
                )
            except PermissionError:
                self.send_error(401)
                return
            except Exception:
                # Отдаём 500 намеренно: Tribute повторит доставку, а событие
                # идемпотентно — дубль не зачислится.
                self.send_error(500)
                return
            if result.get("credited"):
                if on_credit is not None:
                    try:
                        on_credit(result)
                    except Exception:
                        pass
            else:
                # Незачисленный платёж должен быть заметен: дубль ретрая —
                # норма, а вот no_telegram_user_id означает застрявшие деньги.
                print(f"[tribute] не зачислено: {result.get('reason')}", flush=True)
            payload = json.dumps({"status": "ok"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):  # тишина в stdout бота
            return

    server = ThreadingHTTPServer(("127.0.0.1", int(port)), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
```

В `src/reels_factory/bot.py`, в функции `_post_init(app)` (строка ~1313) — рядом с
`mark_running_interrupted`, до создания worker-задачи — добавить:

```python
    tribute_key = os.environ.get("TRIBUTE_API_KEY")
    if tribute_key:
        billing = _billing()
        start_webhook_server(
            _ledger(), api_key=tribute_key, fx=billing["fx"],
            port=int(os.environ.get("TRIBUTE_WEBHOOK_PORT", "8099")),
            on_credit=lambda ev: None,
        )
```

с импортом `from reels_factory.tribute import start_webhook_server`.

- [ ] **Step 4: Запустить тесты**

Run: `.venv\Scripts\python.exe -m pytest tests/test_tribute.py -q`
Expected: PASS, 12 passed

- [ ] **Step 5: Настроить Caddy на сервере**

Дописать в `/etc/caddy/Caddyfile` на `134.209.80.75`:

```
# Tribute — вебхук пополнения баланса. Имя резолвится через sslip.io,
# домен и A-запись не нужны; сертификат Caddy выпускает сам.
tribute.134.209.80.75.sslip.io {
    reverse_proxy localhost:8099
}
```

Применить и проверить:

```bash
ssh root@134.209.80.75 'caddy validate --config /etc/caddy/Caddyfile && systemctl reload caddy'
```

Expected: `Valid configuration`, reload без ошибок.

- [ ] **Step 6: Коммит**

```bash
git add plugins/reels-factory/engine/src/reels_factory/tribute.py plugins/reels-factory/engine/src/reels_factory/bot.py plugins/reels-factory/engine/tests/test_tribute.py
git commit -m "feat(tribute): serve webhook endpoint and wire it into the bot"
```

---

### Task 10: Экраны баланса и пополнения в боте

**Files:**
- Modify: `plugins/reels-factory/engine/src/reels_factory/bot.py`
- Test: `plugins/reels-factory/engine/tests/test_bot.py`

**Interfaces:**
- Consumes: `format_usd`, `_ledger` из Task 7
- Produces: `TOPUP_PRODUCTS: tuple[tuple[str, str], ...]`, `topup_keyboard()` (возвращает `InlineKeyboardMarkup`, аннотации нет — класс импортируется локально), `topup_text(need: int | None, have: int) -> str`, `_show_topup(msg, chat_id, *, need=None, have=None)`, `cmd_balance(update, context)`

> **Порядок задач:** `_show_topup` используется в Task 7 (`_enqueue_build`), а
> определяется здесь. Если Task 10 делается позже — на время Task 7 достаточно
> заглушки `async def _show_topup(msg, chat_id, **kw): await msg.reply_text("Баланса не хватает")`,
> которую эта задача заменяет настоящей. Тесты Task 7 её не проверяют.

- [ ] **Step 1: Написать падающий тест**

Дописать в `tests/test_bot.py`:

```python
def test_кнопки_пополнения_ведут_на_tribute():
    from reels_factory.bot import TOPUP_PRODUCTS, topup_keyboard
    assert len(TOPUP_PRODUCTS) == 7
    for label, url in TOPUP_PRODUCTS:
        # Только внутрителеграмная ссылка: с веб-страницы может прийти оплата
        # без telegram_user_id, и зачислить её будет некому.
        assert url.startswith("https://t.me/tribute/app?startapp=")
        assert "web.tribute.tg" not in url
        assert label
    rows = topup_keyboard().inline_keyboard
    urls = [btn.url for row in rows for btn in row if btn.url]
    assert len(urls) == 7


def test_текст_пополнения_при_нехватке_показывает_обе_суммы():
    from reels_factory.bot import topup_text
    text = topup_text(need=3_184_000, have=1_000_000)
    assert "$3.18" in text
    assert "$1.00" in text


def test_текст_пополнения_без_нехватки_показывает_только_баланс():
    from reels_factory.bot import topup_text
    text = topup_text(need=None, have=1_000_000)
    assert "$1.00" in text
    assert "не хватает" not in text.lower()
```

- [ ] **Step 2: Запустить тест, убедиться что падает**

Run: `.venv\Scripts\python.exe -m pytest tests/test_bot.py -q -k пополнени`
Expected: FAIL — `cannot import name 'TOPUP_PRODUCTS'`

- [ ] **Step 3: Реализация**

В `src/reels_factory/bot.py` рядом с другими константами клавиатур добавить:

```python
# Ссылки на инфопродукты Tribute. Товары создаются вручную в дашборде —
# API для их создания у Tribute нет, поэтому список статичный.
#
# Берём поле link (оплата ОТКРЫВАЕТСЯ ВНУТРИ ТЕЛЕГРАМА), а не webLink
# (страница в браузере). Разница принципиальная: в браузере покупатель может
# войти по почте, тогда в вебхуке не будет telegram_user_id и зачислять будет
# некому. Внутри Телеграма пользователь опознан всегда.
# Актуальные значения обоих полей: GET /api/v1/products с ключом Tribute.
TOPUP_PRODUCTS = (
    ("$1 (тест)", "https://t.me/tribute/app?startapp=pAHq"),
    ("$10", "https://t.me/tribute/app?startapp=pAH1"),
    ("$25", "https://t.me/tribute/app?startapp=pAHh"),
    ("$50", "https://t.me/tribute/app?startapp=pAHj"),
    ("1000 ₽", "https://t.me/tribute/app?startapp=pAHm"),
    ("2500 ₽", "https://t.me/tribute/app?startapp=pAHn"),
    ("5000 ₽", "https://t.me/tribute/app?startapp=pAHo"),
)


def topup_keyboard():
    # Импорт локальный и аннотации возврата нет — в bot.py telegram-классы
    # везде импортируются внутри функций (строки 618, 626, 635), на уровне
    # модуля этих имён не существует.
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    rows = [
        [InlineKeyboardButton(label, url=url)]
        for label, url in TOPUP_PRODUCTS
    ]
    return InlineKeyboardMarkup(rows)


def topup_text(need: int | None, have: int) -> str:
    """Экран пополнения. need=None — пользователь открыл его сам, а не упёрся."""
    lines = [f"Баланс: {format_usd(have)}"]
    if need is not None:
        lines.append(
            f"На этот ролик не хватает — нужно примерно {format_usd(need)}."
        )
    lines.append("")
    lines.append("Пополнить — кнопкой ниже. Баланс обновится сам после оплаты.")
    return "\n".join(lines)


async def _show_topup(msg, chat_id: int, *, need: int | None = None,
                      have: int | None = None) -> None:
    """Экран пополнения. Принимает telegram-сообщение, а не update/context:
    зовётся и из обработчика команды, и из _enqueue_build, где есть только msg."""
    balance = _ledger().balance(chat_id) if have is None else have
    await msg.reply_text(
        topup_text(need, balance), reply_markup=topup_keyboard()
    )
```

Зарегистрировать команду `/balance`:

```python
async def cmd_balance(update, context) -> None:
    await _show_topup(update.message, update.effective_chat.id)
```

Зарегистрировать рядом с существующими (строка ~1362, переменная называется `app`,
не `application`):

```python
    app.add_handler(CommandHandler("balance", cmd_balance))
```

И добавить в меню бота, в список `set_my_commands` (строка ~1317):

```python
            BotCommand("balance", "Баланс и пополнение"),
```

- [ ] **Step 4: Запустить тесты**

Run: `.venv\Scripts\python.exe -m pytest tests/test_bot.py -q`
Expected: PASS

- [ ] **Step 5: Прогнать весь набор**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: PASS — все тесты, включая 301 существующий

- [ ] **Step 6: Коммит**

```bash
git add plugins/reels-factory/engine/src/reels_factory/bot.py plugins/reels-factory/engine/tests/test_bot.py
git commit -m "feat(bot): add balance screen and Tribute top-up buttons"
```

---

### Task 11: Развернуть на сервере

Все предыдущие задачи меняют код локально. Бот живёт на `134.209.80.75` и о них
не знает — эта задача доводит изменения до работающей службы.

**Files:**
- Ничего в репозитории; действия на сервере `root@134.209.80.75`

**Interfaces:**
- Consumes: весь код Task 1–10, влитый в `main`
- Produces: работающая служба `reels-bot` с биллингом и живой слушатель вебхука

**Что уже известно про сервер (проверено 2026-07-27, заново не выяснять):**
- Репозиторий: `/root/reels-factory`, ветка `main`, remote `https://github.com/Vasya1996/reels-factory.git`
- Движок поставлен **editable**, поэтому `git pull` достаточно — переустановка не нужна
- Новых зависимостей план не вводит (`sqlite3`, `hmac`, `http.server` — стандартная библиотека)
- Служба: `reels-bot`, `WorkingDirectory=/root/reels-workspace`, `EnvironmentFile=/root/.reels-factory/bot.env`
- `TRIBUTE_API_KEY` в `bot.env` уже лежит
- Caddy-блок для `tribute.134.209.80.75.sslip.io` добавлен в Task 9

- [ ] **Step 1: Влить ветку в main через PR**

Показать Васе дифф простыми словами, дождаться «ок», затем:

```bash
git push -u origin feat/vasya-billing
gh pr create --title "feat: billing and Tribute top-up" --body "Учёт трат по провайдерам, баланс на пользователя, пополнение через Tribute."
```

После одобрения — слить PR в `main`.

- [ ] **Step 2: Обновить код на сервере**

```bash
ssh root@134.209.80.75 'cd /root/reels-factory && git pull --ff-only && git log --oneline -1'
```

Expected: последний коммит совпадает с влитым в `main`.

- [ ] **Step 3: Убедиться, что тесты зелёные на сервере**

```bash
ssh root@134.209.80.75 'cd /root/reels-factory/plugins/reels-factory/engine && .venv/bin/python -m pytest -q 2>&1 | tail -5'
```

Expected: все тесты проходят. Если падает — не перезапускать службу, разбираться.

- [ ] **Step 4: Перезапустить бота**

```bash
ssh root@134.209.80.75 'systemctl restart reels-bot && sleep 3 && systemctl is-active reels-bot'
```

Expected: `active`

- [ ] **Step 5: Проверить, что слушатель вебхука поднялся**

```bash
ssh root@134.209.80.75 'ss -tlnp | grep 8099; curl -s -o /dev/null -w "%{http_code}\n" -X POST -H "trbt-signature: bad" -d "{}" http://127.0.0.1:8099/tribute'
```

Expected: порт 8099 слушает python бота; ответ `401` — сервер жив и подпись проверяет.

- [ ] **Step 6: Проверить HTTPS снаружи**

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST -H "trbt-signature: bad" -d "{}" https://tribute.134.209.80.75.sslip.io/tribute
```

Expected: `401` — Caddy выпустил сертификат и проксирует до бота. Первый запрос может
занять несколько секунд, пока выпускается сертификат.

- [ ] **Step 7: Проверить, что база биллинга создалась**

```bash
ssh root@134.209.80.75 'ls -la /root/reels-workspace/work/billing.sqlite3'
```

Expected: файл существует.

- [ ] **Step 8: Отдать Васе адрес вебхука**

Сказать Васе вставить `https://tribute.134.209.80.75.sslip.io/tribute` в приложении
Tribute (Настройки → Управление API-ключами → поле WEBHOOK URL) и нажать
«Отправить тестовый запрос». Затем проверить, что запрос дошёл:

```bash
ssh root@134.209.80.75 'journalctl -u reels-bot -n 30 --no-pager'
```

---

## Отложено — сюда не лезть в этом плане

**Возврат за упавшую сборку.** Решение Васи: сбой по вине нашего кода или
неоплаченного счёта провайдера — наши издержки, не пользователя. Но реализуется
это отдельной задачей, после того как заработает оплата.

В Task 1 остаются готовыми и покрытыми тестами `LedgerStore.refund_job` и
колонка `refunded_at` — метод просто **никто не вызывает**. Оставлены намеренно:
колонка входит в схему и в фильтр `job_breakdown`, добавлять её потом — это
миграция живой базы с балансами. Метод без вызова стоит двадцать строк, миграция
стоит дороже.

**Учёт ветки `avatar islands`.** Второй путь рендера аватара
(`master_audio.enabled: true` → `_render_avatar_islands`) в этом плане не
тарифицируется — вместо догадок Task 5 ставит предохранитель, который не даёт
включить эту ветку вместе с биллингом. Чтобы её поддержать, нужно прочитать
`avatar_islands.py` и брать секунды из `rendered.manifest`. Отдельная задача.

Третье отложенное: уведомление владельцу о платеже, который не удалось зачислить.
После перехода на внутрителеграмные ссылки такой платёж почти невозможен —
`telegram_user_id` приходит всегда. Обработчик на этот случай возвращает причину
`no_telegram_user_id` и пишет строку в лог; большего пока не нужно.

## Приёмка вживую (после Task 11, вместе с Васей)

Развёртывание и тестовый запрос вебхука уже сделаны в Task 11. Здесь — только то,
что требует реальных денег и второго аккаунта.

1. **Повторная покупка.** Со второго телеграм-аккаунта купить товар «$1 (тест)»
   **дважды подряд** по кнопке в боте. Ожидаем: баланс вырос на $1, потом ещё на $1;
   в таблице `topups` две строки с разными `purchase_id`. Это и есть проверка того,
   что Tribute не блокирует повторную покупку одного товара — единственный вопрос,
   который документацией не закрывается.

   Проверка: `ssh root@134.209.80.75 'sqlite3 /root/reels-workspace/work/billing.sqlite3 "SELECT purchase_id, chat_id, credited_micro FROM topups;"'`

   Деньги за тест ($2) не вернуть: возврат через API работает только для покупок
   за звёзды, а звёзды на товарах выключены.

   **Если в логе окажется `не зачислено: no_purchase_id`** — это не мелочь, а
   блокер. Спецификация Tribute объявляет `purchase_id` и `transaction_id`
   обязательными полями вебхука, но пример в их же вики их не содержит. Без
   какого-то из них идемпотентность построить не на чем: выводить ключ из суммы,
   товара и пользователя нельзя — у нас именно повторные покупки одного товара
   на одну сумму, и они бы схлопнулись в одну. В этом случае — смотреть сырое
   тело события в `topups.raw_json` и писать в поддержку Tribute.

2. **Повторная доставка вебхука.** В приложении Tribute нажать «Отправить тестовый
   запрос» ещё раз. Ожидаем: баланс НЕ изменился — сработала защита по `purchase_id`.

3. **Сборка ролика.** Собрать короткий ролик с непустого баланса. Ожидаем: чек со
   списанием по трём провайдерам и уменьшившийся баланс.

4. **Блокировка при нехватке.** С третьего аккаунта (баланс $0) попробовать собрать
   ролик. Ожидаем: сборка не началась, показан экран пополнения с суммой нехватки,
   в `work/jobs` не появилось новой папки.
