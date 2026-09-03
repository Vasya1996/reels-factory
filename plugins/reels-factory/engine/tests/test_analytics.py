import time

import pytest

from reels_factory.analytics import FUNNEL_STEPS, EventStore, render_funnel


@pytest.fixture
def store(tmp_path):
    return EventStore(tmp_path / "events.sqlite3")


def _цикл(store, chat_id, cycle, *events, at=None):
    """Записать путь одного цикла."""
    for event in events:
        store.record(chat_id, cycle, event)


def test_шаги_денег_стоят_после_утверждения_сценария(store):
    """Цену человек видит один раз и после сценария — на экране выбора пути.
    Останься её шаги на прежнем месте (перед генерацией), funnel() засчитывал
    бы «увидел цену» каждому, кто дошёл до сценария, и воронка расширялась бы
    там, где на самом деле сузилась."""
    названия = [key for key, _ in FUNNEL_STEPS]

    assert названия.index("price_shown") > названия.index("scenario_approved")
    assert названия.index("balance_ok") == названия.index("price_shown") + 1
    assert названия.index("build_queued") == названия.index("balance_ok") + 1


def test_воронка_считает_циклы_а_не_события(store):
    """Человек может дважды увидеть экран выбора пути с ценами — это один
    цикл, а не два."""
    _цикл(store, 1, 1, "start", "stage:language", "price_shown", "price_shown")

    counts = {r["event"]: r["count"] for r in store.funnel()}

    assert counts["start"] == 1
    assert counts["price_shown"] == 1


def test_второй_ролик_считается_отдельным_циклом(store):
    _цикл(store, 1, 1, "start", "price_shown", "balance_ok")
    _цикл(store, 1, 2, "start", "price_shown")

    counts = {r["event"]: r["count"] for r in store.funnel()}

    assert counts["start"] == 2
    assert counts["price_shown"] == 2
    assert counts["balance_ok"] == 1
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
    assert свежая["price_shown"] == 0


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
    _цикл(store, 1, 1, "start", "price_shown", "topup_opened",
          "payment_received", "payment_received")

    оплата = {r["event"]: r["count"] for r in store.payment_branch()}

    assert оплата["payment_received"] == 1


def test_пропущенное_событие_раннего_шага_не_ломает_воронку(store):
    """Событие фото могло не записаться (данные с прошлого ролика), но раз
    человек дошёл до экрана выбора пути — значит фото у него было."""
    _цикл(store, 1, 1, "start", "stage:language", "stage:material", "price_shown")

    counts = {r["event"]: r["count"] for r in store.funnel()}

    assert counts["stage:photo"] == 1
    assert counts["stage:voice"] == 1
    assert [r["count"] for r in store.funnel()] == sorted(
        [r["count"] for r in store.funnel()], reverse=True
    )


def test_воронка_сужается_даже_у_постоянного_клиента(store):
    """У него фото и голос с прошлого ролика, а денег хватает без оплаты —
    и всё равно каждый следующий шаг не может быть шире предыдущего."""
    _цикл(store, 1, 1, "start", "stage:language", "stage:gender", "stage:photo",
          "stage:voice", "stage:material", "generation_started",
          "scenario_shown", "scenario_approved", "price_shown", "balance_ok")

    counts = [r["count"] for r in store.funnel()]

    assert counts == sorted(counts, reverse=True)


def test_ветка_оплаты_считается_от_тех_кому_не_хватило(store):
    # первый заплатил, второй открыл пополнение и бросил, третьему хватило
    _цикл(store, 1, 1, "start", "price_shown", "topup_opened",
          "invoice_created", "payment_received")
    _цикл(store, 2, 1, "start", "price_shown", "topup_opened")
    _цикл(store, 3, 1, "start", "price_shown", "balance_ok")

    branch = {r["event"]: r["count"] for r in store.payment_branch()}

    assert branch["topup_opened"] == 2
    assert branch["invoice_created"] == 1
    assert branch["payment_received"] == 1


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
          "stage:voice", "stage:material", "generation_started",
          "scenario_shown", "scenario_approved", "price_shown", "topup_opened",
          "invoice_created", "payment_received", "balance_ok", "build_queued",
          "audio_ready", "reel_delivered")
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

def test_три_самых_дорогих_сбоя_названы_в_журнале(store):
    """Сбой сборки, доставка с непройденным QA и несоздавшаяся озвучка —
    самые дорогие отвалы продукта. Без своего ключа в ERROR_EVENTS событие не
    попадает ни в счётчик сбоев, ни в подписи сводки: render_funnel берёт
    названия отсюда, и незнакомое событие показалось бы человеку голым
    `error:audio`."""
    from reels_factory.analytics import ERROR_EVENTS

    for key in ("error:build", "delivered:qa_fail", "error:audio"):
        assert key in ERROR_EVENTS, key
        assert ERROR_EVENTS[key] and not ERROR_EVENTS[key].startswith("error")

    _цикл(store, 1, 1, "start", "build_queued", "error:audio")

    assert store.errors()["error:audio"] == 1
    сводка = render_funnel(store, 0.0, title="Воронка")
    assert ERROR_EVENTS["error:audio"] in сводка


def test_доставленный_с_браком_виден_в_сбоях_но_не_в_остановившихся(store):
    """delivered:qa_fail пишется ПОСЛЕ reel_delivered (bot.py:_process_job) —
    цикл доехал, просто с изъяном. Он обязан посчитаться в «Сбои:» (иначе
    брак невидим), но не в «Остановились на:» — тот раздел читает последнее
    событие цикла, и без исключения доставленный ролик выглядел бы
    оборвавшимся на голом `delivered:qa_fail`."""
    from reels_factory.analytics import ERROR_EVENTS

    _цикл(store, 1, 1, "start", "build_queued", "reel_delivered", "delivered:qa_fail")

    assert store.errors()["delivered:qa_fail"] == 1
    сводка = render_funnel(store, 0.0, title="Воронка")
    assert f"— {ERROR_EVENTS['delivered:qa_fail']}: 1" in сводка
    # Единственный цикл доехал (reel_delivered в его событиях) — «Остановились
    # на:» не должно появиться вовсе, иначе qa_fail посчитался бы обрывом.
    assert "Остановились на:" not in сводка
