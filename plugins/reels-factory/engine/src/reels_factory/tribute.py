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
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from reels_factory.billing import LedgerStore, to_micro

TOPUP_EVENT = "new_digital_product"
# В их доке событие названо camelCase (newDigitalProduct), в примере payload —
# snake_case. Принимаем оба написания: цена ошибки — незачисленный платёж.
TOPUP_EVENT_ALIASES = (TOPUP_EVENT, "newDigitalProduct")

# Счёт магазина оплачен окончательно. Именно это событие несёт status=paid;
# shopOrderPaymentReceived и shopOrderPrepaid — промежуточные, по ним деньги
# продавцу ещё не зачислены (openapi/shop/ru, описание вебхуков).
SHOP_PAID_EVENTS = ("shop_order", "shopOrder")
SHOP_REFUND_EVENTS = ("shop_order_refunded", "shopOrderRefunded")


class UnknownCurrencyError(ValueError):
    """Валюта события отсутствует в таблице курсов — не угадываем 1:1."""
    pass


class InvalidAmountError(ValueError):
    """Сумма события нулевая или отрицательная — бессмысленна для пополнения."""
    pass


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
    key = (currency or "usd").lower()
    if key not in fx:
        # Неизвестная валюта — не угадываем курс 1:1, это переплата в нашу пользу.
        raise UnknownCurrencyError(f"unknown currency: {currency!r}")
    rate = float(fx[key])
    amount = int(amount_minor)
    if amount <= 0:
        # Ноль и отрицательные суммы бессмысленны, а отрицательная тихо спишет баланс.
        raise InvalidAmountError(f"non-positive amount: {amount_minor!r}")
    return to_micro(amount / 100.0 * rate)


def credit_shop_order(store: LedgerStore, event: dict, fx: dict) -> dict:
    """Оплаченный счёт магазина -> пополнение баланса.

    Зачисляем только по `shop_order`: `shopOrderPaymentReceived` их же спека
    называет промежуточным сигналом («деньги продавцу ещё не зачислены и
    оплата может не завершиться»), а `shopOrderPrepaid` — вообще про звёзды до
    подтверждения списания.

    Кто платил, знаем из `customerId` — туда бот кладёт chat_id при создании
    счёта. Ключ идемпотентности — uuid заказа: ретраи идут сутки.
    """
    payload = event.get("payload") or {}
    if payload.get("isTrial"):
        # Активация бесплатного пробного периода: денег не было.
        return {"credited": False, "reason": "trial_activation", "event": event}
    status = str(payload.get("status") or "").lower()
    if status and status != "paid":
        return {"credited": False, "reason": f"status_{status}", "event": event}
    customer_id = str(payload.get("customerId") or "").strip()
    if not customer_id:
        # Счёт создан без customerId (например, руками в дашборде) — зачислять
        # некому, и угадывать по сумме нельзя.
        return {"credited": False, "reason": "no_customer_id", "event": event}
    try:
        chat_id = int(customer_id)
    except ValueError:
        return {"credited": False, "reason": "invalid_customer_id", "event": event}
    order_uuid = str(payload.get("uuid") or "")
    if not order_uuid:
        return {"credited": False, "reason": "no_order_uuid", "event": event}
    try:
        micro = credited_micro(
            payload.get("amount") or 0, payload.get("currency") or "usd", fx
        )
    except UnknownCurrencyError:
        return {"credited": False, "reason": "unknown_currency", "event": event}
    except InvalidAmountError:
        return {"credited": False, "reason": "invalid_amount", "event": event}
    credited = store.credit(
        chat_id, micro, purchase_id=f"shop:{order_uuid}",
        amount_minor=int(payload.get("amount") or 0),
        currency=str(payload.get("currency") or "usd"), raw=event,
    )
    return {
        "credited": credited,
        "reason": "ok" if credited else "duplicate",
        "chat_id": chat_id,
        "micro": micro,
        "order_uuid": order_uuid,
    }


def refund_shop_order(store: LedgerStore, event: dict, fx: dict) -> dict:
    """Возврат по счёту -> снять зачисленное обратно.

    Без этого возврат остаётся деньгами на балансе: Tribute вернул покупателю,
    а у нас он по-прежнему «оплачен». Списываем только по завершённому
    возврату (`status: completed`), инициированный ещё может не пройти.
    """
    payload = event.get("payload") or {}
    if str(payload.get("status") or "").lower() != "completed":
        return {"credited": False, "reason": "refund_not_completed", "event": event}
    customer_id = str(payload.get("customerId") or "").strip()
    order_uuid = str(payload.get("uuid") or "")
    if not (customer_id and order_uuid):
        return {"credited": False, "reason": "no_customer_id", "event": event}
    try:
        chat_id = int(customer_id)
    except ValueError:
        return {"credited": False, "reason": "invalid_customer_id", "event": event}
    try:
        micro = credited_micro(
            payload.get("amount") or 0, payload.get("currency") or "usd", fx
        )
    except (UnknownCurrencyError, InvalidAmountError):
        return {"credited": False, "reason": "invalid_refund_amount", "event": event}
    tx_id = payload.get("transactionId")
    store.charge(
        chat_id,
        entry_id=f"refund:{order_uuid}:{tx_id}",
        job_id=None,
        provider="tribute_refund",
        unit="refund",
        quantity=1,
        unit_price_micro=micro,
        cost_micro=micro,
        charged_micro=micro,
        meta={"order_uuid": order_uuid, "transaction_id": tx_id},
    )
    return {
        "credited": False,
        "reason": "refunded",
        "chat_id": chat_id,
        "micro": -micro,
        "order_uuid": order_uuid,
    }


