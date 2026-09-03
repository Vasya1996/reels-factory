"""Алерт Васе в отдельный телеграм-бот, когда сборка ломается или доезжает с
изъяном (задача 08 из согласованного списка).

Тот же python-telegram-bot `Bot`, что использует основной бот (bot.py) — не
новый HTTP-клиент поверх requests/httpx: та же библиотека, тот же протокол
ошибок и ретраев. Токен и получатель — свои переменные окружения
(``ALERT_BOT_TOKEN``, ``ALERT_CHAT_ID``), не общий ``TELEGRAM_BOT_TOKEN``:
алерт-бот — отдельная сущность у Васи, не второй адрес того же бота.

Оба (или один из двух) не заданы — алерты тихо выключены: значений по
умолчанию в коде нет. ``warn_if_disabled`` пишет ОДНУ строку в лог при старте
сервиса (вызывается из ``bot.py: _post_init``); дальше ``send_alert`` молча
ничего не делает — ни исключения, ни второй записи в лог на каждый пропущенный
алерт.
"""
from __future__ import annotations

import logging
import os

from telegram import Bot

log = logging.getLogger(__name__)


def _config() -> tuple[str, str] | None:
    """Читает env при каждом вызове, а не один раз при импорте: тесты
    подставляют переменные через monkeypatch, и модуль обязан видеть их без
    переимпорта."""
    token = os.environ.get("ALERT_BOT_TOKEN")
    chat_id = os.environ.get("ALERT_CHAT_ID")
    if not token or not chat_id:
        return None
    return token, chat_id


def warn_if_disabled() -> None:
    """Вызывать один раз при старте сервиса. Алерты и так не поднимут
    исключения без переменных окружения — эта функция только оставляет след в
    логе, чтобы отсутствие алертов не осталось незамеченным до первого
    несостоявшегося алерта."""
    if _config() is None:
        log.info(
            "алерты Васе выключены: ALERT_BOT_TOKEN/ALERT_CHAT_ID не заданы "
            "в окружении"
        )


async def send_alert(text: str) -> None:
    """Отправить алерт; без переменных окружения — no-op. Сбой отправки
    (плохой токен, недоступный Telegram) не поднимается наверх: worker должен
    пережить упавший алерт-бот так же, как переживает отказ доставить сам
    ролик — алерт вторичен по отношению к ответу человеку."""
    cfg = _config()
    if cfg is None:
        return
    token, chat_id = cfg
    try:
        async with Bot(token=token) as bot:
            await bot.send_message(chat_id=chat_id, text=text)
    except Exception as e:
        log.warning("алерт Васе не отправился: %s", e)
