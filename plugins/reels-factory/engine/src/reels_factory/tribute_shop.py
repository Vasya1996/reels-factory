"""Клиент Shop API Tribute: счёт на произвольную сумму вместо готовых товаров.

Отличие от цифровых товаров (`/api/v1/products`, семь штук в дашборде, каждый
проходит модерацию): счёт создаётся запросом в момент оплаты, сумму и валюту
задаём мы, а `customerId` несёт наш chat_id — поэтому в вебхуке всегда видно,
кому зачислять. Цифровые товары оплачивались только звёздами или СБП; счёт
магазина покупатель может оплатить и картой, в том числе иностранной.

Спека: https://tribute.tg/api/v1/openapi/shop/ru
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

BASE_URL = "https://tribute.tg/api/v1"
TIMEOUT_S = 25

# Валюты, которые принимает POST /shop/orders (спека, enum currency).
SUPPORTED_CURRENCIES = ("usd", "rub", "eur")


class TributeShopError(RuntimeError):
    """Магазин не ответил или отказал — счёт человеку показывать нечего."""


def _request(method: str, path: str, api_key: str, payload: dict | None = None) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload else None
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=body,
        method=method,
        headers={
            "Api-Key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise TributeShopError(f"{method} {path}: HTTP {e.code} {detail}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise TributeShopError(f"{method} {path}: {e}") from e
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise TributeShopError(f"{method} {path}: ответ не JSON: {raw[:200]}") from e


def create_order(
    *,
    api_key: str,
    amount_minor: int,
    currency: str,
    customer_id: str,
    title: str,
    description: str,
) -> dict:
    """Создать счёт. Возвращает заказ целиком: uuid, paymentUrl, webappPaymentUrl.

    amount_minor — в минимальных единицах (центы для usd/eur, копейки для rub),
    как того требует спека. title и description обязательны, поэтому пустыми их
    не отправляем даже если вызывающий поленился.
    """
    currency = str(currency or "").lower()
    if currency not in SUPPORTED_CURRENCIES:
        raise TributeShopError(f"валюта {currency!r} не поддерживается магазином")
    if int(amount_minor) <= 0:
        raise TributeShopError(f"сумма {amount_minor!r} должна быть больше нуля")
    order = _request("POST", "/shop/orders", api_key, {
        "amount": int(amount_minor),
        "currency": currency,
        "title": title[:100],
        "description": description[:300],
        "customerId": str(customer_id)[:256],
        "period": "onetime",
    })
    if not order.get("uuid"):
        raise TributeShopError(f"магазин не вернул uuid заказа: {str(order)[:200]}")
    return order


def order_status(*, api_key: str, order_uuid: str) -> str:
    """Статус заказа: pending, prepaid, paid, failed.

    Нужен для сверки: если вебхук потерялся, оплату видно отсюда и человеку
    не приходится ждать нашей ручной правки базы.
    """
    data = _request("GET", f"/shop/orders/{order_uuid}/status", api_key)
    return str(data.get("status") or "").lower()


def get_order(*, api_key: str, order_uuid: str) -> dict:
    """Заказ целиком — сумма и валюта для зачисления при сверке."""
    return _request("GET", f"/shop/orders/{order_uuid}", api_key)


def payment_link(order: dict) -> str:
    """Ссылка оплаты для кнопки.

    Берём webappPaymentUrl (оплата открывается внутри Телеграма), а при его
    отсутствии — paymentUrl (страница в браузере). Оба ведут на один заказ, и
    `customerId` в вебхуке будет в любом случае: он привязан к заказу, а не к
    тому, как покупатель вошёл.
    """
    return str(order.get("webappPaymentUrl") or order.get("paymentUrl") or "")
