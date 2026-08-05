"""Журнал событий бота и воронка по нему.

Зачем отдельная таблица, если есть сессии, задания и биллинг: в сессии лежит
только текущий шаг (вернулся назад — прошлое стёрлось), в заданиях — самый
конец пути, в биллинге — деньги. Ни один из них не отвечает на вопрос «сколько
людей дошло до оплаты и где отваливаются остальные».

Считаем по циклам, а не по людям: один человек делает второй ролик, и без
номера цикла его путь смешался бы с первым, а проценты поплыли. cycle_id
растёт на каждый /start и «Новый ролик».

Чего этой аналитикой не измерить, сколько бы событий мы ни писали:
«открыл бота, но не нажал Start» — Telegram о таких людях боту не сообщает.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

# Шаги воронки по порядку. Ключ — событие в базе, значение — подпись в сводке.
FUNNEL_STEPS = (
    ("start", "Запустили бота"),
    ("stage:language", "Выбрали язык"),
    ("stage:gender", "Выбрали пол аватара"),
    ("stage:photo", "Прислали фото"),
    ("stage:voice", "Записали голос"),
    ("stage:material", "Прислали материал"),
    ("price_shown", "Увидели цену"),
    ("topup_opened", "Открыли пополнение"),
    ("invoice_created", "Выставили счёт"),
    ("payment_received", "Оплатили"),
    ("generation_started", "Запустили генерацию"),
    ("scenario_shown", "Получили сценарий"),
    ("scenario_approved", "Утвердили сценарий"),
    ("build_queued", "Отправили в сборку"),
    ("audio_ready", "Получили озвучку"),
    ("reel_delivered", "Получили ролик"),
)

# Сбои: их считаем отдельно, иначе «отвалился на озвучке» значит и «передумал»,
# и «у нас сломалось».
ERROR_EVENTS = {
    "error:invoice": "счёт не выставился",
    "error:voice_clone": "голос не создался",
    "error:scenario": "сценарий не написался",
    "error:build": "сборка упала",
    "error:qa": "не прошло проверку качества",
    "error:delivery": "ролик не доставлен",
    "error:blocked": "бот заблокирован",
}


class EventStore:
    """Событие = (чат, цикл, что случилось, когда)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    cycle_id INTEGER NOT NULL,
                    event TEXT NOT NULL,
                    detail TEXT,
                    created_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS events_cycle "
                "ON events (chat_id, cycle_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS events_time ON events (created_at)"
            )

    def record(self, chat_id: int, cycle_id: int, event: str,
               detail: str | None = None) -> None:
        """Записать событие. Сбой записи не должен ронять разговор — ловим здесь."""
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO events (chat_id, cycle_id, event, detail, created_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (int(chat_id), int(cycle_id), str(event),
                     str(detail) if detail is not None else None, time.time()),
                )
        except sqlite3.Error:
            pass

    def funnel(self, since: float = 0.0) -> list[dict]:
        """Сколько циклов дошло до каждого шага.

        Цикл попадает в выборку по времени своего ПЕРВОГО события: иначе
        человек, начавший вчера и заплативший сегодня, посчитался бы в
        сегодняшней воронке как оплата без старта, и конверсия превысила бы
        100%.
        """
        rows = self._cycle_events(since)
        reached: dict[str, set] = {}
        for key, _label in FUNNEL_STEPS:
            reached[key] = set()
        for (chat_id, cycle_id), events in rows.items():
            for event in events:
                if event in reached:
                    reached[event].add((chat_id, cycle_id))
        out = []
        previous = None
        for key, label in FUNNEL_STEPS:
            count = len(reached[key])
            share = None if previous in (None, 0) else round(count * 100 / previous)
            out.append({
                "event": key, "label": label, "count": count,
                "share_of_previous": share,
            })
            previous = count
        return out

    def errors(self, since: float = 0.0) -> dict[str, int]:
        """Сколько циклов упёрлись в каждый сбой."""
        rows = self._cycle_events(since)
        counts: dict[str, int] = {}
        for events in rows.values():
            for event in set(events):
                if event in ERROR_EVENTS:
                    counts[event] = counts.get(event, 0) + 1
        return counts

    def dropoff(self, since: float = 0.0) -> list[tuple[str, int]]:
        """На каком шаге циклы остановились — по последнему событию."""
        rows = self._cycle_events(since)
        last: dict[str, int] = {}
        for events in rows.values():
            if not events:
                continue
            last[events[-1]] = last.get(events[-1], 0) + 1
        return sorted(last.items(), key=lambda kv: -kv[1])

    def totals(self, since: float = 0.0) -> dict:
        rows = self._cycle_events(since)
        chats = {chat_id for chat_id, _ in rows}
        repeat = {
            chat_id for chat_id, cycle_id in rows if int(cycle_id) > 1
        }
        return {"cycles": len(rows), "chats": len(chats), "repeat_chats": len(repeat)}

    def _cycle_events(self, since: float) -> dict[tuple[int, int], list[str]]:
        """События по циклам, в порядке времени. Циклы старее since отброшены."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT chat_id, cycle_id, event, created_at FROM events"
                " ORDER BY created_at, id"
            ).fetchall()
        started: dict[tuple[int, int], float] = {}
        events: dict[tuple[int, int], list[str]] = {}
        for r in rows:
            key = (r["chat_id"], r["cycle_id"])
            started.setdefault(key, r["created_at"])
            events.setdefault(key, []).append(r["event"])
        return {
            key: ev for key, ev in events.items() if started[key] >= since
        }


def render_funnel(store: EventStore, since: float, *, title: str) -> str:
    """Сводка для чата: воронка, сбои и где стоят остановившиеся."""
    totals = store.totals(since)
    lines = [
        title,
        f"Циклов: {totals['cycles']} · людей: {totals['chats']} · "
        f"вернулись за вторым роликом: {totals['repeat_chats']}",
        "",
    ]
    for row in store.funnel(since):
        share = f" ({row['share_of_previous']}%)" if row["share_of_previous"] is not None else ""
        lines.append(f"{row['label']}: {row['count']}{share}")
    errors = store.errors(since)
    if errors:
        lines.append("")
        lines.append("Сбои:")
        for key, count in sorted(errors.items(), key=lambda kv: -kv[1]):
            lines.append(f"— {ERROR_EVENTS[key]}: {count}")
    stuck = [
        (event, count) for event, count in store.dropoff(since)
        if event != "reel_delivered"
    ][:5]
    if stuck:
        labels = dict(FUNNEL_STEPS) | ERROR_EVENTS
        lines.append("")
        lines.append("Остановились на:")
        for event, count in stuck:
            lines.append(f"— {labels.get(event, event)}: {count}")
    return "\n".join(lines)
