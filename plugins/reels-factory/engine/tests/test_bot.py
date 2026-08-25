import asyncio
import json
import logging
import re

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
        self.photos = []

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

    async def reply_photo(self, photo, caption=None, reply_markup=None):
        self.photos.append((photo, caption, reply_markup))
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
        self.markups = []
        self.videos = []
        self.audios = []

    async def send_message(self, chat_id, text, reply_markup=None):
        self.messages.append((chat_id, text))
        self.markups.append(reply_markup)

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
        "gender": "male",
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
    сценарий остаются, двигается только позиция в разговоре. Написанный
    сценарий возвращает человека к нему же: сброс в начало заставил бы
    присылать материал и ждать текст заново."""
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

    assert s["step"] == bot.REVIEW
    assert s["voices"] == {"ru": "voice-1", "kk": "voice-kk"}
    assert s["photo"] == {"asset_id": "a1", "file": "ф.jpg"}
    assert s["scenario"] == SCENARIO


def test_сессия_с_убранного_экрана_цены_не_остаётся_в_тупике(work):
    """Шага «экран цены» в продукте больше нет. Сессия, стоявшая на нём,
    обязана оказаться на живом экране: сценарий утверждён — выбор пути,
    иначе — сводка принятого материала. Ни материал, ни язык, ни фото при
    этом не теряются: человек прислал их до того, как шаг исчез, и присылать
    заново ему нечего."""
    _старая_сессия(7, {
        "step": "confirm_price",
        "language": "kk",
        "gender": "female",
        "photo": {"asset_id": "a1", "file": "ф.jpg"},
        "voices": {"kk": "voice-kk"},
        "material_mode": "raw",
        "material_text": "сырьё про продажи",
    })

    s = bot.load_session(7)

    assert s["step"] == bot.VIEWING_STAGE and s["stage"] == bot.STAGE_MATERIAL
    assert s["language"] == "kk" and s["gender"] == "female"
    assert s["material_mode"] == "raw"
    assert s["material_text"] == "сырьё про продажи"
    assert s["photo"] == {"asset_id": "a1", "file": "ф.jpg"}
    assert s["voices"] == {"kk": "voice-kk"}

    _старая_сессия(8, {
        "step": "confirm_price",
        "language": "ru",
        "material_mode": "raw",
        "material_text": "сырьё про продажи",
        "scenario": SCENARIO,
        "scenario_approved": True,
    })
    s8 = bot.load_session(8)
    assert s8["step"] == bot.READY and s8["scenario"] == SCENARIO

    # Сценарий есть, но человек его не утверждал: вести к деньгам мимо текста
    # нечестно — сначала пусть прочитает и скажет «Утвердить».
    _старая_сессия(9, {
        "step": "confirm_price",
        "language": "ru",
        "material_mode": "raw",
        "material_text": "сырьё про продажи",
        "scenario": SCENARIO,
    })
    assert bot.load_session(9)["step"] == bot.REVIEW


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


# --- откуда пришёл человек ----------------------------------------------------

class _Ctx:
    """Контекст телеграма: хвост ссылки `?start=<метка>` приезжает в args."""

    def __init__(self, *args):
        self.args = list(args)


def test_метка_из_ссылки_запоминается(work):
    asyncio.run(bot.cmd_start(_Update(_Msg()), _Ctx("anadeko")))

    assert bot.load_session(7)["source"] == "anadeko"


def test_первая_метка_остаётся_при_переходе_по_другой_ссылке(work):
    asyncio.run(bot.cmd_start(_Update(_Msg()), _Ctx("bk5")))
    asyncio.run(bot.cmd_start(_Update(_Msg()), _Ctx("reforma")))

    assert bot.load_session(7)["source"] == "bk5"


def test_метка_переживает_start_и_новый_ролик(work):
    asyncio.run(bot.cmd_start(_Update(_Msg()), _Ctx("reforma")))
    _press("reel_language:ru", _Msg())

    asyncio.run(bot.cmd_start(_Update(_Msg()), None))
    assert bot.load_session(7)["source"] == "reforma"

    asyncio.run(bot.cmd_new(_Update(_Msg()), None))
    assert bot.load_session(7)["source"] == "reforma"


def test_обычный_start_без_ссылки_метку_не_ставит(work):
    asyncio.run(bot.cmd_start(_Update(_Msg()), _Ctx()))

    assert "source" not in bot.load_session(7)


def test_метка_попадает_в_событие_start_воронки(work):
    """Отчёт «кто и сколько пришло» режется по detail события start."""
    asyncio.run(bot.cmd_start(_Update(_Msg()), _Ctx("anadeko")))

    with bot._events()._connect() as conn:
        rows = conn.execute(
            "SELECT event, detail FROM events WHERE event = 'start'"
        ).fetchall()
    assert [(r["event"], r["detail"]) for r in rows] == [("start", "anadeko")]


@pytest.mark.parametrize("mark,expected", [
    ("anadeko", "anadeko"),
    ("BK5", "bk5"),                      # ссылку могли написать в верхнем регистре
    ("re forma", None),                  # пробел — не метка
    ("../../etc", None),                 # чужой ввод в файл сессии не едет
    ("a" * 40, None),
    ("", None),
])
def test_метка_чистится(mark, expected):
    assert bot.parse_source([mark]) == expected


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


def test_после_выбора_казахского_новичка_спрашивают_пол(work):
    asyncio.run(bot.cmd_start(_Update(_Msg()), None))
    msg = _Msg()

    _press("reel_language:kk", msg)

    s = bot.load_session(7)
    assert s["language"] == "kk"
    assert s["step"] == bot.CHOOSING_GENDER
    assert msg.replies[-1] == bot.ASK_GENDER
    assert _labels(msg.markups[-1]) == ["Мужской", "Женский"]


def test_пол_спрашивают_заново_на_каждом_ролике(work):
    """Ведущего человек меняет от ролика к ролику — прежний пол не наследуем."""
    bot.save_session(7, _паспорт(step=bot.DONE))
    msg = _Msg()

    asyncio.run(bot.cmd_new(_Update(msg), None))
    _press("reel_language:ru", msg)

    assert "gender" not in bot.load_session(7)
    assert msg.replies[-1] == bot.ASK_GENDER


def test_выбранный_пол_отмечен_галочкой(work):
    bot.save_session(7, {"step": bot.CHOOSING_GENDER, "language": "ru"})
    msg = _Msg()

    _press("reel_gender:female", msg)

    assert bot.load_session(7)["gender"] == "female"
    assert _labels(msg.markups[-2]) == ["Мужской", "Женский ✅", "Продолжить →"]


def test_смена_пола_на_готовом_сценарии_переспрашивает(work):
    """Текст написан под род прежнего ведущего — другому он уже не подходит.
    Но стирать его молча по одному тапу нельзя: сначала вопрос, и до ответа
    ни пол, ни сценарий не меняются."""
    bot.save_session(7, _паспорт(step=bot.VIEWING_STAGE, stage="gender",
                                 scenario=SCENARIO))
    msg = _Msg()

    _press("reel_gender:female", msg)

    s = bot.load_session(7)
    assert s["gender"] == "male"
    assert s["scenario"] == SCENARIO
    assert "женский" in msg.replies[-1] and "мужской" in msg.replies[-1]
    assert _labels(msg.markups[-1]) == ["Да", "Нет"]


def test_смена_пола_без_сценария_не_переспрашивает(work):
    """Терять нечего — вопрос был бы лишним экраном на пустом месте."""
    bot.save_session(7, _паспорт(step=bot.VIEWING_STAGE, stage="gender"))
    msg = _Msg()

    _press("reel_gender:female", msg)

    assert bot.load_session(7)["gender"] == "female"


def test_отказ_от_смены_пола_возвращает_на_прежний_экран(work):
    """«Нет» обязано вернуть ровно туда, где человек стоял, — иначе отмена
    случайного тапа сама становится потерей места в разговоре."""
    bot.save_session(7, _паспорт(step=bot.READY, scenario=SCENARIO,
                                 scenario_approved=True))
    _press("reel_gender:female", _Msg())

    msg = _Msg()
    _press("switch:gender:no", msg)

    s = bot.load_session(7)
    assert s["gender"] == "male"
    assert s["scenario"] == SCENARIO and s["scenario_approved"] is True
    assert s["step"] == bot.READY
    assert "switch" not in s


def test_согласие_на_смену_пола_пишет_сценарий_заново(work, monkeypatch):
    """«Да» названо в вопросе ценой: прежний текст пропадает, новый пишется
    под новый голос — и род доезжает до генерации."""
    захвачено = {}
    monkeypatch.setattr(
        bot, "step_scenario",
        lambda chat_id, idea, language, gender=None: захвачено.update(
            idea=idea, gender=gender
        ) or {"mode": "generated", "language": language,
              "blocks": [{"role": "hook", "start": 0, "end": 1,
                          "speech": "Новая реплика."}]},
    )
    bot.save_session(7, _паспорт(
        step=bot.REVIEW, scenario=SCENARIO, scenario_idea=1,
        ideas=[{"idea": "первая"}, {"idea": "вторая"}],
    ))
    _press("reel_gender:female", _Msg())

    msg = _Msg()
    _press("switch:gender:yes", msg)

    s = bot.load_session(7)
    assert s["gender"] == "female"
    assert захвачено == {"idea": {"idea": "вторая"}, "gender": "female"}
    assert s["scenario"]["blocks"][0]["speech"] == "Новая реплика."
    assert "scenario_approved" not in s


def test_смена_языка_на_готовом_сценарии_переводит_его(work, monkeypatch):
    """Язык сессии сам по себе текст не переводит: раньше сборка падала на
    несовпадении языков ошибкой, которую человек не мог понять."""
    monkeypatch.setattr(
        bot, "step_translate",
        lambda chat_id, scenario, language: {
            **scenario, "language": language,
            "blocks": [dict(b, speech="Сәлем.") for b in scenario["blocks"]],
        },
    )
    bot.save_session(7, _паспорт(step=bot.READY, scenario=SCENARIO,
                                 scenario_approved=True))
    _press("reel_language:kk", _Msg())

    assert bot.load_session(7)["language"] == "ru"

    msg = _Msg()
    _press("switch:language:yes", msg)

    s = bot.load_session(7)
    assert s["language"] == "kk"
    assert s["scenario"]["language"] == "kk"
    assert s["scenario"]["blocks"][0]["speech"] == "Сәлем."
    # Перевод — другой текст: прежнее утверждение относилось не к нему.
    assert "scenario_approved" not in s
    assert s["step"] == bot.REVIEW


def test_отказ_от_смены_языка_оставляет_сценарий_и_язык(work):
    bot.save_session(7, _паспорт(step=bot.READY, scenario=SCENARIO,
                                 scenario_approved=True))
    _press("reel_language:kk", _Msg())

    msg = _Msg()
    _press("switch:language:no", msg)

    s = bot.load_session(7)
    assert s["language"] == "ru"
    assert s["scenario"] == SCENARIO and s["scenario_approved"] is True
    assert s["step"] == bot.READY


def test_назад_с_фото_показывает_выбранный_пол(work):
    bot.save_session(7, {"step": bot.WAIT_PHOTO, "language": "ru",
                         "gender": "male"})
    msg = _Msg()

    _press("back", msg)

    s = bot.load_session(7)
    assert s["step"] == bot.VIEWING_STAGE and s["stage"] == "gender"
    assert "Мужской ✅" in _labels(msg.markups[-1])


def test_пол_доезжает_до_генерации_сценария(work, monkeypatch):
    """Иначе модель не знает рода и пишет мужчине «сделала»."""
    захвачено = {}
    monkeypatch.setattr(
        bot, "run_generated_path",
        lambda workdir, idea, runner, language, gender=None: (
            захвачено.update(language=language, gender=gender)
            or {"scenario": SCENARIO}
        ),
    )
    monkeypatch.setattr(bot, "_charge_claude", lambda chat_id, runner: None)

    bot.step_scenario(7, {"idea": "тема"}, "ru", "female")

    assert захвачено == {"language": "ru", "gender": "female"}


def test_после_пола_новичка_просят_фото(work):
    asyncio.run(bot.cmd_start(_Update(_Msg()), None))
    msg = _Msg()

    _press("reel_language:kk", msg)
    _press("reel_gender:male", msg)

    s = bot.load_session(7)
    assert s["gender"] == "male"
    assert s["step"] == bot.WAIT_PHOTO
    assert "двойника" in msg.replies[-1]


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
    monkeypatch.setattr(bot, "step_demo", _fake_step_demo)
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
    # язык отмечен галочкой на месте, следом спрашивается пол
    assert selected["step"] == bot.CHOOSING_GENDER
    assert "🇰🇿 Қазақша ✅" in _labels(ask.markups[-2])
    _press("reel_gender:male", ask)
    _press("stage:next", ask)   # фото уже есть
    _press("stage:next", ask)   # казахской записи нет — просят её
    assert bot.load_session(7)["step"] == bot.WAIT_VOICE
    assert "🇰🇿 Қазақша" in ask.replies[-1]

    asyncio.run(bot.on_message(_Update(_Msg(voice=object())), None))
    recorded = bot.load_session(7)
    # Клон нового языка делается сразу — ради бесплатного демо двойника.
    # Русский голос при этом остаётся нетронутым.
    assert captured_languages == ["kk"]
    assert recorded["voices"] == {"ru": "voice-ru", "kk": "voice-kk"}
    assert not recorded["voice_pending"]
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
    assert current["step"] == bot.CHOOSING_GENDER
    assert current["voice_id"] == "voice-ru"
    assert current["voice_language"] == "ru"
    assert "🇷🇺 Русский ✅" in _labels(msg.markups[-2])


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
    bot.save_session(7, {"step": bot.CHOOSING, "language": "ru",
                         "gender": "male"})
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

def test_готовый_текст_сразу_превращается_в_сценарий(work, monkeypatch):
    """Сценарий человеку бесплатен: экрана цены между материалом и текстом
    больше нет, о деньгах разговор пойдёт на выборе пути."""
    monkeypatch.setattr(
        bot, "step_verbatim", lambda chat_id, text, language: SCENARIO
    )
    monkeypatch.setattr(bot, "save_client_profile", lambda chat_id, s: None)
    bot.save_session(7, _паспорт(step=bot.WAIT_TEXT))   # баланс нулевой

    msg = _Msg("Мой текст.")
    asyncio.run(bot.on_message(_Update(msg), None))

    assert msg.replies[0] == bot.MATERIAL_ACCEPTED_MSG
    assert "[хук]" in msg.replies[-1]
    s = bot.load_session(7)
    assert s["step"] == bot.REVIEW and s["scenario"] == SCENARIO
    assert s["material_text"] == "Мой текст."


def test_сырьё_сразу_превращается_в_список_идей(work, monkeypatch):
    ideas = [{"idea": "Раз", "draft_hook": "Хук раз"},
             {"idea": "Два", "draft_hook": "Хук два"}]
    вызовы = []

    def fake_ideas(chat_id, text, language):
        вызовы.append(text)
        return ideas

    monkeypatch.setattr(bot, "step_ideas", fake_ideas)
    monkeypatch.setattr(bot, "save_client_profile", lambda chat_id, s: None)
    bot.save_session(7, _паспорт(
        step=bot.WAIT_RAW, language="kk",
        voices={"kk": "voice-kk"}, voice_id="voice-kk", voice_language="kk",
    ))

    msg = _Msg("Длинное сырьё про продажи.")
    asyncio.run(bot.on_message(_Update(msg), None))

    assert вызовы == ["Длинное сырьё про продажи."]
    assert msg.replies[0] == bot.MATERIAL_ACCEPTED_MSG
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


def test_назад_с_выбора_пути_показывает_сценарий(work):
    """С экрана выбора «Назад» ведёт к тексту, по которому человек и решает,
    заказывать ли ролик, — а не к пустому вводу материала."""
    bot.save_session(7, _паспорт(step=bot.READY, scenario=SCENARIO,
                                 scenario_approved=True, material_mode="raw",
                                 material_text="Длинное сырьё про продажи."))

    msg = _Msg()
    _press("back", msg)

    assert bot.load_session(7)["step"] == bot.REVIEW
    assert "[хук]" in msg.replies[-1]


def test_вперёд_с_материала_показывает_готовый_сценарий_а_не_зовёт_клода(
        work, monkeypatch):
    """«Вперёд →» приходит и с кнопки, висящей в истории чата. Сценарий уже
    написан — второй прогон Клода дал бы другой текст и стоил бы нам ещё раз."""
    вызовы = []
    monkeypatch.setattr(
        bot, "step_verbatim", lambda chat_id, text, language: вызовы.append(text)
    )
    bot.save_session(7, _паспорт(step=bot.VIEWING_STAGE, stage="material",
                                 material_mode="raw", material_text="сырьё",
                                 scenario=SCENARIO))

    msg = _Msg()
    _press("stage:next", msg)

    s = bot.load_session(7)
    assert вызовы == []
    assert s["step"] == bot.REVIEW and s["material_text"] == "сырьё"
    assert "[хук]" in msg.replies[-1]


def test_вперёд_с_материала_после_утверждения_ведёт_к_выбору_пути(work):
    bot.save_session(7, _паспорт(step=bot.VIEWING_STAGE, stage="material",
                                 material_mode="raw", material_text="сырьё",
                                 scenario=SCENARIO, scenario_approved=True))

    msg = _Msg()
    _press("stage:next", msg)

    assert bot.load_session(7)["step"] == bot.READY
    assert msg.replies[-1].startswith(bot.READY_MSG)


def test_вперёд_с_материала_без_сценария_показывает_идеи(work):
    bot.save_session(7, _паспорт(
        step=bot.VIEWING_STAGE, stage="material", material_mode="raw",
        material_text="сырьё", ideas=[{"idea": "Раз", "draft_hook": "Хук"}],
    ))

    msg = _Msg()
    _press("stage:next", msg)

    assert bot.load_session(7)["step"] == bot.CHOOSING_IDEA
    assert "1. Раз" in msg.replies[-1]


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


def test_назад_с_фото_у_новичка_возвращает_к_полу(work):
    """Пол — предыдущий этап; ещё не выбран, поэтому экран выбора, а не сводка."""
    bot.save_session(7, {"step": bot.WAIT_PHOTO, "language": "ru"})

    msg = _Msg()
    _press("back", msg)

    assert bot.load_session(7)["step"] == bot.CHOOSING_GENDER
    assert _labels(msg.markups[-1]) == ["Мужской", "Женский"]


def test_назад_с_пола_показывает_выбранный_язык(work):
    bot.save_session(7, {"step": bot.CHOOSING_GENDER, "language": "ru"})

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
    assert _labels(msg.markups[-2]) == ["🇷🇺 Русский ✅", "🇰🇿 Қазақша", "Продолжить →"]
    # пол спрашивается каждый ролик: ведущий меняется от ролика к ролику
    assert msg.replies[-1] == bot.ASK_GENDER
    _press("reel_gender:female", msg)

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
    monkeypatch.setattr(bot, "step_demo", _fake_step_demo)
    monkeypatch.setattr(bot, "save_client_profile", lambda chat_id, s: None)


def _fake_step_demo(chat_id, photo_asset_id, voice_id, language):
    """Демо без HeyGen: настоящий файл, чтобы бот смог его отправить."""
    d = bot.session_dir(chat_id) / "demo"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"demo_{language}.mp4"
    path.write_bytes(b"demo")
    return path


async def _fake_download(context, media, chat_id):
    """Скачивание телеграма: файл ложится в рабочую папку чата, как в бою."""
    d = bot.session_dir(chat_id) / "input"
    d.mkdir(parents=True, exist_ok=True)
    path = d / "медиа.bin"
    path.write_bytes(b"media")
    return path


def test_первый_ролик_требует_фото_сразу_после_пола(work, профиль):
    bot.save_session(7, {"step": bot.CHOOSING_LANGUAGE})

    msg = _Msg()
    _press("reel_language:ru", msg)
    _press("reel_gender:male", msg)

    assert bot.load_session(7)["step"] == bot.WAIT_PHOTO
    assert "двойника" in msg.replies[-1]


def test_утверждение_сценария_ведёт_сразу_к_сборке(work, профиль):
    """Фото и голос собраны до оплаты — после «Утвердить» спрашивать нечего."""
    bot.save_session(7, _паспорт(step=bot.REVIEW, scenario=SCENARIO))

    msg = _Msg()
    _press("ok", msg)

    assert bot.load_session(7)["step"] == bot.READY
    assert msg.replies[-1].startswith(bot.READY_MSG)
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
    assert msg.replies[-1] == bot.ASK_GENDER

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


def test_запись_голоса_запускает_демо_двойника(work, профиль, monkeypatch):
    """Фото и голос собраны — человек сразу видит СВОЁ демо, до экрана цены.
    Клон делается здесь же (ради демо) и переиспользуется платной частью."""
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
    assert клоны == ["ru"]
    assert s["voices"] == {"ru": "voice-новый"}
    assert not s["voice_pending"]
    assert s["demo"]["key"]
    assert s["step"] == bot.CHOOSING
    assert bot.VOICE_SAVED in голос.replies
    assert bot.DEMO_BUILDING_MSG in голос.replies
    # Само демо ушло видео с подписью «двойник готов»
    assert [c for _, c, _ in голос.videos] == [bot.DEMO_READY_MSG]


def test_демо_не_повторяется_на_том_же_фото_и_записи(work, профиль, monkeypatch):
    """Тот же вход — тот же результат: повторной генерации (и трат) нет."""
    демо = []
    monkeypatch.setattr(
        bot, "step_demo",
        lambda *a: демо.append(a) or _fake_step_demo(*a),
    )
    bot.save_session(7, {"step": bot.WAIT_PHOTO, "language": "ru"})
    asyncio.run(bot.on_message(_Update(_Msg(photo=[object()])), None))
    asyncio.run(bot.on_message(_Update(_Msg(voice=object())), None))
    assert len(демо) == 1

    # Человек перезаписал голос той же записью — демо не перегенерилось.
    msg = _Msg()
    _press("stage:prev", msg)
    _press("stage:edit", msg)
    asyncio.run(bot.on_message(_Update(_Msg(voice=object())), None))
    assert len(демо) == 1


def test_сводка_фото_показывает_само_сохранённое_фото(work, tmp_path):
    """Голое «✅ Фото загружено» рядом с примером читалось как «бот засчитал
    пример за моё фото» — показываем, что именно сохранено."""
    фото = tmp_path / "моё.jpg"
    фото.write_bytes(b"jpg")
    s = _паспорт(photo={"asset_id": "asset-1", "file": str(фото)})
    bot.save_session(7, s)

    msg = _Msg()
    asyncio.run(bot._show_stage(msg, 7, s, bot.STAGE_PHOTO))

    assert [c for _, c, _ in msg.photos] == [bot.PHOTO_SUMMARY_CAPTION]


def test_сводка_фото_без_файла_остаётся_текстом(work):
    """Файл мог не пережить перенос сервера — сводка не должна падать."""
    s = _паспорт()  # photo.file указывает на несуществующий «фото.jpg»
    bot.save_session(7, s)

    msg = _Msg()
    asyncio.run(bot._show_stage(msg, 7, s, bot.STAGE_PHOTO))

    assert msg.photos == []
    assert "Фото загружено" in msg.replies[-1]


class _FakeJobs:
    """JobStore ровно в объёме демо-лимита."""

    def __init__(self, latest=None):
        self._latest = latest

    def latest_for_chat(self, chat_id):
        return self._latest

    def active_for_chat(self, chat_id):
        return None


def test_демо_не_генерится_тому_кто_уже_заказывал_ролик(work, профиль, monkeypatch):
    """Клиент знает, как выглядит его аватар, — генерация только жгла бы деньги."""
    демо = []
    monkeypatch.setattr(
        bot, "step_demo", lambda *a: демо.append(a) or _fake_step_demo(*a)
    )
    monkeypatch.setattr(bot, "_job_store", lambda: _FakeJobs(latest=object()))
    bot.save_session(7, {"step": bot.WAIT_PHOTO, "language": "ru"})

    asyncio.run(bot.on_message(_Update(_Msg(photo=[object()])), None))
    asyncio.run(bot.on_message(_Update(_Msg(voice=object())), None))

    assert демо == []
    assert bot.load_session(7)["step"] == bot.CHOOSING


def test_старый_лид_без_покупок_получает_демо_на_выборе_пути(
        work, профиль, monkeypatch, tmp_path):
    """Фото и запись остались с захода до появления демо — человек его не
    видел. На выборе пути демо догоняет его, но только один раз."""
    демо = []
    monkeypatch.setattr(
        bot, "step_demo", lambda *a: демо.append(a) or _fake_step_demo(*a)
    )
    запись = tmp_path / "запись.ogg"
    запись.write_bytes(b"voice")
    bot.save_session(7, _паспорт(
        step=bot.VIEWING_STAGE, stage="voice",
        voice_samples={"ru": str(запись)},
    ))

    msg = _Msg()
    _press("stage:next", msg)

    assert len(демо) == 1
    assert bot.load_session(7)["demo"]["key"]
    assert [c for _, c, _ in msg.videos] == [bot.DEMO_READY_MSG]

    # Второй заход на тот же экран — повторной генерации нет.
    msg2 = _Msg()
    _press("stage:prev", msg2)
    _press("stage:next", msg2)
    assert len(демо) == 1


def test_упавшее_демо_не_останавливает_разговор(work, профиль, monkeypatch):
    """Демо — подарок, а не ворота: HeyGen упал — идём дальше без демо."""
    def падаем(*a):
        raise RuntimeError("HeyGen отказал")

    monkeypatch.setattr(bot, "step_demo", падаем)
    bot.save_session(7, {"step": bot.WAIT_PHOTO, "language": "ru"})
    asyncio.run(bot.on_message(_Update(_Msg(photo=[object()])), None))

    голос = _Msg(voice=object())
    asyncio.run(bot.on_message(_Update(голос), None))

    s = bot.load_session(7)
    # Попытка помечена, хотя видео не вышло: иначе каждая следующая реплика в
    # чат запускала бы платный рендер заново, за наш счёт.
    assert s["demo"]["failed"]
    assert "file" not in s["demo"]
    assert s["step"] == bot.CHOOSING  # выбор пути открылся как обычно
    assert голос.videos == []


def test_упавшее_демо_не_повторяется_само(work, профиль, monkeypatch):
    """Пометка только успеха означала бы платный рендер на каждое сообщение."""
    попытки = []

    def падаем(*a):
        попытки.append(a)
        raise RuntimeError("HeyGen отказал")

    monkeypatch.setattr(bot, "step_demo", падаем)
    bot.save_session(7, {"step": bot.WAIT_PHOTO, "language": "ru"})
    asyncio.run(bot.on_message(_Update(_Msg(photo=[object()])), None))
    asyncio.run(bot.on_message(_Update(_Msg(voice=object())), None))
    assert len(попытки) == 1

    # Разговор продолжается: любая реплика проходит мимо демо.
    asyncio.run(bot.on_message(_Update(_Msg(text="ещё раз")), None))
    _press("mode:text", _Msg())
    assert len(попытки) == 1


def test_клон_делается_перед_сценарием_и_старый_удаляется(work, monkeypatch,
                                                          tmp_path):
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
    bot.save_session(7, _паспорт(
        step=bot.WAIT_TEXT,
        material_mode="text",
        voices={"ru": "voice-старый"},
        voice_id="voice-старый",
        voice_samples={"ru": str(запись)},
        voice_pending={"ru": str(запись)},
    ))

    asyncio.run(bot.on_message(_Update(_Msg("Мой текст.")), None))

    s = bot.load_session(7)
    assert s["voices"] == {"ru": "voice-новый"}
    assert not s["voice_pending"]
    assert удалённые == ["voice-старый"]  # только после успеха нового
    assert s["step"] == bot.REVIEW


def test_копия_голоса_перед_сценарием_делается_молча(work, monkeypatch, tmp_path):
    """Человек прислал текст и ждёт сценария; согласия на работу он ещё не
    давал. «Делаю голос…» на этом месте читается как начатая без спроса работа
    — и рушит доверие к порядку шагов раньше, чем прозвучит «Утверждаем?».
    Клон при этом делается: он молчит, а не отменён."""
    запись = tmp_path / "запись.ogg"
    запись.write_bytes(b"voice")
    monkeypatch.setattr(
        bot, "step_voice", lambda chat_id, path, language: "voice-новый"
    )
    monkeypatch.setattr(
        bot, "step_verbatim", lambda chat_id, text, language: SCENARIO
    )
    bot.save_session(7, _паспорт(
        step=bot.WAIT_TEXT,
        material_mode="text",
        voices={},
        voice_id=None,
        voice_samples={"ru": str(запись)},
        voice_pending={"ru": str(запись)},
    ))

    msg = _Msg("Мой текст.")
    asyncio.run(bot.on_message(_Update(msg), None))

    assert bot.CLONING_VOICE_MSG not in msg.replies
    assert bot.load_session(7)["voices"] == {"ru": "voice-новый"}
    assert SCENARIO["title"] in msg.replies[-1]   # сценарий показан
    assert bot.load_session(7)["step"] == bot.REVIEW


def test_копия_голоса_на_кнопке_пути_объявлена(work, клиент, monkeypatch,
                                               tmp_path):
    """На кнопке пути человек уже согласился платить и ждёт работы: молчание
    здесь оставило бы минуту тишины без причины."""
    запись = tmp_path / "запись.ogg"
    запись.write_bytes(b"voice")
    monkeypatch.setattr(
        bot, "step_voice", lambda chat_id, path, language: "voice-1"
    )
    bot.save_session(7, _паспорт(
        step=bot.READY, scenario=SCENARIO, scenario_approved=True,
        voices={}, voice_id=None,
        voice_samples={"ru": str(запись)}, voice_pending={"ru": str(запись)},
    ))

    msg = _Msg()
    _press("build:plain", msg)

    assert bot.CLONING_VOICE_MSG in msg.replies


def test_ошибка_копии_голоса_перед_сценарием_видна_человеку(work, monkeypatch,
                                                            tmp_path):
    """Молчит объявление, а не ошибка: без неё человека просят перезаписать
    голос без единого слова о том, почему."""
    запись = tmp_path / "запись.ogg"
    запись.write_bytes(b"voice")

    def падаем(chat_id, path, language):
        raise RuntimeError("ElevenLabs отказал")

    monkeypatch.setattr(bot, "step_voice", падаем)
    bot.save_session(7, _паспорт(
        step=bot.WAIT_TEXT,
        material_mode="text",
        voices={},
        voice_id=None,
        voice_samples={"ru": str(запись)},
        voice_pending={"ru": str(запись)},
    ))

    msg = _Msg("Мой текст.")
    asyncio.run(bot.on_message(_Update(msg), None))

    assert bot.CLONING_VOICE_MSG not in msg.replies
    assert any("ElevenLabs отказал" in ответ for ответ in msg.replies)
    assert bot.ASK_VOICE in msg.replies[-1]


def test_новая_запись_клонируется_и_на_кнопке_пути(work, клиент, monkeypatch,
                                                   tmp_path):
    """Клон делается на демо, а демо получает только новичок. Кто прислал
    запись позже, доходил до кнопки пути без голоса и упирался в «профиль не
    найден» вместо сборки."""
    запись = tmp_path / "запись.ogg"
    запись.write_bytes(b"voice")
    # Клон отдаёт тот же voice_id, что записан в профиле фикстуры: иначе job
    # отвалится не из-за отсутствия голоса, а из-за расхождения с профилем.
    monkeypatch.setattr(
        bot, "step_voice", lambda chat_id, path, language: "voice-1"
    )
    bot.save_session(7, _паспорт(
        step=bot.READY, scenario=SCENARIO, scenario_approved=True,
        voices={}, voice_id=None,
        voice_samples={"ru": str(запись)}, voice_pending={"ru": str(запись)},
    ))

    msg = _Msg()
    _press("build:plain", msg)

    s = bot.load_session(7)
    assert s["voices"] == {"ru": "voice-1"}
    assert bot.CLIENT_NOT_FOUND_MSG not in msg.replies
    assert bot._job_store().latest_for_chat(7) is not None


def test_упавший_клон_при_демо_не_теряет_прежний_голос(work, профиль, monkeypatch):
    """Перезапись при готовом клоне: новый клон делается сразу (ради демо),
    но если он упал — прежний голос остаётся рабочим, а запись pending."""
    удалённые = []
    monkeypatch.setattr(bot, "step_delete_voice", lambda vid: удалённые.append(vid))

    def падаем(chat_id, path, language):
        raise RuntimeError("ElevenLabs отказал")

    monkeypatch.setattr(bot, "step_voice", падаем)
    bot.save_session(7, _паспорт(step=bot.VIEWING_STAGE, stage="voice"))

    msg = _Msg()
    _press("stage:edit", msg)
    asyncio.run(bot.on_message(_Update(_Msg(voice=object())), None))

    s = bot.load_session(7)
    assert удалённые == []
    assert s["voices"] == {"ru": "voice-1"}  # рабочий голос остаётся рабочим
    assert s["voice_pending"]["ru"]          # клон повторится на платном пути
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
    bot.save_session(7, _паспорт(
        step=bot.WAIT_TEXT,
        material_mode="text",
        voices={"ru": "voice-старый"},
        voice_id="voice-старый",
        voice_samples={"ru": str(запись)},
        voice_pending={"ru": str(запись)},
    ))

    with caplog.at_level(logging.WARNING):
        asyncio.run(bot.on_message(_Update(_Msg("Мой текст.")), None))

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
    bot.save_session(7, _паспорт(
        step=bot.WAIT_TEXT,
        material_mode="text",
        voices={},
        voice_id=None,
        voice_samples={"ru": str(запись)},
        voice_pending={"ru": str(запись)},
    ))

    msg = _Msg("Мой текст.")
    asyncio.run(bot.on_message(_Update(msg), None))

    assert сценарии == []  # Клода не зовём, раз голоса не вышло
    # По содержимому, а не по индексу: индекс считал реплики от объявления
    # «делаю голос», которого на этом шаге больше нет.
    assert any("ElevenLabs отказал" in ответ for ответ in msg.replies)
    assert bot.load_session(7)["step"] == bot.WAIT_VOICE


def test_полный_путь_новичка_видит_цену_один_раз_на_выборе_пути(work, monkeypatch):
    """Сквозной прогон: от /start до готовности к сборке. Цена звучит ровно
    один раз — на экране выбора пути; всё до него человеку бесплатно, включая
    сценарий. Клон голоса и Клод — наши затраты на витрину: они уходят раньше
    и платной частью переиспользуются без повтора."""
    вызовы = []
    monkeypatch.setattr(bot, "_download", _fake_download)
    monkeypatch.setattr(bot, "step_photo", lambda chat_id, path: "asset-новый")
    monkeypatch.setattr(
        bot, "step_voice",
        lambda chat_id, path, language: вызовы.append("голос") or "voice-1",
    )
    monkeypatch.setattr(bot, "step_demo", _fake_step_demo)
    monkeypatch.setattr(
        bot, "step_verbatim",
        lambda chat_id, text, language: вызовы.append("клод") or SCENARIO,
    )
    monkeypatch.setattr(bot, "save_client_profile", lambda chat_id, s: None)

    msg = _Msg()
    asyncio.run(bot.cmd_start(_Update(msg), None))
    assert msg.replies[-1] == bot.ASK_LANGUAGE

    _press("reel_language:ru", msg)
    _press("reel_gender:male", msg)
    assert bot.load_session(7)["step"] == bot.WAIT_PHOTO

    asyncio.run(bot.on_message(_Update(_Msg(photo=[object()])), None))
    assert bot.load_session(7)["step"] == bot.WAIT_VOICE

    asyncio.run(bot.on_message(_Update(_Msg(voice=object())), None))
    assert bot.load_session(7)["step"] == bot.CHOOSING
    assert вызовы == ["голос"]     # клон ушёл на демо; Клода ещё не было

    _press("mode:text", msg)
    _press("material:new", msg)
    материал = _Msg("Мой текст.")
    asyncio.run(bot.on_message(_Update(материал), None))
    # Сценарий пишется сразу и без единого слова о деньгах
    assert материал.replies[0] == bot.MATERIAL_ACCEPTED_MSG
    assert bot.load_session(7)["step"] == bot.REVIEW
    assert вызовы == ["голос", "клод"]   # клон не повторился
    assert "$" not in " ".join(материал.replies)

    _press("ok", материал)
    s = bot.load_session(7)
    assert s["step"] == bot.READY and s["voice_id"] == "voice-1"
    # Единственный экран с ценой: обе на кнопках, баланс строкой
    assert "Баланс: " in материал.replies[-1]
    assert sum("$" in подпись for подпись in _labels(материал.markups[-1])) == 2

    # тот же прогон должен читаться воронкой без пропусков
    воронка = {r["event"]: r["count"] for r in bot._events().funnel()}
    for шаг in ("start", "stage:language", "stage:gender", "stage:photo",
                "stage:voice", "demo_started", "demo_sent", "stage:material",
                "generation_started", "scenario_shown", "scenario_approved",
                "price_shown"):
        assert воронка[шаг] == 1, шаг
    assert воронка["balance_ok"] == 0       # кнопку пути ещё не нажимали
    assert воронка["reel_delivered"] == 0   # ролик ещё не собирали


def test_второй_ролик_считается_новым_циклом(work, monkeypatch):
    """Иначе воронка покажет «оплат больше, чем стартов»."""
    monkeypatch.setattr(bot, "_download", _fake_download)
    bot.save_session(7, _паспорт(step=bot.DONE))

    asyncio.run(bot.cmd_new(_Update(_Msg()), None))

    assert bot.load_session(7)["cycle"] == 1
    воронка = {r["event"]: r["count"] for r in bot._events().funnel()}
    assert воронка["start"] == 1

    bot.save_session(7, {**bot.load_session(7), "step": bot.DONE})
    asyncio.run(bot.cmd_new(_Update(_Msg()), None))

    assert bot.load_session(7)["cycle"] == 2
    воронка = {r["event"]: r["count"] for r in bot._events().funnel()}
    assert воронка["start"] == 2
    assert bot._events().totals()["chats"] == 1


def test_stats_молчит_для_обычного_пользователя(work, monkeypatch):
    monkeypatch.delenv("ADMIN_CHAT_IDS", raising=False)
    msg = _Msg("/stats")

    asyncio.run(bot.cmd_stats(_Update(msg), None))

    assert msg.replies == []


def test_stats_показывает_воронку_админу(work, monkeypatch):
    monkeypatch.setenv("ADMIN_CHAT_IDS", "7")
    bot._events().record(7, 1, "start")
    bot._events().record(7, 1, "stage:language")
    msg = _Msg("/stats 30")

    asyncio.run(bot.cmd_stats(_Update(msg), None))

    assert "Воронка за 30 дн." in msg.replies[-1]
    assert "Запустили бота: 1" in msg.replies[-1]
    assert "Выбрали язык: 1 (100%)" in msg.replies[-1]


def test_возврат_кнопкой_назад_не_считается_новым_запуском(work):
    bot.save_session(7, _паспорт(step=bot.CHOOSING_MATERIAL, cycle=1))

    msg = _Msg()
    _press("back", msg)

    воронка = {r["event"]: r["count"] for r in bot._events().funnel()}
    assert воронка["start"] == 0     # «Назад» — не новый заход
    assert bot.load_session(7)["cycle"] == 1


def test_сбой_движка_не_роняет_разговор(work, monkeypatch):
    def падаем(chat_id, text, language):
        raise RuntimeError("claude -p упал")

    monkeypatch.setattr(bot, "step_verbatim", падаем)
    monkeypatch.setattr(bot, "save_client_profile", lambda chat_id, s: None)
    bot.save_session(7, _паспорт(step=bot.WAIT_TEXT, material_mode="text"))

    msg = _Msg("Мой текст.")
    asyncio.run(bot.on_message(_Update(msg), None))

    assert "claude -p упал" in msg.replies[-1]
    # материал принят и не потерян: человек вернётся к нему кнопкой
    assert bot.load_session(7)["material_text"] == "Мой текст."


def _себестоимость_клода(chat_id: int) -> int:
    """Сколько Клод стоил НАМ по журналу: сумма cost_micro всех его строк.

    Читаем таблицу напрямую: с бесплатным для человека сценарием баланс
    больше не показывает эту трату, а потерять её из отчётов нельзя — публичного
    читателя журнала у LedgerStore нет."""
    import sqlite3

    conn = sqlite3.connect(str(bot._ledger().db_path))
    try:
        return int(conn.execute(
            "SELECT COALESCE(SUM(cost_micro), 0) FROM spend_log"
            " WHERE chat_id = ? AND provider = 'claude'", (chat_id,)
        ).fetchone()[0])
    finally:
        conn.close()


def test_провал_step_verbatim_после_ретраев_всё_равно_пишет_себестоимость(
    work, monkeypatch
):
    """Fix 1: раньше _charge_claude звался ТОЛЬКО после успешного возврата.
    scenario.py поднимает ScenarioError после исчерпанных ретраев — а ретраи
    жгут Клода больше, чем успех. Такой провал должен попасть в журнал так же,
    как и успех, иначе трата остаётся вне отчётов."""
    from reels_factory.billing import claude_cost_micro

    def fake_run_verbatim_path(workdir, text, runner, language):
        runner.total_cost_usd = 0.04  # деньги на Клод уже потрачены
        raise bot.ScenarioError("исчерпаны ретраи (2): судья не пропустил")

    monkeypatch.setattr(bot, "run_verbatim_path", fake_run_verbatim_path)

    with pytest.raises(bot.ScenarioError):
        bot.step_verbatim(7, "текст", "ru")

    assert _себестоимость_клода(7) == claude_cost_micro(0.04)


def test_сценарий_человеку_бесплатен_но_из_журнала_не_пропадает(work, monkeypatch):
    """Сценарий — витрина: по нему человек решает, заказывать ли ролик, и
    платить за него мы не просим. Себестоимость при этом настоящая, иначе
    ролик в отчётах выглядел бы дешевле, чем стоил."""
    from reels_factory.billing import claude_cost_micro

    def fake_run_verbatim_path(workdir, text, runner, language):
        runner.total_cost_usd = 0.04
        return {"scenario": SCENARIO}

    monkeypatch.setattr(bot, "run_verbatim_path", fake_run_verbatim_path)

    bot.step_verbatim(7, "текст", "ru")

    assert bot._ledger().balance(7) == 0            # с человека не списано
    assert _себестоимость_клода(7) == claude_cost_micro(0.04)


def test_провал_step_ideas_после_ретраев_всё_равно_пишет_себестоимость(
    work, monkeypatch
):
    from reels_factory.billing import claude_cost_micro

    def fake_run_ideas(workdir, text, runner, language):
        runner.total_cost_usd = 0.02
        raise bot.ScenarioError("ожидалось 2-3 идеи, получено: []")

    monkeypatch.setattr(bot, "run_ideas", fake_run_ideas)

    with pytest.raises(bot.ScenarioError):
        bot.step_ideas(7, "сырьё", "ru")

    assert _себестоимость_клода(7) == claude_cost_micro(0.02)


def test_провал_step_scenario_после_ретраев_всё_равно_пишет_себестоимость(
    work, monkeypatch
):
    from reels_factory.billing import claude_cost_micro

    def fake_run_generated_path(workdir, idea, runner, language, gender=None):
        runner.total_cost_usd = 0.03
        raise bot.ScenarioError("целостность после полировки: [...]")

    monkeypatch.setattr(bot, "run_generated_path", fake_run_generated_path)

    with pytest.raises(bot.ScenarioError):
        bot.step_scenario(7, {"idea": "тема"}, "ru")

    assert _себестоимость_клода(7) == claude_cost_micro(0.03)


def test_подготовка_сценария_под_подпиской_считается_по_токенам(work, monkeypatch):
    """Под подпиской CLI отдаёт нулевую стоимость: без запасного счёта по
    токенам работа Клода над сценарием не попадала бы в журнал вовсе, и
    себестоимость ролика выглядела бы ниже настоящей."""
    from reels_factory.billing import claude_cost_micro, claude_tokens_cost_usd

    прогоны = [{"model": "claude-sonnet-5",
                "usage": {"input_tokens": 20_000, "output_tokens": 4_000}}]

    def fake_run_verbatim_path(workdir, text, runner, language):
        runner.total_cost_usd = 0.0     # так отвечает CLI под подпиской
        runner.runs = прогоны
        return {"scenario": SCENARIO}

    monkeypatch.setattr(bot, "run_verbatim_path", fake_run_verbatim_path)

    bot.step_verbatim(7, "текст", "ru")

    по_токенам = claude_tokens_cost_usd(прогоны, bot._billing()["rates"])
    assert по_токенам > 0
    assert _себестоимость_клода(7) == claude_cost_micro(по_токенам)


def test_цена_готового_сценария_не_считает_его_же_подготовку(work):
    """К экрану выбора пути сценарий уже написан и списан своей строкой:
    вторая надбавка за него обещает человеку больше, чем спишется.

    Работа агента монтажа считается по числу проходов (`claude_montage_attempts`
    в ставках): пересдача плана — это второй полный проход, план и отбор
    бироллов заново. Множитель берём из тех же ставок, а не литералом, иначе
    тест падал бы при каждой правке ставок «не по делу»; само правило «проходов
    больше одного» проверяет test_billing."""
    from reels_factory.billing import (apply_markup, elevenlabs_cost_micro,
                                       heygen_cost_micro, to_micro)

    billing = bot._billing()
    rates = billing["rates"]
    chars = sum(len(b["speech"]) for b in SCENARIO["blocks"])
    сцена = _паспорт(step=bot.READY, scenario=SCENARIO)

    ожидаемая = apply_markup(
        heygen_cost_micro(chars / rates["chars_per_second"], rates)
        + elevenlabs_cost_micro(chars, rates)
        + to_micro(rates["claude_montage_usd_per_reel"]
                   * rates.get("claude_montage_attempts", 1)),
        billing["markup"])

    assert bot.estimate_material_micro(сцена, billing) == ожидаемая


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


def _зарегистрировать_клиента(tmp_path, monkeypatch) -> None:
    """Изолированный реестр клиентов + готовый профиль клиента чата 7, без
    единого цента на балансе. save_client_profile сам по себе читает общий
    factory/config.yaml как базу — в тестах его нет и не нужен, профиль уже
    зарегистрирован напрямую."""
    monkeypatch.setattr(clients_mod, "CLIENTS_DIR", tmp_path / "clients")
    monkeypatch.setattr(bot, "save_client_profile", lambda chat_id, s: None)
    clients_mod.register_client("7", _client_base_cfg(), voice_id="voice-1",
                                asset_id="asset-1")


@pytest.fixture
def клиент(work, tmp_path, monkeypatch):
    """Профиль клиента чата 7 и баланс с запасом: billing включён по умолчанию
    (Task 7 проверяет его в enqueue_build), а фикстуре нужен клиент, готовый
    платить, а не отдельный тест на нехватку денег — для того есть
    test_нехватки_баланса."""
    _зарегистрировать_клиента(tmp_path, monkeypatch)
    bot._ledger().credit(
        7, 1_000_000_000,
        purchase_id="клиент-fixture", amount_minor=1_000_000_00, currency="usd",
    )
    return tmp_path


@pytest.fixture
def клиент_без_денег(work, tmp_path, monkeypatch):
    """Тот же профиль, но с нулевым балансом: им проверяется всё, что человек
    видит и делает до того, как заплатил, — вплоть до сборки сразу после
    зачисления."""
    _зарегистрировать_клиента(tmp_path, monkeypatch)
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


def test_отказ_от_tts_принимает_mp3_файлом(work, клиент, monkeypatch):
    # человек уже записал озвучку в редакторе и шлёт готовый mp3 — это тот же
    # «запишу сам(а)», просто файлом, и заново диктовать его нельзя заставлять
    bot.save_session(7, {
        "step": bot.READY,
        "scenario": SCENARIO,
        "photo": {"asset_id": "a1", "file": "ф.jpg"},
        "voice_id": "voice-1",
    })
    _press("build:plain", _Msg())
    job, _api = _deliver_audio_preview()
    _press(f"audio_self:{job.job_id}", _Msg())

    monkeypatch.setattr(bot, "_download", _fake_download)
    prepared = []
    monkeypatch.setattr(
        bot,
        "prepare_user_audio",
        lambda workdir, source: prepared.append((workdir, source)) or {"ok": True},
    )
    audio_msg = _Msg()
    audio_msg.audio = type("A", (), {"file_id": "aud-1", "file_name": "voice.mp3"})()
    asyncio.run(bot.on_message(_Update(audio_msg), None))

    assert prepared and prepared[0][0] == job.workdir
    assert bot._job_store().get(job.job_id).status == "queued"
    assert bot.load_session(7)["step"] == bot.BUILDING
    assert audio_msg.replies[-1] == bot.FINAL_AUDIO_ACCEPTED


def test_отказ_от_tts_принимает_аудио_документом(work, клиент, monkeypatch):
    # «отправить как файл» в Telegram — это document, а не audio: он тоже
    # должен уходить в сборку, а не в отбивку
    bot.save_session(7, {
        "step": bot.READY,
        "scenario": SCENARIO,
        "photo": {"asset_id": "a1", "file": "ф.jpg"},
        "voice_id": "voice-1",
    })
    _press("build:plain", _Msg())
    job, _api = _deliver_audio_preview()
    _press(f"audio_self:{job.job_id}", _Msg())

    monkeypatch.setattr(bot, "_download", _fake_download)
    prepared = []
    monkeypatch.setattr(
        bot,
        "prepare_user_audio",
        lambda workdir, source: prepared.append((workdir, source)) or {"ok": True},
    )
    doc_msg = _Msg()
    doc_msg.document = type(
        "D", (),
        {"file_id": "doc-1", "file_name": "озвучка.wav", "mime_type": "audio/wav"},
    )()
    asyncio.run(bot.on_message(_Update(doc_msg), None))

    assert prepared and prepared[0][0] == job.workdir
    assert bot._job_store().get(job.job_id).status == "queued"
    assert doc_msg.replies[-1] == bot.FINAL_AUDIO_ACCEPTED


def test_не_аудио_документ_не_уходит_в_сборку_озвучки(work, клиент, monkeypatch):
    # pdf вместо озвучки: job остаётся ждать запись, ffmpeg не зовём
    bot.save_session(7, {
        "step": bot.READY,
        "scenario": SCENARIO,
        "photo": {"asset_id": "a1", "file": "ф.jpg"},
        "voice_id": "voice-1",
    })
    _press("build:plain", _Msg())
    job, _api = _deliver_audio_preview()
    _press(f"audio_self:{job.job_id}", _Msg())

    monkeypatch.setattr(bot, "_download", _fake_download)
    monkeypatch.setattr(
        bot,
        "prepare_user_audio",
        lambda workdir, source: pytest.fail("не аудио не должно идти в сборку"),
    )
    doc_msg = _Msg()
    doc_msg.document = type(
        "D", (),
        {"file_id": "doc-2", "file_name": "сценарий.pdf",
         "mime_type": "application/pdf"},
    )()
    asyncio.run(bot.on_message(_Update(doc_msg), None))

    assert bot._job_store().get(job.job_id).status == "awaiting_user_audio"
    assert bot.load_session(7)["step"] == bot.WAIT_FINAL_AUDIO
    assert "голосовое сообщение" in doc_msg.replies[-1]


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
    _с_балансом()
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
    _с_балансом()
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


def test_кнопка_с_монтажом_ставит_сборку_с_монтажом(work, клиент):
    """Кнопка перестала быть заглушкой: она ставит в очередь полный путь."""
    bot.save_session(7, {"step": bot.READY, "scenario": SCENARIO,
                         "photo": {"asset_id": "a1", "file": "ф.jpg"}, "voice_id": "voice-1"})
    msg = _Msg()

    _press("build:montage", msg)

    job = bot._job_store().latest_for_chat(7)
    assert job is not None
    assert bot.load_session(7)["montage"] is True


def test_кнопка_без_монтажа_ставит_быструю_сборку(work, клиент):
    bot.save_session(7, {"step": bot.READY, "scenario": SCENARIO,
                         "photo": {"asset_id": "a1", "file": "ф.jpg"}, "voice_id": "voice-1"})

    _press("build:plain", _Msg())

    assert bot._job_store().latest_for_chat(7) is not None
    assert bot.load_session(7)["montage"] is False


def test_старая_кнопка_build_ведёт_в_монтаж(work, клиент):
    """Инлайн-кнопки живут в чате вечно, а «build» всегда означал монтаж."""
    bot.save_session(7, {"step": bot.READY, "scenario": SCENARIO,
                         "photo": {"asset_id": "a1", "file": "ф.jpg"}, "voice_id": "voice-1"})

    _press("build", _Msg())

    assert bot._job_store().latest_for_chat(7) is not None
    assert bot.load_session(7)["montage"] is True


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
    assert msg.replies[-1].startswith(bot.READY_MSG)


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
        {"ok": False, "stage": "voice", "error":
         "D21_scene_contrast: FAIL: s-05 и s-06 идут подряд — смени положение "
         "ведущей или объедини их в одну сцену"}
    ))

    # Внутренняя причина написана агенту-сборщику: заказчику она бессмысленна,
    # чинить сцены ему нечем. Разбор остаётся в job, человеку — человеческое.
    assert "D21" not in api.messages[-1][1]
    assert "смени положение" not in api.messages[-1][1]
    assert bot.BUILD_FAILED_MSG in api.messages[-1][1]
    assert job.job_id[:8] in api.messages[-1][1]
    assert "D21" in bot._job_store().get(job.job_id).error
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

    assert bot.BUILD_FAILED_MSG in api.messages[-1][1]
    assert "subprocess" not in api.messages[-1][1]
    assert "subprocess не поднялся" in bot._job_store().get(job.job_id).error
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
    # script=False: сценарий на руках, его подготовка списана раньше и в цену
    # сборки второй раз не входит.
    expected_need = estimate_micro(chars, cfg["rates"], cfg["markup"],
                                   script=False)

    assert exc.value.need == expected_need
    assert exc.value.have == have
    assert exc.value.need > exc.value.have

    # workdir так и не появился — отказ не оставил следов на диске.
    assert not jobs_root.exists()


def _оценка_сборки(*, montage: bool = True, share: float | None = None) -> int:
    """Во сколько очередь оценит сборку SCENARIO: те же аргументы, что берёт
    enqueue_build (script=False — сценарий уже написан и списан своей строкой).

    share=None — полная цена, share=доля — цена island-пути, где ведущую
    заказывают не на весь ролик.
    """
    from reels_factory.billing import estimate_micro
    billing = bot._billing()
    chars = sum(len(b["speech"]) for b in SCENARIO["blocks"])
    kwargs = {} if share is None else {"avatar_share": share}
    return estimate_micro(chars, billing["rates"], billing["markup"],
                          montage=montage, script=False, **kwargs)


def _баланс_между_оценками() -> int:
    """Баланс строго между island-оценкой и полной: с островами сборка
    проходит, без них тот же баланс не пропускает."""
    полная = _оценка_сборки()
    с_островами = _оценка_сборки(
        share=bot._billing()["rates"]["avatar_visible_share"])
    assert с_островами < полная
    баланс = (полная + с_островами) // 2
    assert с_островами <= баланс < полная
    return баланс


def test_с_islands_оценка_меньше_и_хватает_там_где_без_них_не_хватит(
        work, tmp_path, monkeypatch):
    """Реальная проверка интеграции: аватар в кадре не весь ролик, если
    острова включены, значит оценка должна быть ниже. Баланс подобран строго
    между двумя оценками — со включёнными островами сборка проходит,
    без них тот же баланс не пропускает InsufficientBalance.
    master_audio тоже должен быть включён: run_make берёт island-путь только
    когда оба флага на (см. test_islands_без_master_audio_даёт_полную_оценку
    на случай, когда это не так).

    Баланс считаем из ставок, а не литералом: цена ролика меняется вместе со
    ставками (например, числом проходов агента), и подобранное когда-то число
    перестаёт лежать между двумя оценками — тест зеленел бы или падал не по
    делу."""
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
    баланс = _баланс_между_оценками()
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
    здесь.
    master_audio теперь включён по умолчанию (Задача 11) — здесь он должен
    быть выключен явно, иначе профиль перестаёт представлять сценарий
    "islands без master_audio", который тест и проверяет.

    Баланс должен лежать СТРОГО между island-оценкой и полной: прежние 350k
    не покрывали ни ту, ни другую, и тест зеленел бы, даже если бы код
    применял долю ведущей без master_audio — то есть ровно на том дефекте,
    ради которого он написан."""
    monkeypatch.setattr(clients_mod, "CLIENTS_DIR", tmp_path / "clients")
    monkeypatch.setattr(bot, "save_client_profile", lambda chat_id, s: None)
    clients_mod.register_client(
        "3", _client_base_cfg(
            avatar_islands={"enabled": True},
            master_audio={"enabled": False},
        ),
        voice_id="voice-1", asset_id="asset-1",
    )
    баланс = _баланс_между_оценками()
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


