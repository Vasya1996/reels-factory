import asyncio
import json
import logging

import pytest

from reels_factory import bot
from reels_factory import clients as clients_mod
from reels_factory.config import ConfigError


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
        self.markups = []
        self.videos = []

    async def reply_text(self, text, reply_markup=None):
        self.replies.append(text)
        self.markups.append(reply_markup)

    async def reply_video(self, video, caption=None, reply_markup=None,
                          width=None, height=None):
        self.videos.append((video, caption, reply_markup))
        self.video_sizes = (width, height)
        self.replies.append(caption)
        self.markups.append(reply_markup)


class _Update:
    def __init__(self, msg):
        self.message = msg
        self.effective_chat = type("C", (), {"id": msg.chat_id})()


class _Query:
    def __init__(self, data, msg):
        self.data, self.message = data, msg

    async def answer(self):
        pass


class _BotAPI:
    """Минимальный Telegram Bot для background worker."""

    def __init__(self):
        self.messages = []
        self.videos = []

    async def send_message(self, chat_id, text):
        self.messages.append((chat_id, text))

    async def send_video(self, chat_id, video, caption=None, reply_markup=None,
                         width=None, height=None):
        self.videos.append({
            "chat_id": chat_id,
            "bytes": video.read(),
            "caption": caption,
            "reply_markup": reply_markup,
            "width": width,
            "height": height,
        })


def _press(button, msg):
    """Нажатие кнопки в чате."""
    upd = type("U", (), {"callback_query": _Query(button, msg)})()
    asyncio.run(bot.on_button(upd, None))


def _labels(markup):
    """Подписи кнопок клавиатуры — плоским списком."""
    return [b.text for row in markup.inline_keyboard for b in row]


def _claim_job():
    job = bot._job_store().claim_next()
    assert job is not None
    return job


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


def test_копипаста_чистится_от_кавычек_и_пустых_строк():
    текст = '«Первая мысль. И вторая.»\n\n«Третья мысль.»'
    assert bot.clean_input(текст) == "Первая мысль. И вторая. Третья мысль."


def test_сессия_переживает_перезапуск(work):
    bot.save_session(7, {"step": bot.REVIEW, "scenario": SCENARIO})
    assert bot.load_session(7)["scenario"] == SCENARIO
    # чужой чат не видит соседа
    assert bot.load_session(8) == {"step": bot.CHOOSING}


def test_status_читает_последнюю_job_из_sqlite(work):
    job = bot._job_store().enqueue(7)
    msg = _Msg()

    asyncio.run(bot.cmd_status(_Update(msg), None))

    assert job.job_id[:8] in msg.replies[-1]
    assert "в очереди" in msg.replies[-1]


# --- миграция сессий старого формата (photos: [...] + photo: int) -------------

def test_load_session_мигрирует_старый_формат_с_индексом(work):
    old = {"step": bot.READY,
           "photos": [{"asset_id": "a0", "file": "ф0.jpg"},
                      {"asset_id": "a1", "file": "ф1.jpg"}],
           "photo": 1}
    d = bot.session_dir(7)
    d.mkdir(parents=True, exist_ok=True)
    (d / "session.json").write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")

    s = bot.load_session(7)

    assert s["photo"] == {"asset_id": "a1", "file": "ф1.jpg"}
    assert "photos" not in s


def test_load_session_мигрирует_старый_формат_с_индексом_ноль(work):
    # ключевой баг ревью: photo=0 в старом формате — это индекс первого
    # фото, а не «фото нет»
    old = {"step": bot.READY,
           "photos": [{"asset_id": "a0", "file": "ф0.jpg"}],
           "photo": 0}
    d = bot.session_dir(7)
    d.mkdir(parents=True, exist_ok=True)
    (d / "session.json").write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")

    s = bot.load_session(7)

    assert s["photo"] == {"asset_id": "a0", "file": "ф0.jpg"}
    assert "photos" not in s


def test_новый_чат_ведёт_к_выбору_пути(work):
    msg = _Msg("привет")
    asyncio.run(bot.on_message(_Update(msg), None))
    assert msg.replies == [bot.NOT_NOW]


def test_loop_session_сохраняет_только_фото_и_голос():
    s = {"step": bot.DONE, "scenario": SCENARIO, "photo": {"asset_id": "a"},
         "voice_id": "v", "ideas": [1], "material_mode": "raw"}
    assert bot.loop_session(s) == {"step": bot.CHOOSING, "photo": {"asset_id": "a"},
                                    "voice_id": "v"}


def test_fresh_session_не_сохраняет_сценарий():
    s = {"step": bot.DONE, "scenario": SCENARIO, "photo": {"asset_id": "a"}, "voice_id": "v"}
    assert bot.fresh_session(s) == {"step": bot.CHOOSING, "photo": {"asset_id": "a"},
                                     "voice_id": "v"}


# --- язык каждого нового ролика ----------------------------------------------

def test_первый_start_спрашивает_один_язык(work):
    msg = _Msg()

    asyncio.run(bot.cmd_start(_Update(msg), None))

    assert msg.replies[-1] == bot.ASK_LANGUAGE
    assert _labels(msg.markups[-1]) == ["🇷🇺 Русский", "🇰🇿 Қазақша"]
    assert bot.load_session(7)["step"] == bot.CHOOSING_LANGUAGE


def test_после_выбора_казахского_показывается_выбор_пути(work):
    asyncio.run(bot.cmd_start(_Update(_Msg()), None))
    msg = _Msg()

    _press("reel_language:kk", msg)

    s = bot.load_session(7)
    assert s["language"] == "kk"
    assert s["step"] == bot.CHOOSING
    assert msg.replies[-1] == bot.HELLO
    assert _labels(msg.markups[-1]) == [
        "У меня готовый сценарий", "Предложи сценарий"
    ]


def test_готовый_русский_текст_блокируется_для_казахского_ролика(work, monkeypatch):
    called = []
    monkeypatch.setattr(
        bot,
        "step_verbatim",
        lambda chat_id, text, language: called.append(language),
    )
    bot.save_session(7, {
        "step": bot.WAIT_TEXT,
        "language": "kk",
    })
    msg = _Msg(
        "Это готовый русский сценарий, который мы хотим использовать для "
        "нового ролика, но выбран другой язык."
    )

    asyncio.run(bot.on_message(_Update(msg), None))

    assert called == []
    assert "Для этого ролика выбран язык: 🇰🇿 Қазақша" in msg.replies[-1]
    assert "Изменить язык ролика" in _labels(msg.markups[-1])


def test_готовый_казахский_текст_идёт_в_kk_обработку(work, monkeypatch):
    calls = []

    def fake_step(chat_id, text, language):
        calls.append(language)
        return {**SCENARIO, "language": language}

    monkeypatch.setattr(bot, "step_verbatim", fake_step)
    bot.save_session(7, {
        "step": bot.WAIT_TEXT,
        "language": "kk",
    })
    msg = _Msg(
        "Бұл қазақша дайын сценарий және біз оны жаңа ролик үшін "
        "қолданғымыз келеді."
    )

    asyncio.run(bot.on_message(_Update(msg), None))

    assert calls == ["kk"]
    assert bot.load_session(7)["scenario"]["language"] == "kk"


def test_при_смене_ru_на_kk_русский_голос_сохраняется_а_казахский_запрашивается(
        work, monkeypatch):
    monkeypatch.setattr(bot, "_download", _fake_download)
    captured_languages = []
    monkeypatch.setattr(
        bot,
        "step_voice",
        lambda chat_id, path, language: (
            captured_languages.append(language) or "voice-kk"
        ),
    )
    monkeypatch.setattr(bot, "save_client_profile", lambda chat_id, s: None)
    bot.save_session(7, {
        "step": bot.DONE,
        "photo": {"asset_id": "asset-1", "file": "photo.jpg"},
        "voices": {"ru": "voice-ru"},
        "voice_id": "voice-ru",
        "voice_language": "ru",
        "language": "ru",
    })

    asyncio.run(bot.cmd_new(_Update(_Msg()), None))
    _press("reel_language:kk", _Msg())

    selected = bot.load_session(7)
    assert selected["voices"] == {"ru": "voice-ru"}
    assert "voice_id" not in selected and "voice_language" not in selected

    selected.update({
        "step": bot.CHOOSING_PHOTO,
        "scenario": {**SCENARIO, "language": "kk"},
    })
    bot.save_session(7, selected)
    ask = _Msg()
    _press("photo:old", ask)

    assert bot.load_session(7)["step"] == bot.WAIT_VOICE
    assert "🇰🇿 Қазақша" in ask.replies[-1]

    asyncio.run(bot.on_message(_Update(_Msg(voice=object())), None))
    recorded = bot.load_session(7)
    assert captured_languages == ["kk"]
    assert recorded["voices"] == {
        "ru": "voice-ru",
        "kk": "voice-kk",
    }
    assert recorded["voice_id"] == "voice-kk"
    assert recorded["voice_language"] == "kk"
    assert recorded["step"] == bot.READY


