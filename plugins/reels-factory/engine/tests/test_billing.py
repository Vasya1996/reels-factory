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