# --- пункт G: доля ведущей в цене на кнопке ------------------------------------

@pytest.fixture
def реестр(work, tmp_path, monkeypatch):
    """Пустой изолированный реестр клиентов: профили заводит сам тест.
    Без подмены CLIENTS_DIR тесты читали бы профили рабочей машины."""
    monkeypatch.setattr(clients_mod, "CLIENTS_DIR", tmp_path / "clients")
    monkeypatch.setattr(bot, "save_client_profile", lambda chat_id, s: None)
    return tmp_path


def _цены_экрана_выбора(chat_id: int) -> tuple[str, str]:
    """Обе цены с экрана выбора пути так, как их видит человек: они стоят на
    самих кнопках, (с монтажом, без монтажа)."""
    msg = _Msg(chat_id=chat_id)
    asyncio.run(bot._show_ready_screen(
        msg, chat_id, _паспорт(step=bot.READY, scenario=SCENARIO)))
    подписи = _labels(msg.markups[-1])
    цены = [re.search(r"\$\d+\.\d{2}", п) for п in подписи]
    цены = [м.group(0) for м in цены if м]
    assert len(цены) == 2, f"экран выбора назвал не две цены: {подписи!r}"
    return цены[0], цены[1]


def _нужно_очереди(chat_id: int, *, montage: bool = True) -> int:
    """Сколько потребует очередь за ту же сборку. Считаем через отказ по
    нехватке: другого способа узнать число очереди, не начав платную работу,
    нет, а именно это число человек и увидит в отказе."""
    with pytest.raises(bot.InsufficientBalance) as exc:
        bot.enqueue_build(chat_id, SCENARIO, language="ru", voice_id="voice-1",
                          montage=montage)
    return exc.value.need