def test_при_возврате_на_ru_бот_активирует_сохранённый_русский_голос(work):
    bot.save_session(7, {
        "step": bot.DONE,
        "photo": {"asset_id": "asset-1", "file": "photo.jpg"},
        "voices": {"ru": "voice-ru", "kk": "voice-kk"},
        "voice_id": "voice-kk",
        "voice_language": "kk",
        "language": "kk",
    })

    asyncio.run(bot.cmd_new(_Update(_Msg()), None))
    _press("reel_language:ru", _Msg())
    selected = bot.load_session(7)
    selected.update({
        "step": bot.CHOOSING_PHOTO,
        "scenario": {**SCENARIO, "language": "ru"},
    })
    bot.save_session(7, selected)

    msg = _Msg()
    _press("photo:old", msg)

    current = bot.load_session(7)
    assert current["step"] == bot.CHOOSING_VOICE
    assert current["voice_id"] == "voice-ru"
    assert current["voice_language"] == "ru"
    assert "🇷🇺 Русский" in msg.replies[-1]


# --- шаг 2: выбор материала --------------------------------------------------

def test_материал_для_новичка_без_кнопки_редактировать(work):
    bot.save_session(7, {"step": bot.CHOOSING})
    msg = _Msg()
    _press("mode:text", msg)

    s = bot.load_session(7)
    assert s["step"] == bot.CHOOSING_MATERIAL and s["material_mode"] == "text"
    labels = _labels(msg.markups[-1])
    assert "Редактировать существующий" not in labels
    assert "Прислать новый текст" in labels


def test_материал_с_прошлым_сценарием_предлагает_редактировать(work):
    bot.save_session(7, {"step": bot.CHOOSING, "scenario": SCENARIO})
    msg = _Msg()
    _press("mode:raw", msg)

    labels = _labels(msg.markups[-1])
    assert "Редактировать существующий" in labels
    assert "Прислать новое сырьё" in labels


def test_редактировать_существующий_ведёт_сразу_к_сценарию(work):
    bot.save_session(7, {"step": bot.CHOOSING_MATERIAL, "material_mode": "text",
                         "scenario": SCENARIO})
    msg = _Msg()
    _press("material:edit", msg)

    assert bot.load_session(7)["step"] == bot.REVIEW
    assert "[хук]" in msg.replies[-1]


def test_прислать_новый_текст_ведёт_к_вводу_текста(work):
    bot.save_session(7, {"step": bot.CHOOSING_MATERIAL, "material_mode": "text",
                         "scenario": SCENARIO})
    msg = _Msg()
    _press("material:new", msg)

    assert bot.load_session(7)["step"] == bot.WAIT_TEXT
    assert msg.replies[-1] == bot.ASK_TEXT


def test_прислать_новое_сырьё_ведёт_к_вводу_сырья(work):
    bot.save_session(7, {"step": bot.CHOOSING_MATERIAL, "material_mode": "raw",
                         "scenario": SCENARIO})
    msg = _Msg()
    _press("material:new", msg)

    assert bot.load_session(7)["step"] == bot.WAIT_RAW
    assert msg.replies[-1] == bot.ASK_RAW


# --- шаг 3: приём материала ---------------------------------------------------

def test_готовый_текст_превращается_в_сценарий(work, monkeypatch):
    monkeypatch.setattr(
        bot, "step_verbatim", lambda chat_id, text, language: SCENARIO
    )
    bot.save_session(7, {
        "step": bot.WAIT_TEXT, "language": "ru"
    })

    msg = _Msg("Мой текст.")
    asyncio.run(bot.on_message(_Update(msg), None))

    assert msg.replies[0] == bot.WORKING
    assert "[хук]" in msg.replies[1]
    s = bot.load_session(7)
    assert s["step"] == bot.REVIEW and s["scenario"] == SCENARIO


def test_сырьё_превращается_в_список_идей(work, monkeypatch):
    ideas = [{"idea": "Раз", "draft_hook": "Хук раз"},
             {"idea": "Два", "draft_hook": "Хук два"}]
    monkeypatch.setattr(
        bot, "step_ideas", lambda chat_id, text, language: ideas
    )
    bot.save_session(7, {
        "step": bot.WAIT_RAW, "language": "kk"
    })

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


# --- назад: ничего не теряем --------------------------------------------------

def test_назад_с_ввода_текста_возвращает_к_материалу(work):
    bot.save_session(7, {"step": bot.WAIT_TEXT, "material_mode": "text"})

    msg = _Msg()
    _press("back", msg)

    assert bot.load_session(7)["step"] == bot.CHOOSING_MATERIAL
    assert msg.replies[-1] == bot.ASK_MATERIAL


def test_назад_с_материала_возвращает_к_выбору_пути_сохраняя_сценарий(work):
    # сценарий уже утверждён (кнопка «Редактировать существующий» видна) —
    # «Назад» отсюда не имеет права его стереть
    bot.save_session(7, {"step": bot.CHOOSING_MATERIAL, "material_mode": "text",
                         "scenario": SCENARIO, "photo": {"asset_id": "a1"},
                         "voice_id": "voice-1", "voice_language": "ru",
                         "voices": {"ru": "voice-1"}, "language": "ru"})

    msg = _Msg()
    _press("back", msg)

    s = bot.load_session(7)
    assert s["step"] == bot.CHOOSING
    assert s["scenario"] == SCENARIO
    assert s["photo"] == {"asset_id": "a1"} and s["voice_id"] == "voice-1"
    assert msg.replies[-1] == bot.HELLO


def test_назад_с_правки_возвращает_сценарий(work):
    bot.save_session(7, {"step": bot.WAIT_EDIT, "scenario": SCENARIO})

    msg = _Msg()
    _press("back", msg)

    assert bot.load_session(7)["step"] == bot.REVIEW
    assert "[хук]" in msg.replies[-1]


def test_назад_со_сценария_возвращает_к_идеям(work):
    ideas = [{"idea": "Раз", "draft_hook": "Хук раз"}]
    bot.save_session(7, {"step": bot.REVIEW, "scenario": SCENARIO, "ideas": ideas})

    msg = _Msg()
    _press("back", msg)

    assert bot.load_session(7)["step"] == bot.CHOOSING_IDEA
    assert "1. Раз" in msg.replies[-1]


def test_назад_со_сценария_без_идей_и_сырья_возвращает_к_сырью(work):
    bot.save_session(7, {"step": bot.REVIEW, "scenario": SCENARIO, "material_mode": "raw"})

    msg = _Msg()
    _press("back", msg)

    assert bot.load_session(7)["step"] == bot.WAIT_RAW
    assert msg.replies[-1] == bot.ASK_RAW


def test_назад_с_идей_возвращает_к_сырью(work):
    bot.save_session(7, {"step": bot.CHOOSING_IDEA, "ideas": [{"idea": "Раз",
                                                              "draft_hook": "Х"}]})

    msg = _Msg()
    _press("back", msg)

    assert bot.load_session(7)["step"] == bot.WAIT_RAW
    assert msg.replies[-1] == bot.ASK_RAW


def test_назад_с_фото_возвращает_к_сценарию(work):
    bot.save_session(7, {"step": bot.WAIT_PHOTO, "scenario": SCENARIO})

    msg = _Msg()
    _press("back", msg)

    assert bot.load_session(7)["step"] == bot.REVIEW


def test_назад_с_выбора_голоса_возвращает_к_фото(work):
    bot.save_session(7, {"step": bot.CHOOSING_VOICE, "scenario": SCENARIO,
                         "photo": {"asset_id": "a1", "file": "ф.jpg"}, "voice_id": "v1"})

    msg = _Msg()
    _press("back", msg)

    assert bot.load_session(7)["step"] == bot.CHOOSING_PHOTO


# --- «новый ролик»: заново язык и сценарий, профильные медиа сохраняются ------

