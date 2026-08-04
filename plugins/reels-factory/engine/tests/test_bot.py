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
        self.message_id = 1
        self.photo = photo
        self.voice = voice
        self.audio = self.video = self.video_note = self.document = None
        self.replies = []
        self.markups = []
        self.kinds = []      # 'reply' — новое сообщение, 'edit' — правка на месте
        self.videos = []

    async def reply_text(self, text, reply_markup=None):
        self.replies.append(text)
        self.markups.append(reply_markup)
        self.kinds.append("reply")
        sent = _Msg(chat_id=self.chat_id)
        sent.message_id = 100 + len(self.replies)
        return sent

    async def edit_text(self, text, reply_markup=None):
        """Правка сообщения на месте: экран меняется, нового сообщения нет."""
        self.text = text
        self.replies.append(text)
        self.markups.append(reply_markup)
        self.kinds.append("edit")

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
        self.audios = []

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

    async def send_audio(self, chat_id, audio, caption=None, reply_markup=None,
                         title=None):
        self.audios.append({
            "chat_id": chat_id,
            "bytes": audio.read(),
            "caption": caption,
            "reply_markup": reply_markup,
            "title": title,
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


def _паспорт(**over):
    """Сессия, где всё бесплатное уже собрано: язык, фото, голос языка."""
    s = {
        "language": "ru",
        "photo": {"asset_id": "asset-1", "file": "фото.jpg"},
        "voices": {"ru": "voice-1"},
        "voice_id": "voice-1",
        "voice_language": "ru",
    }
    s.update(over)
    return s


def _пополнить(chat_id: int, micro: int) -> None:
    """Зачислить баланс так же, как это делает вебхук Tribute."""
    bot._ledger().credit(
        chat_id,
        micro,
        purchase_id=f"test-topup:{chat_id}:{micro}",
        amount_minor=micro // 10_000,
        currency="usd",
    )


def _с_балансом(chat_id: int = 7, множитель: float = 3.0) -> None:
    """Баланса заведомо хватает на любую оценку ролика."""
    billing = bot._billing()
    need = bot.estimate_material_micro({"material_mode": "raw"}, billing)
    _пополнить(chat_id, int(need * множитель))


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


def _старая_сессия(chat_id: int, data: dict) -> None:
    """Файл сессии прежнего порядка шагов — без метки flow."""
    d = bot.session_dir(chat_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "session.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )


def test_сессия_прежнего_порядка_не_теряет_фото_голос_и_сценарий(work):
    """Порядок шагов поменялся, а оплаченное — нет: клоны голоса, фото и
    сценарий остаются, двигается только позиция в разговоре."""
    _старая_сессия(7, {
        "step": "choosing_photo",          # экрана с таким шагом больше нет
        "language": "ru",
        "scenario": SCENARIO,
        "photo": {"asset_id": "a1", "file": "ф.jpg"},
        "voices": {"ru": "voice-1", "kk": "voice-kk"},
        "voice_id": "voice-1",
        "voice_language": "ru",
    })

    s = bot.load_session(7)

    assert s["step"] == bot.CHOOSING
    assert s["voices"] == {"ru": "voice-1", "kk": "voice-kk"}
    assert s["photo"] == {"asset_id": "a1", "file": "ф.jpg"}
    assert s["scenario"] == SCENARIO


def test_сессия_прежнего_порядка_без_языка_ведёт_к_выбору_языка(work):
    _старая_сессия(7, {"step": "wait_text"})

    assert bot.load_session(7)["step"] == bot.CHOOSING_LANGUAGE


def test_миграция_не_трогает_разговор_с_оплаченной_сборкой(work):
    """Job уже оплачена и ждёт решения — сдвинуть шаг значит потерять её."""
    _старая_сессия(7, {
        "step": bot.AUDIO_REVIEW,
        "language": "ru",
        "current_job_id": "job-1",
    })

    s = bot.load_session(7)

    assert s["step"] == bot.AUDIO_REVIEW and s["current_job_id"] == "job-1"


def test_новый_чат_ведёт_к_выбору_языка(work):
    msg = _Msg("привет")
    asyncio.run(bot.on_message(_Update(msg), None))
    assert msg.replies == [bot.HELLO, bot.ASK_LANGUAGE]


def test_текст_вместо_кнопки_показывает_экран_заново(work):
    """Кнопки уезжают вверх по переписке — повторить экран полезнее отписки."""
    bot.save_session(7, _паспорт(step=bot.CHOOSING))

    msg = _Msg("ну давай уже")
    asyncio.run(bot.on_message(_Update(msg), None))

    assert msg.replies[-1] == bot.ASK_PATH
    assert _labels(msg.markups[-1]) == [
        "У меня готовый сценарий", "Сгенерировать сценарий"
    ]


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


def test_после_выбора_казахского_новичка_просят_фото(work):
    asyncio.run(bot.cmd_start(_Update(_Msg()), None))
    msg = _Msg()

    _press("reel_language:kk", msg)

    s = bot.load_session(7)
    assert s["language"] == "kk"
    assert s["step"] == bot.WAIT_PHOTO
    assert "AI-аватара" in msg.replies[-1]


def test_выбор_пути_открывается_после_фото_и_голоса(work):
    bot.save_session(7, _паспорт(step=bot.CHOOSING_LANGUAGE))
    msg = _Msg()

    _press("reel_language:ru", msg)
    _press("profile:keep", msg)

    assert bot.load_session(7)["step"] == bot.CHOOSING
    assert msg.replies[-1] == bot.ASK_PATH
    assert _labels(msg.markups[-1]) == [
        "У меня готовый сценарий", "Сгенерировать сценарий"
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
    monkeypatch.setattr(bot, "save_client_profile", lambda chat_id, s: None)
    _с_балансом()
    bot.save_session(7, _паспорт(
        step=bot.WAIT_TEXT,
        language="kk",
        voices={"kk": "voice-kk"},
        voice_id="voice-kk",
        voice_language="kk",
    ))
    msg = _Msg(
        "Бұл қазақша дайын сценарий және біз оны жаңа ролик үшін "
        "қолданғымыз келеді."
    )

    asyncio.run(bot.on_message(_Update(msg), None))
    assert calls == []  # до экрана цены Клод не зовётся

    _press("pay:go", msg)

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
    bot.save_session(7, _паспорт(
        step=bot.DONE,
        voices={"ru": "voice-ru"},
        voice_id="voice-ru",
    ))

    asyncio.run(bot.cmd_new(_Update(_Msg()), None))
    ask = _Msg()
    _press("reel_language:kk", ask)

    selected = bot.load_session(7)
    assert selected["voices"] == {"ru": "voice-ru"}
    assert "voice_id" not in selected and "voice_language" not in selected
    # язык отмечен галочкой на месте; дальше по «Вперёд» — фото и голос
    assert selected["step"] == bot.VIEWING_STAGE and selected["stage"] == "language"
    assert "🇰🇿 Қазақша ✅" in _labels(ask.markups[-1])
    _press("stage:next", ask)   # фото уже есть
    _press("stage:next", ask)   # казахской записи нет — просят её
    assert bot.load_session(7)["step"] == bot.WAIT_VOICE
    assert "🇰🇿 Қазақша" in ask.replies[-1]

    asyncio.run(bot.on_message(_Update(_Msg(voice=object())), None))
    recorded = bot.load_session(7)
    assert captured_languages == []  # клон платный, его тут ещё не делают
    assert recorded["voices"] == {"ru": "voice-ru"}
    assert recorded["voice_pending"]["kk"] == recorded["voice_samples"]["kk"]
    assert recorded["step"] == bot.CHOOSING


def test_при_возврате_на_ru_бот_активирует_сохранённый_русский_голос(work):
    bot.save_session(7, _паспорт(
        step=bot.DONE,
        language="kk",
        voices={"ru": "voice-ru", "kk": "voice-kk"},
        voice_id="voice-kk",
        voice_language="kk",
    ))

    asyncio.run(bot.cmd_new(_Update(_Msg()), None))
    msg = _Msg()
    _press("reel_language:ru", msg)

    current = bot.load_session(7)
    assert current["step"] == bot.VIEWING_STAGE and current["stage"] == "language"
    assert current["voice_id"] == "voice-ru"
    assert current["voice_language"] == "ru"
    assert "🇷🇺 Русский ✅" in _labels(msg.markups[-1])


# --- шаг 2: выбор материала --------------------------------------------------

def test_готовый_сценарий_сразу_просит_текст(work):
    """Экрана «Что используем?» больше нет: он был загадкой для новичка."""
    bot.save_session(7, _паспорт(step=bot.CHOOSING))
    msg = _Msg()
    _press("mode:text", msg)

    s = bot.load_session(7)
    assert s["step"] == bot.WAIT_TEXT and s["material_mode"] == "text"
    assert msg.replies[-1] == bot.ASK_TEXT


def test_сгенерировать_сценарий_сразу_просит_материал(work):
    bot.save_session(7, _паспорт(step=bot.CHOOSING, scenario=SCENARIO))
    msg = _Msg()
    _press("mode:raw", msg)

    s = bot.load_session(7)
    assert s["step"] == bot.WAIT_RAW and s["material_mode"] == "raw"
    assert msg.replies[-1] == bot.ASK_RAW
    assert "Пришлите материал" in msg.replies[-1]


def test_без_фото_выбор_пути_уводит_на_фото(work):
    """Кнопка из истории чата не должна проносить человека мимо паспорта."""
    bot.save_session(7, {"step": bot.CHOOSING, "language": "ru"})
    msg = _Msg()

    _press("mode:text", msg)

    assert bot.load_session(7)["step"] == bot.WAIT_PHOTO


def test_кнопка_убранного_экрана_ведёт_к_вводу_материала(work):
    """material:edit и material:new живут в истории чата — они не должны
    вести в никуда."""
    bot.save_session(7, _паспорт(step=bot.CHOOSING_MATERIAL, material_mode="text",
                                 scenario=SCENARIO))
    msg = _Msg()
    _press("material:edit", msg)

    assert bot.load_session(7)["step"] == bot.WAIT_TEXT
    assert msg.replies[-1] == bot.ASK_TEXT


def test_старая_кнопка_прислать_новое_сырьё_ведёт_к_вводу(work):
    bot.save_session(7, _паспорт(step=bot.CHOOSING_MATERIAL, material_mode="raw",
                                 scenario=SCENARIO))
    msg = _Msg()
    _press("material:new", msg)

    assert bot.load_session(7)["step"] == bot.WAIT_RAW
    assert msg.replies[-1] == bot.ASK_RAW


# --- шаг 3: приём материала ---------------------------------------------------

def test_готовый_текст_только_запоминается_и_ведёт_к_цене(work, monkeypatch):
    вызовы = []
    monkeypatch.setattr(
        bot, "step_verbatim", lambda chat_id, text, language: вызовы.append(text)
    )
    _с_балансом()
    bot.save_session(7, _паспорт(step=bot.WAIT_TEXT))

    msg = _Msg("Мой текст.")
    asyncio.run(bot.on_message(_Update(msg), None))

    s = bot.load_session(7)
    assert вызовы == []                      # Клод до оплаты не зовётся
    assert s["step"] == bot.CONFIRM_PRICE
    assert s["material_text"] == "Мой текст."
    assert "Поехали" in " ".join(_labels(msg.markups[-1]))


def test_поехали_превращает_текст_в_сценарий(work, monkeypatch):
    monkeypatch.setattr(
        bot, "step_verbatim", lambda chat_id, text, language: SCENARIO
    )
    monkeypatch.setattr(bot, "save_client_profile", lambda chat_id, s: None)
    _с_балансом()
    bot.save_session(7, _паспорт(step=bot.WAIT_TEXT))

    msg = _Msg("Мой текст.")
    asyncio.run(bot.on_message(_Update(msg), None))
    _press("pay:go", msg)

    assert bot.WORKING in msg.replies
    assert "[хук]" in msg.replies[-1]
    s = bot.load_session(7)
    assert s["step"] == bot.REVIEW and s["scenario"] == SCENARIO


def test_сырьё_превращается_в_список_идей_после_оплаты(work, monkeypatch):
    ideas = [{"idea": "Раз", "draft_hook": "Хук раз"},
             {"idea": "Два", "draft_hook": "Хук два"}]
    вызовы = []

    def fake_ideas(chat_id, text, language):
        вызовы.append(text)
        return ideas

    monkeypatch.setattr(bot, "step_ideas", fake_ideas)
    monkeypatch.setattr(bot, "save_client_profile", lambda chat_id, s: None)
    _с_балансом()
    bot.save_session(7, _паспорт(
        step=bot.WAIT_RAW, language="kk",
        voices={"kk": "voice-kk"}, voice_id="voice-kk", voice_language="kk",
    ))

    msg = _Msg("Длинное сырьё про продажи.")
    asyncio.run(bot.on_message(_Update(msg), None))
    assert вызовы == []
    assert bot.load_session(7)["step"] == bot.CONFIRM_PRICE

    _press("pay:go", msg)

    assert "1. Раз" in msg.replies[-1] and "2. Два" in msg.replies[-1]
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

def test_назад_с_ввода_текста_возвращает_к_выбору_пути(work):
    bot.save_session(7, _паспорт(step=bot.WAIT_TEXT, material_mode="text"))

    msg = _Msg()
    _press("back", msg)

    assert bot.load_session(7)["step"] == bot.CHOOSING
    assert msg.replies[-1] == bot.ASK_PATH


def test_назад_с_цены_показывает_принятый_материал_а_не_просит_заново(work):
    """Баг: «Назад» с оплаты просил прислать сырьё снова, хотя оно уже принято,
    и вперёд пути не было."""
    bot.save_session(7, _паспорт(step=bot.CONFIRM_PRICE, material_mode="raw",
                                 material_text="Длинное сырьё про продажи."))

    msg = _Msg()
    _press("back", msg)

    s = bot.load_session(7)
    assert s["step"] == bot.VIEWING_STAGE and s["stage"] == "material"
    assert "Материал принят" in msg.replies[-1]
    assert "Длинное сырьё про продажи." in msg.replies[-1]
    assert _labels(msg.markups[-1]) == ["← Назад", "Вперёд →", "✏️ Изменить"]


def test_вперёд_с_материала_возвращает_к_цене_без_пересылки(work):
    _с_балансом()
    bot.save_session(7, _паспорт(step=bot.VIEWING_STAGE, stage="material",
                                 material_mode="raw", material_text="сырьё"))

    msg = _Msg()
    _press("stage:next", msg)

    s = bot.load_session(7)
    assert s["step"] == bot.CONFIRM_PRICE and s["material_text"] == "сырьё"
    assert "Поехали" in " ".join(_labels(msg.markups[-1]))


def test_присланное_на_экране_этапа_не_затирает_данные(work):
    bot.save_session(7, _паспорт(step=bot.VIEWING_STAGE, stage="material",
                                 material_mode="raw", material_text="старое сырьё"))

    msg = _Msg("совсем другое сырьё")
    asyncio.run(bot.on_message(_Update(msg), None))

    s = bot.load_session(7)
    assert s["material_text"] == "старое сырьё"
    assert "старое сырьё" in msg.replies[-1]
    assert "✏️ Изменить" in _labels(msg.markups[-1])


def test_изменить_открывает_ввод_того_же_этапа(work):
    bot.save_session(7, _паспорт(step=bot.VIEWING_STAGE, stage="material",
                                 material_mode="raw", material_text="старое сырьё"))

    msg = _Msg()
    _press("stage:edit", msg)
    assert bot.load_session(7)["step"] == bot.WAIT_RAW

    asyncio.run(bot.on_message(_Update(_Msg("новое сырьё")), None))

    assert bot.load_session(7)["material_text"] == "новое сырьё"


def test_кнопки_этапов_не_работают_во_время_сборки(work, клиент):
    """Кнопка из истории чата не должна уводить разговор с оплаченной job."""
    bot.save_session(7, _паспорт(step=bot.READY, scenario=SCENARIO))
    bot.enqueue_build(7, SCENARIO, language="ru", voice_id="voice-1")
    _claim_job()
    s = bot.load_session(7)
    s.update({"step": bot.BUILDING, "current_job_id": bot._job_store()
              .latest_for_chat(7).job_id})
    bot.save_session(7, s)

    msg = _Msg()
    _press("stage:next", msg)
    _press("pay:go", msg)

    assert msg.replies == [bot.BUSY_MSG, bot.BUSY_MSG]
    assert bot.load_session(7)["step"] == bot.BUILDING


def test_продолжить_после_готового_ролика_не_платит_заново(work, monkeypatch):
    """Кнопка «Продолжить ➡️» из старого сообщения об оплате не должна
    запускать вторую платную генерацию по тому же материалу."""
    вызовы = []
    monkeypatch.setattr(
        bot, "step_verbatim", lambda chat_id, text, language: вызовы.append(text)
    )
    _с_балансом()
    bot.save_session(7, _паспорт(step=bot.DONE, material_mode="text",
                                 material_text="Мой текст."))

    msg = _Msg()
    _press("pay:go", msg)

    assert вызовы == []
    assert bot.load_session(7)["step"] == bot.DONE


def test_навигация_по_этапам_после_готового_ролика_ведёт_к_новому(work):
    bot.save_session(7, _паспорт(step=bot.DONE, material_mode="text",
                                 material_text="Мой текст."))

    msg = _Msg()
    _press("stage:next", msg)

    assert bot.load_session(7)["step"] == bot.DONE
    assert "Новый ролик" in _labels(msg.markups[-1])


def test_назад_с_первого_этапа_никуда_не_проваливается(work):
    bot.save_session(7, _паспорт(step=bot.VIEWING_STAGE, stage="language"))

    msg = _Msg()
    _press("stage:prev", msg)

    s = bot.load_session(7)
    assert s["step"] == bot.VIEWING_STAGE and s["stage"] == "language"


def test_назад_с_ввода_материала_не_стирает_сценарий(work):
    bot.save_session(7, _паспорт(step=bot.WAIT_RAW,
                                 material_mode="raw", scenario=SCENARIO))

    msg = _Msg()
    _press("back", msg)

    s = bot.load_session(7)
    assert s["step"] == bot.CHOOSING
    assert s["scenario"] == SCENARIO
    assert s["photo"]["asset_id"] == "asset-1" and s["voice_id"] == "voice-1"
    assert msg.replies[-1] == bot.ASK_PATH


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


def test_назад_с_фото_у_новичка_показывает_выбранный_язык(work):
    bot.save_session(7, {"step": bot.WAIT_PHOTO, "language": "ru"})

    msg = _Msg()
    _press("back", msg)

    s = bot.load_session(7)
    assert s["step"] == bot.VIEWING_STAGE and s["stage"] == "language"
    assert "🇷🇺 Русский ✅" in _labels(msg.markups[-1])


def test_назад_с_записи_голоса_у_новичка_возвращает_к_фото(work):
    bot.save_session(7, {"step": bot.WAIT_VOICE, "language": "ru"})

    msg = _Msg()
    _press("back", msg)

    # фото ещё нет — показываем экран загрузки, а не пустую сводку
    assert bot.load_session(7)["step"] == bot.WAIT_PHOTO


def test_назад_с_замены_голоса_возвращает_к_прежнему_голосу(work):
    """Замена начата по «Изменить» — «Назад» должен её отменять, а не
    проваливать человека на шаг раньше."""
    bot.save_session(7, _паспорт(step=bot.WAIT_VOICE))

    msg = _Msg()
    _press("back", msg)

    s = bot.load_session(7)
    assert s["step"] == bot.VIEWING_STAGE and s["stage"] == "voice"
    assert s["voices"] == {"ru": "voice-1"}


def test_назад_с_выбора_пути_показывает_голос(work):
    bot.save_session(7, _паспорт(step=bot.CHOOSING))

    msg = _Msg()
    _press("back", msg)

    s = bot.load_session(7)
    assert s["step"] == bot.VIEWING_STAGE and s["stage"] == "voice"


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


def test_after_new_язык_выбирается_до_всего_остального(work):
    bot.save_session(7, _паспорт(step=bot.DONE))
    msg = _Msg()
    asyncio.run(bot.cmd_new(_Update(msg), None))
    assert msg.replies[-1] == bot.ASK_LANGUAGE

    _press("reel_language:ru", msg)
    # Язык отмечается галочкой в том же сообщении, отдельного экрана нет
    assert _labels(msg.markups[-1]) == ["🇷🇺 Русский ✅", "🇰🇿 Қазақша", "Продолжить →"]

    _press("stage:next", msg)

    # Фото у повторного уже есть — сводка с навигацией, а не просьба прислать
    assert "Фото загружено" in msg.replies[-1]
    assert _labels(msg.markups[-1]) == ["← Назад", "Вперёд →", "✏️ Изменить"]


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
    """Скачивание телеграма: файл ложится в рабочую папку чата, как в бою."""
    d = bot.session_dir(chat_id) / "input"
    d.mkdir(parents=True, exist_ok=True)
    path = d / "медиа.bin"
    path.write_bytes(b"media")
    return path


def test_первый_ролик_требует_фото_сразу_после_языка(work, профиль):
    bot.save_session(7, {"step": bot.CHOOSING_LANGUAGE})

    msg = _Msg()
    _press("reel_language:ru", msg)

    assert bot.load_session(7)["step"] == bot.WAIT_PHOTO
    assert "AI-аватара" in msg.replies[-1]


def test_утверждение_сценария_ведёт_сразу_к_сборке(work, профиль):
    """Фото и голос собраны до оплаты — после «Утвердить» спрашивать нечего."""
    bot.save_session(7, _паспорт(step=bot.REVIEW, scenario=SCENARIO))

    msg = _Msg()
    _press("ok", msg)

    assert bot.load_session(7)["step"] == bot.READY
    assert msg.replies[-1] == bot.READY_MSG
    callbacks = [
        b.callback_data
        for row in msg.markups[-1].inline_keyboard
        for b in row
    ]
    assert "build:montage" in callbacks and "build:plain" in callbacks


def test_повторный_профиль_показывает_сводки_а_не_вопросы(work, профиль):
    bot.save_session(7, _паспорт(step=bot.CHOOSING_LANGUAGE))
    msg = _Msg()

    _press("reel_language:ru", msg)
    _press("stage:next", msg)
    assert "Фото загружено" in msg.replies[-1]

    _press("stage:next", msg)
    s = bot.load_session(7)
    assert s["step"] == bot.VIEWING_STAGE and s["stage"] == "voice"
    assert "уже создан" in msg.replies[-1]


def test_вперёд_с_голоса_ведёт_к_выбору_пути(work, профиль):
    bot.save_session(7, _паспорт(step=bot.VIEWING_STAGE, stage="voice"))

    msg = _Msg()
    _press("stage:next", msg)

    s = bot.load_session(7)
    assert s["step"] == bot.CHOOSING  # материала ещё нет — спрашиваем путь
    assert s["photo"]["asset_id"] == "asset-1"


def test_новое_фото_затирает_старое_в_сессии_и_на_диске(work, профиль, tmp_path):
    старое_фото = tmp_path / "старое.jpg"
    старое_фото.write_bytes(b"old")
    bot.save_session(7, _паспорт(
        step=bot.WAIT_PHOTO,
        photo={"asset_id": "asset-старый", "file": str(старое_фото)},
    ))

    msg = _Msg(photo=[object()])
    asyncio.run(bot.on_message(_Update(msg), None))

    s = bot.load_session(7)
    assert s["photo"]["asset_id"] == "asset-новый"
    # запись голоса уже есть — следующий этап показывается сводкой
    assert s["step"] == bot.VIEWING_STAGE and s["stage"] == "voice"
    assert not старое_фото.exists()


def test_запись_голоса_не_создаёт_клон(work, профиль, monkeypatch):
    """Клон платный: на бесплатном шаге сохраняем только файл записи."""
    клоны = []
    monkeypatch.setattr(
        bot, "step_voice",
        lambda chat_id, path, language: клоны.append(language) or "voice-новый",
    )
    bot.save_session(7, {"step": bot.WAIT_PHOTO, "language": "ru"})

    asyncio.run(bot.on_message(_Update(_Msg(photo=[object()])), None))
    assert bot.load_session(7)["step"] == bot.WAIT_VOICE

    голос = _Msg(voice=object())
    asyncio.run(bot.on_message(_Update(голос), None))

    s = bot.load_session(7)
    assert клоны == []
    assert "voice_id" not in s and not s.get("voices")
    assert s["voice_pending"]["ru"] == s["voice_samples"]["ru"]
    assert s["step"] == bot.CHOOSING
    assert голос.replies[-2] == bot.VOICE_SAVED


def test_клон_делается_после_оплаты_и_старый_удаляется(work, monkeypatch, tmp_path):
    запись = tmp_path / "запись.ogg"
    запись.write_bytes(b"voice")
    удалённые = []
    monkeypatch.setattr(bot, "step_delete_voice", lambda vid: удалённые.append(vid))
    monkeypatch.setattr(
        bot, "step_voice", lambda chat_id, path, language: "voice-новый"
    )
    monkeypatch.setattr(
        bot, "step_verbatim", lambda chat_id, text, language: SCENARIO
    )
    monkeypatch.setattr(bot, "save_client_profile", lambda chat_id, s: None)
    _с_балансом()
    bot.save_session(7, _паспорт(
        step=bot.CONFIRM_PRICE,
        material_mode="text",
        material_text="Мой текст.",
        voices={"ru": "voice-старый"},
        voice_id="voice-старый",
        voice_samples={"ru": str(запись)},
        voice_pending={"ru": str(запись)},
    ))

    msg = _Msg()
    _press("pay:go", msg)

    s = bot.load_session(7)
    assert s["voices"] == {"ru": "voice-новый"}
    assert not s["voice_pending"]
    assert удалённые == ["voice-старый"]  # только после успеха нового
    assert s["step"] == bot.REVIEW


def test_запись_заново_не_трогает_прежний_клон_до_оплаты(work, профиль, monkeypatch):
    удалённые = []
    monkeypatch.setattr(bot, "step_delete_voice", lambda vid: удалённые.append(vid))
    bot.save_session(7, _паспорт(step=bot.VIEWING_STAGE, stage="voice"))

    msg = _Msg()
    _press("stage:edit", msg)
    asyncio.run(bot.on_message(_Update(_Msg(voice=object())), None))

    s = bot.load_session(7)
    assert удалённые == []
    assert s["voices"] == {"ru": "voice-1"}  # рабочий голос остаётся рабочим
    assert s["voice_pending"]["ru"]
    assert bot.ASK_VOICE in msg.replies[-1]


def test_ошибка_удаления_старого_голоса_не_блокирует_сборку(
    work, monkeypatch, tmp_path, caplog
):
    запись = tmp_path / "запись.ogg"
    запись.write_bytes(b"voice")

    def падаем(vid):
        raise RuntimeError("сеть упала")

    monkeypatch.setattr(bot, "step_delete_voice", падаем)
    monkeypatch.setattr(
        bot, "step_voice", lambda chat_id, path, language: "voice-новый"
    )
    monkeypatch.setattr(
        bot, "step_verbatim", lambda chat_id, text, language: SCENARIO
    )
    monkeypatch.setattr(bot, "save_client_profile", lambda chat_id, s: None)
    _с_балансом()
    bot.save_session(7, _паспорт(
        step=bot.CONFIRM_PRICE,
        material_mode="text",
        material_text="Мой текст.",
        voices={"ru": "voice-старый"},
        voice_id="voice-старый",
        voice_samples={"ru": str(запись)},
        voice_pending={"ru": str(запись)},
    ))

    with caplog.at_level(logging.WARNING):
        _press("pay:go", _Msg())

    assert bot.load_session(7)["step"] == bot.REVIEW
    assert "voice-старый" in caplog.text and "сеть упала" in caplog.text


def test_упавший_клон_не_пускает_в_генерацию(work, monkeypatch, tmp_path):
    запись = tmp_path / "запись.ogg"
    запись.write_bytes(b"voice")
    сценарии = []

    def падаем(chat_id, path, language):
        raise RuntimeError("ElevenLabs отказал")

    monkeypatch.setattr(bot, "step_voice", падаем)
    monkeypatch.setattr(
        bot, "step_verbatim",
        lambda chat_id, text, language: сценарии.append(text) or SCENARIO,
    )
    _с_балансом()
    bot.save_session(7, _паспорт(
        step=bot.CONFIRM_PRICE,
        material_mode="text",
        material_text="Мой текст.",
        voices={},
        voice_id=None,
        voice_samples={"ru": str(запись)},
        voice_pending={"ru": str(запись)},
    ))

    msg = _Msg()
    _press("pay:go", msg)

    assert сценарии == []  # Клода не зовём, раз голоса не вышло
    assert "ElevenLabs отказал" in msg.replies[-2]
    assert bot.load_session(7)["step"] == bot.WAIT_VOICE


def test_полный_путь_новичка_платит_только_после_экрана_цены(work, monkeypatch):
    """Сквозной прогон: от /start до готовности к сборке. Все платные вызовы
    (клон голоса, Клод) обязаны случиться строго после «Поехали»."""
    платные = []
    monkeypatch.setattr(bot, "_download", _fake_download)
    monkeypatch.setattr(bot, "step_photo", lambda chat_id, path: "asset-новый")
    monkeypatch.setattr(
        bot, "step_voice",
        lambda chat_id, path, language: платные.append("голос") or "voice-1",
    )
    monkeypatch.setattr(
        bot, "step_verbatim",
        lambda chat_id, text, language: платные.append("клод") or SCENARIO,
    )
    monkeypatch.setattr(bot, "save_client_profile", lambda chat_id, s: None)

    msg = _Msg()
    asyncio.run(bot.cmd_start(_Update(msg), None))
    assert msg.replies[-1] == bot.ASK_LANGUAGE

    _press("reel_language:ru", msg)
    assert bot.load_session(7)["step"] == bot.WAIT_PHOTO

    asyncio.run(bot.on_message(_Update(_Msg(photo=[object()])), None))
    assert bot.load_session(7)["step"] == bot.WAIT_VOICE

    asyncio.run(bot.on_message(_Update(_Msg(voice=object())), None))
    assert bot.load_session(7)["step"] == bot.CHOOSING

    _press("mode:text", msg)
    _press("material:new", msg)
    asyncio.run(bot.on_message(_Update(_Msg("Мой текст.")), None))
    assert bot.load_session(7)["step"] == bot.CONFIRM_PRICE
    assert платные == []           # всё, что было до сих пор, — бесплатно

    _с_балансом()
    _press("pay:go", msg)
    assert платные == ["голос", "клод"]

    _press("ok", msg)
    s = bot.load_session(7)
    assert s["step"] == bot.READY and s["voice_id"] == "voice-1"


def test_сбой_движка_не_роняет_разговор(work, monkeypatch):
    def падаем(chat_id, text, language):
        raise RuntimeError("claude -p упал")

    monkeypatch.setattr(bot, "step_verbatim", падаем)
    monkeypatch.setattr(bot, "save_client_profile", lambda chat_id, s: None)
    _с_балансом()
    bot.save_session(7, _паспорт(step=bot.CONFIRM_PRICE, material_mode="text",
                                 material_text="Мой текст."))

    msg = _Msg()
    _press("pay:go", msg)

    assert "claude -p упал" in msg.replies[-1]
    assert bot.load_session(7)["step"] == bot.CONFIRM_PRICE


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
    _press("build:plain", msg)

    assert вызовы == [7]
    s = bot.load_session(7)
    assert s["step"] == bot.AUDIO_PREPARING
    assert s["current_job_id"]
    assert bot.BUILDING_MSG in msg.replies[-1]
    assert not msg.videos
    job = bot._job_store().get(s["current_job_id"])
    assert job.status == "audio_queued"
    assert (job.workdir / "scenario.json").exists()


def _deliver_audio_preview():
    job = _claim_job()
    api = _BotAPI()

    def fake_preview(chat_id, workdir):
        audio = workdir / "audio" / "tts" / "voice_master.mp3"
        audio.parent.mkdir(parents=True)
        audio.write_bytes(b"preview-audio")
        return {"ok": True, "audio": str(audio), "stage": "audio_review"}

    asyncio.run(bot._process_audio_job(api, job, preview_fn=fake_preview))
    return job, api


def test_audio_preview_отправляется_до_рендера_и_job_ждёт_решения(
        work, клиент):
    bot.save_session(7, {
        "step": bot.READY,
        "scenario": SCENARIO,
        "photo": {"asset_id": "a1", "file": "ф.jpg"},
        "voice_id": "voice-1",
    })
    _press("build:plain", _Msg())

    job, api = _deliver_audio_preview()

    saved = bot._job_store().get(job.job_id)
    assert saved.status == "awaiting_audio_approval"
    assert bot.load_session(7)["step"] == bot.AUDIO_REVIEW
    assert api.audios[-1]["bytes"] == b"preview-audio"
    assert api.audios[-1]["caption"] == bot.AUDIO_REVIEW_MSG
    assert _labels(api.audios[-1]["reply_markup"]) == [
        "✅ Аудио подходит",
        "🎙 Не подходит — запишу сам(а)",
    ]
    assert not api.videos


def test_утверждённое_audio_переходит_в_render_queue_без_повторного_tts(
        work, клиент, monkeypatch):
    bot.save_session(7, {
        "step": bot.READY,
        "scenario": SCENARIO,
        "photo": {"asset_id": "a1", "file": "ф.jpg"},
        "voice_id": "voice-1",
    })
    _press("build:plain", _Msg())
    job, _api = _deliver_audio_preview()
    approved = []
    monkeypatch.setattr(
        bot, "approve_tts_audio",
        lambda workdir: approved.append(workdir) or {},
    )

    msg = _Msg()
    _press(f"audio_ok:{job.job_id}", msg)

    assert approved == [job.workdir]
    assert bot._job_store().get(job.job_id).status == "queued"
    assert bot.load_session(7)["step"] == bot.BUILDING
    assert msg.replies[-1] == bot.RENDER_QUEUED_MSG


def test_отказ_от_tts_принимает_одно_telegram_voice_и_ставит_render(
        work, клиент, monkeypatch):
    bot.save_session(7, {
        "step": bot.READY,
        "scenario": SCENARIO,
        "photo": {"asset_id": "a1", "file": "ф.jpg"},
        "voice_id": "voice-1",
    })
    _press("build:plain", _Msg())
    job, _api = _deliver_audio_preview()

    reject_msg = _Msg()
    _press(f"audio_self:{job.job_id}", reject_msg)
    assert bot._job_store().get(job.job_id).status == "awaiting_user_audio"
    assert bot.load_session(7)["step"] == bot.WAIT_FINAL_AUDIO
    assert "одним голосовым" in reject_msg.replies[-1]

    script_msg = _Msg()
    _press(f"audio_script:{job.job_id}", script_msg)
    assert "Продажи начинаются раньше." in script_msg.replies[-1]
    assert "Сохрани себе." in script_msg.replies[-1]

    monkeypatch.setattr(bot, "_download", _fake_download)
    prepared = []
    monkeypatch.setattr(
        bot,
        "prepare_user_audio",
        lambda workdir, source: prepared.append((workdir, source)) or {"ok": True},
    )
    voice_msg = _Msg(voice=object())
    asyncio.run(bot.on_message(_Update(voice_msg), None))

    assert prepared and prepared[0][0] == job.workdir
    assert bot._job_store().get(job.job_id).status == "queued"
    assert bot.load_session(7)["step"] == bot.BUILDING
    assert voice_msg.replies[-1] == bot.FINAL_AUDIO_ACCEPTED


def test_new_отменяет_job_которая_ждёт_audio_approval(work, клиент):
    # ролик стоит на подтверждении озвучки и ждёт юзера — /new его отменяет
    # и начинает новый, а не блокирует пользователя в тупике
    bot.save_session(7, {
        "step": bot.READY,
        "scenario": SCENARIO,
        "photo": {"asset_id": "a1", "file": "ф.jpg"},
        "voice_id": "voice-1",
    })
    _press("build:plain", _Msg())
    job, _api = _deliver_audio_preview()
    assert bot._job_store().get(job.job_id).status == "awaiting_audio_approval"
    msg = _Msg()

    asyncio.run(bot.cmd_new(_Update(msg), None))

    assert bot._job_store().get(job.job_id).status == "cancelled"
    assert bot.CANCELLED_PENDING_MSG in msg.replies
    # сессия отвязана от отменённой job и начат новый заход
    assert bot.load_session(7).get("current_job_id") is None
    assert bot.load_session(7)["step"] != bot.READY


def test_new_не_бросает_реально_идущий_рендер(work, клиент, monkeypatch):
    # активный рендер (не пауза) нельзя отменять на полпути — /new блокируется
    bot.save_session(7, {
        "step": bot.READY,
        "scenario": SCENARIO,
        "photo": {"asset_id": "a1", "file": "ф.jpg"},
        "voice_id": "voice-1",
    })
    _press("build:plain", _Msg())
    job = bot._job_store().latest_for_chat(7)
    # протолкнуть job в реально исполняемое состояние
    bot._job_store().transition(
        job.job_id, "queued", expected="audio_queued", stage="build",
    )
    bot._job_store().transition(
        job.job_id, "running", expected="queued", stage="build",
    )
    msg = _Msg()

    asyncio.run(bot.cmd_new(_Update(msg), None))

    assert msg.replies[-1] == bot.BUSY_MSG
    assert bot._job_store().get(job.job_id).status == "running"


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
    assert snapshot["tts"]["model_id"] == "eleven_multilingual_v2"
    # по умолчанию ролик собирается с монтажом
    assert snapshot["montage"] is True
    assert input_doc["language"] == "ru"


def test_enqueue_build_без_монтажа_пишет_флаг_в_snapshot(work, клиент):
    import yaml

    job = bot.enqueue_build(
        7, {**SCENARIO, "language": "ru"},
        language="ru", voice_id="voice-1", montage=False,
    )
    snapshot = yaml.safe_load(
        (job.workdir / "build-config.yaml").read_text(encoding="utf-8")
    )
    assert snapshot["montage"] is False


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
    # kk-профиль озвучивается через eleven_v3 (v2 не знает казахский)
    assert cfg["tts"]["model_id"] == "eleven_v3"


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
    _press("build:plain", msg)

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
    _press("build:plain", msg)

    assert вызвано == []
    assert msg.replies == [bot.NOT_NOW]


def test_устаревшая_кнопка_создать_ролик_на_шаге_choosing_не_запускает_сборку(
        work, клиент, monkeypatch):
    вызвано = []
    monkeypatch.setattr(bot, "run_build", lambda chat_id, workdir: вызвано.append(1))
    bot.save_session(7, {"step": bot.CHOOSING})

    msg = _Msg()
    _press("build:plain", msg)

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
    _press("build:plain", msg)

    assert msg.replies[-1] == bot.CLIENT_NOT_FOUND_MSG
    assert вызвано == []


def test_повторное_нажатие_создать_ролик_пока_сборка_идёт(work, клиент):
    bot._job_store().enqueue(7)
    bot.save_session(7, {"step": bot.READY, "scenario": SCENARIO,
                         "photo": {"asset_id": "a1", "file": "ф.jpg"}, "voice_id": "voice-1"})
    msg = _Msg()
    _press("build:plain", msg)
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
    _press("build:plain", _Msg())
    api = _BotAPI()

    asyncio.run(bot._process_job(api, _claim_job(), build_fn=fake_run_build))

    assert api.videos
    assert (api.videos[-1]["width"], api.videos[-1]["height"]) == (bot.OUT_W, bot.OUT_H)


def test_сценарий_пишется_в_job_workdir_с_uuid(work, клиент):
    bot.save_session(7, {"step": bot.READY, "scenario": SCENARIO,
                         "photo": {"asset_id": "a1", "file": "ф.jpg"}, "voice_id": "voice-1"})

    _press("build:plain", _Msg())

    job = bot._job_store().latest_for_chat(7)
    assert job.workdir.parent == bot.WORK_ROOT / "jobs"
    assert job.workdir.name == job.job_id
    assert len(job.job_id) == 32
    saved = json.loads((job.workdir / "scenario.json").read_text(encoding="utf-8"))
    assert saved == {**SCENARIO, "language": "ru"}
    assert (job.workdir / "job.input.json").exists()
    assert (job.workdir / "build-config.yaml").exists()


def test_кнопка_без_монтажа_пишет_montage_false_в_snapshot(work, клиент):
    import yaml

    bot.save_session(7, {"step": bot.READY, "scenario": SCENARIO,
                         "photo": {"asset_id": "a1", "file": "ф.jpg"}, "voice_id": "voice-1"})
    _press("build:plain", _Msg())

    job = bot._job_store().latest_for_chat(7)
    cfg = yaml.safe_load((job.workdir / "build-config.yaml").read_text(encoding="utf-8"))
    assert cfg["montage"] is False
    assert bot.load_session(7)["montage"] is False


def test_кнопка_с_монтажом_ничего_не_собирает_а_спрашивает_пожелание(work, клиент):
    """Монтаж ещё не сделан: платная сборка по этой кнопке не запускается."""
    bot.save_session(7, {"step": bot.READY, "scenario": SCENARIO,
                         "photo": {"asset_id": "a1", "file": "ф.jpg"}, "voice_id": "voice-1"})
    msg = _Msg()

    _press("build:montage", msg)

    assert bot._job_store().latest_for_chat(7) is None
    assert msg.replies[-1] == bot.MONTAGE_WIP_MSG
    assert _labels(msg.markups[-1]) == ["Пропустить"]
    assert bot.load_session(7)["step"] == bot.WAIT_WISH


def test_старая_кнопка_build_тоже_ведёт_в_заглушку_монтажа(work, клиент):
    """Инлайн-кнопки живут в чате вечно, а «build» — это монтажный режим."""
    bot.save_session(7, {"step": bot.READY, "scenario": SCENARIO,
                         "photo": {"asset_id": "a1", "file": "ф.jpg"}, "voice_id": "voice-1"})

    _press("build", _Msg())

    assert bot._job_store().latest_for_chat(7) is None
    assert bot.load_session(7)["step"] == bot.WAIT_WISH


def test_пожелание_к_монтажу_попадает_в_базу(work, клиент):
    bot.save_session(7, {"step": bot.WAIT_WISH, "wish_topic": bot.MONTAGE_TOPIC,
                         "scenario": SCENARIO,
                         "photo": {"asset_id": "a1", "file": "ф.jpg"},
                         "voice_id": "voice-1"})
    msg = _Msg("Хочу перебивки под музыку и крупные титры.")
    upd = _Update(msg)
    upd.effective_user = type("U", (), {"username": "vasya"})()

    asyncio.run(bot.on_message(upd, None))

    записи = bot._feedback().list(topic=bot.MONTAGE_TOPIC)
    assert len(записи) == 1
    assert записи[0]["chat_id"] == 7
    assert записи[0]["username"] == "vasya"
    assert записи[0]["text"] == "Хочу перебивки под музыку и крупные титры."
    assert msg.replies[0] == bot.WISH_THANKS
    # и человек не заперт в тупике: снова видит экран сборки
    assert bot.load_session(7)["step"] == bot.READY
    assert msg.replies[-1] == bot.READY_MSG


def test_пожелание_можно_пропустить(work, клиент):
    bot.save_session(7, {"step": bot.WAIT_WISH, "wish_topic": bot.MONTAGE_TOPIC,
                         "scenario": SCENARIO,
                         "photo": {"asset_id": "a1", "file": "ф.jpg"},
                         "voice_id": "voice-1"})
    msg = _Msg()

    _press("wish:skip", msg)

    assert bot._feedback().count() == 0
    assert bot.load_session(7)["step"] == bot.READY


def test_без_имени_пользователя_пожелание_всё_равно_пишется(work, клиент):
    bot.save_session(7, {"step": bot.WAIT_WISH, "wish_topic": bot.MONTAGE_TOPIC,
                         "scenario": SCENARIO,
                         "photo": {"asset_id": "a1", "file": "ф.jpg"},
                         "voice_id": "voice-1"})

    asyncio.run(bot.on_message(_Update(_Msg("Хочу как у блогеров.")), None))

    записи = bot._feedback().list()
    assert len(записи) == 1 and записи[0]["username"] is None


def test_сбой_сборки_сообщается_человеческим_текстом(work, клиент, monkeypatch):
    bot.save_session(7, {"step": bot.READY, "scenario": SCENARIO,
                         "photo": {"asset_id": "a1", "file": "ф.jpg"}, "voice_id": "voice-1"})
    _press("build:plain", _Msg())
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
    _press("build:plain", _Msg())
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
    _press("build:plain", _Msg())
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
    _press("build:plain", _Msg())
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
    _press("build:plain", _Msg())
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
    _press("build:plain", _Msg())
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
    _press("build:plain", _Msg())
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
    _press("build:plain", _Msg())
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
    _press("build:plain", _Msg())
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
    _press("build:plain", _Msg())
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
    _press("build:plain", msg)

    job = bot._job_store().latest_for_chat(7)
    assert job.status == "audio_queued"
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
    assert job.status == "audio_queued"


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


def test_пресеты_пополнения_в_минимальных_единицах():
    """Суммы уходят в Shop API как есть: центы для usd, копейки для rub.
    Опечатка тут — счёт в сто раз больше или меньше."""
    from reels_factory.bot import TOPUP_PRESETS
    assert dict(TOPUP_PRESETS["usd"])[10_00] == "$10"
    assert dict(TOPUP_PRESETS["rub"])[1000_00] == "1000 ₽"
    for currency, presets in TOPUP_PRESETS.items():
        assert currency in ("usd", "rub")
        for minor, label in presets:
            assert minor > 0 and label


@pytest.fixture
def магазин(monkeypatch):
    """Shop API без сети: запоминаем, с чем звали, и отдаём готовый заказ."""
    from reels_factory import tribute_shop

    вызовы = {"created": [], "status": ["pending"]}

    def fake_create(*, api_key, amount_minor, currency, customer_id, title,
                    description):
        вызовы["created"].append({
            "amount": amount_minor, "currency": currency,
            "customerId": customer_id, "title": title,
        })
        return {
            "uuid": "order-1",
            "paymentUrl": "https://web.tribute.tg/shop/pay/order-1",
            "webappPaymentUrl": "https://t.me/tribute/app?startapp=shop_pay_order-1",
        }

    monkeypatch.setattr(tribute_shop, "create_order", fake_create)
    monkeypatch.setattr(
        tribute_shop, "order_status",
        lambda *, api_key, order_uuid: вызовы["status"][-1],
    )
    monkeypatch.setenv("TRIBUTE_API_KEY", "test-key")
    return вызовы


def test_пополнение_меняет_кнопки_в_том_же_сообщении(work, магазин):
    """Новых экранов «В какой валюте платить?» быть не должно: кнопки валюты
    встают на место «Пополнить баланс» в том же сообщении."""
    bot.save_session(7, _паспорт(step=bot.CONFIRM_PRICE))
    msg = _Msg("Материал принял. Ролик обойдётся примерно в $4.21…")

    _press("topup:start", msg)

    assert msg.kinds[-1] == "edit"
    assert _labels(msg.markups[-1]) == [
        "Оплатить в RUB", "Оплатить в USD", "← Назад"
    ]

    _press("topup:cur:rub", msg)

    assert bot.load_session(7)["pay_currency"] == "rub"
    assert "Выберите сумму для пополнения" in msg.replies[-1]
    assert _labels(msg.markups[-1]) == ["1000 ₽", "2500 ₽", "5000 ₽", "← Назад"]


def test_назад_с_выбора_валюты_возвращает_прежние_кнопки(work, магазин):
    bot.save_session(7, _паспорт(step=bot.CONFIRM_PRICE))
    msg = _Msg("Материал принял…")

    _press("topup:start", msg)
    _press("topup:cancel", msg)

    assert msg.kinds[-1] == "edit"
    assert _labels(msg.markups[-1]) == [
        "💳 Пополнить баланс", "Проверить баланс", "← Назад"
    ]


def test_сумма_создаёт_счёт_с_chat_id_в_customerId(work, магазин):
    bot.save_session(7, _паспорт(step=bot.CONFIRM_PRICE, pay_currency="rub"))
    msg = _Msg()

    _press("topup:amt:rub:100000", msg)

    assert магазин["created"] == [{
        "amount": 100000, "currency": "rub", "customerId": "7",
        "title": "Пополнение баланса 1000 ₽",
    }]
    assert bot.load_session(7)["pending_order"]["uuid"] == "order-1"
    ссылки = [b.url for row in msg.markups[-1].inline_keyboard for b in row if b.url]
    assert ссылки == ["https://t.me/tribute/app?startapp=shop_pay_order-1"]


def test_проверка_оплаты_зачисляет_оплаченный_счёт(work, магазин):
    bot.save_session(7, _паспорт(step=bot.CONFIRM_PRICE, pay_currency="usd"))
    msg = _Msg()
    _press("topup:amt:usd:1000", msg)

    магазин["status"].append("paid")
    _press("topup:check", msg)

    assert bot._ledger().balance(7) == 10_000_000
    assert "Оплата получена" in msg.replies[-1]
    assert "pending_order" not in bot.load_session(7)


def test_после_оплаты_счёт_превращается_в_продолжить(work, магазин):
    """Одно сообщение на оплату: счёт правится на месте, новых экранов нет."""
    bot.save_session(7, _паспорт(step=bot.CONFIRM_PRICE, pay_currency="usd",
                                 material_mode="text", material_text="Мой текст."))
    msg = _Msg()
    _press("topup:amt:usd:5000", msg)
    счёт = msg.replies[-1]

    магазин["status"].append("paid")
    _press("topup:check", msg)

    assert msg.kinds[-1] == "edit"          # то же сообщение, а не новое
    assert счёт not in msg.replies[-1:]
    assert "Оплата получена" in msg.replies[-1]
    assert _labels(msg.markups[-1]) == ["Продолжить ➡️"]


def test_после_оплаты_с_нехваткой_показывает_сколько_добавить(work, магазин):
    # длинный текст — ролик дороже одного пополнения на $10
    bot.save_session(7, _паспорт(step=bot.CONFIRM_PRICE, pay_currency="usd",
                                 material_mode="text", material_text="а" * 2000))
    msg = _Msg()
    _press("topup:amt:usd:1000", msg)

    магазин["status"].append("paid")
    _press("topup:check", msg)

    assert "Не хватает" in msg.replies[-1]
    assert "оплата ещё не дошла" not in msg.replies[-1].lower()
    assert _labels(msg.markups[-1]) == [
        "💳 Пополнить баланс", "Проверить баланс", "← Назад"
    ]


def test_вебхук_правит_то_же_сообщение_со_счётом(work, магазин):
    """Вебхук и кнопка проверки не должны давать двух сообщений об одной
    оплате: оба правят сообщение со счётом."""
    bot.save_session(7, _паспорт(step=bot.CONFIRM_PRICE, pay_currency="usd",
                                 material_mode="text", material_text="Мой текст."))
    _press("topup:amt:usd:5000", _Msg())
    _пополнить(7, 50_000_000)

    правки = []

    class _BotAPI:
        async def edit_message_text(self, chat_id, message_id, text,
                                    reply_markup=None):
            правки.append((chat_id, message_id, text))

        async def send_message(self, chat_id, text, reply_markup=None):
            правки.append(("новое сообщение", chat_id, text))

    asyncio.run(bot._apply_credit_to_chat(_BotAPI(), 7))

    assert len(правки) == 1
    chat_id, message_id, text = правки[0]
    assert chat_id == 7 and message_id == bot.load_session(7).get(
        "pending_order", {}
    ).get("message_id", message_id)
    assert "Оплата получена" in text
    assert "pending_order" not in bot.load_session(7)


def test_проверка_оплаты_не_удваивает_баланс_после_вебхука(work, магазин):
    """Вебхук и кнопка «Проверить оплату» могут сработать оба — ключ
    идемпотентности у них общий, иначе человек получит деньги дважды."""
    from reels_factory.tribute import credit_shop_order

    bot.save_session(7, _паспорт(step=bot.CONFIRM_PRICE, pay_currency="usd"))
    _press("topup:amt:usd:1000", _Msg())

    credit_shop_order(bot._ledger(), {
        "name": "shop_order",
        "payload": {"uuid": "order-1", "status": "paid", "amount": 1000,
                    "currency": "usd", "customerId": "7"},
    }, bot._billing()["fx"])
    магазин["status"].append("paid")
    _press("topup:check", _Msg())

    assert bot._ledger().balance(7) == 10_000_000


def test_неудачный_счёт_не_молчит(work, monkeypatch):
    from reels_factory import tribute_shop

    def падаем(**kwargs):
        raise tribute_shop.TributeShopError("HTTP 500 магазин лёг")

    monkeypatch.setattr(tribute_shop, "create_order", падаем)
    bot.save_session(7, _паспорт(step=bot.CONFIRM_PRICE, pay_currency="usd"))
    msg = _Msg()

    _press("topup:amt:usd:1000", msg)

    assert "магазин лёг" in msg.replies[-1]
    assert "pending_order" not in bot.load_session(7)


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


def test_нехватка_баланса_показывает_цену_и_кнопки_пополнения(work, monkeypatch):
    вызовы = []
    monkeypatch.setattr(
        bot, "step_verbatim", lambda chat_id, text, language: вызовы.append(text)
    )
    bot.save_session(7, _паспорт(step=bot.WAIT_TEXT))

    msg = _Msg("Мой текст.")
    asyncio.run(bot.on_message(_Update(msg), None))

    assert "не хватает" in msg.replies[-1].lower()
    labels = _labels(msg.markups[-1])
    assert "💳 Пополнить баланс" in labels
    assert "Проверить баланс" in labels
    assert "Поехали" not in " ".join(labels)
    assert вызовы == [] and bot.WORKING not in msg.replies
    # материал не потерян: после пополнения продолжим с того же места
    s = bot.load_session(7)
    assert s["step"] == bot.CONFIRM_PRICE and s["material_text"] == "Мой текст."


def test_поехали_с_пустым_балансом_не_запускает_генерацию(work, monkeypatch):
    вызовы = []
    monkeypatch.setattr(
        bot, "step_verbatim", lambda chat_id, text, language: вызовы.append(text)
    )
    bot.save_session(7, _паспорт(step=bot.CONFIRM_PRICE, material_mode="text",
                                 material_text="Мой текст."))

    msg = _Msg()
    _press("pay:go", msg)

    assert вызовы == []
    assert "не хватает" in msg.replies[-1].lower()


def test_проверить_баланс_после_пополнения_открывает_поехали(work):
    bot.save_session(7, _паспорт(step=bot.CONFIRM_PRICE, material_mode="text",
                                 material_text="Мой текст."))
    msg = _Msg()
    _press("pay:check", msg)
    assert "Поехали" not in " ".join(_labels(msg.markups[-1]))

    _с_балансом()
    _press("pay:check", msg)

    assert "Поехали" in " ".join(_labels(msg.markups[-1]))


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


def test_нулевой_баланс_не_пускает_в_платную_часть(work, monkeypatch):
    """Бесплатных роликов нет: с нулём человек упирается в экран цены, но
    материал и паспорт остаются собранными — платить он идёт с готовым."""
    вызовы = []
    monkeypatch.setattr(
        bot, "step_verbatim", lambda chat_id, text, language: вызовы.append(text)
    )
    assert bot._ledger().balance(7) == 0
    bot.save_session(7, _паспорт(step=bot.WAIT_TEXT))

    msg = _Msg("Мой текст.")
    asyncio.run(bot.on_message(_Update(msg), None))

    assert вызовы == []
    assert bot.load_session(7)["step"] == bot.CONFIRM_PRICE


def test_биллинг_выключен_ведёт_прямо_в_генерацию(work, monkeypatch):
    _charge_flat(7, 1)
    billing_on = bot._billing()
    monkeypatch.setattr(bot, "_billing", lambda: {**billing_on, "enabled": False})
    monkeypatch.setattr(
        bot, "step_verbatim", lambda chat_id, text, language: SCENARIO
    )
    monkeypatch.setattr(bot, "save_client_profile", lambda chat_id, s: None)
    bot.save_session(7, _паспорт(step=bot.WAIT_TEXT))

    msg = _Msg("Мой текст.")
    asyncio.run(bot.on_message(_Update(msg), None))

    assert bot.WORKING in msg.replies
    assert bot.load_session(7)["step"] == bot.REVIEW