def test_экран_выбора_режет_цену_ведущей_при_островах_и_мастер_звуке(реестр):
    """Пункт G: очередь считает ведущую по доле в кадре, когда у профиля
    включены И avatar_islands, И master_audio (enqueue_build). Экран выбора
    считал полную цену всегда, и человек с островами видел цифру выше той,
    что спишется, — на единственном экране, где он решает, платить ли вообще.

    Быстрый путь острова не берёт вовсе (montage=False у run_make), поэтому
    его цена остаётся полной: доля применяется только к монтажной."""
    clients_mod.register_client(
        "2",
        _client_base_cfg(avatar_islands={"enabled": True},
                         master_audio={"enabled": True}),
        voice_id="voice-1", asset_id="asset-1",
    )
    доля = bot._billing()["rates"]["avatar_visible_share"]

    с_монтажом, без_монтажа = _цены_экрана_выбора(2)

    assert с_монтажом == bot.format_usd(_оценка_сборки(share=доля))
    assert с_монтажом != bot.format_usd(_оценка_сборки())
    assert без_монтажа == bot.format_usd(_оценка_сборки(montage=False))


def test_экран_выбора_не_режет_цену_без_мастер_звука(реестр):
    """Условие ровно то же, что у очереди: island-путь берётся только когда
    включены ОБА флага. С одними островами ролик пойдёт полной ценой, и экран
    не должен обещать урезанную — иначе человек пополнит ровно по экрану и
    получит отказ уже от очереди, после того как согласился платить."""
    clients_mod.register_client(
        "3",
        _client_base_cfg(avatar_islands={"enabled": True},
                         master_audio={"enabled": False}),
        voice_id="voice-1", asset_id="asset-1",
    )

    с_монтажом, без_монтажа = _цены_экрана_выбора(3)

    assert с_монтажом == bot.format_usd(_оценка_сборки())
    assert без_монтажа == bot.format_usd(_оценка_сборки(montage=False))