def test_новый_ролик_спрашивает_язык_и_сохраняет_фото_и_голос(work):
    bot.save_session(7, {"step": bot.DONE, "scenario": SCENARIO,
                         "photo": {"asset_id": "a1", "file": "ф.jpg"},
                         "voice_id": "voice-1", "language": "ru"})

    msg = _Msg()
    _press("new_reel", msg)

    s = bot.load_session(7)
    assert s["step"] == bot.CHOOSING_LANGUAGE
    assert "scenario" not in s and "language" not in s
    assert s["photo"] == {"asset_id": "a1", "file": "ф.jpg"}
    assert s["voice_id"] == "voice-1"
    assert msg.replies[-1] == bot.ASK_LANGUAGE


def test_команда_new_делает_то_же_что_кнопка(work):
    bot.save_session(7, {
        "step": bot.DONE, "scenario": SCENARIO, "voice_id": "voice-1",
        "language": "ru",
    })

    msg = _Msg()
    asyncio.run(bot.cmd_new(_Update(msg), None))

    s = bot.load_session(7)
    assert s["step"] == bot.CHOOSING_LANGUAGE
    assert "scenario" not in s and "language" not in s
    assert s["voice_id"] == "voice-1"
    assert msg.replies[-1] == bot.ASK_LANGUAGE


def test_start_сбрасывает_язык_и_сценарий_но_не_фото_и_голос(work):
    bot.save_session(7, {"step": bot.REVIEW, "scenario": SCENARIO,
                         "photo": {"asset_id": "a1"}, "voice_id": "voice-1",
                         "language": "ru"})

    msg = _Msg()
    asyncio.run(bot.cmd_start(_Update(msg), None))

    s = bot.load_session(7)
    assert s["step"] == bot.CHOOSING_LANGUAGE
    assert "scenario" not in s and "language" not in s
    assert s["photo"] == {"asset_id": "a1"} and s["voice_id"] == "voice-1"
    assert msg.replies[-1] == bot.ASK_LANGUAGE


def test_after_new_язык_выбирается_до_пути(work):
    bot.save_session(7, {"step": bot.DONE, "voice_id": "voice-1"})
    msg = _Msg()
    asyncio.run(bot.cmd_new(_Update(msg), None))

    _press("reel_language:ru", msg)

    assert msg.replies[-1] == bot.HELLO
    assert _labels(msg.markups[-1]) == [
        "У меня готовый сценарий", "Предложи сценарий"
    ]


def test_new_отменяет_незавершённую_перезапись_и_возвращает_старый_голос(work):
    bot.save_session(7, {
        "step": bot.WAIT_VOICE,
        "language": "kk",
        "voices": {"ru": "voice-ru"},
        "pending_previous_voice": {
            "language": "kk",
            "voice_id": "voice-kk-old",
        },
    })

    asyncio.run(bot.cmd_new(_Update(_Msg()), None))

    s = bot.load_session(7)
    assert s["voices"] == {
        "ru": "voice-ru",
        "kk": "voice-kk-old",
    }
    assert "pending_previous_voice" not in s


def test_post_init_регистрирует_new_в_меню():
    зарегистрировано = {}

    class FakeBot:
        async def set_my_commands(self, commands):
            зарегистрировано["commands"] = commands

    class FakeApp:
        bot = FakeBot()

    asyncio.run(bot._post_init(FakeApp()))

    names = [c.command for c in зарегистрировано["commands"]]
    assert "new" in names


def test_post_init_без_tribute_key_громко_предупреждает_но_не_падает(
    work, monkeypatch, caplog
):
    """Fix 6: без TRIBUTE_API_KEY вебхук не поднимается, но кнопки пополнения
    остаются активны — Tribute всё равно спишет деньги пользователя и будет
    ретраить недоставленный вебхук ~сутки, после чего платёж зависает без
    ручной сверки. Бот не должен упасть, но обязан заметно предупредить."""
    monkeypatch.delenv("TRIBUTE_API_KEY", raising=False)

    class FakeBot:
        async def set_my_commands(self, commands):
            pass

    class FakeApp:
        bot = FakeBot()

    with caplog.at_level(logging.ERROR):
        asyncio.run(bot._post_init(FakeApp()))

    assert "TRIBUTE_API_KEY" in caplog.text


# --- шаг 5/6: профиль (фото + голос) -------------------------------------------

@pytest.fixture
def профиль(monkeypatch):
    """Внешние шаги профиля — без сети: HeyGen и ElevenLabs не зовём."""
    monkeypatch.setattr(bot, "_download", _fake_download)
    monkeypatch.setattr(bot, "step_photo", lambda chat_id, path: "asset-новый")
    monkeypatch.setattr(
        bot, "step_voice", lambda chat_id, path, language: "voice-1"
    )
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


def test_повторный_профиль_предлагает_выбор_фото(work, профиль):
    bot.save_session(7, {"step": bot.REVIEW, "scenario": SCENARIO,
                         "photo": {"asset_id": "asset-старый", "file": "старый.jpg"},
                         "voice_id": "voice-1"})

    _press("ok", _Msg())

    assert bot.load_session(7)["step"] == bot.CHOOSING_PHOTO


def test_прежнее_фото_ведёт_к_выбору_голоса(work, профиль):
    bot.save_session(7, {"step": bot.CHOOSING_PHOTO, "scenario": SCENARIO,
                         "photo": {"asset_id": "asset-старый", "file": "старый.jpg"},
                         "voice_id": "voice-1"})

    msg = _Msg()
    _press("photo:old", msg)

    s = bot.load_session(7)
    assert s["step"] == bot.CHOOSING_VOICE
    assert s["photo"]["asset_id"] == "asset-старый"


def test_новое_фото_затирает_старое_в_сессии_и_на_диске(work, профиль, tmp_path):
    старое_фото = tmp_path / "старое.jpg"
    старое_фото.write_bytes(b"old")
    bot.save_session(7, {"step": bot.WAIT_PHOTO, "scenario": SCENARIO,
                         "photo": {"asset_id": "asset-старый", "file": str(старое_фото)},
                         "voice_id": "voice-1"})

    msg = _Msg(photo=[object()])
    asyncio.run(bot.on_message(_Update(msg), None))

    s = bot.load_session(7)
    assert s["photo"]["asset_id"] == "asset-новый"
    assert s["step"] == bot.CHOOSING_VOICE  # голос уже был — предложат выбор
    assert not старое_фото.exists()


def test_голос_спрашивается_один_раз(work, профиль):
    bot.save_session(7, {"step": bot.WAIT_PHOTO, "scenario": SCENARIO})

    msg = _Msg(photo=[object()])
    asyncio.run(bot.on_message(_Update(msg), None))
    assert bot.load_session(7)["step"] == bot.WAIT_VOICE

    голос = _Msg(voice=object())
    asyncio.run(bot.on_message(_Update(голос), None))
    s = bot.load_session(7)
    assert s["voice_id"] == "voice-1" and s["step"] == bot.READY


def test_использовать_прежнюю_запись_ведёт_к_готовности(work, профиль):
    bot.save_session(7, {"step": bot.CHOOSING_VOICE, "scenario": SCENARIO,
                         "photo": {"asset_id": "a1", "file": "ф.jpg"}, "voice_id": "voice-1"})

    msg = _Msg()
    _press("voice:old", msg)

    s = bot.load_session(7)
    assert s["step"] == bot.READY and s["voice_id"] == "voice-1"
    assert msg.replies[-1] == bot.READY_MSG
    assert "Создать ролик" in _labels(msg.markups[-1])


def test_записать_заново_удаляет_старый_клон_и_просит_новую_запись(work, monkeypatch):
    удалённые = []
    monkeypatch.setattr(bot, "step_delete_voice", lambda vid: удалённые.append(vid))
    bot.save_session(7, {"step": bot.CHOOSING_VOICE, "scenario": SCENARIO,
                         "photo": {"asset_id": "a1", "file": "ф.jpg"},
                         "voice_id": "voice-старый"})

    msg = _Msg()
    _press("voice:new", msg)

    assert удалённые == []  # удалим только после успешного сохранения нового
    s = bot.load_session(7)
    assert s["step"] == bot.WAIT_VOICE and "voice_id" not in s
    assert s["pending_previous_voice"]["voice_id"] == "voice-старый"
    assert bot.ASK_VOICE in msg.replies[-1]