def handle_webhook(store: LedgerStore, raw: bytes, signature: str, *,
                   api_key: str, fx: dict) -> dict:
    """Проверить подпись, разобрать событие, зачислить пополнение.

    PermissionError — единственный случай, когда отвечать не-2xx: всё
    остальное Tribute будет ретраить сутки без всякой пользы.
    """
    if not verify_signature(raw, signature, api_key):
        raise PermissionError("bad signature")
    event = json.loads(raw.decode("utf-8"))
    name = event.get("name")
    if name in SHOP_PAID_EVENTS:
        return credit_shop_order(store, event, fx)
    if name in SHOP_REFUND_EVENTS:
        return refund_shop_order(store, event, fx)
    if name not in TOPUP_EVENT_ALIASES:
        return {"credited": False, "reason": "ignored_event", "event": event}
    payload = event.get("payload") or {}
    chat_id = payload.get("telegram_user_id")
    if not chat_id:
        # Покупка через веб без входа по Telegram — не знаем, кому зачислять.
        return {"credited": False, "reason": "no_telegram_user_id", "event": event}
    try:
        chat_id = int(chat_id)
    except (TypeError, ValueError):
        # Нечисловой telegram_user_id — не даём int() уронить обработчик 500-й.
        return {"credited": False, "reason": "invalid_telegram_user_id", "event": event}
    purchase_id = str(payload.get("purchase_id") or payload.get("transaction_id") or "")
    if not purchase_id:
        return {"credited": False, "reason": "no_purchase_id", "event": event}
    try:
        micro = credited_micro(payload.get("amount") or 0, payload.get("currency") or "usd", fx)
    except UnknownCurrencyError:
        # Неизвестная валюта — не угадываем курс 1:1, это переплата в нашу пользу.
        return {"credited": False, "reason": "unknown_currency", "event": event}
    except InvalidAmountError:
        # Ноль и отрицательные суммы бессмысленны, а отрицательная тихо спишет баланс.
        return {"credited": False, "reason": "invalid_amount", "event": event}
    credited = store.credit(
        chat_id, micro, purchase_id=purchase_id,
        amount_minor=int(payload.get("amount") or 0),
        currency=str(payload.get("currency") or "usd"), raw=event,
    )
    return {
        "credited": credited,
        "reason": "ok" if credited else "duplicate",
        "chat_id": chat_id,
        "micro": micro,
    }


WEBHOOK_PATH = "/tribute"
MAX_BODY_BYTES = 1_000_000


def start_webhook_server(store: LedgerStore, *, api_key: str, fx: dict,
                         port: int, on_credit=None) -> ThreadingHTTPServer:
    """Поднять слушатель вебхука в демон-потоке.

    ThreadingHTTPServer из стандартной библиотеки, а не веб-фреймворк: новых
    зависимостей ради одного эндпоинта не вводим, а SQLite потокобезопасен при
    connection-per-call. Снаружи HTTPS терминирует Caddy.
    """

    class Handler(BaseHTTPRequestHandler):
        # Клиент может прислать Content-Length и замолчать — rfile.read()
        # блокируется бесконечно, а поток на соединение не освобождается.
        # Эндпоинт публично достижим через Caddy, так что это безлимитное
        # создание потоков снаружи без таймаута. socketserver сам применяет
        # timeout к сокету соединения (StreamRequestHandler.setup).
        timeout = 30

        def do_POST(self):  # noqa: N802 — имя задано базовым классом
            if self.path.rstrip("/") != WEBHOOK_PATH:
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                # Битый заголовок иначе роняет int() наружу do_POST и рвёт
                # соединение вместо честного 400.
                self.send_error(400)
                return
            if length <= 0 or length > MAX_BODY_BYTES:
                self.send_error(400)
                return
            raw = self.rfile.read(length)
            signature = self.headers.get("trbt-signature", "")
            try:
                result = handle_webhook(
                    store, raw, signature, api_key=api_key, fx=fx
                )
            except PermissionError:
                # Ключ в дашборде Tribute могли перевыпустить: без этой строки
                # отбитые доставки не видны вообще, а деньги у человека уже
                # списаны — платёж просто «теряется».
                print(
                    "[tribute] отклонено: подпись не совпала с TRIBUTE_API_KEY",
                    flush=True,
                )
                self.send_error(401)
                return
            except Exception:
                # Отдаём 500 намеренно: Tribute повторит доставку, а событие
                # идемпотентно — дубль не зачислится.
                self.send_error(500)
                return
            if result.get("credited"):
                print(
                    f"[tribute] зачислено {result.get('micro')} мкдолл "
                    f"чату {result.get('chat_id')}",
                    flush=True,
                )
                if on_credit is not None:
                    try:
                        on_credit(result)
                    except Exception:
                        pass
            else:
                # Незачисленный платёж должен быть заметен: дубль ретрая —
                # норма, а вот no_telegram_user_id означает застрявшие деньги.
                # Событие печатаем целиком: разбирать чужой формат по одному
                # слову «unknown_currency» — гадание, а деньги уже списаны.
                event = result.get("event")
                tail = f" | {json.dumps(event, ensure_ascii=False)[:800]}" if event else ""
                print(
                    f"[tribute] не зачислено: {result.get('reason')}{tail}",
                    flush=True,
                )
            payload = json.dumps({"status": "ok"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):  # тишина в stdout бота
            return

    server = ThreadingHTTPServer(("127.0.0.1", int(port)), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