def test_экран_и_очередь_называют_одно_число_с_островами(реестр):
    """Экран выбора и очередь считают одну и ту же сборку — числа обязаны
    совпасть до цента, и пополнения ровно по экрану должно хватить очереди.
    Разойдись они, отказ придёт после того, как человек заплатил."""
    clients_mod.register_client(
        "2",
        _client_base_cfg(avatar_islands={"enabled": True},
                         master_audio={"enabled": True}),
        voice_id="voice-1", asset_id="asset-1",
    )

    с_монтажом, _ = _цены_экрана_выбора(2)
    нужно = _нужно_очереди(2)

    assert с_монтажом == bot.format_usd(нужно)

    _пополнить(2, нужно)
    job = bot.enqueue_build(2, SCENARIO, language="ru", voice_id="voice-1")
    assert job.status == "audio_queued"


def test_экран_и_очередь_называют_одно_число_без_островов(реестр):
    """Тот же контракт для профиля без островов: доля не применяется нигде,
    оба числа полные. Проверка держит вторую половину пункта G — доля не
    должна протечь в цену там, где очередь её не применит."""
    clients_mod.register_client(
        "1", _client_base_cfg(), voice_id="voice-1", asset_id="asset-1",
    )

    с_монтажом, без_монтажа = _цены_экрана_выбора(1)
    нужно = _нужно_очереди(1)

    assert с_монтажом == bot.format_usd(нужно) == bot.format_usd(_оценка_сборки())
    assert без_монтажа == bot.format_usd(
        _нужно_очереди(1, montage=False)
    )

    _пополнить(1, нужно)
    job = bot.enqueue_build(1, SCENARIO, language="ru", voice_id="voice-1")
    assert job.status == "audio_queued"


def test_битый_и_отсутствующий_профиль_не_роняют_экран_выбора(реестр):
    """Цена на кнопке считается ДО первого платного шага и не должна падать
    из-за профиля. Профиля может не быть вовсе: save_client_profile перед этим
    экраном падает молча (_ready_stage глотает ошибку), а load_client на
    незаведённом чате поднимает ConfigError. У заведённого профиля настройки
    avatar_islands могут быть вне допустимого диапазона — avatar_islands_settings
    поднимает на них голый ValueError, которого load_config не проверяет (тот же
    дефект, что в test_битые_avatar_islands_settings_не_ломают_оценку).
    В обоих случаях экран обязан показать полную цену, а не уронить разговор."""
    clients_mod.register_client(
        "4",
        _client_base_cfg(avatar_islands={
            "enabled": True,
            "min_request_seconds": 20.0,
            "max_shot_seconds": 5.0,
        }),
        voice_id="voice-1", asset_id="asset-1",
    )

    for chat_id in (4, 9):      # 4 — битые настройки, 9 — профиля нет вовсе
        с_монтажом, без_монтажа = _цены_экрана_выбора(chat_id)
        assert с_монтажом == bot.format_usd(_оценка_сборки())
        assert без_монтажа == bot.format_usd(_оценка_сборки(montage=False))


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


def _сценарий_на(chars: int) -> dict:
    """Сценарий заданной длины речи: цена ролика считается по её символам."""
    return {"title": "Длинный", "blocks": [
        {"role": "hook", "start": 0.0, "end": 30.0, "speech": "а" * chars},
    ]}


def test_пополнение_меняет_кнопки_в_том_же_сообщении(work, магазин):
    """Новых экранов «В какой валюте платить?» быть не должно: кнопки валюты
    встают на место «Пополнить баланс» в том же сообщении."""
    bot.save_session(7, _паспорт(step=bot.READY, scenario=SCENARIO))
    msg = _Msg("Всё на месте: сценарий, фото и голос…")

    _press("topup:start", msg)

    assert msg.kinds[-1] == "edit"
    assert _labels(msg.markups[-1]) == [
        "Оплатить в RUB", "Оплатить в USD", "← Назад"
    ]

    _press("topup:cur:rub", msg)

    assert bot.load_session(7)["pay_currency"] == "rub"
    assert msg.kinds[-1] == "edit"
    assert "Выберите сумму для пополнения" in msg.replies[-1]
    assert _labels(msg.markups[-1])[1:] == ["1000 ₽", "2500 ₽", "5000 ₽", "← Назад"]


def test_прогулка_по_пополнению_живёт_одним_сообщением(work, магазин):
    """Вся прогулка — валюта, суммы и «Назад» с обеих — правит одно сообщение.

    Суммы новым сообщением оставляли в чате прежний экран с живыми кнопками,
    а «Назад» правил уже не его: человек получал два экрана выбора валюты
    подряд (в боевой базе это двойное `topup_opened`)."""
    bot.save_session(7, _паспорт(step=bot.READY, scenario=SCENARIO,
                                 scenario_approved=True))
    msg = _Msg("Всё на месте: сценарий, фото и голос…")

    _press("topup:start", msg)          # экран выбора пути → валюта
    _press("topup:cur:rub", msg)        # валюта → суммы
    _press("topup:start", msg)          # «← Назад» с сумм → валюта
    _press("topup:cancel", msg)         # «← Назад» с валюты → выбор пути

    assert msg.kinds == ["edit"] * 4                    # ни одного нового
    # Экран выбора пути вернулся целиком, а не одной кнопкой пополнения.
    подписи = _labels(msg.markups[-1])
    assert подписи[0].startswith("🎬 С монтажом — $")
    assert подписи[1].startswith("🎥 Без монтажа — $")
    assert подписи[-2:] == ["💳 Пополнить баланс", "← Назад"]


def _нехватка_на_ролик(chat_id: int, было: int) -> int:
    """Сколько не хватает до цены пути, за которым человек пришёл в пополнение.
    Считаем из ставок, а не литералом: цена ролика меняется вместе со ставками
    (например, числом проходов агента), и подпись кнопки не должна ронять тест
    не по делу."""
    s = bot.load_session(chat_id)
    цены = bot.path_prices(chat_id, s, bot._billing())
    путь = "montage" if s.get("topup_path") == "montage" else "plain"
    return цены[путь] - было


def test_кнопка_ровно_на_ролик_стоит_первой(work, магазин):
    """Первый номинал $10 отпугивал тех, чей ролик стоит втрое дешевле: сумма,
    которой не хватает именно на этот ролик, стоит выше готовых номиналов."""
    было = 2_000_000
    bot.save_session(7, _паспорт(step=bot.READY, scenario=_сценарий_на(700)))
    _пополнить(7, было)
    msg = _Msg()

    _press("topup:cur:usd", msg)

    ровно = bot.format_minor(
        bot.exact_topup_minor(_нехватка_на_ролик(7, было), "usd",
                              bot._billing()["fx"]),
        "usd",
    )
    assert ровно not in ("$10", "$25", "$50")   # иначе проверка ничего не ловит
    assert _labels(msg.markups[-1]) == [
        f"{ровно} — ровно на этот ролик", "$10", "$25", "$50", "← Назад"
    ]


def test_кнопка_ровно_на_ролик_в_рублях_целым_числом(work, магазин):
    """Рубли считаются тем же курсом, каким вебхук зачисляет платёж, и вверх —
    иначе человек заплатит по кнопке и всё равно не доберёт до оценки."""
    было = 2_000_000
    bot.save_session(7, _паспорт(step=bot.READY, scenario=_сценарий_на(700)))
    _пополнить(7, было)
    msg = _Msg()

    _press("topup:cur:rub", msg)

    рублями = bot.exact_topup_minor(_нехватка_на_ролик(7, было), "rub",
                                    bot._billing()["fx"])
    assert рублями % 100 == 0                   # целые рубли, без копеек
    assert _labels(msg.markups[-1])[0] == f"{рублями // 100} ₽ — ровно на этот ролик"
    # Кнопка обязана добирать до нехватки, а не оставлять копейки: сумма на
    # кнопке по курсу зачисления перекрывает недостающее до оценки.
    нехватка = _нехватка_на_ролик(7, было)
    курс = bot._billing()["fx"]["rub"]
    assert рублями / 100 * курс >= нехватка / 1_000_000


def test_кнопка_ровно_на_ролик_создаёт_счёт_на_свою_сумму(work, магазин):
    bot.save_session(7, _паспорт(step=bot.READY, scenario=_сценарий_на(700)))
    _пополнить(7, 2_000_000)
    msg = _Msg()

    _press("topup:amt:usd:324", msg)

    assert магазин["created"] == [{
        "amount": 324, "currency": "usd", "customerId": "7",
        "title": "Пополнение баланса $3.24",
    }]


def test_ровная_сумма_считается_от_пути_чью_кнопку_жали(work, магазин):
    """Пути стоят по-разному, а нехватка считалась одним числом на оба. Человек
    жал «С монтажом», платил по кнопке ровной суммы — и всё равно не доезжал до
    монтажа, потому что кнопка собирала на быстрый путь."""
    bot.save_session(7, _паспорт(step=bot.READY, scenario=_сценарий_на(700),
                                 scenario_approved=True))
    цены = bot.path_prices(7, bot.load_session(7), bot._billing())
    assert цены["montage"] > цены["plain"]      # иначе проверять нечего
    fx = bot._billing()["fx"]
    msg = _Msg()

    _press("build:montage", msg)                # денег нет — уводит в пополнение
    _press("topup:cur:usd", msg)
    дорогая = _labels(msg.markups[-1])[0]

    _press("build:plain", msg)
    _press("topup:cur:usd", msg)
    дешёвая = _labels(msg.markups[-1])[0]

    ровно = bot.format_minor(
        bot.exact_topup_minor(цены["montage"], "usd", fx), "usd")
    assert дорогая == f"{ровно} — ровно на этот ролик"
    assert дешёвая == "{} — ровно на этот ролик".format(
        bot.format_minor(bot.exact_topup_minor(цены["plain"], "usd", fx), "usd"))
    assert дорогая != дешёвая


def test_без_нажатой_кнопки_ровная_сумма_считается_от_дешёвого_пути(work, магазин):
    """Пополнение открыто с экрана выбора, пути человек не назвал. Нижняя
    граница — дешёвый путь: после неё доступен хотя бы один ролик, а обещать
    «ровно на этот ролик» больше неё значит собирать за то, чего не выбирали."""
    bot.save_session(7, _паспорт(step=bot.READY, scenario=_сценарий_на(700),
                                 scenario_approved=True))
    цены = bot.path_prices(7, bot.load_session(7), bot._billing())
    msg = _Msg()

    _press("topup:start", msg)
    _press("topup:cur:usd", msg)

    ровно = bot.format_minor(
        bot.exact_topup_minor(цены["plain"], "usd", bot._billing()["fx"]), "usd")
    assert _labels(msg.markups[-1])[0] == f"{ровно} — ровно на этот ролик"


def test_без_ролика_кнопки_ровной_суммы_нет(work, магазин):
    """/balance и гейт при минусе открывают тот же экран, но ролика перед
    человеком нет — считать нечего, остаются одни номиналы."""
    bot.save_session(7, _паспорт(step=bot.WAIT_TEXT))
    msg = _Msg()

    _press("topup:cur:usd", msg)

    assert _labels(msg.markups[-1]) == ["$10", "$25", "$50", "← Назад"]


def test_кнопки_ровной_суммы_нет_когда_баланса_хватает(work, магазин):
    """Баланс берём с запасом от самой оценки, а не круглой суммой: цена ролика
    растёт вместе со ставками (например, числом проходов агента), и прежние
    $10 однажды перестали её покрывать — тест ловил бы уже не своё."""
    bot.save_session(7, _паспорт(step=bot.READY, scenario=_сценарий_на(700)))
    _пополнить(7, bot.path_prices(7, bot.load_session(7),
                                  bot._billing())["montage"] + 1_000_000)
    msg = _Msg()

    _press("topup:cur:usd", msg)

    assert _labels(msg.markups[-1]) == ["$10", "$25", "$50", "← Назад"]


def test_ровная_сумма_не_ниже_минимума_магазина():
    """Минимум у каждой валюты свой (снято живыми запросами в магазин): доллар
    пропускает 100 единиц, рубль — только 10000. Плоская сотня роняла счёт
    ошибкой error_amount_too_small."""
    fx = {"usd": 1.0, "rub": 0.011}
    assert bot.exact_topup_minor(20_000, "usd", fx) == 100
    assert bot.exact_topup_minor(20_000, "rub", fx) == 10000


def test_дешёвый_ролик_показывает_минимальный_платёж(work, магазин):
    """Не хватает меньше минимального счёта: обещать «ровно на этот ролик»
    нельзя — человек заплатит больше и должен видеть, за что."""
    bot.save_session(7, _паспорт(step=bot.READY, scenario=SCENARIO))
    # Баланс почти покрывает ролик: не хватает копеек, а счёт меньше доллара
    # платёжный шлюз не примет.
    _пополнить(7, bot.path_prices(7, bot.load_session(7),
                                  bot._billing())["plain"] - 100_000)
    msg = _Msg()

    _press("topup:cur:rub", msg)
    assert _labels(msg.markups[-1])[0] == "100 ₽ — минимальный платёж"

    _press("topup:cur:usd", msg)
    assert _labels(msg.markups[-1])[0] == "$1.00 — минимальный платёж"


def test_дешёвый_ролик_создаёт_счёт_не_ниже_минимума(work, магазин):
    bot.save_session(7, _паспорт(step=bot.READY, scenario=SCENARIO))
    _press("topup:amt:rub:10000", _Msg())

    assert магазин["created"] == [{
        "amount": 10000, "currency": "rub", "customerId": "7",
        "title": "Пополнение баланса 100 ₽",
    }]


def test_назад_с_выбора_валюты_возвращает_прежние_кнопки(work, магазин):
    """«Назад» с валюты — на экран выбора пути, с которого пополнение и
    открыли: одна кнопка «Пополнить баланс» здесь была бы тупиком."""
    bot.save_session(7, _паспорт(step=bot.READY, scenario=SCENARIO))
    msg = _Msg("Всё на месте…")

    _press("topup:start", msg)
    _press("topup:cancel", msg)

    assert msg.kinds[-1] == "edit"
    подписи = _labels(msg.markups[-1])
    assert подписи[0].startswith("🎬 С монтажом — $")
    assert подписи[1].startswith("🎥 Без монтажа — $")
    assert подписи[-2:] == ["💳 Пополнить баланс", "← Назад"]


def test_сумма_создаёт_счёт_с_chat_id_в_customerId(work, магазин):
    bot.save_session(7, _паспорт(step=bot.READY, pay_currency="rub",
                                 scenario=SCENARIO))
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
    bot.save_session(7, _паспорт(step=bot.WAIT_TEXT, pay_currency="usd"))
    msg = _Msg()
    _press("topup:amt:usd:1000", msg)

    магазин["status"].append("paid")
    _press("topup:check", msg)

    assert bot._ledger().balance(7) == 10_000_000
    assert "Оплата получена" in msg.replies[-1]
    assert "pending_order" not in bot.load_session(7)


def test_после_оплаты_счёт_превращается_в_выбор_пути(work, магазин):
    """Одно сообщение на оплату: счёт правится на месте, новых экранов нет.
    Возврат — на тот самый экран, ради которого человек и платил, со свежими
    числами: прежняя кнопка «Продолжить» вела в убранный шаг."""
    bot.save_session(7, _паспорт(step=bot.READY, pay_currency="usd",
                                 scenario=SCENARIO, scenario_approved=True))
    msg = _Msg()
    _press("topup:amt:usd:5000", msg)
    счёт = msg.replies[-1]

    магазин["status"].append("paid")
    _press("topup:check", msg)

    assert msg.kinds[-1] == "edit"          # то же сообщение, а не новое
    assert счёт not in msg.replies[-1:]
    assert msg.replies[-1].startswith(bot.READY_MSG)
    assert f"Баланс: {bot.format_usd(50_000_000)}" in msg.replies[-1]
    подписи = _labels(msg.markups[-1])
    assert подписи[0].startswith("🎬 С монтажом — $")
    assert "недостаточно средств" not in " ".join(подписи)


def test_после_оплаты_с_нехваткой_оставляет_путь_помеченным(work, магазин):
    # длинный сценарий — ролик дороже одного пополнения на $10
    bot.save_session(7, _паспорт(step=bot.READY, pay_currency="usd",
                                 scenario=_сценарий_на(4000),
                                 scenario_approved=True))
    msg = _Msg()
    _press("topup:amt:usd:1000", msg)

    магазин["status"].append("paid")
    _press("topup:check", msg)

    assert msg.replies[-1].startswith(bot.READY_MSG)
    assert "оплата ещё не дошла" not in msg.replies[-1].lower()
    подписи = _labels(msg.markups[-1])
    assert подписи[0].endswith(bot.NO_FUNDS_SUFFIX)
    assert подписи[-2:] == ["💳 Пополнить баланс", "← Назад"]


