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

    def job_provider_stats(self, job_id: str) -> dict[str, dict]:
        """Себестоимость по провайдеру для карточки сборки (задача 19) —
        не списание (`job_breakdown`/`charged_micro`, всегда 0 у JobMeter,
        см. его docstring), а настоящая себестоимость каждого шага
        (`cost_micro`) вместе с её объёмом (`quantity`: секунды HeyGen, доллары
        Клода) и числом записей. `JobMeter._record` пишет обе колонки уже
        сейчас — здесь только агрегат по тому, что уже в `spend_log`."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT provider, SUM(cost_micro) AS cost, SUM(quantity) AS qty,
                       COUNT(*) AS n
                FROM spend_log WHERE job_id = ? AND refunded_at IS NULL
                GROUP BY provider
                """,
                (job_id,),
            ).fetchall()
        return {
            row["provider"]: {
                "cost_micro": int(row["cost"] or 0),
                "quantity": float(row["qty"] or 0.0),
                "count": int(row["n"] or 0),
            }
            for row in rows
        }


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


def _model_price(model: str, prices: dict, fallback: dict) -> dict:
    """Ставка модели по её имени из ответа CLI.

    Сессия называет модель либо коротким именем (`claude-sonnet-5`), либо с
    датой сборки (`claude-haiku-4-5-20251001`). Поэтому сначала точное
    совпадение, потом самый длинный ключ-начало: короткое имя новой версии
    той же модели попадёт в свою ставку, а не в ставку по умолчанию.
    """
    name = str(model or "")
    if name in prices:
        return prices[name]
    matches = [key for key in prices if name.startswith(key)]
    if matches:
        return prices[max(matches, key=len)]
    return fallback


def claude_tokens_cost_usd(runs: list[dict], rates: dict) -> float:
    """Во сколько обошлась работа Клода по прайсу API — счёт по токенам.

    Запасной счёт: обычно стоимость называет сам CLI в `total_cost_usd`, и она
    точнее — там учтён и срок жизни кэша, и тариф на момент вызова. Эта
    функция нужна там, где CLI прислал ноль (так бывает под подпиской), потому
    что иначе работа агента выпадет из себестоимости ролика целиком.

    Токены берутся из `usage` каждого прогона: обычный вход, запись и чтение
    кэша считаются по входной ставке со своими множителями, выход — по
    выходной. Запись в кэш на час стоит дороже записи на пять минут, и
    считается отдельно: сессия агента живёт часами, у неё почти вся запись
    часовая, и по пятиминутной ставке счёт вышел бы заниженным вдвое.
    """
    prices = rates.get("claude_models_usd_per_mtok") or {}
    fallback = prices.get(rates.get("claude_default_model")) or {}
    write_mult = float(rates.get("claude_cache_write_multiplier", 1.25))
    write_1h_mult = float(rates.get("claude_cache_write_1h_multiplier", 2.0))
    read_mult = float(rates.get("claude_cache_read_multiplier", 0.1))

    total = 0.0
    for run in runs or []:
        usage = run.get("usage") or {}
        price = _model_price(run.get("model"), prices, fallback)
        if not price:
            continue
        input_rate = float(price["input"]) / 1_000_000
        output_rate = float(price["output"]) / 1_000_000
        written = usage.get("cache_creation") or {}
        hour = float(written.get("ephemeral_1h_input_tokens") or 0)
        short = float(written.get("ephemeral_5m_input_tokens") or 0)
        if not hour and not short:
            # Разбивки по сроку нет — считаем всю запись пятиминутной, то есть
            # по дешёвой ставке: занизить счёт честнее, чем выдумать час.
            short = float(usage.get("cache_creation_input_tokens") or 0)
        total += float(usage.get("input_tokens") or 0) * input_rate
        total += short * input_rate * write_mult
        total += hour * input_rate * write_1h_mult
        total += (float(usage.get("cache_read_input_tokens") or 0)
                  * input_rate * read_mult)
        total += float(usage.get("output_tokens") or 0) * output_rate
    return total


def claude_run_cost_usd(runs: list[dict], reported_usd: float,
                        rates: dict) -> float:
    """Стоимость работы агента: слово CLI, а при нуле — счёт по токенам."""
    if reported_usd and float(reported_usd) > 0:
        return float(reported_usd)
    try:
        return claude_tokens_cost_usd(runs, rates)
    except Exception as e:
        # Сборка уже оплачена у провайдеров и вот-вот уедет человеку: ошибка
        # подсчёта своей работы не повод её ронять. Но и молчать нельзя —
        # иначе себестоимость тихо занижается на всю работу агента.
        print(f"[billing] claude_run_cost_usd: не удалось посчитать: {e}",
              file=sys.stderr)
        return 0.0


def apply_markup(cost_micro: int, markup: float) -> int:
    return int(math.ceil(int(cost_micro) * float(markup) - 1e-9))


