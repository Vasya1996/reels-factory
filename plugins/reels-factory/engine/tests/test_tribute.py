import hashlib
import hmac
import json
import urllib.error
import urllib.request

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


def shop_body(name="shop_order", **over) -> bytes:
    payload = {
        "uuid": "ord-1", "shopId": 133, "amount": 1000, "currency": "usd",
        "fee": 100, "status": "paid", "customerId": "777", "isRecurrent": False,
    }
    payload.update(over)
    return json.dumps({"name": name, "payload": payload}).encode()


def test_оплаченный_счёт_магазина_зачисляется_по_customer_id(store):
    raw = shop_body()

    res = handle_webhook(store, raw, sign(raw), api_key=KEY, fx=FX)

    assert res["credited"] is True
    assert store.balance(777) == 10_000_000


def test_промежуточное_событие_оплаты_не_зачисляется(store):
    """Их спека прямо говорит: shopOrderPaymentReceived — сигнал до зачисления
    денег продавцу, «не выдавайте товар». Финальное событие — shop_order."""
    raw = shop_body(name="shopOrderPaymentReceived")

    res = handle_webhook(store, raw, sign(raw), api_key=KEY, fx=FX)

    assert res["credited"] is False
    assert store.balance(777) == 0


def test_счёт_без_customer_id_не_зачисляется(store):
    # Счёт, выставленный руками в дашборде: чей он — неизвестно.
    raw = shop_body(customerId=None)

    res = handle_webhook(store, raw, sign(raw), api_key=KEY, fx=FX)

    assert res["credited"] is False
    assert res["reason"] == "no_customer_id"


def test_пробный_период_не_даёт_денег(store):
    raw = shop_body(isTrial=True)

    res = handle_webhook(store, raw, sign(raw), api_key=KEY, fx=FX)

    assert res["credited"] is False
    assert res["reason"] == "trial_activation"
    assert store.balance(777) == 0


def test_повторная_доставка_счёта_не_зачисляет_дважды(store):
    raw = shop_body()
    handle_webhook(store, raw, sign(raw), api_key=KEY, fx=FX)

    res = handle_webhook(store, raw, sign(raw), api_key=KEY, fx=FX)

    assert res["credited"] is False and res["reason"] == "duplicate"
    assert store.balance(777) == 10_000_000


def test_рублёвый_счёт_пересчитывается_в_доллары(store):
    raw = shop_body(amount=100_000, currency="rub", uuid="ord-rub")

    handle_webhook(store, raw, sign(raw), api_key=KEY, fx=FX)

    assert store.balance(777) == 11_000_000  # 1000 ₽ по курсу 0.011


def test_возврат_снимает_зачисленное(store):
    paid = shop_body()
    handle_webhook(store, paid, sign(paid), api_key=KEY, fx=FX)
    refund = json.dumps({"name": "shop_order_refunded", "payload": {
        "uuid": "ord-1", "shopId": 133, "transactionId": 55, "amount": 1000,
        "currency": "usd", "status": "completed", "customerId": "777",
    }}).encode()

    res = handle_webhook(store, refund, sign(refund), api_key=KEY, fx=FX)

    assert res["reason"] == "refunded"
    assert store.balance(777) == 0


def test_инициированный_возврат_баланс_не_трогает(store):
    paid = shop_body()
    handle_webhook(store, paid, sign(paid), api_key=KEY, fx=FX)
    refund = json.dumps({"name": "shop_order_refunded", "payload": {
        "uuid": "ord-1", "transactionId": 55, "amount": 1000, "currency": "usd",
        "status": "initiated", "customerId": "777",
    }}).encode()

    handle_webhook(store, refund, sign(refund), api_key=KEY, fx=FX)

    assert store.balance(777) == 10_000_000


def test_событие_camelCase_тоже_зачисляется(store):
    """В доке Tribute событие названо newDigitalProduct, в примере payload —
    new_digital_product. Промах по написанию = потерянный платёж."""
    raw = json.dumps({
        "name": "newDigitalProduct",
        "payload": {"amount": 100, "currency": "usd",
                    "telegram_user_id": 777, "purchase_id": "pur_camel"},
    }).encode()

    res = handle_webhook(store, raw, sign(raw), api_key=KEY, fx=FX)

    assert res["credited"] is True
    assert store.balance(777) == 1_000_000


def test_незачисленное_событие_печатается_целиком(store, capsys):
    """Чужой формат разбирается по логу: «unknown_currency» без payload —
    гадание, а деньги у человека уже списаны."""
    from reels_factory.tribute import start_webhook_server

    srv = start_webhook_server(store, api_key=KEY, fx=FX, port=0)
    try:
        port = srv.server_address[1]
        raw = body(currency="xtr", amount=7700)
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/tribute",
            data=raw, method="POST",
            headers={"trbt-signature": sign(raw)},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200
    finally:
        srv.shutdown()

    out = capsys.readouterr().out
    assert "unknown_currency" in out
    assert "xtr" in out and "7700" in out
    assert store.balance(777) == 0


def test_сервер_отвергает_плохую_подпись(store, capsys):
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

    # Перевыпущенный в дашборде ключ иначе выглядит как полная тишина
    assert "подпись не совпала" in capsys.readouterr().out


def test_сервер_отвечает_400_на_битый_content_length(store):
    """Fix 2: int(Content-Length) на нечисловом заголовке раньше поднимал
    ValueError прямо из do_POST — сокет рвался вместо честного 400."""
    from reels_factory.tribute import start_webhook_server

    srv = start_webhook_server(store, api_key=KEY, fx=FX, port=0)
    try:
        port = srv.server_address[1]
        raw = body()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/tribute",
            data=raw, method="POST",
            headers={
                "trbt-signature": sign(raw),
                "Content-Length": "not-a-number",
            },
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=5)
        assert exc.value.code == 400
        assert store.balance(777) == 0
    finally:
        srv.shutdown()


def test_обработчик_вебхука_ограничивает_время_чтения_соединения(store):
    """Fix 2: без таймаута клиент с Content-Length и без тела держит поток и
    сокет бесконечно — эндпоинт публично достижим через Caddy. Реального
    зависшего клиента здесь не гоняем (небыстрый тест), фиксируем сам факт,
    что socketserver применит таймаут к соединению (StreamRequestHandler)."""
    from reels_factory.tribute import start_webhook_server

    srv = start_webhook_server(store, api_key=KEY, fx=FX, port=0)
    try:
        assert srv.RequestHandlerClass.timeout == 30
    finally:
        srv.shutdown()