def test_вебхук_правит_то_же_сообщение_со_счётом(work, магазин):
    """Вебхук и кнопка проверки не должны давать двух сообщений об одной
    оплате: оба правят сообщение со счётом."""
    bot.save_session(7, _паспорт(step=bot.READY, pay_currency="usd",
                                 scenario=SCENARIO, scenario_approved=True))
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
    # Вебхук возвращает туда же, куда и кнопка проверки: на экран выбора пути
    assert text.startswith(bot.READY_MSG)
    assert "pending_order" not in bot.load_session(7)


def test_проверка_оплаты_не_удваивает_баланс_после_вебхука(work, магазин):
    """Вебхук и кнопка «Проверить оплату» могут сработать оба — ключ
    идемпотентности у них общий, иначе человек получит деньги дважды."""
    from reels_factory.tribute import credit_shop_order

    bot.save_session(7, _паспорт(step=bot.WAIT_TEXT, pay_currency="usd"))
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
    bot.save_session(7, _паспорт(step=bot.WAIT_TEXT, pay_currency="usd"))
    msg = _Msg()

    _press("topup:amt:usd:1000", msg)

    assert "магазин лёг" in msg.replies[-1]
    assert "pending_order" not in bot.load_session(7)


def test_текст_пополнения_при_нехватке_называет_баланс_и_нехватку():
    from reels_factory.bot import topup_text
    text = topup_text(need=3_184_000, have=1_000_000)
    assert "$1.00" in text
    assert "не хватает" in text.lower()


def test_текст_пополнения_не_называет_цену_ролика():
    """Цена звучит один раз — на кнопках экрана выбора пути. Второе число
    здесь, да ещё с оговоркой «ориентировочно», делало из одной цены две."""
    from reels_factory.bot import topup_text
    text = topup_text(need=3_184_000, have=1_000_000)
    assert "$3.18" not in text
    assert "ориентировочн" not in text.lower()


def test_текст_пополнения_без_нехватки_показывает_только_баланс():
    from reels_factory.bot import topup_text
    text = topup_text(need=None, have=1_000_000)
    assert "$1.00" in text
    assert "не хватает" not in text.lower()


# --- деньги спрашиваются один раз: на экране выбора пути ----------------------

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


def test_нехватка_баланса_видна_только_на_выборе_пути(work, monkeypatch):
    """С нулём человек проходит весь бесплатный путь и упирается в деньги
    ровно там, где выбирает ролик: обе кнопки помечены нехваткой, рядом стоит
    пополнение, а «Назад» уводит к сценарию — тупика нет."""
    monkeypatch.setattr(
        bot, "step_verbatim", lambda chat_id, text, language: SCENARIO
    )
    monkeypatch.setattr(bot, "save_client_profile", lambda chat_id, s: None)
    assert bot._ledger().balance(7) == 0
    bot.save_session(7, _паспорт(step=bot.WAIT_TEXT))

    msg = _Msg("Мой текст.")
    asyncio.run(bot.on_message(_Update(msg), None))
    # деньги до сценария не упоминаются вовсе
    assert "$" not in " ".join(msg.replies)

    _press("ok", msg)

    подписи = _labels(msg.markups[-1])
    assert подписи[0].endswith(bot.NO_FUNDS_SUFFIX)
    assert подписи[1].endswith(bot.NO_FUNDS_SUFFIX)
    assert подписи[-2:] == ["💳 Пополнить баланс", "← Назад"]


def test_второе_утверждение_не_повторяет_ни_слов_ни_воронки(work, monkeypatch):
    """Кнопка «Утвердить» живёт в истории чата, и второй тап по ней —
    хоть подряд, хоть через неделю — утверждает уже утверждённое: два
    «Сценарий утверждён» подряд и лишний шаг в воронке."""
    monkeypatch.setattr(bot, "save_client_profile", lambda chat_id, s: None)
    bot.save_session(7, _паспорт(step=bot.REVIEW, scenario=SCENARIO))
    msg = _Msg()

    _press("ok", msg)
    _press("ok", msg)

    assert msg.replies.count(bot.APPROVED_MSG) == 1
    assert _события().count("scenario_approved") == 1
    # И это не тупик: экран выбора пути с полным набором кнопок на месте.
    assert msg.replies[-1].startswith(bot.READY_MSG)
    подписи = _labels(msg.markups[-1])
    assert подписи[0].startswith("🎬 С монтажом — $")
    assert подписи[1].startswith("🎥 Без монтажа — $")


def test_после_правки_сценарий_утверждается_снова(work, monkeypatch):
    """Защита от второго утверждения не должна запирать новый текст: правка
    снимает признак, и «Утвердить» работает как в первый раз."""
    monkeypatch.setattr(bot, "save_client_profile", lambda chat_id, s: None)
    bot.save_session(7, _паспорт(step=bot.REVIEW, scenario=SCENARIO))
    msg = _Msg()
    _press("ok", msg)

    _press("edit", msg)
    правка = _Msg("Продажи начинаются раньше. Сохрани себе на потом.")
    asyncio.run(bot.on_message(_Update(правка), None))
    assert "scenario_approved" not in bot.load_session(7)

    _press("ok", правка)

    assert правка.replies.count(bot.APPROVED_MSG) == 1
    assert bot.load_session(7)["scenario_approved"] is True
    assert правка.replies[-1].startswith(bot.READY_MSG)


def test_кнопка_пути_без_денег_ведёт_на_пополнение_а_не_в_сборку(work, клиент):
    _charge_flat(7, 1_000_000_000)      # съесть баланс фикстуры
    bot.save_session(7, _паспорт(step=bot.READY, scenario=SCENARIO,
                                 scenario_approved=True))

    msg = _Msg()
    _press("build:montage", msg)

    assert bot._job_store().latest_for_chat(7) is None
    assert "Не хватает средств на сборку ролика." in msg.replies[-1]
    assert _labels(msg.markups[-1]) == ["💳 Пополнить баланс", "← Назад"]

    # и это не тупик: «Назад» возвращает к выбору пути
    _press("ready:show", msg)
    assert msg.replies[-1].startswith(bot.READY_MSG)
    assert bot.load_session(7)["step"] == bot.READY


def test_после_пополнения_кнопка_пути_перестаёт_быть_помеченной(work):
    """Кнопки убранного экрана цены живут в истории чата: они обязаны
    показывать актуальный экран, а не вести в исчезнувший шаг."""
    bot.save_session(7, _паспорт(step=bot.READY, scenario=SCENARIO,
                                 scenario_approved=True))
    msg = _Msg()
    _press("pay:check", msg)
    assert bot.NO_FUNDS_SUFFIX in " ".join(_labels(msg.markups[-1]))

    _с_балансом()
    _press("pay:check", msg)

    подписи = _labels(msg.markups[-1])
    assert bot.NO_FUNDS_SUFFIX not in " ".join(подписи)
    assert "💳 Пополнить баланс" not in подписи


def test_отрицательный_баланс_не_мешает_выбрать_идею(work):
    """Сценарий бесплатен для человека — гейт по балансу на выборе идеи
    больше не стоит: о деньгах разговор пойдёт на экране выбора пути."""
    _charge_flat(7, 1)
    сценарии = []
    bot.save_session(7, {
        "step": bot.CHOOSING_IDEA, "language": "ru",
        "ideas": [{"idea": "Раз", "draft_hook": "Хук раз"}],
    })

    msg = _Msg()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            bot, "step_scenario",
            lambda chat_id, idea, language, gender=None:
                сценарии.append(idea) or SCENARIO,
        )
        _press("idea:0", msg)

    assert сценарии and bot.load_session(7)["step"] == bot.REVIEW


def test_кнопка_идеи_из_истории_не_переписывает_готовый_сценарий(work, monkeypatch):
    вызовы = []
    monkeypatch.setattr(
        bot, "step_scenario",
        lambda chat_id, idea, language, gender=None: вызовы.append(idea) or SCENARIO,
    )
    bot.save_session(7, {
        "step": bot.REVIEW, "language": "ru", "scenario": SCENARIO,
        "scenario_idea": 0,
        "ideas": [{"idea": "Раз", "draft_hook": "Хук раз"}],
    })

    msg = _Msg()
    _press("idea:0", msg)

    assert вызовы == []
    assert "[хук]" in msg.replies[-1]


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

    assert bot.MATERIAL_ACCEPTED_MSG in msg.replies
    assert bot.load_session(7)["step"] == bot.REVIEW


# --- экран выбора пути: цена, баланс и кнопки --------------------------------

def _экран_выбора(chat_id: int = 7):
    """Показать экран выбора пути и вернуть (текст, подписи кнопок)."""
    msg = _Msg(chat_id=chat_id)
    asyncio.run(bot._show_ready_screen(msg, chat_id, bot.load_session(chat_id)))
    return msg.replies[-1], _labels(msg.markups[-1])


def _события(chat_id: int = 7) -> list[str]:
    """События воронки так, как они записаны.

    Читаем таблицу, а не funnel(): та засчитывает циклу все шаги до самого
    дальнего достигнутого, и пропавшая запись в ней не видна — проверка «шаг
    не записан» прошла бы на любом коде."""
    import sqlite3

    conn = sqlite3.connect(str(bot._events().path))
    try:
        return [r[0] for r in conn.execute(
            "SELECT event FROM events WHERE chat_id = ? ORDER BY id", (chat_id,)
        )]
    finally:
        conn.close()


def test_экран_выбора_называет_баланс_строкой(work, monkeypatch):
    """Цена стоит на кнопках, и без второго числа человек не видит, хватает
    ли ему. Баланс — часть экрана, а не сообщение о нехватке: он на месте и
    когда денег полно."""
    bot.save_session(7, _паспорт(step=bot.READY, scenario=SCENARIO))

    текст, _ = _экран_выбора()
    assert текст.startswith(bot.READY_MSG)
    assert f"Баланс: {bot.format_usd(0)}" in текст

    _с_балансом()
    текст, _ = _экран_выбора()
    assert f"Баланс: {bot.format_usd(bot._ledger().balance(7))}" in текст


def test_с_выключенным_биллингом_экран_выбора_молчит_о_деньгах(work, monkeypatch):
    """Без биллинга цен на кнопках нет — и баланс тогда врёт про то, чего не
    существует: экран остаётся выбором пути, а не разговором о деньгах."""
    _с_балансом()
    bot.save_session(7, _паспорт(step=bot.READY, scenario=SCENARIO))
    billing_on = bot._billing()
    monkeypatch.setattr(bot, "_billing", lambda: {**billing_on, "enabled": False})

    текст, подписи = _экран_выбора()

    assert текст == bot.READY_MSG
    assert "Баланс" not in текст
    assert not any("$" in подпись for подпись in подписи)   # называть нечего


def test_цены_стоят_на_кнопках_а_не_в_тексте_экрана(work):
    """Текст экрана дословный и цен не называет: путь и его цену человек
    выбирает одним нажатием, а единственное число в тексте — его баланс."""
    _с_балансом()
    bot.save_session(7, _паспорт(step=bot.READY, scenario=SCENARIO))
    цены = bot.path_prices(7, bot.load_session(7), bot._billing())
    баланс = bot.format_usd(bot._ledger().balance(7))

    текст, подписи = _экран_выбора()

    assert текст == bot.READY_MSG + f"\n\nБаланс: {баланс}"
    assert re.findall(r"\$\d+\.\d{2}", текст) == [баланс]
    assert подписи[0] == f"🎬 С монтажом — {bot.format_usd(цены['montage'])}"
    assert подписи[1] == f"🎥 Без монтажа — {bot.format_usd(цены['plain'])}"
    assert подписи[-1] == "← Назад"


def test_хватает_на_оба_пути_кнопки_пополнения_нет(work):
    """Пополнение приходит на экран только тогда, когда оно человеку нужно."""
    _с_балансом()
    bot.save_session(7, _паспорт(step=bot.READY, scenario=SCENARIO))

    _, подписи = _экран_выбора()

    assert bot.NO_FUNDS_SUFFIX not in " ".join(подписи)
    assert "💳 Пополнить баланс" not in подписи
    assert подписи[-1] == "← Назад"


def test_нехватка_на_один_путь_метит_только_его_кнопку(work):
    """«Хватает» считается по каждому пути отдельно. Считай экран по дорогому
    пути — и человек с деньгами ровно на быстрый ролик увидел бы запертыми обе
    кнопки, хотя один ролик оплатить он может."""
    bot.save_session(7, _паспорт(step=bot.READY, scenario=SCENARIO))
    цены = bot.path_prices(7, bot.load_session(7), bot._billing())
    assert цены["montage"] > цены["plain"]      # иначе проверять нечего
    _пополнить(7, цены["plain"])

    _, подписи = _экран_выбора()

    assert подписи[0].endswith(bot.NO_FUNDS_SUFFIX)
    assert not подписи[1].endswith(bot.NO_FUNDS_SUFFIX)
    assert подписи[1].startswith("🎥 Без монтажа — $")
    assert подписи[-2:] == ["💳 Пополнить баланс", "← Назад"]


def test_доступный_путь_собирается_даже_когда_на_дорогой_не_хватает(
        work, клиент_без_денег):
    """Помеченная кнопка дорогого пути не запирает дешёвый: денег на него
    хватает, и нажатие уходит в сборку, а не в пополнение."""
    bot.save_session(7, _паспорт(step=bot.READY, scenario=SCENARIO,
                                 scenario_approved=True))
    цены = bot.path_prices(7, bot.load_session(7), bot._billing())
    _пополнить(7, цены["plain"])

    msg = _Msg()
    _press("build:plain", msg)

    s = bot.load_session(7)
    assert s["montage"] is False
    assert s["current_job_id"]
    assert bot.BUILDING_MSG in msg.replies[-1]


def test_до_экрана_выбора_о_деньгах_не_говорят_ни_словом(work, monkeypatch):
    """Раньше цена звучала дважды: сразу после материала и потом на выборе
    пути, и числа не сходились. Теперь весь путь до выбора для человека
    бесплатен, и до него не должно прозвучать ни одной суммы."""
    monkeypatch.setattr(
        bot, "step_ideas",
        lambda chat_id, text, language: [{"idea": "Раз", "draft_hook": "Хук"}],
    )
    monkeypatch.setattr(
        bot, "step_scenario",
        lambda chat_id, idea, language, gender=None: SCENARIO,
    )
    monkeypatch.setattr(bot, "save_client_profile", lambda chat_id, s: None)
    bot.save_session(7, _паспорт(step=bot.WAIT_RAW))

    msg = _Msg("Длинное сырьё про продажи.")
    asyncio.run(bot.on_message(_Update(msg), None))
    _press("idea:0", msg)

    сказанное = " ".join(р for р in msg.replies if р)
    подписи = [п for m in msg.markups if m for п in _labels(m)]
    assert "$" not in сказанное and "Баланс" not in сказанное
    assert "пополн" not in сказанное.lower()
    assert not any("$" in п or "Пополнить" in п for п in подписи)
    assert "price_shown" not in _события()

    _press("ok", msg)

    assert msg.replies[-1].startswith(bot.READY_MSG)
    assert _события().count("price_shown") == 1


def test_денег_хватило_записывается_на_нажатии_доступного_пути(
        work, клиент_без_денег):
    """Шаг воронки «денег хватило» больше не привязан к убранному экрану цены.
    Нажатие пути, на который не хватает, его не даёт — иначе воронка считала бы
    дошедшими до денег тех, кого увели пополнять."""
    bot.save_session(7, _паспорт(step=bot.READY, scenario=SCENARIO,
                                 scenario_approved=True))

    msg = _Msg()
    _press("build:montage", msg)

    assert "balance_ok" not in _события()
    assert "topup_opened" not in _события()   # пополнение он ещё не открывал

    _с_балансом()
    _press("build:montage", msg)

    assert _события().count("balance_ok") == 1
    assert bot.load_session(7)["current_job_id"]


def test_после_оплаты_человек_возвращается_к_выбору_и_сразу_собирает(
        work, клиент_без_денег, магазин):
    """Возврат после оплаты вёл на кнопку «Продолжить», а её обработчик пускал
    дальше не всякую сессию — человек попадал на показ текущего экрана вместо
    обещанного продолжения. Теперь зачисление рисует тот самый экран выбора со
    свежими числами, и следующее нажатие уже ставит ролик в очередь."""
    bot.save_session(7, _паспорт(step=bot.READY, scenario=SCENARIO,
                                 scenario_approved=True))
    msg = _Msg()
    _press("build:montage", msg)                 # денег нет
    assert "Не хватает средств на сборку ролика." in msg.replies[-1]

    _press("topup:amt:usd:5000", msg)
    магазин["status"].append("paid")
    _press("topup:check", msg)

    assert msg.replies[-1].startswith(bot.READY_MSG)
    assert f"Баланс: {bot.format_usd(50_000_000)}" in msg.replies[-1]
    подписи = _labels(msg.markups[-1])
    assert bot.NO_FUNDS_SUFFIX not in " ".join(подписи)
    assert "💳 Пополнить баланс" not in подписи

    _press("build:montage", msg)

    s = bot.load_session(7)
    assert s["current_job_id"] and s["montage"] is True


def test_старые_кнопки_оплаты_не_роняют_разговор(work, monkeypatch):
    """pay:go и pay:check — кнопки убранного экрана цены, они висят в истории
    чата вечно. Обе обязаны показать текущий экран и не звать Клода."""
    вызовы = []
    monkeypatch.setattr(
        bot, "step_verbatim", lambda chat_id, text, language: вызовы.append(text)
    )
    _с_балансом()
    bot.save_session(7, _паспорт(step=bot.REVIEW, scenario=SCENARIO,
                                 material_mode="text",
                                 material_text="Мой текст."))

    msg = _Msg()
    _press("pay:go", msg)
    _press("pay:check", msg)

    assert вызовы == []
    assert bot._job_store().latest_for_chat(7) is None
    assert bot.load_session(7)["step"] == bot.REVIEW
    assert msg.replies.count(bot.render_scenario(SCENARIO)) == 2

    bot.save_session(7, _паспорт(step=bot.DONE))
    хвост = _Msg()
    _press("pay:check", хвост)

    assert хвост.replies[-1] == bot.DONE_MSG
    assert bot.load_session(7)["step"] == bot.DONE


def test_отказ_очереди_по_деньгам_перерисовывает_экран_выбора(work):
    """Очередь считает цену сама и может отказать уже после нажатия кнопки.
    Отдельный экран «пополните» был тупиком: вернуться к выбору с него нечем —
    вместо него тот же экран выбора с погашенной кнопкой."""
    bot.save_session(7, _паспорт(step=bot.READY, scenario=SCENARIO,
                                 scenario_approved=True))
    msg = _Msg()

    job = asyncio.run(bot._enqueue_build(msg, 7, bot.load_session(7)))

    assert job is None
    assert msg.replies[-1].startswith(bot.READY_MSG)
    подписи = _labels(msg.markups[-1])
    assert подписи[0].endswith(bot.NO_FUNDS_SUFFIX)
    assert подписи[-2:] == ["💳 Пополнить баланс", "← Назад"]


