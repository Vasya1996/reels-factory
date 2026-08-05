import time

import pytest

from reels_factory.analytics import EventStore, render_funnel


@pytest.fixture
def store(tmp_path):
    return EventStore(tmp_path / "events.sqlite3")


def _цикл(store, chat_id, cycle, *events, at=None):
    """Записать путь одного цикла."""
    for event in events:
        store.record(chat_id, cycle, event)


def test_воронка_считает_циклы_а_не_события(store):
    """Человек может дважды увидеть экран цены — это один цикл, а не два."""
    _цикл(store, 1, 1, "start", "stage:language", "price_shown", "price_shown")

    counts = {r["event"]: r["count"] for r in store.funnel()}

    assert counts["start"] == 1
    assert counts["price_shown"] == 1


def test_второй_ролик_считается_отдельным_циклом(store):
    _цикл(store, 1, 1, "start", "price_shown", "payment_received")
    _цикл(store, 1, 2, "start", "price_shown")

    counts = {r["event"]: r["count"] for r in store.funnel()}

    assert counts["start"] == 2
    assert counts["price_shown"] == 2
    assert counts["payment_received"] == 1
    assert store.totals()["chats"] == 1  # человек один
    assert store.totals()["repeat_chats"] == 1


def test_цикл_попадает_в_период_по_первому_событию(store, monkeypatch):
    """Начал вчера, заплатил сегодня — иначе в сегодняшней воронке была бы
    оплата без старта и конверсия выше 100%."""
    вчера = time.time() - 86_400 * 2
    monkeypatch.setattr(time, "time", lambda: вчера)
    _цикл(store, 1, 1, "start", "price_shown")
    monkeypatch.undo()
    store.record(1, 1, "payment_received")

    свежая = {r["event"]: r["count"] for r in store.funnel(since=time.time() - 86_400)}

    assert свежая["start"] == 0
    assert свежая["payment_received"] == 0


def test_проценты_считаются_от_предыдущего_шага(store):
    for chat in range(1, 11):
        _цикл(store, chat, 1, "start")
    for chat in range(1, 6):
        store.record(chat, 1, "stage:language")

    rows = {r["event"]: r for r in store.funnel()}

    assert rows["start"]["share_of_previous"] is None      # первому не от чего
    assert rows["stage:language"]["share_of_previous"] == 50


def test_дубль_оплаты_не_удваивает_шаг(store):
    """Вебхук и кнопка «Проверить оплату» пишут событие оба — цикл всё равно
    один."""
    _цикл(store, 1, 1, "start", "payment_received", "payment_received")

    counts = {r["event"]: r["count"] for r in store.funnel()}

    assert counts["payment_received"] == 1


def test_сбои_считаются_отдельно_от_шагов(store):
    _цикл(store, 1, 1, "start", "generation_started", "error:voice_clone")
    _цикл(store, 2, 1, "start", "generation_started", "error:voice_clone")
    _цикл(store, 3, 1, "start", "generation_started", "error:scenario")

    errors = store.errors()

    assert errors == {"error:voice_clone": 2, "error:scenario": 1}


def test_остановившиеся_видно_по_последнему_событию(store):
    _цикл(store, 1, 1, "start", "stage:language", "stage:gender")
    _цикл(store, 2, 1, "start", "stage:language", "stage:gender")
    _цикл(store, 3, 1, "start", "stage:language")

    dropoff = dict(store.dropoff())

    assert dropoff["stage:gender"] == 2
    assert dropoff["stage:language"] == 1


def test_сводка_читается_человеком(store):
    _цикл(store, 1, 1, "start", "stage:language", "stage:gender", "stage:photo",
          "stage:voice", "stage:material", "price_shown", "topup_opened",
          "invoice_created", "payment_received", "generation_started",
          "scenario_shown", "scenario_approved", "build_queued", "audio_ready",
          "reel_delivered")
    _цикл(store, 2, 1, "start", "stage:language", "error:scenario")

    text = render_funnel(store, 0, title="Воронка за 7 дн.")

    assert "Воронка за 7 дн." in text
    assert "Запустили бота: 2" in text
    assert "Получили ролик: 1" in text
    assert "сценарий не написался: 1" in text
    assert "Остановились на:" in text


def test_запись_не_падает_на_битой_базе(tmp_path):
    """Аналитика не имеет права уронить разговор с человеком."""
    битая = tmp_path / "events.sqlite3"
    store = EventStore(битая)
    битая.write_bytes("не sqlite".encode("utf-8"))

    store.record(1, 1, "start")  # не должно бросить
