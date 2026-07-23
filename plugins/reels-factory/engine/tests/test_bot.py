import asyncio
import json

import pytest

from reels_factory import bot


@pytest.fixture
def work(tmp_path, monkeypatch):
    monkeypatch.setattr(bot, "WORK_ROOT", tmp_path / "work")
    return tmp_path


class _Msg:
    """Сообщение телеграма ровно в том объёме, в каком его трогает бот."""

    def __init__(self, text=None, chat_id=7, photo=None, voice=None):
        self.text = text
        self.caption = None
        self.chat_id = chat_id
        self.photo = photo
        self.voice = voice
        self.audio = self.video = self.video_note = self.document = None
        self.replies = []

    async def reply_text(self, text, reply_markup=None):
        self.replies.append(text)


class _Update:
    def __init__(self, msg):
        self.message = msg
        self.effective_chat = type("C", (), {"id": msg.chat_id})()


class _Query:
    def __init__(self, data, msg):
        self.data, self.message = data, msg

    async def answer(self):
        pass


def _press(button, msg):
    """Нажатие кнопки в чате."""
    upd = type("U", (), {"callback_query": _Query(button, msg)})()
    asyncio.run(bot.on_button(upd, None))


SCENARIO = {"title": "Про подготовку", "blocks": [
    {"role": "hook", "start": 0.0, "end": 3.0, "speech": "Продажи начинаются раньше."},
    {"role": "cta", "start": 3.0, "end": 28.0, "speech": "Сохрани себе."}]}


def test_сценарий_показывается_ролями_и_длительностью():
    out = bot.render_scenario(SCENARIO)
    assert "🎬 Про подготовку" in out
    assert "[хук] Продажи начинаются раньше." in out
    assert "[призыв] Сохрани себе." in out
    assert "28 сек" in out


def test_идеи_показываются_с_хуками():
    out = bot.render_ideas([{"idea": "Подготовка важнее встречи",
                             "draft_hook": "Вы опоздали ещё до встречи"}])
    assert "1. Подготовка важнее встречи" in out
    assert "Вы опоздали ещё до встречи" in out


def test_правка_пользователя_не_переписывается():
    text = "Первое предложение. Второе предложение. Третье предложение."
    sc = bot.scenario_from_text(text)
    склеено = " ".join(b["speech"] for b in sc["blocks"])
    assert склеено == text
    assert sc["mode"] == "verbatim"


def test_сессия_переживает_перезапуск(work):
    bot.save_session(7, {"step": bot.REVIEW, "scenario": SCENARIO})
    assert bot.load_session(7)["scenario"] == SCENARIO
    # чужой чат не видит соседа
    assert bot.load_session(8) == {"step": bot.CHOOSING}


def test_новый_чат_ведёт_к_выбору_пути(work):
    msg = _Msg("привет")
    asyncio.run(bot.on_message(_Update(msg), None))
    assert msg.replies == [bot.NOT_NOW]


def test_готовый_текст_превращается_в_сценарий(work, monkeypatch):
    monkeypatch.setattr(bot, "step_verbatim", lambda chat_id, text: SCENARIO)
    bot.save_session(7, {"step": bot.WAIT_TEXT})

    msg = _Msg("Мой текст.")
    asyncio.run(bot.on_message(_Update(msg), None))

    assert msg.replies[0] == bot.WORKING
    assert "[хук]" in msg.replies[1]
    s = bot.load_session(7)
    assert s["step"] == bot.REVIEW and s["scenario"] == SCENARIO


def test_сырьё_превращается_в_список_идей(work, monkeypatch):
    ideas = [{"idea": "Раз", "draft_hook": "Хук раз"},
             {"idea": "Два", "draft_hook": "Хук два"}]
    monkeypatch.setattr(bot, "step_ideas", lambda chat_id, text: ideas)
    bot.save_session(7, {"step": bot.WAIT_RAW})

    msg = _Msg("Длинное сырьё про продажи.")
    asyncio.run(bot.on_message(_Update(msg), None))

    assert "1. Раз" in msg.replies[1] and "2. Два" in msg.replies[1]
    s = bot.load_session(7)
    assert s["step"] == bot.CHOOSING_IDEA and s["ideas"] == ideas