def test_отказ_сборки_возвращает_к_готовому_сценарию(work, клиент):
    """После провала человека гнали на новый круг — язык, пол, материал и
    сценарий заново ради ролика, текст которого уже написан и утверждён."""
    bot.save_session(7, _паспорт(step=bot.READY, scenario=SCENARIO,
                                 scenario_approved=True))
    _press("build:plain", _Msg())
    job = _claim_job()
    api = _BotAPI()

    asyncio.run(bot._process_job(
        api, job,
        build_fn=lambda chat_id, workdir: {"ok": False, "stage": "render",
                                           "error": "движок лёг"},
    ))

    assert bot.load_session(7)["step"] == bot.BUILD_FAILED
    # Полным составом: перед возвратом встаёт кнопка продолжения упавшей
    # сборки (ПРОДОЛЖИТЬ и ВОЗВРАТ объявлены ниже по файлу).
    assert _labels(api.markups[-1]) == [ПРОДОЛЖИТЬ] + ВОЗВРАТ

    msg = _Msg()
    _press("ready:show", msg)

    s = bot.load_session(7)
    assert s["step"] == bot.READY and s["scenario"] == SCENARIO
    assert msg.replies[-1].startswith(bot.READY_MSG)


def test_кнопки_этапов_после_отказа_сборки_не_ведут_к_оплате(work):
    """Проверка stage:* после DONE/BUILD_FAILED осталась, но обоснование иное:
    навигация по этапам кончается экраном выбора пути, то есть предложением
    оплатить второй ролик по тому же материалу. Выходы отсюда только явные."""
    bot.save_session(7, _паспорт(step=bot.BUILD_FAILED, scenario=SCENARIO,
                                 material_mode="text",
                                 material_text="Мой текст."))

    msg = _Msg()
    _press("stage:next", msg)

    assert bot.load_session(7)["step"] == bot.BUILD_FAILED
    assert msg.replies[-1] == bot.BUILD_FAILED_AGAIN_HINT
    assert _labels(msg.markups[-1]) == ["← Назад к выбору", "Новый ролик"]


def test_упавший_клон_на_кнопке_пути_ведёт_к_записи_голоса(
        work, клиент, monkeypatch, tmp_path):
    """Клон делается на демо, а демо получает только новичок. Приславший запись
    позже доходил до кнопки пути без голоса и упирался в «профиль не найден» —
    сообщение, из которого не следует ни одного действия."""
    запись = tmp_path / "запись.ogg"
    запись.write_bytes(b"voice")

    def падаем(chat_id, path, language):
        raise RuntimeError("ElevenLabs отказал")

    monkeypatch.setattr(bot, "step_voice", падаем)
    bot.save_session(7, _паспорт(
        step=bot.READY, scenario=SCENARIO, scenario_approved=True,
        voices={}, voice_id=None,
        voice_samples={"ru": str(запись)}, voice_pending={"ru": str(запись)},
    ))

    msg = _Msg()
    _press("build:plain", msg)

    assert bot._job_store().latest_for_chat(7) is None
    assert bot.CLIENT_NOT_FOUND_MSG not in msg.replies
    assert "ElevenLabs отказал" in " ".join(msg.replies)
    assert bot.load_session(7)["step"] == bot.WAIT_VOICE


# --- ревизия флоу: потери данных, тупики и платные повторы --------------------
#
# Каждая проверка ниже названа своей ошибкой: что именно теряет человек (или
# платим мы), если правку откатить.

def test_переспрос_смены_называет_цену_ответа_дословно(work):
    """Тап по другому языку или полу — смена, а не подтверждение, и до ответа
    ничего не меняется. Текст вопроса дословный: он единственное место, где
    человеку сказано, во что обойдётся «Да»."""
    bot.save_session(7, _паспорт(step=bot.READY, scenario=SCENARIO,
                                 scenario_approved=True))
    язык = _Msg()
    _press("reel_language:kk", язык)

    assert язык.replies[-1] == (
        "Сценарий написан на русском. Хотите на казахском?\n\n"
        "Да — переведу этот же сценарий на казахский.\n"
        "Нет — вернёмся туда, где вы остановились, сценарий останется прежним."
    )
    assert _labels(язык.markups[-1]) == ["Да", "Нет"]

    bot.save_session(7, _паспорт(step=bot.READY, gender="female",
                                 scenario=SCENARIO, scenario_approved=True))
    пол = _Msg()
    _press("reel_gender:male", пол)

    assert пол.replies[-1] == (
        "Сценарий уже написан под женский голос. Сменить на мужской?\n\n"
        "Да — напишу сценарий заново под мужской голос, прежний текст пропадёт.\n"
        "Нет — вернёмся туда, где вы остановились, сценарий останется прежним."
    )
    assert _labels(пол.markups[-1]) == ["Да", "Нет"]


def test_да_на_смене_языка_переводит_тот_же_текст_а_не_пишет_новый(
        work, monkeypatch):
    """«Да» обещало перевод именно этого сценария. Новая генерация вместо
    перевода дала бы другой текст на тот же вопрос — и стоила бы ещё раз."""
    отдано = {}
    monkeypatch.setattr(
        bot, "step_translate",
        lambda chat_id, scenario, language: отдано.update(
            scenario=scenario, language=language
        ) or {**scenario, "language": language},
    )
    генерации = []
    monkeypatch.setattr(
        bot, "step_scenario",
        lambda *a, **kw: генерации.append(a) or SCENARIO,
    )
    monkeypatch.setattr(
        bot, "step_verbatim",
        lambda *a, **kw: генерации.append(a) or SCENARIO,
    )
    bot.save_session(7, _паспорт(step=bot.READY, scenario=SCENARIO,
                                 scenario_approved=True, material_mode="text",
                                 material_text="Мой текст."))
    _press("reel_language:kk", _Msg())

    _press("switch:language:yes", _Msg())

    assert отдано == {"scenario": SCENARIO, "language": "kk"}
    assert генерации == []
    assert bot.load_session(7)["language"] == "kk"


def test_смена_языка_без_сценария_не_переспрашивает(work):
    """Переводить нечего — вопрос был бы лишним экраном на пустом месте."""
    bot.save_session(7, _паспорт(step=bot.VIEWING_STAGE,
                                 stage=bot.STAGE_LANGUAGE))
    msg = _Msg()

    _press("reel_language:kk", msg)

    s = bot.load_session(7)
    assert s["language"] == "kk"
    assert "switch" not in s
    assert "Хотите на" not in " ".join(msg.replies)


def test_нет_возвращает_на_тот_экран_с_которого_пришёл_тап(work):
    """«Нет» проверяется не только с экрана выбора: человек мог стоять на
    карточке голоса — туда и обязан вернуться, ничего не потеряв."""
    bot.save_session(7, _паспорт(step=bot.VIEWING_STAGE, stage=bot.STAGE_VOICE,
                                 scenario=SCENARIO, scenario_approved=True,
                                 ideas=[{"idea": "Раз", "draft_hook": "Хук"}]))
    _press("reel_gender:female", _Msg())

    msg = _Msg()
    _press("switch:gender:no", msg)

    s = bot.load_session(7)
    assert s["step"] == bot.VIEWING_STAGE and s["stage"] == bot.STAGE_VOICE
    assert s["gender"] == "male"
    assert s["scenario"] == SCENARIO and s["scenario_approved"] is True
    assert s["ideas"] == [{"idea": "Раз", "draft_hook": "Хук"}]
    assert "switch" not in s


def test_тап_по_уже_выбранному_полу_ничего_не_стирает(work):
    """Тап по своей же галочке сменой не является. Прежний обработчик стирал
    сценарий, идеи и утверждение на любом нажатии — в том числе на этом."""
    bot.save_session(7, _паспорт(step=bot.VIEWING_STAGE, stage=bot.STAGE_GENDER,
                                 scenario=SCENARIO, scenario_approved=True,
                                 ideas=[{"idea": "Раз", "draft_hook": "Хук"}]))
    msg = _Msg()

    _press("reel_gender:male", msg)

    s = bot.load_session(7)
    assert s["scenario"] == SCENARIO and s["scenario_approved"] is True
    assert s["ideas"] == [{"idea": "Раз", "draft_hook": "Хук"}]
    assert "switch" not in s
    assert "Сменить на" not in " ".join(msg.replies)


def test_изменить_под_карточкой_правит_её_этап_а_не_текущий(work):
    """Сообщение с кнопкой живёт в чате вечно, а «текущий» этап к моменту
    нажатия уже другой. Голое stage:edit брало этап из сессии: человек жал
    «Изменить» под карточкой фото, а попадал на выбор языка — и тот сносил
    написанный сценарий."""
    bot.save_session(7, _паспорт(step=bot.VIEWING_STAGE,
                                 stage=bot.STAGE_LANGUAGE, scenario=SCENARIO,
                                 material_mode="text",
                                 material_text="Мой текст."))

    msg = _Msg()
    _press(f"stage:edit:{bot.STAGE_PHOTO}", msg)

    s = bot.load_session(7)
    assert s["step"] == bot.WAIT_PHOTO
    assert s["language"] == "ru"
    assert s["scenario"] == SCENARIO
    assert s["material_text"] == "Мой текст."


def test_навигация_под_карточкой_считает_от_её_этапа(work):
    """«← Назад» и «Вперёд →» из истории чата двигались от текущего этапа, а не
    от того, под которым висят: с карточки голоса человек уезжал не туда."""
    bot.save_session(7, _паспорт(step=bot.VIEWING_STAGE,
                                 stage=bot.STAGE_MATERIAL, material_mode="raw",
                                 material_text="сырьё"))

    msg = _Msg()
    _press(f"stage:prev:{bot.STAGE_VOICE}", msg)

    s = bot.load_session(7)
    assert s["step"] == bot.VIEWING_STAGE and s["stage"] == bot.STAGE_PHOTO


def test_старая_кнопка_идеи_после_замены_материала_не_роняет_разговор(
        work, monkeypatch):
    """Замена материала снимает список идей целиком, а кнопки под ним остаются
    в переписке. Обработчик индексировал список без проверок: тап падал
    IndexError, и человек не получал вообще ничего."""
    генерации = []
    monkeypatch.setattr(
        bot, "step_scenario",
        lambda chat_id, idea, language, gender=None:
            генерации.append(idea) or SCENARIO,
    )
    bot.save_session(7, _паспорт(step=bot.REVIEW, scenario=SCENARIO,
                                 material_mode="text",
                                 material_text="Мой текст."))

    msg = _Msg()
    _press("idea:1", msg)

    assert генерации == []
    assert bot.load_session(7)["step"] == bot.REVIEW
    assert "[хук]" in msg.replies[-1]


def test_кнопка_идеи_с_мусорным_индексом_показывает_текущий_экран(work):
    """int() на чужом callback роняет обработчик так же, как выход за границы
    списка."""
    bot.save_session(7, _паспорт(step=bot.REVIEW, scenario=SCENARIO))

    msg = _Msg()
    _press("idea:мусор", msg)

    assert "[хук]" in msg.replies[-1]


def test_кнопка_идеи_во_время_сборки_не_запускает_вторую_генерацию(
        work, клиент, monkeypatch):
    """Оплаченная сборка идёт: вторая генерация на тот же профиль — это ещё
    один прогон Клода и уведённый с job разговор."""
    генерации = []
    monkeypatch.setattr(
        bot, "step_scenario",
        lambda chat_id, idea, language, gender=None:
            генерации.append(idea) or SCENARIO,
    )
    bot.save_session(7, _паспорт(step=bot.READY, scenario=SCENARIO,
                                 scenario_approved=True))
    bot.enqueue_build(7, SCENARIO, language="ru", voice_id="voice-1")
    s = bot.load_session(7)
    s.update({"step": bot.CHOOSING_IDEA,
              "ideas": [{"idea": "Раз", "draft_hook": "Хук"}],
              "current_job_id": bot._job_store().latest_for_chat(7).job_id})
    bot.save_session(7, s)

    msg = _Msg()
    _press("idea:0", msg)

    assert генерации == []
    assert msg.replies == [bot.BUSY_MSG]


def test_кнопка_возврата_к_выбору_после_доставленного_ролика_не_продаёт_второй(
        work):
    """Кнопка «← Назад к выбору» с экрана упавшей сборки живёт в переписке и
    после того, как следующий ролик доставлен. Экран выбора по ней — это счёт
    за второй ролик по тому же материалу, которого никто не просил."""
    _с_балансом()
    bot.save_session(7, _паспорт(step=bot.DONE, scenario=SCENARIO,
                                 scenario_approved=True))

    msg = _Msg()
    _press("ready:show", msg)

    assert bot.load_session(7)["step"] == bot.DONE
    assert msg.replies[-1] == bot.DONE_MSG
    assert _labels(msg.markups[-1]) == ["Новый ролик"]
    assert "$" not in msg.replies[-1]


def test_сообщение_во_время_оплаченной_работы_не_зовёт_нажать_start(work):
    """/start отменяет ждущую job: человек своей же рукой стирает то, за что
    заплатил. Ответ на этих шагах обязан говорить, что работа идёт."""
    for шаг, ожидание in ((bot.AUDIO_PREPARING, bot.WORK_IN_PROGRESS_MSG),
                          (bot.BUILDING, bot.WORK_IN_PROGRESS_MSG),
                          (bot.AUDIO_REVIEW, bot.AUDIO_REVIEW_WAITING_MSG)):
        bot.save_session(7, _паспорт(step=шаг, scenario=SCENARIO,
                                     current_job_id="job-1"))
        msg = _Msg("а долго ещё?")
        asyncio.run(bot.on_message(_Update(msg), None))

        assert msg.replies[-1] == ожидание, шаг
        assert "/start" not in msg.replies[-1]
        assert bot.load_session(7)["step"] == шаг

    # Ожидание голосового обслуживается раньше _reshow (там своя сверка с job),
    # поэтому его ответ проверяем на самом экране.
    msg = _Msg()
    asyncio.run(bot._reshow(msg, 7, _паспорт(step=bot.WAIT_FINAL_AUDIO)))
    assert msg.replies[-1] == bot.FINAL_AUDIO_WAITING_MSG
    assert "/start" not in msg.replies[-1]


def _job_на_сборке(chat_id: int = 7):
    """Сессия с утверждённым сценарием и её job, уже взятая worker'ом."""
    bot.save_session(chat_id, _паспорт(step=bot.READY, scenario=SCENARIO,
                                       scenario_approved=True))
    job = bot.enqueue_build(chat_id, SCENARIO, language="ru",
                            voice_id="voice-1")
    s = bot.load_session(chat_id)
    s["current_job_id"] = job.job_id
    bot.save_session(chat_id, s)
    return _claim_job()


def _выходы_отказа(api) -> list[str]:
    """Подписи кнопок последнего сообщения worker'а."""
    assert api.markups[-1] is not None, "экран отказа пришёл без кнопок"
    return _labels(api.markups[-1])


#: Хвост клавиатуры отказа. Проверяем именно хвостом: перед ним встаёт
#: кнопка продолжения упавшей сборки, и она есть не на каждом отказе —
#: её наличие проверяют отдельные тесты продолжения.
ВОЗВРАТ = ["← Назад к выбору", "Новый ролик"]


def test_все_отказы_озвучки_дают_кнопку_возврата(work, клиент, tmp_path):
    """Клавиатуру возврата получили только два выхода в BUILD_FAILED. На
    остальных человек оставался с текстом отказа и без единой кнопки — при
    живом утверждённом сценарии, по которому можно пересобрать."""
    # 1. озвучка не создалась
    job = _job_на_сборке()
    api = _BotAPI()
    asyncio.run(bot._process_audio_job(
        api, job, preview_fn=lambda chat_id, workdir:
            {"ok": False, "stage": "audio_preview", "error": "TTS лёг"},
    ))
    assert bot.AUDIO_FAILED_MSG in api.messages[-1][1]
    assert _выходы_отказа(api)[-2:] == ВОЗВРАТ

    # 2. озвучка отчиталась об успехе, а файла нет
    job = _job_на_сборке()
    api = _BotAPI()
    asyncio.run(bot._process_audio_job(
        api, job, preview_fn=lambda chat_id, workdir:
            {"ok": True, "audio": str(tmp_path / "нет.mp3")},
    ))
    assert "audio-файл не найден" in api.messages[-1][1]
    assert _выходы_отказа(api)[-2:] == ВОЗВРАТ

    # 3. Telegram не принял аудио
    class ОтказПоАудио(_BotAPI):
        async def send_audio(self, **kwargs):
            raise RuntimeError("Telegram отказал")

    def превью(chat_id, workdir):
        audio = workdir / "audio" / "tts" / "voice_master.mp3"
        audio.parent.mkdir(parents=True)
        audio.write_bytes(b"preview-audio")
        return {"ok": True, "audio": str(audio), "stage": "audio_review"}

    job = _job_на_сборке()
    api = ОтказПоАудио()
    asyncio.run(bot._process_audio_job(api, job, preview_fn=превью))
    assert "не принял аудиофайл" in api.messages[-1][1]
    assert _выходы_отказа(api)[-2:] == ВОЗВРАТ


def test_все_отказы_сборки_дают_кнопку_возврата(work, клиент, monkeypatch):
    """Те же тупики на стороне рендера: сценарий цел, а выхода к нему с экрана
    отказа не было."""
    def собрать(chat_id, workdir, *, qa=True, размер=1):
        mp4 = workdir / "reel.mp4"
        mp4.write_bytes(b"x" * размер)
        return {"ok": True, "mp4": str(mp4), "qa_pass": qa}

    # 1. файла ролика нет
    job = _job_на_сборке()
    api = _BotAPI()
    asyncio.run(bot._process_job(
        api, job,
        build_fn=lambda chat_id, workdir: {"ok": True, "qa_pass": True},
    ))
    assert api.messages[-1][1] == bot.MISSING_FILE_MSG
    assert _выходы_отказа(api)[-2:] == ВОЗВРАТ

    # 2. QA не пройден
    job = _job_на_сборке()
    api = _BotAPI()
    asyncio.run(bot._process_job(
        api, job, build_fn=lambda c, w: собрать(c, w, qa=False)))
    assert bot.QA_FAIL_MSG in api.messages[-1][1]
    assert _выходы_отказа(api)[-2:] == ВОЗВРАТ

    # 3. ролик тяжелее 50 МБ
    monkeypatch.setattr(bot, "MAX_TG_VIDEO_BYTES", 3)
    job = _job_на_сборке()
    api = _BotAPI()
    asyncio.run(bot._process_job(
        api, job, build_fn=lambda c, w: собрать(c, w, размер=10)))
    assert "50 МБ" in api.messages[-1][1]
    assert _выходы_отказа(api)[-2:] == ВОЗВРАТ

    # 4. Telegram не принял видео
    monkeypatch.setattr(bot, "MAX_TG_VIDEO_BYTES", 1_000_000)

    class ОтказПоВидео(_BotAPI):
        async def send_video(self, **kwargs):
            raise RuntimeError("Telegram отказал")

    job = _job_на_сборке()
    api = ОтказПоВидео()
    asyncio.run(bot._process_job(api, job, build_fn=собрать))
    assert "не принял файл" in api.messages[-1][1]
    assert _выходы_отказа(api)[-2:] == ВОЗВРАТ


def test_прерванный_перезапуском_прогон_даёт_кнопку_возврата(work, клиент,
                                                             monkeypatch):
    """Сервис перезапустили посреди сборки: job закрывается сама, а человеку
    уходит сообщение, из которого раньше не следовало ни одного действия."""
    monkeypatch.delenv("TRIBUTE_API_KEY", raising=False)
    _job_на_сборке()
    api = _BotAPI()

    async def _меню(commands):
        pass

    api.set_my_commands = _меню

    class FakeApp:
        bot = api

    asyncio.run(bot._post_init(FakeApp()))

    assert bot.INTERRUPTED_MSG in api.messages[-1][1]
    assert _выходы_отказа(api)[-2:] == ВОЗВРАТ
    assert bot.load_session(7)["step"] == bot.BUILD_FAILED