def test_записать_заново_чистит_voice_id_в_профиле_клиента(work, monkeypatch):
    monkeypatch.setattr(bot, "step_delete_voice", lambda vid: None)
    вызовы = []
    monkeypatch.setattr(
        bot,
        "clear_client_voice_profile",
        lambda chat_id, language: вызовы.append((chat_id, language)),
    )
    bot.save_session(7, {"step": bot.CHOOSING_VOICE, "voice_id": "voice-старый"})

    _press("voice:new", _Msg())

    assert вызовы == [(7, "ru")]


def test_ошибка_удаления_старого_голоса_не_блокирует_запись(work, monkeypatch):
    def падаем(vid):
        raise RuntimeError("сеть упала")

    monkeypatch.setattr(bot, "step_delete_voice", падаем)
    bot.save_session(7, {"step": bot.CHOOSING_VOICE, "voice_id": "voice-старый"})

    msg = _Msg()
    _press("voice:new", msg)
    assert bot.load_session(7)["step"] == bot.WAIT_VOICE


def test_ошибка_удаления_старого_голоса_логируется(work, monkeypatch, caplog):
    def падаем(vid):
        raise RuntimeError("сеть упала")

    monkeypatch.setattr(bot, "step_delete_voice", падаем)
    bot.save_session(7, {"step": bot.CHOOSING_VOICE, "voice_id": "voice-старый"})

    _press("voice:new", _Msg())
    s = bot.load_session(7)
    s["voices"] = {"ru": "voice-новый"}
    s["voice_id"] = "voice-новый"
    s["voice_language"] = "ru"
    s["photo"] = {"asset_id": "a1"}
    bot.save_session(7, s)
    monkeypatch.setattr(bot, "save_client_profile", lambda chat_id, session: None)
    with caplog.at_level(logging.WARNING):
        asyncio.run(bot._finish_voice(_Msg(), 7, s))

    assert "voice-старый" in caplog.text
    assert "сеть упала" in caplog.text


def test_сбой_движка_не_роняет_разговор(work, monkeypatch):
    def падаем(chat_id, text, language):
        raise RuntimeError("claude -p упал")

    monkeypatch.setattr(bot, "step_verbatim", падаем)
    bot.save_session(7, {"step": bot.WAIT_TEXT})

    msg = _Msg("Мой текст.")
    asyncio.run(bot.on_message(_Update(msg), None))

    assert "claude -p упал" in msg.replies[-1]
    assert bot.load_session(7)["step"] == bot.WAIT_TEXT


def _ожидаемое_списание_клода(usd: float) -> int:
    from reels_factory.billing import apply_markup, claude_cost_micro
    cfg = bot._billing()
    return apply_markup(claude_cost_micro(usd), cfg["markup"])


def test_провал_step_verbatim_после_ретраев_всё_равно_списывает_клода(
    work, monkeypatch
):
    """Fix 1: раньше _charge_claude звался ТОЛЬКО после успешного возврата.
    scenario.py поднимает ScenarioError после исчерпанных ретраев — а ретраи
    жгут Клода больше, чем успех. Такой провал должен списаться так же, как
    и успех, иначе трата остаётся вне журнала."""
    def fake_run_verbatim_path(workdir, text, runner, language):
        runner.total_cost_usd = 0.04  # деньги на Клод уже потрачены
        raise bot.ScenarioError("исчерпаны ретраи (2): судья не пропустил")

    monkeypatch.setattr(bot, "run_verbatim_path", fake_run_verbatim_path)

    with pytest.raises(bot.ScenarioError):
        bot.step_verbatim(7, "текст", "ru")

    assert bot._ledger().balance(7) == -_ожидаемое_списание_клода(0.04)


def test_провал_step_ideas_после_ретраев_всё_равно_списывает_клода(
    work, monkeypatch
):
    def fake_run_ideas(workdir, text, runner, language):
        runner.total_cost_usd = 0.02
        raise bot.ScenarioError("ожидалось 2-3 идеи, получено: []")

    monkeypatch.setattr(bot, "run_ideas", fake_run_ideas)

    with pytest.raises(bot.ScenarioError):
        bot.step_ideas(7, "сырьё", "ru")

    assert bot._ledger().balance(7) == -_ожидаемое_списание_клода(0.02)


def test_провал_step_scenario_после_ретраев_всё_равно_списывает_клода(
    work, monkeypatch
):
    def fake_run_generated_path(workdir, idea, runner, language):
        runner.total_cost_usd = 0.03
        raise bot.ScenarioError("целостность после полировки: [...]")

    monkeypatch.setattr(bot, "run_generated_path", fake_run_generated_path)

    with pytest.raises(bot.ScenarioError):
        bot.step_scenario(7, {"idea": "тема"}, "ru")

    assert bot._ledger().balance(7) == -_ожидаемое_списание_клода(0.03)


# --- шаг 7/8: готовность и повторный цикл --------------------------------------

def _client_base_cfg(**over):
    """Минимальный валидный конфиг-шаблон под profile-фикстуры (формат avatar)."""
    b = {
        "theme": "Тема", "format": "avatar", "voice_id": "voice-1",
        "language": "ru",
        "voice_language": "ru",
        "voices": {"ru": "voice-1"},
        "persona": {"description": "ведущий"},
        "product": {"name": "Продукт", "cta_phrase": "подпишись"},
        "avatar": {},
    }
    b.update(over)
    return b


@pytest.fixture
def клиент(work, tmp_path, monkeypatch):
    """Изолированный реестр клиентов + готовый профиль клиента чата 7.
    save_client_profile сам по себе читает общий factory/config.yaml как базу —
    в тестах его нет и не нужен, профиль уже зарегистрирован напрямую.
    Баланс пополняем с запасом: billing включён по умолчанию (Task 7 проверяет
    его в enqueue_build), а фикстуре нужен клиент, готовый платить, а не
    отдельный тест на нехватку денег — для того есть test_нехватки_баланса."""
    monkeypatch.setattr(clients_mod, "CLIENTS_DIR", tmp_path / "clients")
    monkeypatch.setattr(bot, "save_client_profile", lambda chat_id, s: None)
    clients_mod.register_client("7", _client_base_cfg(), voice_id="voice-1",
                                asset_id="asset-1")
    bot._ledger().credit(
        7, 1_000_000_000,
        purchase_id="клиент-fixture", amount_minor=1_000_000_00, currency="usd",
    )
    return tmp_path


def test_создать_ролик_сохраняет_профиль_и_ставит_job_в_очередь(work, клиент, monkeypatch):
    вызовы = []
    monkeypatch.setattr(bot, "save_client_profile", lambda chat_id, s: вызовы.append(chat_id))
    bot.save_session(7, {"step": bot.READY, "scenario": SCENARIO,
                         "photo": {"asset_id": "a1", "file": "ф.jpg"}, "voice_id": "voice-1"})

    msg = _Msg()
    _press("build", msg)

    assert вызовы == [7]
    s = bot.load_session(7)
    assert s["step"] == bot.BUILDING
    assert s["current_job_id"]
    assert bot.BUILDING_MSG in msg.replies[-1]
    assert not msg.videos
    job = bot._job_store().get(s["current_job_id"])
    assert job.status == "queued"
    assert (job.workdir / "scenario.json").exists()


# --- шаг 9: сборка ролика ------------------------------------------------------

def test_run_build_зовёт_make_через_subprocess(tmp_path, monkeypatch):
    вызовы = {}

    class Completed:
        stdout = json.dumps({"ok": True, "mp4": "x", "qa_pass": True})
        stderr = ""

    def fake_run(cmd, **kw):
        вызовы["cmd"] = cmd
        return Completed()

    monkeypatch.setattr(bot.subprocess, "run", fake_run)
    wd = tmp_path / "wd"

    result = bot.run_build(7, wd)

    assert вызовы["cmd"] == [bot.sys.executable, "-m", "reels_factory", "make",
                             "--workdir", str(wd), "--client", "7"]
    assert result == {"ok": True, "mp4": "x", "qa_pass": True}


def test_run_build_для_новой_job_использует_immutable_config(tmp_path, monkeypatch):
    вызовы = {}

    class Completed:
        stdout = json.dumps({"ok": True, "mp4": "x", "qa_pass": True})
        stderr = ""

    wd = tmp_path / "wd"
    wd.mkdir()
    snapshot = wd / "build-config.yaml"
    snapshot.write_text("language: kk", encoding="utf-8")

    def fake_run(cmd, **kw):
        вызовы["cmd"] = cmd
        return Completed()

    monkeypatch.setattr(bot.subprocess, "run", fake_run)
    result = bot.run_build(7, wd)

    assert вызовы["cmd"] == [
        bot.sys.executable, "-m", "reels_factory", "make",
        "--workdir", str(wd), "--config", str(snapshot),
    ]
    assert result["ok"] is True


