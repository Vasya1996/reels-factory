import time

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


def test_оценка_с_долей_аватара_уменьшает_только_heygen():
    # Та же основа: 420 символов -> 30 секунд. С долей 0.7 в HeyGen идут
    # только 21 сек: heygen $1.05 + eleven $0.042 (от полного текста) +
    # claude $0.05 = $1.142, с наценкой 2.0 -> $2.284.
    rates = {**RATES, "avatar_visible_share": 0.7}
    без_доли = estimate_micro(420, RATES, 2.0)
    с_долей = estimate_micro(420, rates, 2.0, avatar_share=rates["avatar_visible_share"])
    assert с_долей == 2_284_000
    # heygen-часть при доле 0.7 ровно на 30% меньше полной
    heygen_без_доли = heygen_cost_micro(30.0, RATES)
    heygen_с_долей = heygen_cost_micro(30.0 * 0.7, RATES)
    assert heygen_с_долей == round(heygen_без_доли * 0.7)
    # eleven и claude не меняются от доли
    assert с_долей != без_доли
    прочее_без_доли = elevenlabs_cost_micro(420, RATES) + claude_cost_micro(0.05)
    прочее_с_долей = elevenlabs_cost_micro(420, RATES) + claude_cost_micro(0.05)
    assert прочее_без_доли == прочее_с_долей


def test_оценка_без_доли_аватара_не_меняется():
    # avatar_share по умолчанию 1.0 — старое поведение для тех, кто его не передаёт.
    assert estimate_micro(420, RATES, 2.0) == estimate_micro(420, RATES, 2.0, avatar_share=1.0)


def test_конфиг_биллинга_отдаёт_дефолты_без_файла(tmp_path, monkeypatch):
    # Подменяем сам CONFIG_PATH, а не cwd: путь вычисляется один раз при
    # импорте модуля, и monkeypatch.chdir на него уже не влияет — тест
    # молча читал бы реальный конфиг машины.
    import reels_factory.config as cfg_mod
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", tmp_path / "config.yaml")

    cfg = load_billing_config()
    assert cfg["markup"] == 2.0
    assert cfg["rates"]["heygen_usd_per_second"] == 0.05
    assert cfg["rates"]["avatar_visible_share"] == 0.7
    assert cfg["enabled"] is True


def test_конфиг_биллинга_накладывает_значения_поверх_дефолтов(tmp_path, monkeypatch):
    import reels_factory.config as cfg_mod
    path = tmp_path / "config.yaml"
    path.write_text(
        "billing:\n  markup: 3.0\n  rates:\n    heygen_usd_per_second: 0.07\n"
        "    avatar_visible_share: 0.5\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", path)

    cfg = load_billing_config()
    assert cfg["markup"] == 3.0
    assert cfg["rates"]["heygen_usd_per_second"] == 0.07
    assert cfg["rates"]["avatar_visible_share"] == 0.5
    # не заданное в файле остаётся дефолтным
    assert cfg["rates"]["elevenlabs_usd_per_1k_chars"] == 0.10
    assert cfg["fx"]["rub"] == 0.011


from reels_factory.billing import billable_seconds


def test_billable_seconds_сбой_замера_логируется_но_не_роняет(monkeypatch, capsys):
    """Probe длительности может упасть уже ПОСЛЕ платного HeyGen-рендера —
    сборка не должна падать (остаётся 0.0), но раньше сбой проглатывался
    молча, и оператор не видел, что метр ничего не увидел. Живёт в billing.py
    (не в pipeline.py), чтобы им мог пользоваться и avatar_islands.py без
    цикла импорта."""
    import reels_factory.render as render_mod

    def bad_media_dur(path):
        raise RuntimeError("ffprobe упал")

    monkeypatch.setattr(render_mod, "media_dur", bad_media_dur)

    result = billable_seconds("неважно.mp4")

    assert result == 0.0
    assert "ffprobe упал" in capsys.readouterr().err


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


