import json

import pytest

from reels_factory import tribute_shop


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def перехват(monkeypatch):
    """Подменяем сеть: запоминаем запрос и отдаём готовый ответ."""
    записано = {}

    def fake_urlopen(req, timeout=None):
        записано["url"] = req.full_url
        записано["method"] = req.method
        записано["headers"] = {k.lower(): v for k, v in req.headers.items()}
        записано["body"] = json.loads(req.data.decode()) if req.data else None
        return _Resp(записано.get("ответ") or {"uuid": "ord-1"})

    monkeypatch.setattr(tribute_shop.urllib.request, "urlopen", fake_urlopen)
    return записано


def test_счёт_уходит_с_ключом_и_нашими_полями(перехват):
    tribute_shop.create_order(
        api_key="k", amount_minor=1000, currency="usd", customer_id="777",
        title="Пополнение", description="Депозит",
    )

    assert перехват["url"] == "https://tribute.tg/api/v1/shop/orders"
    assert перехват["method"] == "POST"
    assert перехват["headers"]["api-key"] == "k"
    assert перехват["body"] == {
        "amount": 1000, "currency": "usd", "title": "Пополнение",
        "description": "Депозит", "customerId": "777", "period": "onetime",
    }


def test_чужая_валюта_отклоняется_до_запроса(перехват):
    with pytest.raises(tribute_shop.TributeShopError):
        tribute_shop.create_order(
            api_key="k", amount_minor=1000, currency="kzt", customer_id="7",
            title="t", description="d",
        )
    assert "url" not in перехват  # запроса не было


def test_нулевая_сумма_отклоняется_до_запроса(перехват):
    with pytest.raises(tribute_shop.TributeShopError):
        tribute_shop.create_order(
            api_key="k", amount_minor=0, currency="usd", customer_id="7",
            title="t", description="d",
        )
    assert "url" not in перехват


def test_ответ_без_uuid_считается_ошибкой(перехват):
    перехват["ответ"] = {"paymentUrl": "https://web.tribute.tg/shop/pay/x"}

    with pytest.raises(tribute_shop.TributeShopError):
        tribute_shop.create_order(
            api_key="k", amount_minor=100, currency="usd", customer_id="7",
            title="t", description="d",
        )


def test_статус_заказа_читается(перехват):
    перехват["ответ"] = {"status": "PAID"}

    assert tribute_shop.order_status(api_key="k", order_uuid="ord-1") == "paid"
    assert перехват["url"].endswith("/shop/orders/ord-1/status")


def test_ссылка_оплаты_предпочитает_телеграм():
    order = {
        "webappPaymentUrl": "https://t.me/tribute/app?startapp=shop_pay_x",
        "paymentUrl": "https://web.tribute.tg/shop/pay/x",
    }
    assert tribute_shop.payment_link(order).startswith("https://t.me/")


def test_ссылка_оплаты_откатывается_на_браузер():
    order = {"paymentUrl": "https://web.tribute.tg/shop/pay/x"}
    assert tribute_shop.payment_link(order) == "https://web.tribute.tg/shop/pay/x"