def test_job_snapshot_не_меняется_после_смены_профиля(
        work, клиент, monkeypatch):
    import yaml

    scenario = {**SCENARIO, "language": "ru"}
    job = bot.enqueue_build(
        7, scenario, language="ru", voice_id="voice-1"
    )

    clients_mod.register_client(
        "7",
        _client_base_cfg(
            language="kk",
            voice_language="kk",
            voices={"kk": "voice-2"},
        ),
        voice_id="voice-2",
        asset_id="asset-2",
        overwrite=True,
    )

    snapshot = yaml.safe_load(
        (job.workdir / "build-config.yaml").read_text(encoding="utf-8")
    )
    input_doc = json.loads(
        (job.workdir / "job.input.json").read_text(encoding="utf-8")
    )
    assert snapshot["language"] == "ru"
    assert snapshot["voice_id"] == "voice-1"
    assert snapshot["tts"]["language_code"] == "ru"
    assert input_doc["language"] == "ru"


def test_run_build_невалидный_json_превращается_в_ошибку(tmp_path, monkeypatch):
    class Completed:
        stdout = "Traceback (most recent call last): ..."
        stderr = "boom"

    monkeypatch.setattr(bot.subprocess, "run", lambda cmd, **kw: Completed())

    result = bot.run_build(7, tmp_path / "wd")

    assert result["ok"] is False
    assert "boom" in result["error"]


def test_run_build_разбирает_json_среди_шума_рендера(tmp_path, monkeypatch):
    """node/vite-рендер пишет свой вывод в stdout движка ДО финального JSON —
    реальный кейс первого платного прогона: успешная сборка выглядела провалом."""
    class Completed:
        stdout = ("Render progress, worker 0: 99%\n"
                  "Rendered video to C:\\work\\reel.mp4\n"
                  + json.dumps({"ok": True, "mp4": "x", "qa_pass": True}) + "\n")
        stderr = "[make] assemble"

    monkeypatch.setattr(bot.subprocess, "run", lambda cmd, **kw: Completed())

    result = bot.run_build(7, tmp_path / "wd")

    assert result == {"ok": True, "mp4": "x", "qa_pass": True}


def test_run_build_логирует_stderr_движка_даже_при_успехе(tmp_path, monkeypatch, caplog):
    """До фикса run_build читал p.stderr только на ветке разбора неудачного
    JSON — оба денежных предупреждения (_build_meter, _billable_seconds)
    пишутся в stderr движка и терялись при успешной сборке, потому что их
    никто не читал. Теперь стадийные логи и предупреждения обязаны попасть
    в логгер бота, даже если сборка ok."""
    class Completed:
        stdout = json.dumps({"ok": True, "mp4": "x", "qa_pass": True})
        stderr = ("[make] job.input.json повреждён, учёт трат отключён: "
                   "boom\n[make] assemble")

    monkeypatch.setattr(bot.subprocess, "run", lambda cmd, **kw: Completed())

    with caplog.at_level(logging.WARNING):
        result = bot.run_build(7, tmp_path / "wd")

    assert result == {"ok": True, "mp4": "x", "qa_pass": True}
    assert "job.input.json повреждён" in caplog.text
    assert "[make] assemble" in caplog.text


def test_профиль_клиента_готов(tmp_path, monkeypatch):
    monkeypatch.setattr(clients_mod, "CLIENTS_DIR", tmp_path / "clients")
    clients_mod.register_client("7", _client_base_cfg(), voice_id="voice-1", asset_id="asset-1")
    assert bot.client_profile_ready(7) is True


def test_save_client_profile_сохраняет_голоса_обоих_языков_и_активирует_текущий(
        tmp_path, monkeypatch):
    monkeypatch.setattr(clients_mod, "CLIENTS_DIR", tmp_path / "clients")
    monkeypatch.setattr(bot, "load_config", lambda: _client_base_cfg())
    session = {
        "language": "kk",
        "photo": {"asset_id": "asset-1"},
        "voices": {"ru": "voice-ru", "kk": "voice-kk"},
    }

    bot.save_client_profile(7, session)

    cfg = clients_mod.load_client("7")
    assert cfg["language"] == "kk"
    assert cfg["voice_language"] == "kk"
    assert cfg["voice_id"] == "voice-kk"
    assert cfg["voices"] == {"ru": "voice-ru", "kk": "voice-kk"}
    assert cfg["tts"]["language_code"] == "kk"


def test_профиль_клиента_без_файла_не_готов(tmp_path, monkeypatch):
    monkeypatch.setattr(clients_mod, "CLIENTS_DIR", tmp_path / "clients")
    assert bot.client_profile_ready(7) is False


def test_профиль_клиента_без_voice_id_не_готов(tmp_path, monkeypatch):
    # ровно сценарий из спеки: голос не склонировался/удалён — clear_client_voice
    # чистит voice_id, но профиль остаётся на диске
    monkeypatch.setattr(clients_mod, "CLIENTS_DIR", tmp_path / "clients")
    clients_mod.register_client("7", _client_base_cfg(), voice_id="voice-1", asset_id="asset-1")
    clients_mod.clear_client_voice("7")
    assert bot.client_profile_ready(7) is False


def test_нет_профиля_клиента_честно_говорит_и_не_запускает_сборку(work, tmp_path, monkeypatch):
    monkeypatch.setattr(clients_mod, "CLIENTS_DIR", tmp_path / "clients")
    monkeypatch.setattr(bot, "save_client_profile", lambda chat_id, s: None)
    вызвано = []
    monkeypatch.setattr(bot, "run_build", lambda chat_id, workdir: вызвано.append(1))
    bot.save_session(7, {"step": bot.READY, "scenario": SCENARIO,
                         "photo": {"asset_id": "a1", "file": "ф.jpg"}, "voice_id": "voice-1"})

    msg = _Msg()
    _press("build", msg)

    assert msg.replies[-1] == bot.CLIENT_NOT_FOUND_MSG
    assert вызвано == []
    assert bot.load_session(7)["step"] != bot.DONE


def test_устаревшая_кнопка_создать_ролик_на_шаге_done_не_запускает_сборку(
        work, клиент, monkeypatch):
    # инлайн-кнопки живут в истории чата вечно: тап по старому READY-сообщению
    # после DONE не должен зазывать платную сборку заново
    вызвано = []
    monkeypatch.setattr(bot, "run_build", lambda chat_id, workdir: вызвано.append(1))
    bot.save_session(7, {"step": bot.DONE, "scenario": SCENARIO,
                         "photo": {"asset_id": "a1", "file": "ф.jpg"}, "voice_id": "voice-1"})

    msg = _Msg()
    _press("build", msg)

    assert вызвано == []
    assert msg.replies == [bot.NOT_NOW]


def test_устаревшая_кнопка_создать_ролик_на_шаге_choosing_не_запускает_сборку(
        work, клиент, monkeypatch):
    вызвано = []
    monkeypatch.setattr(bot, "run_build", lambda chat_id, workdir: вызвано.append(1))
    bot.save_session(7, {"step": bot.CHOOSING})

    msg = _Msg()
    _press("build", msg)

    assert вызвано == []
    assert msg.replies == [bot.NOT_NOW]


def test_сбой_save_client_profile_не_роняет_бота(work, tmp_path, monkeypatch):
    # битый/отсутствующий factory/config.yaml — save_client_profile может
    # бросить ConfigError, пользователь должен получить честный ответ, а не тишину
    monkeypatch.setattr(clients_mod, "CLIENTS_DIR", tmp_path / "clients")

    def падаем(chat_id, s):
        raise ConfigError("битый config.yaml")

    monkeypatch.setattr(bot, "save_client_profile", падаем)
    вызвано = []
    monkeypatch.setattr(bot, "run_build", lambda chat_id, workdir: вызвано.append(1))
    bot.save_session(7, {"step": bot.READY, "scenario": SCENARIO,
                         "photo": {"asset_id": "a1", "file": "ф.jpg"}, "voice_id": "voice-1"})

    msg = _Msg()
    _press("build", msg)

    assert msg.replies[-1] == bot.CLIENT_NOT_FOUND_MSG
    assert вызвано == []