def estimate_micro(chars: int, rates: dict, markup: float, *, twin: bool = False,
                    avatar_share: float = 1.0, montage: bool = True,
                    script: bool = True) -> int:
    """Грубая оценка до первого платного шага.

    Задача оценки — не угадать цену, а не пустить в рендер с пустым балансом,
    поэтому Клод учитывается плоской добавкой, а секунды считаются из символов.

    avatar_share уменьшает только секунды HeyGen: с avatar islands аватар в
    кадре не весь ролик, остальное закрыто B-roll. ElevenLabs всё равно
    озвучивает полный текст независимо от того, виден ли аватар, поэтому
    считается от chars без поправки. По умолчанию 1.0 — прежнее поведение.

    montage=False — ролик собирается одним проходом HeyGen, агент монтажа не
    работает вовсе, и его добавка в оценку не входит. По умолчанию True: пока
    человек не выбрал путь, считаем по дорогому, иначе экран цены пообещает
    меньше, чем спишется.

    script=False — сценарий уже написан, и его подготовка списана своей строкой
    журнала (`_charge_claude` в bot.py). Складывать её в цену второй раз значит
    обещать человеку больше, чем спишется.

    Работа агента монтажа считается по числу проходов (`claude_montage_attempts`):
    проверка плана до заказа аватара даёт агенту пересдачу, а пересдача — это
    второй полный проход, план и отбор бироллов заново. Отсутствие ключа = один
    проход: старые конфиги пользователей считаются как раньше.
    """
    seconds = int(chars) / float(rates["chars_per_second"])
    avatar_seconds = seconds * float(avatar_share)
    claude = float(rates["claude_flat_usd_per_reel"]) if script else 0.0
    if montage:
        attempts = float(rates.get("claude_montage_attempts") or 1)
        claude += float(rates.get("claude_montage_usd_per_reel") or 0.0) * attempts
    cost = (
        heygen_cost_micro(avatar_seconds, rates, twin=twin)
        + elevenlabs_cost_micro(chars, rates)
        + to_micro(claude)
    )
    return apply_markup(cost, markup)


class JobMeter:
    """Учёт трат одной сборки: пишет себестоимость каждого платного шага в
    журнал, но НЕ списывает её с баланса.

    Списание — одной строкой, ровно на названную кнопкой цену (quoted_micro),
    делает enqueue_build при постановке в очередь, ДО первого платного шага.
    Списывать здесь ещё раз, по факту, значило бы посчитать дважды: кнопка
    обещала одну сумму, а провайдерский факт (особенно у HeyGen — по
    настоящей длительности рендера) почти всегда чуть другую, и баланс
    клиента плыл в минус на разницу (Артём −$1.94, Nagimash −$1.01 — решение
    Васи, пачка 2). Поэтому каждая запись здесь уходит с charged_micro=0, а
    cost_micro остаётся настоящим — источник маржи (quoted − Σ cost_micro по
    job_id), не источник списания. Тот же приём уже был у `_charge_claude`
    в bot.py для подготовки сценария.

    `rates`/`markup` остаются в конструкторе — вызывающая сторона всё равно
    собирает их вместе с job_id/chat_id, а по какой ставке считать
    себестоимость знать по-прежнему нужно (см. `heygen_cost_micro`,
    `elevenlabs_cost_micro`); markup просто больше ни на что не умножается.
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
        # avatar_islands рендерит шоты параллельно (ThreadPoolExecutor), но
        # сегодня _record зовётся из потока, что разбирает as_completed
        # (вызывающий поток), а не из рабочих потоков — гонки на self._step
        # сейчас нет. Лок — задел на случай, если метринг когда-нибудь
        # переедет в воркер: тогда несколько потоков смогут звать _record
        # одновременно, и он должен уже держать выдачу номера шага.
        self._lock = threading.Lock()

    def _record(self, provider: str, unit: str, quantity: float,
                unit_price_micro: int, cost_micro: int) -> None:
        with self._lock:
            entry_id = f"{self.job_id}:{self.run_id}:{provider}:{self._step}"
            self._step += 1
        # charged_micro=0: себестоимость идёт в журнал для видимости маржи,
        # а не списывается — деньги за путь уже списаны одной строкой в
        # enqueue_build (quoted_micro).
        self.store.charge(
            self.chat_id, entry_id=entry_id, job_id=self.job_id,
            provider=provider, unit=unit, quantity=quantity,
            unit_price_micro=unit_price_micro, cost_micro=cost_micro,
            charged_micro=0,
        )

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

    def claude_agent(self, runs: list[dict], reported_usd: float = 0.0) -> None:
        """Учесть себестоимость работы агента монтажа: план и отбор бироллов.

        До этого метода агент был единственным платным шагом, чья
        себестоимость нигде не считалась: подготовку сценария видит бот
        (`_charge_claude`), HeyGen и озвучку — метр, а план монтажа обходился
        ролику даром даже в отчётах. По замеру это около доллара — примерно
        пятая часть себестоимости ролика (см. `claude_montage_usd_per_reel`
        в config.py).
        """
        self.claude(claude_run_cost_usd(runs, reported_usd, self.rates))

    def total_charged(self) -> int:
        """Сколько этот метр списал с баланса — всегда 0.

        Метр только считает себестоимость (charged_micro=0 у каждой записи,
        см. `_record`); списание — одной строкой на цену с кнопки — делает
        enqueue_build. Метод остаётся инвариантом «метр не списывает», а не
        мёртвым кодом: на нём стоят тесты billing.
        """
        return self._charged