class _МедленноеЧисло(int):
    """int, который специально тормозит при форматировании в f-строку.

    Голая гонка на self._step (прочитать -> сформировать entry_id ->
    увеличить) на практике почти никогда не ловится обычным threading:
    GIL сериализует это крошечное окно быстрее, чем ОС успевает переключить
    поток именно между чтением и записью. Чтобы тест был воспроизводим, а не
    иногда-зелёным, окно гонки расширяется искусственно — но через реальный
    код _record, без подмены его логики: счётчик шагов просто на старте
    заводится этим типом, а __add__ сохраняет тип при инкременте, так что
    задержка сохраняется на каждом шаге.
    """

    def __format__(self, spec):
        time.sleep(0.001)
        return super().__format__(spec)

    def __add__(self, other):
        return _МедленноеЧисло(int(self) + other)


def test_meter_потокобезопасен_под_параллельной_нагрузкой(store):
    # avatar_islands рендерит шоты параллельно (ThreadPoolExecutor). Без лока
    # вокруг выдачи номера шага два потока читают один self._step, строят
    # одинаковый entry_id, и store.charge вторую запись молча отбрасывает —
    # оплаченный рендер HeyGen пропадает из журнала.
    import threading

    threads_n = 8
    per_thread = 20
    meter = JobMeter(store, chat_id=777, job_id="job1", rates=RATES, markup=2.0)
    meter._step = _МедленноеЧисло(meter._step)

    def worker():
        for _ in range(per_thread):
            meter.heygen(1.0)

    threads = [threading.Thread(target=worker) for _ in range(threads_n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    rows = store.job_breakdown("job1")
    expected_total = threads_n * per_thread * to_micro(RATES["heygen_usd_per_second"] * 2.0)
    assert rows["heygen"] == expected_total
    assert meter.total_charged() == expected_total

    with store._connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM spend_log WHERE job_id = ?", ("job1",)
        ).fetchone()["n"]
    assert count == threads_n * per_thread


def test_meter_повтор_сборки_с_тем_же_job_id_списывает_второй_раз(store):
    # Владелец решил: повторный ручной запуск упавшей сборки должен честно
    # показать второй расход, а не спрятать его дедупликацией по job_id.
    store.credit(777, 20_000_000, purchase_id="p1", amount_minor=2000, currency="usd")

    meter1 = JobMeter(store, chat_id=777, job_id="job1", rates=RATES, markup=2.0)
    meter1.elevenlabs(1000)

    meter2 = JobMeter(store, chat_id=777, job_id="job1", rates=RATES, markup=2.0)
    meter2.elevenlabs(1000)

    with store._connect() as conn:
        rows = conn.execute(
            "SELECT entry_id FROM spend_log WHERE job_id = ?", ("job1",)
        ).fetchall()
    assert len(rows) == 2
    assert rows[0]["entry_id"] != rows[1]["entry_id"]
    assert store.balance(777) == 20_000_000 - 2 * 200_000


def test_meter_защита_от_дубля_внутри_одного_запуска_сохраняется(store):
    meter = JobMeter(store, chat_id=777, job_id="job1", rates=RATES, markup=2.0)
    meter.heygen(30.0)
    meter.heygen(30.0)

    with store._connect() as conn:
        rows = conn.execute(
            "SELECT entry_id FROM spend_log WHERE job_id = ?", ("job1",)
        ).fetchall()
    assert len(rows) == 2
    entry_ids = {row["entry_id"] for row in rows}
    assert len(entry_ids) == 2

    # А прямая повторная запись тем же ключом через store.charge всё ещё
    # отклоняется — дедупликация внутри одного запуска никуда не делась.
    same_entry_id = rows[0]["entry_id"]
    assert store.charge(
        777, entry_id=same_entry_id, job_id="job1", provider="heygen",
        unit="seconds", quantity=30.0, unit_price_micro=50_000,
        cost_micro=1_500_000, charged_micro=3_000_000,
    ) is False