def test_повторное_нажатие_создать_ролик_пока_сборка_идёт(work, клиент):
    bot._job_store().enqueue(7)
    bot.save_session(7, {"step": bot.READY, "scenario": SCENARIO,
                         "photo": {"asset_id": "a1", "file": "ф.jpg"}, "voice_id": "voice-1"})
    msg = _Msg()
    _press("build", msg)
    assert msg.replies == [bot.BUSY_MSG]
    assert not msg.videos


def test_ролик_шлётся_с_явными_размерами_кадра(work, клиент, monkeypatch):
    """Без width/height телеграм-плеер не знает размеров до полной загрузки
    и показывает вертикальный ролик квадратом (реальный кейс первого прогона)."""
    def fake_run_build(chat_id, workdir):
        (workdir / "reel.mp4").write_bytes(b"x")
        return {"ok": True, "mp4": str(workdir / "reel.mp4"), "qa_pass": True}

    bot.save_session(7, {"step": bot.READY, "scenario": SCENARIO,
                         "photo": {"asset_id": "a1", "file": "ф.jpg"}, "voice_id": "voice-1"})
    _press("build", _Msg())
    api = _BotAPI()

    asyncio.run(bot._process_job(api, _claim_job(), build_fn=fake_run_build))

    assert api.videos
    assert (api.videos[-1]["width"], api.videos[-1]["height"]) == (bot.OUT_W, bot.OUT_H)


def test_сценарий_пишется_в_job_workdir_с_uuid(work, клиент):
    bot.save_session(7, {"step": bot.READY, "scenario": SCENARIO,
                         "photo": {"asset_id": "a1", "file": "ф.jpg"}, "voice_id": "voice-1"})

    _press("build", _Msg())

    job = bot._job_store().latest_for_chat(7)
    assert job.workdir.parent == bot.WORK_ROOT / "jobs"
    assert job.workdir.name == job.job_id
    assert len(job.job_id) == 32
    saved = json.loads((job.workdir / "scenario.json").read_text(encoding="utf-8"))
    assert saved == {**SCENARIO, "language": "ru"}
    assert (job.workdir / "job.input.json").exists()
    assert (job.workdir / "build-config.yaml").exists()


def test_сбой_сборки_сообщается_человеческим_текстом(work, клиент, monkeypatch):
    bot.save_session(7, {"step": bot.READY, "scenario": SCENARIO,
                         "photo": {"asset_id": "a1", "file": "ф.jpg"}, "voice_id": "voice-1"})
    _press("build", _Msg())
    job = _claim_job()
    api = _BotAPI()

    asyncio.run(bot._process_job(
        api, job, build_fn=lambda chat_id, workdir:
        {"ok": False, "stage": "voice", "error": "HeyGen 500"}
    ))

    assert "HeyGen 500" in api.messages[-1][1]
    assert not api.videos
    assert bot._job_store().get(job.job_id).status == "failed"
    assert bot.load_session(7)["step"] == bot.BUILD_FAILED


def test_исключение_при_сборке_не_роняет_бота(work, клиент, monkeypatch):
    def падаем(chat_id, workdir):
        raise RuntimeError("subprocess не поднялся")

    bot.save_session(7, {"step": bot.READY, "scenario": SCENARIO,
                         "photo": {"asset_id": "a1", "file": "ф.jpg"}, "voice_id": "voice-1"})
    _press("build", _Msg())
    job = _claim_job()
    api = _BotAPI()

    asyncio.run(bot._process_job(api, job, build_fn=падаем))

    assert "subprocess не поднялся" in api.messages[-1][1]
    assert bot._job_store().get(job.job_id).status == "failed"


def test_ролик_собран_но_qa_не_пройден_не_отправляется(work, клиент):
    def fake_run_build(chat_id, workdir):
        (workdir / "reel.mp4").write_bytes(b"x")
        return {"ok": True, "mp4": str(workdir / "reel.mp4"), "qa_pass": False}

    bot.save_session(7, {"step": bot.READY, "scenario": SCENARIO,
                         "photo": {"asset_id": "a1", "file": "ф.jpg"}, "voice_id": "voice-1"})
    _press("build", _Msg())
    job = _claim_job()
    api = _BotAPI()

    asyncio.run(bot._process_job(api, job, build_fn=fake_run_build))

    assert not api.videos
    assert bot.QA_FAIL_MSG in api.messages[-1][1]
    assert bot._job_store().get(job.job_id).status == "qa_failed"
    assert bot.load_session(7)["step"] == bot.BUILD_FAILED


def test_ролик_больше_50мб_не_отправляется(work, клиент, monkeypatch):
    monkeypatch.setattr(bot, "MAX_TG_VIDEO_BYTES", 3)

    def fake_run_build(chat_id, workdir):
        (workdir / "reel.mp4").write_bytes(b"1234567890")
        return {"ok": True, "mp4": str(workdir / "reel.mp4"), "qa_pass": True}

    bot.save_session(7, {"step": bot.READY, "scenario": SCENARIO,
                         "photo": {"asset_id": "a1", "file": "ф.jpg"}, "voice_id": "voice-1"})
    _press("build", _Msg())
    job = _claim_job()
    api = _BotAPI()

    asyncio.run(bot._process_job(api, job, build_fn=fake_run_build))

    assert "50 МБ" in api.messages[-1][1]
    assert not api.videos
    assert bot._job_store().get(job.job_id).status == "delivery_failed"


def _зачесть_расход_на_job(job_id: str) -> None:
    """Сымитировать реальный платный шаг сборки: build-субпроцесс уже
    списал деньги через свой собственный LedgerStore до провала QA/доставки."""
    bot._ledger().charge(
        7, entry_id=f"heygen:{job_id}", job_id=job_id, provider="heygen",
        unit="seconds", quantity=10.0, unit_price_micro=50_000,
        cost_micro=500_000, charged_micro=1_000_000,
    )


def test_qa_провал_сообщает_сколько_уже_стоил_рендер(work, клиент):
    """Fix 8: build-субпроцесс уже списал деньги до провала QA — баланс
    просел, а бот раньше говорил только «остановлен проверкой качества»,
    не упоминая списание. Формулировка выровнена с квитанцией (Fix C):
    не «списано», а «стоил сам рендер» — без Клода, который тратится
    отдельно и в этот breakdown не входит."""
    def fake_run_build(chat_id, workdir):
        (workdir / "reel.mp4").write_bytes(b"x")
        return {"ok": True, "mp4": str(workdir / "reel.mp4"), "qa_pass": False}

    bot.save_session(7, {"step": bot.READY, "scenario": SCENARIO,
                         "photo": {"asset_id": "a1", "file": "ф.jpg"}, "voice_id": "voice-1"})
    _press("build", _Msg())
    job = _claim_job()
    _зачесть_расход_на_job(job.job_id)
    api = _BotAPI()

    asyncio.run(bot._process_job(api, job, build_fn=fake_run_build))

    assert "уже стоил" in api.messages[-1][1]
    assert "$1.00" in api.messages[-1][1]


def test_слишком_большой_файл_сообщает_сколько_уже_стоил_рендер(work, клиент, monkeypatch):
    monkeypatch.setattr(bot, "MAX_TG_VIDEO_BYTES", 3)

    def fake_run_build(chat_id, workdir):
        (workdir / "reel.mp4").write_bytes(b"1234567890")
        return {"ok": True, "mp4": str(workdir / "reel.mp4"), "qa_pass": True}

    bot.save_session(7, {"step": bot.READY, "scenario": SCENARIO,
                         "photo": {"asset_id": "a1", "file": "ф.jpg"}, "voice_id": "voice-1"})
    _press("build", _Msg())
    job = _claim_job()
    _зачесть_расход_на_job(job.job_id)
    api = _BotAPI()

    asyncio.run(bot._process_job(api, job, build_fn=fake_run_build))

    assert "уже стоил" in api.messages[-1][1]
    assert "$1.00" in api.messages[-1][1]