def test_отмена_пополнения_возвращает_экран_выбора_целиком(work):
    """Возвращались только кнопки: под ними оставался текст экрана пополнения,
    и человек читал про баланс, выбирая монтаж."""
    _с_балансом()
    bot.save_session(7, _паспорт(step=bot.READY, scenario=SCENARIO,
                                 scenario_approved=True))
    msg = _Msg(bot.topup_text(3_000_000, bot._ledger().balance(7)))

    _press("topup:cancel", msg)

    assert msg.replies[-1].startswith(bot.READY_MSG)
    assert "Пополнить — кнопкой ниже" not in msg.replies[-1]
    подписи = _labels(msg.markups[-1])
    assert подписи[0].startswith("🎬 С монтажом — $")
    assert подписи[-1] == "← Назад"


def test_оплата_вне_ролика_не_запирает_человека_в_экране_денег(work, магазин):
    """Экран выбора отдаётся только на шаге READY. На любом другом человек
    получал сообщение об оплате с одной кнопкой «Пополнить баланс» — и никакого
    пути обратно в разговор."""
    bot.save_session(7, _паспорт(step=bot.REVIEW, scenario=SCENARIO,
                                 pay_currency="usd"))
    msg = _Msg()
    _press("topup:amt:usd:1000", msg)

    магазин["status"].append("paid")
    _press("topup:check", msg)

    assert "Оплата получена" in msg.replies[-1]
    assert _labels(msg.markups[-1]) == ["💳 Пополнить баланс", "← Вернуться"]

    возврат = _Msg()
    _press("screen:current", возврат)

    assert bot.load_session(7)["step"] == bot.REVIEW
    assert "[хук]" in возврат.replies[-1]


def test_выбранный_путь_протухает_при_возврате_на_экран_выбора(work, магазин):
    """topup_path жил до конца цикла: тапнув однажды по дорогому пути, человек
    считал нехватку по нему и после того, как передумал и вернулся."""
    bot.save_session(7, _паспорт(step=bot.READY, scenario=_сценарий_на(700),
                                 scenario_approved=True))
    msg = _Msg()

    _press("build:montage", msg)
    assert bot.load_session(7)["topup_path"] == "montage"

    _press("ready:show", msg)
    assert "topup_path" not in bot.load_session(7)

    _press("topup:start", msg)
    _press("topup:cur:usd", msg)

    цены = bot.path_prices(7, bot.load_session(7), bot._billing())
    ровно = bot.format_minor(
        bot.exact_topup_minor(цены["plain"], "usd", bot._billing()["fx"]), "usd")
    assert _labels(msg.markups[-1])[0] == f"{ровно} — ровно на этот ролик"


def test_экран_сценария_без_сценария_возвращает_на_материал(work):
    """Сценарий мог не пережить замену материала. Сброс в /start отсюда терял
    язык, пол, фото и само сырьё — всё, что человек уже прислал."""
    bot.save_session(7, _паспорт(step=bot.REVIEW, material_mode="raw",
                                 material_text="сырьё про продажи"))

    msg = _Msg()
    asyncio.run(bot._show_review(msg, 7, bot.load_session(7)))

    s = bot.load_session(7)
    assert s["step"] == bot.VIEWING_STAGE and s["stage"] == bot.STAGE_MATERIAL
    assert s["language"] == "ru" and s["gender"] == "male"
    assert s["photo"] == {"asset_id": "asset-1", "file": "фото.jpg"}
    assert s["material_text"] == "сырьё про продажи"
    assert "сырьё про продажи" in msg.replies[-1]


def test_доля_ведущей_считается_один_раз_и_не_плавает_к_очереди(
        реестр, monkeypatch):
    """island_avatar_share ловит ошибки широко и молча откатывается на полную
    цену. Профиль пишется как раз между экраном и очередью, поэтому два вызова
    подряд могли дать разные числа: человек читал урезанную цену на кнопке, а
    очередь требовала полную. Доля считается один раз и живёт в сессии."""
    clients_mod.register_client(
        "2",
        _client_base_cfg(avatar_islands={"enabled": True},
                         master_audio={"enabled": True}),
        voice_id="voice-1", asset_id="asset-1",
    )
    s = _паспорт(step=bot.READY, scenario=SCENARIO, scenario_approved=True)
    bot.save_session(2, s)

    msg = _Msg(chat_id=2)
    asyncio.run(bot._show_ready_screen(msg, 2, s))
    цена_на_кнопке = re.search(r"\$\d+\.\d{2}",
                               _labels(msg.markups[-1])[0]).group(0)
    assert цена_на_кнопке != bot.format_usd(_оценка_сборки())   # доля применена

    def лежит(_chat_id):
        raise RuntimeError("реестр не прочитался")

    monkeypatch.setattr(clients_mod, "load_client", лежит)

    with pytest.raises(bot.InsufficientBalance) as отказ:
        bot.enqueue_build(2, SCENARIO, language="ru", voice_id="voice-1",
                          session=bot.load_session(2))

    assert bot.format_usd(отказ.value.need) == цена_на_кнопке


# --- сам перевод сценария (step_translate) -----------------------------------
#
# Путь «Да» на смене языка целиком опирается на него: блоки и роли обязаны
# дожить до сборки в том же числе и порядке, потому что озвучивается
# blocks[i]["speech"], а цена ролика считается по их символам.

class _Переводчик:
    """_PromptRunner без claude: отдаёт заготовленный ответ и свою стоимость."""

    ответ = "{}"

    def __init__(self):
        self.runs = []
        self.total_cost_usd = 0.0

    def run_prompt(self, prompt):
        self.заданный_промпт = prompt
        self.total_cost_usd = 0.03
        self.runs.append({"skill": "translate", "cost_usd": 0.03})
        if isinstance(self.ответ, Exception):
            raise self.ответ
        return self.ответ


def _переводчик(monkeypatch, ответ):
    """Подменить раннер перевода и вернуть его экземпляры для проверок."""
    созданные = []

    class Р(_Переводчик):
        pass

    Р.ответ = ответ
    monkeypatch.setattr(
        bot, "_PromptRunner",
        lambda: созданные.append(Р()) or созданные[-1],
    )
    return созданные


def test_перевод_сохраняет_роли_и_пересчитывает_тайминги(work, monkeypatch):
    """Роли и их число держат всё остальное: сборка озвучивает blocks[i], а
    цена считается по их символам. Тайминги пересчитываются по новому тексту —
    перевод длиннее оригинала, и старые границы разъехались бы с речью."""
    _переводчик(monkeypatch, json.dumps({"blocks": [
        {"role": "hook", "speech": "Сатылымдар ертерек басталады."},
        {"role": "cta", "speech": "Өзіңе сақтап қой."},
    ]}, ensure_ascii=False))

    sc = bot.step_translate(7, SCENARIO, "kk")

    assert [b["role"] for b in sc["blocks"]] == ["hook", "cta"]
    assert sc["language"] == "kk"
    assert sc["title"] == SCENARIO["title"]
    assert sc["blocks"][0]["speech"] == "Сатылымдар ертерек басталады."
    # границы идут встык и посчитаны по словам нового текста, а не унаследованы
    assert sc["blocks"][0]["start"] == 0.0
    assert sc["blocks"][1]["start"] == sc["blocks"][0]["end"]
    assert sc["blocks"][0]["end"] != SCENARIO["blocks"][0]["end"]
    from reels_factory.scenario import validate_integrity
    assert validate_integrity(sc) == []
    # исходник не тронут: «Нет» и повторный перевод должны иметь что переводить
    assert SCENARIO["blocks"][0]["speech"] == "Продажи начинаются раньше."


def test_перевод_с_потерянным_блоком_отклоняется(work, monkeypatch):
    """Пропавший блок — это молча вырезанная реплика: сборка озвучит меньше,
    чем человек утвердил, и заметит он это уже в готовом ролике."""
    _переводчик(monkeypatch, json.dumps(
        {"blocks": [{"role": "hook", "speech": "Бір ғана блок."}]},
        ensure_ascii=False))

    with pytest.raises(bot.ScenarioError):
        bot.step_translate(7, SCENARIO, "kk")


def test_перевод_с_пустой_репликой_отклоняется(work, monkeypatch):
    """Пустой speech проходит все гейты и даёт немую дырку в озвучке."""
    _переводчик(monkeypatch, json.dumps({"blocks": [
        {"role": "hook", "speech": "Сатылымдар ертерек басталады."},
        {"role": "cta", "speech": "   "},
    ]}, ensure_ascii=False))

    with pytest.raises(bot.ScenarioError):
        bot.step_translate(7, SCENARIO, "kk")


def test_провал_перевода_всё_равно_пишет_себестоимость(work, monkeypatch):
    """Провал стоит столько же, сколько успех: без записи трата Клода на
    неудачный перевод пропадает из отчётов."""
    from reels_factory.billing import claude_cost_micro

    _переводчик(monkeypatch, RuntimeError("claude -p (перевод) failed"))

    with pytest.raises(RuntimeError):
        bot.step_translate(7, SCENARIO, "kk")

    assert _себестоимость_клода(7) == claude_cost_micro(0.03)
    assert bot._ledger().balance(7) == 0        # с человека не списано

# =============================================================================
# Продолжение упавшей сборки с места остановки
# =============================================================================

ПРОДОЛЖИТЬ = "Перезапустить сборку"
ПРОДОЛЖЕНИЕ_ОБЕЩАНО = (
    "Ролик остановился на середине. Всё, что уже сделано — озвучка и снятые "
    "кадры — сохранено: продолжу с этого места, платить за них второй раз не "
    "придётся."
)


def _данные_кнопки(markup, подпись: str):
    """callback_data кнопки с такой подписью; None — кнопки нет."""
    if markup is None:
        return None
    for row in markup.inline_keyboard:
        for кнопка in row:
            if кнопка.text == подпись:
                return кнопка.callback_data
    return None


def _события(chat_id: int = 7) -> list[str]:
    with bot._events()._connect() as conn:
        rows = conn.execute(
            "SELECT event FROM events WHERE chat_id = ? ORDER BY id",
            (chat_id,),
        ).fetchall()
    return [r["event"] for r in rows]


def _сколько_job(chat_id: int = 7) -> int:
    with bot._job_store()._connect() as conn:
        return int(conn.execute(
            "SELECT COUNT(*) AS n FROM build_jobs WHERE chat_id = ?",
            (chat_id,),
        ).fetchone()["n"])


def _собрать(chat_id, workdir, *, qa=True, размер=1):
    mp4 = workdir / "reel.mp4"
    mp4.write_bytes(b"x" * размер)
    return {"ok": True, "mp4": str(mp4), "qa_pass": qa}


def _упавшая_сборка():
    """Дошли до рендера и упали: job failed, сессия в BUILD_FAILED."""
    job = _job_на_сборке()
    api = _BotAPI()

    def падаем(chat_id, workdir):
        raise RuntimeError("рендер лёг на середине")

    asyncio.run(bot._process_job(api, job, build_fn=падаем))
    return job, api


def _провал_проверок():
    """Ролик собрался, но не прошёл гейты: озвучка и ведущая уже оплачены."""
    job = _job_на_сборке()
    api = _BotAPI()
    asyncio.run(bot._process_job(
        api, job, build_fn=lambda c, w: _собрать(c, w, qa=False)))
    return job, api


def test_экран_упавшей_сборки_предлагает_продолжить_первой_строкой(
        work, клиент):
    """Единственным выходом с экрана отказа была новая сборка — то есть новая
    папка, новая оценка баланса на весь ролик и повторная оплата озвучки и
    ведущей, которые в старой папке уже лежат готовыми."""
    job, api = _упавшая_сборка()

    подписи = _выходы_отказа(api)
    assert подписи[0] == ПРОДОЛЖИТЬ, подписи
    assert job.job_id in (_данные_кнопки(api.markups[-1], ПРОДОЛЖИТЬ) or "")
    # Обещание в тексте: не «ничего не спишется» — кадр, застигнутый рестартом
    # ровно в момент заказа, HeyGen не хранит и закажется снова.
    assert ПРОДОЛЖЕНИЕ_ОБЕЩАНО in api.messages[-1][1]
    assert bot.BUILD_FAILED_MSG in api.messages[-1][1]

    # Тот же экран, показанный заново (человек написал в чат текстом).
    msg = _Msg("и что теперь?")
    asyncio.run(bot.on_message(_Update(msg), None))
    assert _данные_кнопки(msg.markups[-1], ПРОДОЛЖИТЬ)


def test_провал_проверок_качества_тоже_предлагает_продолжить(work, клиент):
    """Ролик собрался, но не прошёл гейты: озвучка и ведущая оплачены,
    пересобрать надо только монтаж."""
    job, api = _провал_проверок()

    assert bot._job_store().get(job.job_id).status == "qa_failed"
    assert _выходы_отказа(api)[0] == ПРОДОЛЖИТЬ


def test_кнопки_продолжения_нет_там_где_продолжать_нечего(
        work, клиент, monkeypatch):
    """Чёрный список: озвучка (продолжать нечего — она и есть первый шаг),
    ролик тяжелее лимита Telegram (пересборка веса не изменит) и доставленный
    ролик (человек его уже получил)."""
    # 1. озвучка не создалась
    job = _job_на_сборке()
    api = _BotAPI()
    asyncio.run(bot._process_audio_job(
        api, job, preview_fn=lambda chat_id, workdir:
            {"ok": False, "stage": "audio_preview", "error": "TTS лёг"},
    ))
    assert bot.AUDIO_FAILED_MSG in api.messages[-1][1]
    assert _данные_кнопки(api.markups[-1], ПРОДОЛЖИТЬ) is None

    # 2. ролик тяжелее лимита Telegram
    monkeypatch.setattr(bot, "MAX_TG_VIDEO_BYTES", 3)
    job = _job_на_сборке()
    api = _BotAPI()
    asyncio.run(bot._process_job(
        api, job, build_fn=lambda c, w: _собрать(c, w, размер=10)))
    assert "50 МБ" in api.messages[-1][1]
    assert _данные_кнопки(api.markups[-1], ПРОДОЛЖИТЬ) is None

    # 3. ролик доставлен
    monkeypatch.setattr(bot, "MAX_TG_VIDEO_BYTES", 1_000_000)
    job = _job_на_сборке()
    api = _BotAPI()
    asyncio.run(bot._process_job(api, job, build_fn=_собрать))
    assert api.videos
    assert _данные_кнопки(api.videos[-1]["reply_markup"], ПРОДОЛЖИТЬ) is None
    msg = _Msg("ещё разок")
    asyncio.run(bot.on_message(_Update(msg), None))
    assert _данные_кнопки(msg.markups[-1], ПРОДОЛЖИТЬ) is None


def test_кнопки_продолжения_нет_после_трёх_попыток_и_без_папки(work, клиент):
    """Сборка, падающая раз за разом, чинится руками, а не кнопкой. И папки
    может уже не быть — тогда продолжать физически нечего."""
    import shutil

    def экран_отказа():
        """Экран неудачи, показанный заново: человек написал в чат."""
        msg = _Msg("что там?")
        asyncio.run(bot.on_message(_Update(msg), None))
        return _данные_кнопки(msg.markups[-1], ПРОДОЛЖИТЬ)

    def перезапусков(n: int) -> None:
        """Столько раз сборку уже возвращали в очередь кнопкой."""
        with bot._job_store()._connect() as conn:
            conn.execute("UPDATE build_jobs SET resumes = ? WHERE job_id = ?",
                         (n, job.job_id))

    job, api = _упавшая_сборка()
    assert _данные_кнопки(api.markups[-1], ПРОДОЛЖИТЬ)

    перезапусков(bot.MAX_RESUME_ATTEMPTS)
    assert экран_отказа() is None

    перезапусков(bot.MAX_RESUME_ATTEMPTS - 1)
    assert экран_отказа()
    shutil.rmtree(job.workdir)
    assert экран_отказа() is None


def test_продолжение_возвращает_ту_же_сборку_мимо_enqueue_build(
        work, клиент, monkeypatch):
    """enqueue_build заводит НОВУЮ папку и заново проверяет баланс на весь
    ролик: пройти через него значит потерять готовую озвучку и снятые кадры и
    попросить денег второй раз."""
    job, api = _упавшая_сборка()
    данные = _данные_кнопки(api.markups[-1], ПРОДОЛЖИТЬ)
    assert данные, "на экране отказа нет кнопки продолжения"

    def запрещено(*a, **kw):
        raise AssertionError("продолжение пошло через enqueue_build")

    monkeypatch.setattr(bot, "enqueue_build", запрещено)
    msg = _Msg()
    _press(данные, msg)

    возвращённая = bot._job_store().get(job.job_id)
    assert возвращённая.status == "queued"
    assert возвращённая.stage == "build"
    assert возвращённая.workdir == job.workdir
    assert _сколько_job(7) == 1, "продолжение завело вторую сборку"
    s = bot.load_session(7)
    assert s["step"] == bot.BUILDING
    assert s["current_job_id"] == job.job_id
    assert msg.replies and msg.replies[-1]
    # Воркер обязан получить ту же папку, а не новую.
    assert _claim_job().workdir == job.workdir


def test_продолжение_с_чужим_или_устаревшим_номером_ничего_не_создаёт(
        work, клиент):
    """Кнопка живёт в истории чата вечно: по ней тапнут и через неделю, и с
    номером сборки, которой уже нет."""
    job, api = _упавшая_сборка()
    данные = _данные_кнопки(api.markups[-1], ПРОДОЛЖИТЬ)
    assert данные, "на экране отказа нет кнопки продолжения"

    _press(данные.replace(job.job_id, "чужой-номер"), _Msg())
    assert bot._job_store().get(job.job_id).status == "failed"
    assert _сколько_job(7) == 1

    # Тот же номер, но сборка уже доставлена — продолжать нечего.
    bot._job_store().finish(job.job_id, "completed", stage="delivery")
    msg = _Msg()
    _press(данные, msg)
    assert bot._job_store().get(job.job_id).status == "completed"
    assert _сколько_job(7) == 1
    assert msg.replies, "тап по устаревшей кнопке остался без ответа"


def test_продолжение_при_идущей_сборке_отвечает_занят(work, клиент):
    """Второй прогон на том же чате — это два платных рендера разом."""
    job, api = _упавшая_сборка()
    данные = _данные_кнопки(api.markups[-1], ПРОДОЛЖИТЬ)
    assert данные, "на экране отказа нет кнопки продолжения"
    другая = bot._job_store().enqueue(7)

    msg = _Msg()
    _press(данные, msg)

    assert msg.replies[-1] == bot.BUSY_MSG
    assert bot._job_store().get(job.job_id).status == "failed"
    assert bot._job_store().get(другая.job_id).status == "queued"


def test_продолжение_после_провала_проверок_сбрасывает_монтажные_маркеры(
        work, клиент):
    """Провал гейтов чинится пересборкой монтажа. Маркеры prepare и plan-early
    при этом неприкосновенны: по плану, помеченному plan-early, ведущая УЖЕ
    куплена, и новый план агента сделал бы оплаченные клипы ненужными."""
    from reels_factory.hf_render import EARLY_PLAN_STEP, step_done

    job, api = _провал_проверок()
    монтажные = ("compose", "gates", "shots", "render", "loudness")
    for шаг in ("prepare", "plan", EARLY_PLAN_STEP, *монтажные):
        (job.workdir / f".hf-{шаг}.done").write_text("ok", encoding="utf-8")

    данные = _данные_кнопки(api.markups[-1], ПРОДОЛЖИТЬ)
    assert данные, "на экране отказа нет кнопки продолжения"
    _press(данные, _Msg())

    for шаг in монтажные:
        assert step_done(job.workdir, шаг) is False, шаг
    assert step_done(job.workdir, "prepare") is True
    assert step_done(job.workdir, EARLY_PLAN_STEP) is True


