"""Приём вебхуков Tribute: пополнение баланса пользователя.

Tribute шлёт new_digital_product на каждую покупку инфопродукта и ретраит
доставку около суток, поэтому обработчик обязан быть идемпотентным — ключ
идемпотентности purchase_id.

Сумма берётся из полей события (amount в минимальных единицах + currency), а не
из таблицы соответствия товаров: так новые номиналы заработают без правки кода.
"""
from __future__ import annotations

import hashlib
import hmac
import json

from reels_factory.billing import LedgerStore, to_micro

TOPUP_EVENT = "new_digital_product"


def verify_signature(raw: bytes, signature: str, api_key: str) -> bool:
    """HMAC-SHA256 тела запроса ключом API, заголовок trbt-signature.

    Сравнение постоянного времени: обычное == утекает побайтово.
    """
    expected = hmac.new(api_key.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, (signature or "").strip().lower())


def credited_micro(amount_minor: int, currency: str, fx: dict) -> int:
    """Сумма события -> микродоллары.

    amount приходит в минимальных единицах (центы, копейки), поэтому делим
    на 100 и умножаем на курс к доллару.
    """
    rate = float(fx.get((currency or "usd").lower(), 1.0))
    return to_micro(int(amount_minor) / 100.0 * rate)


def handle_webhook(store: LedgerStore, raw: bytes, signature: str, *,
                   api_key: str, fx: dict) -> dict:
    """Проверить подпись, разобрать событие, зачислить пополнение.

    PermissionError — единственный случай, когда отвечать не-2xx: всё
    остальное Tribute будет ретраить сутки без всякой пользы.
    """
    if not verify_signature(raw, signature, api_key):
        raise PermissionError("bad signature")
    event = json.loads(raw.decode("utf-8"))
    if event.get("name") != TOPUP_EVENT:
        return {"credited": False, "reason": "ignored_event"}
    payload = event.get("payload") or {}
    chat_id = payload.get("telegram_user_id")
    if not chat_id:
        # Покупка через веб без входа по Telegram — не знаем, кому зачислять.
        return {"credited": False, "reason": "no_telegram_user_id"}
    purchase_id = str(payload.get("purchase_id") or payload.get("transaction_id") or "")
    if not purchase_id:
        return {"credited": False, "reason": "no_purchase_id"}
    micro = credited_micro(payload.get("amount") or 0, payload.get("currency") or "usd", fx)
    credited = store.credit(
        int(chat_id), micro, purchase_id=purchase_id,
        amount_minor=int(payload.get("amount") or 0),
        currency=str(payload.get("currency") or "usd"), raw=event,
    )
    return {
        "credited": credited,
        "reason": "ok" if credited else "duplicate",
        "chat_id": int(chat_id),
        "micro": micro,
    }