def test_отказ_telegram_принять_файл_сообщает_сколько_уже_стоил_рендер(
    work, клиент
):
    def fake_run_build(chat_id, workdir):
        (workdir / "reel.mp4").write_bytes(b"x")
        return {"ok": True, "mp4": str(workdir / "reel.mp4"), "qa_pass": True}

    class _ОтказывающийАпи(_BotAPI):
        async def send_video(self, chat_id, video, caption=None,
                             reply_markup=None, width=None, height=None):
            raise RuntimeError("Telegram отверг файл")

    bot.save_session(7, {"step": bot.READY, "scenario": SCENARIO,
                         "photo": {"asset_id": "a1", "file": "ф.jpg"}, "voice_id": "voice-1"})
    _press("build", _Msg())
    job = _claim_job()
    _зачесть_расход_на_job(job.job_id)
    api = _ОтказывающийАпи()

    asyncio.run(bot._process_job(api, job, build_fn=fake_run_build))

    assert "уже стоил" in api.messages[-1][1]
    assert "$1.00" in api.messages[-1][1]
    assert bot._job_store().get(job.job_id).status == "delivery_failed"


def test_qa_провал_с_битым_breakdown_всё_равно_доставляет_отказ(
    work, клиент, monkeypatch, caplog
):
    """Fix B: _charged_but_undelivered_notice раньше звалась вне защиты
    _safe_job_message — упавшее чтение SQLite (заблокирован/битый) роняло
    бы _process_job целиком, и пользователь не получил бы вообще ничего,
    хотя job уже finished и повторов не будет. Теперь чтение breakdown
    защищено само по себе: пустое уведомление, но голый текст отказа
    доходит."""
    def fake_run_build(chat_id, workdir):
        (workdir / "reel.mp4").write_bytes(b"x")
        return {"ok": True, "mp4": str(workdir / "reel.mp4"), "qa_pass": False}

    def падающий_breakdown(self, job_id):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(bot.LedgerStore, "job_breakdown", падающий_breakdown)

    bot.save_session(7, {"step": bot.READY, "scenario": SCENARIO,
                         "photo": {"asset_id": "a1", "file": "ф.jpg"}, "voice_id": "voice-1"})
    _press("build", _Msg())
    job = _claim_job()
    api = _BotAPI()

    with caplog.at_level(logging.WARNING):
        asyncio.run(bot._process_job(api, job, build_fn=fake_run_build))

    assert bot.QA_FAIL_MSG in api.messages[-1][1]
    assert "database is locked" in caplog.text


def test_успешная_доставка_с_битым_breakdown_всё_равно_обновляет_сессию(
    work, клиент, monkeypatch, caplog
):
    """Fix C: чтение breakdown вне защиты _safe_job_message — видео уже
    доставлено, повторов не будет. Раньше упавшее чтение SQLite (заблокирован/
    битый) роняло бы _process_job целиком, и сессия осталась бы в BUILDING,
    хотя пользователь уже получил ролик. Теперь чтение защищено: пропускаем
    чек, но обновление сессии гарантировано."""
    def fake_run_build(chat_id, workdir):
        (workdir / "reel.mp4").write_bytes(b"x")
        return {"ok": True, "mp4": str(workdir / "reel.mp4"), "qa_pass": True}

    def падающий_breakdown(self, job_id):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(bot.LedgerStore, "job_breakdown", падающий_breakdown)

    bot.save_session(7, {"step": bot.READY, "scenario": SCENARIO,
                         "photo": {"asset_id": "a1", "file": "ф.jpg"}, "voice_id": "voice-1"})
    _press("build", _Msg())
    job = _claim_job()
    _зачесть_расход_на_job(job.job_id)
    api = _BotAPI()

    with caplog.at_level(logging.WARNING):
        asyncio.run(bot._process_job(api, job, build_fn=fake_run_build))

    assert bot.load_session(7)["step"] == bot.DONE
    assert "database is locked" in caplog.text


def test_receipt_называет_сумму_рендером_а_не_общим_списанием(work, клиент):
    """Fix 7: _charge_claude пишет свои строки с job_id=None, поэтому
    job_breakdown никогда не содержит траты на подготовку сценария — сумма
    в квитанции не должна выдавать себя за «списано всего»."""
    def fake_run_build(chat_id, workdir):
        (workdir / "reel.mp4").write_bytes(b"x")
        return {"ok": True, "mp4": str(workdir / "reel.mp4"), "qa_pass": True}

    bot.save_session(7, {"step": bot.READY, "scenario": SCENARIO,
                         "photo": {"asset_id": "a1", "file": "ф.jpg"}, "voice_id": "voice-1"})
    _press("build", _Msg())
    job = _claim_job()
    _зачесть_расход_на_job(job.job_id)
    api = _BotAPI()

    asyncio.run(bot._process_job(api, job, build_fn=fake_run_build))

    text = api.messages[-1][1]
    assert "Списано" not in text  # больше не звучит как «итог за ролик»
    assert "рендер" in text.lower()
    assert "Баланс" in text
    assert "$1.00" in text


def test_сбой_статусного_сообщения_не_теряет_durable_job(work, клиент):
    """После INSERT job уже принадлежит очереди, даже если Telegram временно
    не принял служебное сообщение о постановке."""

    class FlakyMsg(_Msg):
        async def reply_text(self, text, reply_markup=None):
            if text.startswith(bot.BUILDING_MSG):
                raise RuntimeError("Telegram недоступен")
            await super().reply_text(text, reply_markup)

    bot.save_session(7, {"step": bot.READY, "scenario": SCENARIO,
                         "photo": {"asset_id": "a1", "file": "ф.jpg"}, "voice_id": "voice-1"})

    msg = FlakyMsg()
    _press("build", msg)

    job = bot._job_store().latest_for_chat(7)
    assert job.status == "queued"
    assert bot.load_session(7)["current_job_id"] == job.job_id


# --- биллинг: оценка до рендера и блокировка -----------------------------------

def test_форматирование_баланса():
    from reels_factory.bot import format_usd
    assert format_usd(3_184_000) == "$3.18"
    assert format_usd(0) == "$0.00"
    assert format_usd(-100_000) == "-$0.10"


