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


def test_нет_purchase_id_и_transaction_id_не_зачисляется(store):
    raw = body(purchase_id=None, transaction_id=None)
    res = handle_webhook(store, raw, sign(raw), api_key=KEY, fx=FX)
    assert res["credited"] is False
    assert res["reason"] == "no_purchase_id"
    assert store.balance(777) == 0


def test_неизвестная_валюта_не_зачисляется(store):
    # В fx нет "kzt" — угадывать курс 1:1 к доллару нельзя, это переплата.
    raw = body(currency="kzt")
    res = handle_webhook(store, raw, sign(raw), api_key=KEY, fx=FX)
    assert res["credited"] is False
    assert res["reason"] == "unknown_currency"
    assert store.balance(777) == 0


def test_отрицательная_сумма_не_зачисляется(store):
    # Отрицательный amount иначе тихо спишет баланс, а credited будет True.
    raw = body(amount=-1000)
    res = handle_webhook(store, raw, sign(raw), api_key=KEY, fx=FX)
    assert res["credited"] is False
    assert res["reason"] == "invalid_amount"
    assert store.balance(777) == 0


def test_нулевая_сумма_не_зачисляется(store):
    raw = body(amount=0)
    res = handle_webhook(store, raw, sign(raw), api_key=KEY, fx=FX)
    assert res["credited"] is False
    assert res["reason"] == "invalid_amount"
    assert store.balance(777) == 0


def test_нечисловой_telegram_user_id_не_роняет_обработчик(store):
    raw = body(telegram_user_id="abc")
    res = handle_webhook(store, raw, sign(raw), api_key=KEY, fx=FX)
    assert res["credited"] is False
    assert res["reason"] == "invalid_telegram_user_id"