def test_правленый_текст_становится_итоговым(work):
    bot.save_session(7, {"step": bot.WAIT_EDIT, "scenario": SCENARIO})

    msg = _Msg("Совсем другой текст. И вторая фраза.")
    asyncio.run(bot.on_message(_Update(msg), None))

    s = bot.load_session(7)
    assert s["step"] == bot.REVIEW
    assert "Совсем другой текст." in json.dumps(s["scenario"], ensure_ascii=False)


@pytest.fixture
def профиль(monkeypatch):
    """Внешние шаги профиля — без сети: HeyGen и ElevenLabs не зовём."""
    monkeypatch.setattr(bot, "_download", _fake_download)
    monkeypatch.setattr(bot, "step_photo", lambda chat_id, path: "asset-новый")
    monkeypatch.setattr(bot, "step_voice", lambda chat_id, path: "voice-1")
    monkeypatch.setattr(bot, "save_client_profile", lambda chat_id, s: None)


async def _fake_download(context, media, chat_id):
    from pathlib import Path
    return Path("фото.jpg")


def test_первый_ролик_требует_фото(work, профиль):
    bot.save_session(7, {"step": bot.REVIEW, "scenario": SCENARIO})

    msg = _Msg()
    _press("ok", msg)

    assert bot.load_session(7)["step"] == bot.WAIT_PHOTO
    assert "Кисти рук" in msg.replies[-1]


def test_второй_ролик_предлагает_выбор_фото(work, профиль):
    bot.save_session(7, {"step": bot.REVIEW, "scenario": SCENARIO,
                         "photos": [{"asset_id": "asset-старый"}], "voice_id": "voice-1"})

    _press("ok", _Msg())

    assert bot.load_session(7)["step"] == bot.CHOOSING_PHOTO


def test_загруженное_фото_идёт_в_работу_без_повторного_голоса(work, профиль):
    bot.save_session(7, {"step": bot.CHOOSING_PHOTO, "scenario": SCENARIO,
                         "photos": [{"asset_id": "asset-старый"}], "voice_id": "voice-1"})

    msg = _Msg()
    _press("photo:old", msg)

    s = bot.load_session(7)
    assert s["step"] == bot.READY and s["photo"] == 0
    assert msg.replies[-1] == bot.READY_MSG


def test_новое_фото_запоминается_и_становится_текущим(work, профиль):
    bot.save_session(7, {"step": bot.WAIT_PHOTO, "scenario": SCENARIO,
                         "photos": [{"asset_id": "asset-старый"}], "voice_id": "voice-1"})

    msg = _Msg(photo=[object()])
    asyncio.run(bot.on_message(_Update(msg), None))

    s = bot.load_session(7)
    assert [p["asset_id"] for p in s["photos"]] == ["asset-старый", "asset-новый"]
    assert s["photo"] == 1 and s["step"] == bot.READY


def test_голос_спрашивается_один_раз(work, профиль):
    bot.save_session(7, {"step": bot.WAIT_PHOTO, "scenario": SCENARIO})

    msg = _Msg(photo=[object()])
    asyncio.run(bot.on_message(_Update(msg), None))
    assert bot.load_session(7)["step"] == bot.WAIT_VOICE

    голос = _Msg(voice=object())
    asyncio.run(bot.on_message(_Update(голос), None))
    s = bot.load_session(7)
    assert s["voice_id"] == "voice-1" and s["step"] == bot.READY


def test_сбой_движка_не_роняет_разговор(work, monkeypatch):
    def падаем(chat_id, text):
        raise RuntimeError("claude -p упал")

    monkeypatch.setattr(bot, "step_verbatim", падаем)
    bot.save_session(7, {"step": bot.WAIT_TEXT})

    msg = _Msg("Мой текст.")
    asyncio.run(bot.on_message(_Update(msg), None))

    assert "claude -p упал" in msg.replies[-1]
    assert bot.load_session(7)["step"] == bot.WAIT_TEXT