def test_ledger_переиспользуется_между_вызовами(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import importlib
    from reels_factory import bot as bot_mod
    importlib.reload(bot_mod)
    assert bot_mod._ledger() is bot_mod._ledger()


def test_нехватки_баланса_достаточно_чтобы_не_создавать_job(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import importlib
    from reels_factory import bot as bot_mod
    importlib.reload(bot_mod)
    cfg = bot_mod._billing()
    from reels_factory.billing import estimate_micro
    need = estimate_micro(500, cfg["rates"], cfg["markup"])
    assert bot_mod._ledger().balance(777) < need


def test_нехватки_баланса_блокирует_enqueue_build_и_не_оставляет_workdir(work):
    """Настоящая проверка гварда: без денег enqueue_build должен и поднять
    InsufficientBalance с верными need/have, и не создать рабочую папку job —
    именно ради этого проверка баланса стоит в коде ДО workdir.mkdir."""
    chat_id = 777
    have = bot._ledger().balance(chat_id)
    assert have == 0  # свежий чат, начислений не было

    jobs_root = bot.WORK_ROOT / "jobs"
    assert not jobs_root.exists()  # до вызова папки job ещё нет

    with pytest.raises(bot.InsufficientBalance) as exc:
        bot.enqueue_build(chat_id, SCENARIO, language="ru", voice_id="voice-1")

    from reels_factory.billing import estimate_micro
    cfg = bot._billing()
    chars = sum(len(b["speech"]) for b in SCENARIO["blocks"])
    expected_need = estimate_micro(chars, cfg["rates"], cfg["markup"])

    assert exc.value.need == expected_need
    assert exc.value.have == have
    assert exc.value.need > exc.value.have

    # workdir так и не появился — отказ не оставил следов на диске.
    assert not jobs_root.exists()


def test_с_islands_оценка_меньше_и_хватает_там_где_без_них_не_хватит(
        work, tmp_path, monkeypatch):
    """Реальная проверка интеграции: аватар в кадре не весь ролик, если
    острова включены, значит оценка должна быть ниже. Баланс подобран строго
    между двумя оценками — со включёнными островами сборка проходит,
    без них тот же баланс не пропускает InsufficientBalance.
    master_audio тоже должен быть включён: run_make берёт island-путь только
    когда оба флага на (см. test_islands_без_master_audio_даёт_полную_оценку
    на случай, когда это не так)."""
    monkeypatch.setattr(clients_mod, "CLIENTS_DIR", tmp_path / "clients")
    monkeypatch.setattr(bot, "save_client_profile", lambda chat_id, s: None)
    clients_mod.register_client(
        "1", _client_base_cfg(), voice_id="voice-1", asset_id="asset-1",
    )
    clients_mod.register_client(
        "2",
        _client_base_cfg(
            avatar_islands={"enabled": True},
            master_audio={"enabled": True},
        ),
        voice_id="voice-1", asset_id="asset-1",
    )
    баланс = 350_000  # между оценкой без островов (~386k) и с ними (~303k)
    for chat_id in (1, 2):
        bot._ledger().credit(
            chat_id, баланс, purchase_id=f"islands-estimate-{chat_id}",
            amount_minor=баланс, currency="usd",
        )

    with pytest.raises(bot.InsufficientBalance):
        bot.enqueue_build(1, SCENARIO, language="ru", voice_id="voice-1")

    job = bot.enqueue_build(2, SCENARIO, language="ru", voice_id="voice-1")
    assert job.status == "queued"


def test_islands_без_master_audio_даёт_полную_оценку(work, tmp_path, monkeypatch):
    """Fix 5: run_make берёт island-путь только когда включены ОБА флага —
    avatar_islands и master_audio (см. pipeline.run_make). Профиль с
    islands включёнными, но master_audio выключенным, не может пойти по
    island-пути, значит оценка не должна притворяться, что может: тот же
    баланс, которого не хватает без островов вообще, не должен хватать и
    здесь."""
    monkeypatch.setattr(clients_mod, "CLIENTS_DIR", tmp_path / "clients")
    monkeypatch.setattr(bot, "save_client_profile", lambda chat_id, s: None)
    clients_mod.register_client(
        "3", _client_base_cfg(avatar_islands={"enabled": True}),
        voice_id="voice-1", asset_id="asset-1",
    )
    баланс = 350_000  # хватает только на урезанную (islands) оценку, не на полную
    bot._ledger().credit(
        3, баланс, purchase_id="islands-no-master-audio",
        amount_minor=баланс, currency="usd",
    )

    with pytest.raises(bot.InsufficientBalance):
        bot.enqueue_build(3, SCENARIO, language="ru", voice_id="voice-1")


def test_битые_avatar_islands_settings_не_ломают_оценку_при_enqueue_build(
        work, tmp_path, monkeypatch):
    """Fix 4: avatar_islands_enabled зовёт avatar_islands_settings, который
    поднимает голый ValueError для диапазонов, что load_config не проверяет
    (например min_request_seconds > max_shot_seconds). Раньше это ронялось
    прямо из enqueue_build общей ошибкой постановки в очередь; это только
    оценка ДО платного шага — она не должна мешать очереди вовсе, поэтому
    ожидаем откат на полную оценку и обычную InsufficientBalance, а не
    ValueError."""
    monkeypatch.setattr(clients_mod, "CLIENTS_DIR", tmp_path / "clients")
    monkeypatch.setattr(bot, "save_client_profile", lambda chat_id, s: None)
    clients_mod.register_client(
        "4",
        _client_base_cfg(
            avatar_islands={
                "enabled": True,
                "min_request_seconds": 20.0,
                "max_shot_seconds": 5.0,
            },
        ),
        voice_id="voice-1", asset_id="asset-1",
    )

    with pytest.raises(bot.InsufficientBalance):
        bot.enqueue_build(4, SCENARIO, language="ru", voice_id="voice-1")


def test_кнопки_пополнения_ведут_на_tribute():
    from reels_factory.bot import TOPUP_PRODUCTS, topup_keyboard
    assert len(TOPUP_PRODUCTS) == 7
    for label, url in TOPUP_PRODUCTS:
        # Только внутрителеграмная ссылка: с веб-страницы может прийти оплата
        # без telegram_user_id, и зачислить её будет некому.
        assert url.startswith("https://t.me/tribute/app?startapp=")
        assert "web.tribute.tg" not in url
        assert label
    rows = topup_keyboard().inline_keyboard
    urls = [btn.url for row in rows for btn in row if btn.url]
    assert len(urls) == 7


def test_текст_пополнения_при_нехватке_показывает_обе_суммы():
    from reels_factory.bot import topup_text
    text = topup_text(need=3_184_000, have=1_000_000)
    assert "$3.18" in text
    assert "$1.00" in text


def test_текст_пополнения_при_нехватке_помечает_сумму_как_ориентировочную():
    # Оценка до сборки — не точная цена: с avatar islands факт может быть
    # меньше. Пользователь должен видеть, что спишется по факту, а не ровно
    # показанную сумму.
    from reels_factory.bot import topup_text
    text = topup_text(need=3_184_000, have=1_000_000)
    assert "ориентировочн" in text.lower()


def test_текст_пополнения_без_нехватки_показывает_только_баланс():
    from reels_factory.bot import topup_text
    text = topup_text(need=None, have=1_000_000)
    assert "$1.00" in text
    assert "не хватает" not in text.lower()


# --- гейт: генерация сценария (Клод) блокируется при отрицательном балансе ----

def _charge_flat(chat_id: int, micro: int) -> None:
    """Загнать баланс в минус тестовым списанием — провайдер тут не важен."""
    bot._ledger().charge(
        chat_id,
        entry_id=f"test:{chat_id}:{micro}",
        job_id=None,
        provider="test",
        unit="usd",
        quantity=1,
        unit_price_micro=0,
        cost_micro=micro,
        charged_micro=micro,
    )


def test_отрицательный_баланс_блокирует_готовый_текст(work):
    _charge_flat(7, 1)  # -0.000001$, но уже < 0 — этого достаточно для гейта
    bot.save_session(7, {"step": bot.WAIT_TEXT, "language": "ru"})

    msg = _Msg("Мой текст.")
    asyncio.run(bot.on_message(_Update(msg), None))

    assert "исчерпан" in msg.replies[-1].lower()
    assert len(msg.markups[-1].inline_keyboard) == len(bot.TOPUP_PRODUCTS)
    assert bot.WORKING not in msg.replies  # генерация не запускалась
    assert bot.load_session(7)["step"] == bot.WAIT_TEXT  # шаг не сдвинулся


def test_отрицательный_баланс_блокирует_сырьё(work):
    _charge_flat(7, 1)
    bot.save_session(7, {"step": bot.WAIT_RAW, "language": "ru"})

    msg = _Msg("Длинное сырьё про продажи.")
    asyncio.run(bot.on_message(_Update(msg), None))

    assert "исчерпан" in msg.replies[-1].lower()
    assert bot.WORKING not in msg.replies
    assert bot.load_session(7)["step"] == bot.WAIT_RAW


def test_отрицательный_баланс_блокирует_выбор_идеи(work):
    _charge_flat(7, 1)
    bot.save_session(7, {
        "step": bot.CHOOSING_IDEA, "language": "ru",
        "ideas": [{"idea": "Раз", "draft_hook": "Хук раз"}],
    })

    msg = _Msg()
    _press("idea:0", msg)

    assert "исчерпан" in msg.replies[-1].lower()
    assert bot.WORKING not in msg.replies
    assert bot.load_session(7)["step"] == bot.CHOOSING_IDEA


def test_нулевой_баланс_не_блокирует_пробную_генерацию(work, monkeypatch):
    """Ровно 0 — старт бесплатного триала, не «уже потрачено больше, чем было».
    Порог намеренно «< 0», а не «<= 0»: тут регрессия сломала бы пробу новичку."""
    monkeypatch.setattr(
        bot, "step_verbatim", lambda chat_id, text, language: SCENARIO
    )
    assert bot._ledger().balance(7) == 0
    bot.save_session(7, {"step": bot.WAIT_TEXT, "language": "ru"})

    msg = _Msg("Мой текст.")
    asyncio.run(bot.on_message(_Update(msg), None))

    assert msg.replies[0] == bot.WORKING
    assert bot.load_session(7)["step"] == bot.REVIEW


def test_биллинг_выключен_не_блокирует_даже_при_минусе(work, monkeypatch):
    _charge_flat(7, 1)
    billing_on = bot._billing()
    monkeypatch.setattr(bot, "_billing", lambda: {**billing_on, "enabled": False})
    monkeypatch.setattr(
        bot, "step_verbatim", lambda chat_id, text, language: SCENARIO
    )
    bot.save_session(7, {"step": bot.WAIT_TEXT, "language": "ru"})

    msg = _Msg("Мой текст.")
    asyncio.run(bot.on_message(_Update(msg), None))

    assert msg.replies[0] == bot.WORKING
    assert bot.load_session(7)["step"] == bot.REVIEW