def test_продолжение_упавшей_сборки_монтаж_не_трогает(work, клиент):
    """Сборка не дошла до файла: пройденные монтажные шаги — это уже снятые
    кадры, снимать с них маркеры значит снимать их заново."""
    from reels_factory.hf_render import step_done

    job, api = _упавшая_сборка()
    for шаг in ("prepare", "compose", "shots"):
        (job.workdir / f".hf-{шаг}.done").write_text("ok", encoding="utf-8")

    данные = _данные_кнопки(api.markups[-1], ПРОДОЛЖИТЬ)
    assert данные, "на экране отказа нет кнопки продолжения"
    _press(данные, _Msg())

    assert step_done(job.workdir, "compose") is True
    assert step_done(job.workdir, "shots") is True


def test_текст_о_прерванной_сборке_обещает_продолжение(work, клиент,
                                                       monkeypatch):
    """Прежний текст обещал обратное: «автоматически повторять не буду, чтобы
    исключить повторную оплату». Продолжение оплату не повторяет."""
    monkeypatch.delenv("TRIBUTE_API_KEY", raising=False)
    assert bot.INTERRUPTED_MSG == (
        "Сборка прервалась. Готовые части сохранены — можно продолжить с того "
        "же места."
    )

    # Именно СБОРКА: у прерванной озвучки продолжения нет и быть не может —
    # оно уводит в монтаж мимо утверждения звука человеком.
    job = _job_на_сборке()
    bot._job_store().transition(
        job.job_id, "queued", expected="audio_running", stage="build")
    _claim_job()
    api = _BotAPI()

    async def _меню(commands):
        pass

    api.set_my_commands = _меню

    class FakeApp:
        bot = api

    asyncio.run(bot._post_init(FakeApp()))

    assert bot.INTERRUPTED_MSG in api.messages[-1][1]
    assert _выходы_отказа(api)[0] == ПРОДОЛЖИТЬ


def test_три_самых_дорогих_сбоя_попадают_в_аналитику(work, клиент):
    """Сборка, проверки и озвучка — самые дорогие сбои продукта, и ни один не
    писал в журнал событий ни строки: в отчёте они выглядели как «человек
    передумал», а не как «у нас сломалось»."""
    from reels_factory.analytics import ERROR_EVENTS

    _упавшая_сборка()
    assert "error:build" in _события(7)

    _провал_проверок()
    assert "error:qa" in _события(7)

    job = _job_на_сборке()
    asyncio.run(bot._process_audio_job(
        _BotAPI(), job, preview_fn=lambda chat_id, workdir:
            {"ok": False, "stage": "audio_preview", "error": "TTS лёг"},
    ))
    события = _события(7)
    сбой_озвучки = [e for e in события if e.startswith("error:audio")]
    assert сбой_озвучки, события
    # Иначе render_funnel упадёт на подписи для незнакомого события.
    for event in ("error:build", "error:qa", *сбой_озвучки):
        assert event in ERROR_EVENTS, event

def test_человеку_доступны_три_перезапуска_а_не_один(work, клиент, monkeypatch):
    """Д4. Кнопка обещает три попытки, а даёт одну.

    Предел считается по `attempts` job, а его увеличивает `claim_next` — то
    есть это число ВЗЯТИЙ job из очереди, а не число перезапусков. За один
    полный проход worker берёт job дважды: сперва на озвучку, потом на сборку.
    Значит к первому же падению `attempts` уже равен двум, первый перезапуск
    доводит его до трёх, и на втором `MAX_RESUME_ATTEMPTS` закрывает кнопку.

    Человек с ролика, который лёг на сетевой осечке дважды подряд, остаётся
    без выхода: единственное, что ему предложат, — новая сборка, а это новая
    папка, новая озвучка и новая ведущая за его же деньги.

    Прогон здесь полный, как в жизни: озвучка (первое взятие), утверждение
    человеком, сборка (второе взятие) — и только потом отказ.
    """
    bot.save_session(7, {
        "step": bot.READY,
        "scenario": SCENARIO,
        "photo": {"asset_id": "a1", "file": "ф.jpg"},
        "voice_id": "voice-1",
    })
    _press("build:plain", _Msg())
    job, _api = _deliver_audio_preview()
    monkeypatch.setattr(bot, "approve_tts_audio", lambda workdir: {})
    _press(f"audio_ok:{job.job_id}", _Msg())

    def падаем(chat_id, workdir):
        raise RuntimeError("рендер лёг на середине")

    def прогон():
        """Worker берёт job из очереди и роняет сборку."""
        api = _BotAPI()
        asyncio.run(bot._process_job(api, _claim_job(), build_fn=падаем))
        return api

    api = прогон()
    for номер in (1, 2, 3):
        данные = _данные_кнопки(api.markups[-1], ПРОДОЛЖИТЬ)
        assert данные, (
            f"перезапуск №{номер} человеку уже недоступен: предел считает "
            f"взятия job из очереди, а их за прогон два")
        _press(данные, _Msg())
        assert bot._job_store().get(job.job_id).status == "queued"
        api = прогон()

    assert _данные_кнопки(api.markups[-1], ПРОДОЛЖИТЬ) is None, (
        "после трёх перезапусков сборка чинится руками, а не четвёртым тапом")


# =============================================================================
# Тупики разговора: экраны, с которых нет выхода, и кнопки без проверки шага
# =============================================================================


def test_экран_баланса_не_запирает_человека(work, клиент):
    """/balance открывался с одной кнопкой «Пополнить баланс»: человек,
    заглянувший на баланс посреди разговора, не мог вернуться к ролику ничем,
    кроме команды."""
    bot.save_session(7, _паспорт(step=bot.READY, scenario=SCENARIO,
                                 scenario_approved=True))
    msg = _Msg("/balance")

    asyncio.run(bot.cmd_balance(_Update(msg), None))

    назад = _данные_кнопки(msg.markups[-1], "← Назад")
    assert назад, _labels(msg.markups[-1])

    возврат = _Msg()
    _press(назад, возврат)
    assert возврат.replies[-1].startswith(bot.READY_MSG)


def test_после_восстановления_озвучки_остаётся_кнопка_показа_сценария(
        work, клиент, monkeypatch):
    """Рестарт посреди проверки голосового: бот просит записать сценарий
    заново — и отправляет просьбу без единой кнопки. Текст сценария человек
    читать не может, а записать его целиком просят именно сейчас."""
    monkeypatch.delenv("TRIBUTE_API_KEY", raising=False)
    job = _job_на_сборке()
    bot._job_store().transition(
        job.job_id, "user_audio_processing", expected="audio_running",
        stage="user_audio",
    )
    api = _BotAPI()

    async def _меню(commands):
        pass

    api.set_my_commands = _меню

    class FakeApp:
        bot = api

    asyncio.run(bot._post_init(FakeApp()))

    assert "голосов" in api.messages[-1][1]
    assert _данные_кнопки(api.markups[-1], "📄 Показать текст сценария")


def test_несовпадение_языка_сценария_ведёт_к_переспросу_с_переводом(
        work, клиент, monkeypatch):
    """«Начните новый ролик через /new или вернитесь к тексту» — текст без
    единой кнопки на утверждённом сценарии. Переспрос с переводом для этого
    случая уже написан (смена языка), и вести надо в него."""
    переводы = []

    def перевод(chat_id, scenario, language):
        переводы.append(language)
        return {**SCENARIO, "language": language}

    monkeypatch.setattr(bot, "step_translate", перевод)
    monkeypatch.setattr(bot, "save_client_profile", lambda chat_id, s: None)
    bot.save_session(7, _паспорт(
        step=bot.REVIEW, language="ru",
        scenario={**SCENARIO, "language": "kk"},
    ))

    msg = _Msg()
    _press("ok", msg)

    assert _labels(msg.markups[-1]) == ["Да", "Нет"], msg.replies[-1]
    да = _данные_кнопки(msg.markups[-1], "Да")

    ответ = _Msg()
    _press(да, ответ)

    assert переводы == ["ru"], "перевод на язык ролика не предложен"
    assert bot.load_session(7)["scenario"]["language"] == "ru"


def test_назад_на_шагах_доставки_и_сборки_не_сбрасывает_разговор(work, клиент):
    """«Назад» — единственная ветка навигации без проверки шага: с экрана
    доставленного ролика, экрана неудачи и идущей сборки она уводила к выбору
    языка и по дороге стирала сценарий и материал."""
    for шаг in (bot.DONE, bot.BUILD_FAILED, bot.BUILDING, bot.AUDIO_PREPARING):
        bot.save_session(7, _паспорт(
            step=шаг, scenario=SCENARIO, scenario_approved=True,
            material_mode="text", material_text="сырьё про продажи",
        ))
        msg = _Msg()

        _press("back", msg)

        s = bot.load_session(7)
        assert s.get("scenario") == SCENARIO, шаг
        assert s.get("material_text") == "сырьё про продажи", шаг
        assert s["step"] == шаг, шаг
        assert msg.replies[-1] != bot.ASK_LANGUAGE, шаг


def test_экран_выбора_языка_сам_по_себе_ничего_не_стирает(work, клиент):
    """Показ экрана — это ещё не смена языка. Сценарий и материал стирает
    только подтверждённая смена, а не открытие экрана: иначе человек, зашедший
    посмотреть, какой язык выбран, теряет написанный текст."""
    bot.save_session(7, _паспорт(
        step=bot.READY, scenario=SCENARIO, scenario_approved=True,
        material_mode="text", material_text="сырьё про продажи",
    ))

    asyncio.run(bot._show_language_choice(_Msg(), 7, bot.load_session(7)))

    s = bot.load_session(7)
    assert s.get("scenario") == SCENARIO
    assert s.get("material_text") == "сырьё про продажи"


def test_платная_кнопка_над_доставленным_роликом_ведёт_к_новому_ролику(
        work, клиент):
    """Кнопка пути живёт в истории чата вечно. Над доставленным роликом она
    отвечала «Сначала выберите, с чего начать: /start» — то есть тупиком без
    кнопок, хотя выход отсюда ровно один и он есть: новый ролик."""
    bot.save_session(7, _паспорт(step=bot.DONE, scenario=SCENARIO,
                                 scenario_approved=True))

    msg = _Msg()
    _press("build:montage", msg)

    assert _сколько_job(7) == 0, "платная сборка запущена над готовым роликом"
    assert _данные_кнопки(msg.markups[-1], "Новый ролик"), msg.replies[-1]


def test_кнопки_языка_и_пола_во_время_сборки_не_запускают_платную_работу(
        work, клиент, monkeypatch):
    """Смена языка — это перевод сценария Клодом, смена пола — новый сценарий:
    обе платные. Кнопки обеих живут в истории чата, и тап по ним посреди уже
    оплаченной сборки тратил деньги на текст, который этой сборке не достанется.
    """
    def запрещено(*a, **kw):
        raise AssertionError("платная работа запущена во время сборки")

    monkeypatch.setattr(bot, "step_translate", запрещено)
    monkeypatch.setattr(bot, "step_scenario", запрещено)
    bot.save_session(7, _паспорт(step=bot.READY, scenario=SCENARIO,
                                 scenario_approved=True))
    job = bot.enqueue_build(7, SCENARIO, language="ru", voice_id="voice-1")
    s = bot.load_session(7)
    s["step"] = bot.BUILDING
    s["current_job_id"] = job.job_id
    # Переспрос о смене языка мог остаться висеть с прошлого экрана.
    s["switch"] = {"kind": "language", "target": "kk", "step": bot.READY}
    bot.save_session(7, s)

    for кнопка in ("reel_language:kk", "reel_gender:female",
                   "switch:language:yes"):
        msg = _Msg()
        _press(кнопка, msg)
        assert msg.replies[-1] == bot.BUSY_MSG, кнопка
        assert bot.load_session(7).get("scenario") == SCENARIO, кнопка
        assert bot.load_session(7).get("step") == bot.BUILDING, кнопка


# =============================================================================
# Дефекты продолжения, найденные ревизией стендом
# =============================================================================


def _рестарт_службы(api) -> None:
    """Перезапуск службы: _post_init закрывает осиротевшие jobs и пишет в чат."""
    async def _меню(commands):
        pass

    api.set_my_commands = _меню

    class FakeApp:
        bot = api

    asyncio.run(bot._post_init(FakeApp()))


def test_прерванная_рестартом_озвучка_не_даёт_кнопку_продолжения(
        work, клиент, monkeypatch):
    """Д1. Рестарт службы посреди озвучки затирает стадию `audio_preview`
    на `restart`, а именно по стадии бот и отсекает такие сборки. С затёртой
    стадией человек получает кнопку продолжения, и она возвращает job в общую
    очередь — то есть в монтаж по озвучке, которую человек ещё не слышал и не
    утверждал. Сборка соберётся по неутверждённому звуку, и это платный рендер.

    Прерванная СБОРКА (стадия `build`) кнопку продолжения обязана сохранить:
    там продолжать есть что, ради этого кнопка и делалась.
    """
    monkeypatch.delenv("TRIBUTE_API_KEY", raising=False)

    # 1. рестарт застал озвучку
    озвучка = _job_на_сборке()
    assert bot._job_store().get(озвучка.job_id).stage == "audio_preview"
    api = _BotAPI()
    _рестарт_службы(api)

    assert bot.INTERRUPTED_MSG in api.messages[-1][1]
    assert _данные_кнопки(api.markups[-1], ПРОДОЛЖИТЬ) is None, (
        "прерванная озвучка предлагает продолжение — оно уведёт в монтаж "
        "мимо утверждения звука"
    )
    # Обещать продолжение текстом там, где кнопки нет, тоже нельзя.
    assert ПРОДОЛЖЕНИЕ_ОБЕЩАНО not in api.messages[-1][1]

    # 2. рестарт застал сборку
    следующая = _job_на_сборке()
    bot._job_store().transition(
        следующая.job_id, "queued", expected="audio_running", stage="build")
    сборка = _claim_job()
    assert bot._job_store().get(сборка.job_id).stage == "build"
    api = _BotAPI()
    _рестарт_службы(api)

    assert _данные_кнопки(api.markups[-1], ПРОДОЛЖИТЬ), (
        "прерванная сборка осталась без кнопки продолжения")


def test_старая_кнопка_продолжения_не_перехватывает_новый_цикл(work, клиент):
    """Д2. Кнопка живёт в истории чата вечно. Человек закрыл упавший ролик,
    начал новый и стоит в начале нового цикла; тап по старой кнопке (случайный
    или из любопытства) возвращает ПРЕЖНЮЮ сборку в очередь и уводит сессию в
    состояние сборки — человек ждёт ролик по новому материалу, а получит
    прежний, и заплатит за его рендер.

    Кнопка обязана работать только для того цикла, в котором человек сейчас
    стоит: номер сборки совпадает с `last_job_id` сессии. Иначе — молча
    показать текущий экран и ничего не запускать.
    """
    job, api = _упавшая_сборка()
    данные = _данные_кнопки(api.markups[-1], ПРОДОЛЖИТЬ)
    assert данные, "на экране отказа нет кнопки продолжения"
    assert bot.load_session(7).get("last_job_id") == job.job_id

    # «Новый ролик»: цикл закрыт, номер прежней сборки сессия больше не помнит.
    _press("new_reel", _Msg())
    было = bot.load_session(7)
    assert было.get("last_job_id") != job.job_id

    msg = _Msg()
    _press(данные, msg)

    стало = bot.load_session(7)
    assert bot._job_store().get(job.job_id).status == "failed", (
        "старая кнопка вернула в очередь сборку прошлого цикла")
    assert bot._job_store().active_for_chat(7) is None
    assert стало["step"] == было["step"], "старая кнопка увела новый цикл"
    assert "current_job_id" not in стало
    assert msg.replies, "тап остался без ответа — экран пропал"


def test_продолжение_без_файла_ролика_пересобирает_монтаж(work, клиент):
    """Д3. Стадия «файла ролика нет»: монтажные маркеры целы, а сам файл
    создаёт последний шаг, чей маркер стоит. Продолжение с такой стадии не
    делает ничего — файла не будет ни на второй попытке, ни на третьей, и три
    тапа человека уходят впустую (а каждый прогон стоит работы агента).

    Лечится тем же, чем провал проверок: монтажные маркеры снимаются, ролик
    собирается заново. Оплаченное — снятые сайты (`prepare`) и план, по
    которому куплена ведущая (`plan-early`), — не трогаем.
    """
    from reels_factory.hf_render import EARLY_PLAN_STEP, step_done

    job = _job_на_сборке()
    api = _BotAPI()
    asyncio.run(bot._process_job(
        api, job,
        # Сборка отчиталась об успехе, а файла на диске нет.
        build_fn=lambda chat_id, workdir: {
            "ok": True, "qa_pass": True, "mp4": str(workdir / "reel.mp4")},
    ))
    упавшая = bot._job_store().get(job.job_id)
    assert упавшая.status == "failed" and упавшая.stage == "output"

    монтажные = ("compose", "gates", "shots", "render", "loudness")
    for шаг in ("prepare", "plan", EARLY_PLAN_STEP, *монтажные):
        (job.workdir / f".hf-{шаг}.done").write_text("ok", encoding="utf-8")

    данные = _данные_кнопки(api.markups[-1], ПРОДОЛЖИТЬ)
    assert данные, "на экране «файла нет» нет кнопки продолжения"
    _press(данные, _Msg())

    for шаг in монтажные:
        assert step_done(job.workdir, шаг) is False, шаг
    assert step_done(job.workdir, "prepare") is True
    assert step_done(job.workdir, EARLY_PLAN_STEP) is True


def test_при_минусе_на_балансе_вместо_продолжения_предлагают_пополнить(
        work, клиент):
    """Д4. Продолжение не смотрит на баланс вовсе. Каждый перезапуск после
    провала проверок — это работа агента-сборщика, и тремя тапами человек
    уводит баланс в минус, ничего об этом не зная: деньги спрашиваются один
    раз, на выборе пути, а тут не спрашиваются никогда.

    Пока баланс отрицательный, на экране неудачи стоит пополнение вместо
    перезапуска; как только минуса нет — возвращается перезапуск.
    """
    job, api = _упавшая_сборка()
    assert _данные_кнопки(api.markups[-1], ПРОДОЛЖИТЬ)

    def экран_отказа():
        """Экран неудачи, показанный заново: человек написал в чат."""
        msg = _Msg("что там с роликом?")
        asyncio.run(bot.on_message(_Update(msg), None))
        return msg.markups[-1]

    _charge_flat(7, bot._ledger().balance(7) + 1_000_000)
    assert bot._ledger().balance(7) < 0

    экран = экран_отказа()
    assert _данные_кнопки(экран, ПРОДОЛЖИТЬ) is None, (
        "перезапуск предложен в минус — каждый тап углубляет долг")
    assert _данные_кнопки(экран, "💳 Пополнить баланс") == "topup:start", (
        _labels(экран))

    _пополнить(7, 5_000_000)
    assert bot._ledger().balance(7) >= 0

    assert _данные_кнопки(экран_отказа(), ПРОДОЛЖИТЬ), (
        "баланс поправлен, а перезапуск не вернулся")
