import asyncio
import logging

import pytest

from reels_factory import alerts


class _FakeBot:
    """Замена telegram.Bot: тот же интерфейс (async context manager +
    send_message), без сети."""

    instances = []

    def __init__(self, token):
        self.token = token
        self.sent = []
        _FakeBot.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def send_message(self, chat_id, text):
        self.sent.append({"chat_id": chat_id, "text": text})


@pytest.fixture(autouse=True)
def _очистить_инстансы():
    _FakeBot.instances = []
    yield
    _FakeBot.instances = []


def test_без_переменных_окружения_ни_одного_вызова_и_без_исключений(
    monkeypatch,
):
    monkeypatch.delenv("ALERT_BOT_TOKEN", raising=False)
    monkeypatch.delenv("ALERT_CHAT_ID", raising=False)
    monkeypatch.setattr(alerts, "Bot", _FakeBot)

    asyncio.run(alerts.send_alert("текст, который никуда не должен уйти"))

    assert _FakeBot.instances == []


def test_с_одной_из_двух_переменных_тоже_молчит(monkeypatch):
    monkeypatch.setenv("ALERT_BOT_TOKEN", "token-1")
    monkeypatch.delenv("ALERT_CHAT_ID", raising=False)
    monkeypatch.setattr(alerts, "Bot", _FakeBot)

    asyncio.run(alerts.send_alert("текст"))

    assert _FakeBot.instances == []


def test_с_обеими_переменными_уходит_одно_сообщение(monkeypatch):
    monkeypatch.setenv("ALERT_BOT_TOKEN", "token-1")
    monkeypatch.setenv("ALERT_CHAT_ID", "999")
    monkeypatch.setattr(alerts, "Bot", _FakeBot)

    asyncio.run(alerts.send_alert("сборка упала"))

    assert len(_FakeBot.instances) == 1
    bot = _FakeBot.instances[0]
    assert bot.token == "token-1"
    assert bot.sent == [{"chat_id": "999", "text": "сборка упала"}]


def test_сбой_отправки_не_поднимается_наверх(monkeypatch, caplog):
    monkeypatch.setenv("ALERT_BOT_TOKEN", "token-1")
    monkeypatch.setenv("ALERT_CHAT_ID", "999")

    class _ПадающийБот(_FakeBot):
        async def send_message(self, chat_id, text):
            raise RuntimeError("Telegram недоступен")

    monkeypatch.setattr(alerts, "Bot", _ПадающийБот)

    with caplog.at_level(logging.WARNING):
        asyncio.run(alerts.send_alert("сборка упала"))  # не поднимает исключение

    assert "Telegram недоступен" in caplog.text


def test_warn_if_disabled_пишет_одну_строку_без_переменных(monkeypatch, caplog):
    monkeypatch.delenv("ALERT_BOT_TOKEN", raising=False)
    monkeypatch.delenv("ALERT_CHAT_ID", raising=False)

    with caplog.at_level(logging.INFO):
        alerts.warn_if_disabled()

    assert "алерты Васе выключены" in caplog.text


def test_warn_if_disabled_молчит_когда_переменные_заданы(monkeypatch, caplog):
    monkeypatch.setenv("ALERT_BOT_TOKEN", "token-1")
    monkeypatch.setenv("ALERT_CHAT_ID", "999")

    with caplog.at_level(logging.INFO):
        alerts.warn_if_disabled()

    assert "выключены" not in caplog.text
