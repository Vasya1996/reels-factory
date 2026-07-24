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
        self.markups = []

    async def reply_text(self, text, reply_markup=None):
        self.replies.append(text)
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


def _press(button, msg):
    """Нажатие кнопки в чате."""
    upd = type("U", (), {"callback_query": _Query(button, msg)})()
    asyncio.run(bot.on_button(upd, None))


def _labels(markup):
    """Подписи кнопок клавиатуры — плоским списком."""
    return [b.text for row in markup.inline_keyboard for b in row]


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


def test_новый_чат_ведёт_к_выбору_пути(work):
    msg = _Msg("привет")
    asyncio.run(bot.on_message(_Update(msg), None))
    assert msg.replies == [bot.NOT_NOW]


def test_loop_session_сохраняет_сценарий_фото_и_голос():
    s = {"step": bot.DONE, "scenario": SCENARIO, "photo": {"asset_id": "a"},
         "voice_id": "v", "ideas": [1], "material_mode": "raw"}
    assert bot.loop_session(s) == {"step": bot.CHOOSING, "photo": {"asset_id": "a"},
                                    "voice_id": "v", "scenario": SCENARIO}


def test_fresh_session_не_сохраняет_сценарий():
    s = {"step": bot.DONE, "scenario": SCENARIO, "photo": {"asset_id": "a"}, "voice_id": "v"}
    assert bot.fresh_session(s) == {"step": bot.CHOOSING, "photo": {"asset_id": "a"},
                                     "voice_id": "v"}


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
                         "voice_id": "voice-1"})

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


# --- «новый ролик»: цикл без повторного онбординга ----------------------------

def test_новый_ролик_сохраняет_фото_голос_и_сценарий(work):
    bot.save_session(7, {"step": bot.DONE, "scenario": SCENARIO,
                         "photo": {"asset_id": "a1", "file": "ф.jpg"}, "voice_id": "voice-1"})

    msg = _Msg()
    _press("new_reel", msg)

    s = bot.load_session(7)
    assert s["step"] == bot.CHOOSING
    assert s["scenario"] == SCENARIO
    assert s["photo"] == {"asset_id": "a1", "file": "ф.jpg"}
    assert s["voice_id"] == "voice-1"
    assert msg.replies[-1] == bot.HELLO


def test_команда_new_делает_то_же_что_кнопка(work):
    bot.save_session(7, {"step": bot.DONE, "scenario": SCENARIO, "voice_id": "voice-1"})

    msg = _Msg()
    asyncio.run(bot.cmd_new(_Update(msg), None))

    s = bot.load_session(7)
    assert s["step"] == bot.CHOOSING and s["scenario"] == SCENARIO
    assert msg.replies[-1] == bot.HELLO


def test_start_сбрасывает_сценарий_но_не_фото_и_голос(work):
    bot.save_session(7, {"step": bot.REVIEW, "scenario": SCENARIO,
                         "photo": {"asset_id": "a1"}, "voice_id": "voice-1"})

    msg = _Msg()
    asyncio.run(bot.cmd_start(_Update(msg), None))

    s = bot.load_session(7)
    assert s["step"] == bot.CHOOSING and "scenario" not in s
    assert s["photo"] == {"asset_id": "a1"} and s["voice_id"] == "voice-1"


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


# --- шаг 5/6: профиль (фото + голос) -------------------------------------------

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

    assert удалённые == ["voice-старый"]
    s = bot.load_session(7)
    assert s["step"] == bot.WAIT_VOICE and "voice_id" not in s
    assert msg.replies[-1] == bot.ASK_VOICE


def test_записать_заново_чистит_voice_id_в_профиле_клиента(work, monkeypatch):
    monkeypatch.setattr(bot, "step_delete_voice", lambda vid: None)
    вызовы = []
    monkeypatch.setattr(bot, "clear_client_voice_profile", lambda chat_id: вызовы.append(chat_id))
    bot.save_session(7, {"step": bot.CHOOSING_VOICE, "voice_id": "voice-старый"})

    _press("voice:new", _Msg())

    assert вызовы == [7]  # профиль клиента честно неполон, не ссылается на удалённый голос


def test_ошибка_удаления_старого_голоса_не_блокирует_запись(work, monkeypatch):
    def падаем(vid):
        raise RuntimeError("сеть упала")

    monkeypatch.setattr(bot, "step_delete_voice", падаем)
    bot.save_session(7, {"step": bot.CHOOSING_VOICE, "voice_id": "voice-старый"})

    msg = _Msg()
    _press("voice:new", msg)

    assert bot.load_session(7)["step"] == bot.WAIT_VOICE


def test_сбой_движка_не_роняет_разговор(work, monkeypatch):
    def падаем(chat_id, text):
        raise RuntimeError("claude -p упал")

    monkeypatch.setattr(bot, "step_verbatim", падаем)
    bot.save_session(7, {"step": bot.WAIT_TEXT})

    msg = _Msg("Мой текст.")
    asyncio.run(bot.on_message(_Update(msg), None))

    assert "claude -p упал" in msg.replies[-1]
    assert bot.load_session(7)["step"] == bot.WAIT_TEXT


# --- шаг 7/8: готовность и повторный цикл --------------------------------------

def test_создать_ролик_сохраняет_профиль_и_показывает_новый_ролик(work, monkeypatch):
    вызовы = []
    monkeypatch.setattr(bot, "save_client_profile", lambda chat_id, s: вызовы.append(chat_id))
    bot.save_session(7, {"step": bot.READY, "scenario": SCENARIO,
                         "photo": {"asset_id": "a1", "file": "ф.jpg"}, "voice_id": "voice-1"})

    msg = _Msg()
    _press("build", msg)

    assert вызовы == [7]
    s = bot.load_session(7)
    assert s["step"] == bot.DONE
    assert msg.replies[-1] == bot.DONE_MSG
    assert "Новый ролик" in _labels(msg.markups[-1])
