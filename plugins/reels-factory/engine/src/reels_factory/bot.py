"""Телеграм-бот фабрики: сырьё или готовый текст -> утверждённый сценарий.

Разговор: /start -> выбор пути -> вход пользователя -> (для сырья: выбор идеи)
-> сценарий в чате -> правка текста руками или утверждение. Итоговый вариант
запоминается в сессии чата — с ним дальше работает сборка.

Сборка платная (HeyGen/ElevenLabs), поэтому в этом слое её нет: бот доводит до
утверждённого текста и на этом останавливается.

Состояние чата — json-файл в <workdir>/bot/<chat_id>/session.json: перезапуск
бота не теряет разговор, а рядом лежат рабочие файлы движка этого же чата.

Токен бота — env TELEGRAM_BOT_TOKEN. Запуск: python -m reels_factory.bot
"""
import asyncio
import json
import os
from pathlib import Path

from reels_factory.config import WORK_ROOT, load_config
from reels_factory.llm import ClaudeSkillRunner
from reels_factory.scenario import (ScenarioError, run_generated_path, run_ideas,
                                    run_verbatim_path, split_verbatim)

# Шаги разговора.
CHOOSING = "choosing"        # ждём выбора пути
WAIT_TEXT = "wait_text"      # ждём готовый текст реплик
WAIT_RAW = "wait_raw"        # ждём сырьё (мысли, отрывок, запись)
CHOOSING_IDEA = "choosing_idea"
REVIEW = "review"            # сценарий показан, ждём решения
WAIT_EDIT = "wait_edit"      # ждём отредактированный текст
CHOOSING_PHOTO = "choosing_photo"  # фото уже есть: прежнее или новое
WAIT_PHOTO = "wait_photo"
WAIT_VOICE = "wait_voice"
READY = "ready"              # сценарий утверждён, фото и голос собраны

ROLE_RU = {"hook": "хук", "context": "контекст", "development": "развитие",
           "payoff": "вывод", "cta": "призыв"}

HELLO = (
    "Это фабрика рилсов. Сделаю вертикальный ролик, где вашим голосом и лицом "
    "говорят ваши мысли.\n\nС чего начнём?"
)
ASK_TEXT = (
    "Пришлите текст ролика — ровно те слова, которые должны прозвучать.\n\n"
    "Ничего переписывать не буду: разобью на блоки и расставлю ударения, "
    "чтобы голос не спотыкался. Хорошая длина — 60–90 слов, это около 30 секунд."
)
ASK_RAW = (
    "Пришлите сырьё — из него соберу сценарий.\n\n"
    "Подойдёт что угодно: ваши мысли текстом, кусок расшифровки урока, отрывок "
    "из книги, голосовое, видео или аудиозапись. Чем конкретнее и живее "
    "исходник, тем меньше воды в ролике."
)
WORKING = "Работаю, это займёт минуту-другую…"
TRANSCRIBING = "Распознаю запись, это дольше обычного…"
ASK_EDIT = (
    "Пришлите свой вариант текста целиком — запомню его как итоговый и "
    "покажу, как он ляжет в блоки."
)
APPROVED_MSG = "Сценарий утверждён и сохранён."
ASK_PHOTO = (
    "Теперь фото — с него сделаю говорящего ведущего.\n\n"
    "Снимите или пришлите портрет: смотрите в камеру, лицо целиком, ровный "
    "свет, без тёмных очков и без чужих лиц в кадре.\n\n"
    "Важно: всё, что должно выглядеть настоящим, должно быть видно на фото. "
    "Кисти рук — чтобы ногти были ваши, кольца, часы, одежда. Чего на фото "
    "нет, то модель додумает по-своему."
)
ASK_VOICE = (
    "Осталась запись голоса — её делаем один раз.\n\n"
    "Наговорите 1–2 минуты в тихой комнате, обычным разговорным тоном: так, "
    "как будете звучать в ролике. Не читайте по бумажке нараспев и не "
    "торопитесь — ровный живой темп. Годится голосовое прямо в чат."
)
PHOTO_SAVED = "Фото принял."
VOICE_SAVED = "Голос принял."
READY_MSG = (
    "Всё на месте: сценарий, фото и голос. Сборка ролика — следующий шаг, "
    "включу её отдельно."
)
NOT_NOW = "Сначала выберите, с чего начать: /start"


def render_scenario(sc: dict) -> str:
    """Сценарий человеку: заголовок, блоки по ролям, оценка длительности."""
    lines = []
    title = str(sc.get("title") or "").strip()
    if title:
        lines.append(f"🎬 {title}\n")
    for b in sc.get("blocks") or []:
        role = ROLE_RU.get(b.get("role"), b.get("role") or "")
        lines.append(f"[{role}] {b.get('speech')}")
    last = (sc.get("blocks") or [{}])[-1]
    end = last.get("end")
    if isinstance(end, (int, float)):
        lines.append(f"\n⏱ примерно {round(end)} сек")
    return "\n".join(lines)


def render_ideas(ideas: list) -> str:
    """Идеи с хуками — чтобы выбор был осмысленным, а не «первая/вторая»."""
    out = ["Вот что нашёл в сырье. Выберите, про что снимаем:\n"]
    for i, idea in enumerate(ideas, 1):
        out.append(f"{i}. {idea.get('idea')}\n   Хук: «{idea.get('draft_hook')}»\n")
    return "\n".join(out)


# Копипаста приходит с «ёлочками» и пустыми строками между абзацами — в речь
# это лезть не должно, иначе кавычка попадает в реплику, а абзац рвёт блок.
_QUOTES = "«»„“”\"'"


def clean_input(text: str) -> str:
    lines = [ln.strip().strip(_QUOTES).strip() for ln in str(text or "").splitlines()]
    return " ".join(ln for ln in lines if ln)


def scenario_from_text(text: str) -> dict:
    """Правка пользователя — закон: слова его, движок только режет на блоки."""
    return {"mode": "verbatim", "blocks": split_verbatim(text)}


def session_dir(chat_id: int) -> Path:
    return WORK_ROOT / "bot" / str(chat_id)


def load_session(chat_id: int) -> dict:
    p = session_dir(chat_id) / "session.json"
    if not p.exists():
        return {"step": CHOOSING}
    return json.loads(p.read_text(encoding="utf-8"))


def save_session(chat_id: int, data: dict) -> None:
    d = session_dir(chat_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "session.json").write_text(json.dumps(data, ensure_ascii=False, indent=1),
                                    encoding="utf-8")


# --- шаги движка (синхронные и небыстрые — в боте зовутся через to_thread) ---

def _language() -> str:
    try:
        return load_config().get("language", "ru")
    except Exception:
        return "ru"


def step_verbatim(chat_id: int, text: str) -> dict:
    res = run_verbatim_path(session_dir(chat_id), text, ClaudeSkillRunner(),
                            language=_language())
    return res["scenario"]


def step_ideas(chat_id: int, text: str) -> list:
    return run_ideas(session_dir(chat_id), text, ClaudeSkillRunner(), _language())["ideas"]


def step_scenario(chat_id: int, idea: dict) -> dict:
    res = run_generated_path(session_dir(chat_id), idea, ClaudeSkillRunner(),
                             language=_language())
    return res["scenario"]


def step_photo(chat_id: int, photo: Path) -> str:
    """Фото -> asset_id в HeyGen (бесплатно, платит только рендер)."""
    from reels_factory.profile import upload_photo

    return upload_photo(photo)


def step_voice(chat_id: int, audio: Path) -> str:
    """Запись -> клон голоса в ElevenLabs -> voice_id."""
    from reels_factory.tts import create_voice_clone

    return create_voice_clone(str(audio), f"tg-{chat_id}")


def save_client_profile(chat_id: int, session: dict) -> None:
    """Профиль клиента в реестре — с ним сборка идёт как `make --client <id>`."""
    from reels_factory.clients import register_client

    photos = session.get("photos") or []
    if not (photos and session.get("voice_id")):
        return
    register_client(str(chat_id), load_config(), name=f"tg-{chat_id}",
                    voice_id=session["voice_id"],
                    asset_id=photos[session.get("photo", -1)]["asset_id"],
                    overwrite=True)


def transcribe(chat_id: int, media: Path) -> str:
    """Речь из записи в текст — локально, без сети и без денег."""
    from reels_factory.transcribe import transcribe_file

    meta = transcribe_file(str(media), str(session_dir(chat_id)), language=_language())
    words = json.loads(Path(meta["out"]).read_text(encoding="utf-8"))["words"]
    return " ".join(w["text"] for w in words)


# --- слой телеграма ---------------------------------------------------------

def _kb_start():
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("У меня готовый сценарий", callback_data="mode:text")],
        [InlineKeyboardButton("Предложи сценарий", callback_data="mode:raw")],
    ])


def _kb_ideas(n: int):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(str(i + 1), callback_data=f"idea:{i}")]
         for i in range(n)])


def _kb_photo():
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Использовать загруженное фото", callback_data="photo:old")],
        [InlineKeyboardButton("Загрузить новое фото", callback_data="photo:new")],
    ])


def _kb_review():
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Утвердить", callback_data="ok")],
        [InlineKeyboardButton("Изменить текст", callback_data="edit")],
        [InlineKeyboardButton("Начать заново", callback_data="restart")],
    ])


async def cmd_start(update, context):
    chat_id = update.effective_chat.id
    save_session(chat_id, {"step": CHOOSING})
    await update.message.reply_text(HELLO, reply_markup=_kb_start())


async def on_button(update, context):
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    s = load_session(chat_id)
    data = q.data

    if data == "mode:text":
        s["step"] = WAIT_TEXT
        save_session(chat_id, s)
        await q.message.reply_text(ASK_TEXT)
    elif data == "mode:raw":
        s["step"] = WAIT_RAW
        save_session(chat_id, s)
        await q.message.reply_text(ASK_RAW)
    elif data.startswith("idea:"):
        idea = (s.get("ideas") or [])[int(data.split(":")[1])]
        await q.message.reply_text(WORKING)
        try:
            sc = await asyncio.to_thread(step_scenario, chat_id, idea)
        except (ScenarioError, RuntimeError) as e:
            await q.message.reply_text(f"Не получилось собрать сценарий: {e}")
            return
        s.update(step=REVIEW, scenario=sc)
        save_session(chat_id, s)
        await q.message.reply_text(render_scenario(sc), reply_markup=_kb_review())
    elif data == "edit":
        s["step"] = WAIT_EDIT
        save_session(chat_id, s)
        await q.message.reply_text(ASK_EDIT)
    elif data == "ok":
        await q.message.reply_text(APPROVED_MSG)
        await _photo_stage(q.message, chat_id, s)
    elif data == "photo:old":
        s["photo"] = len(s.get("photos") or []) - 1
        save_session(chat_id, s)
        await _voice_stage(q.message, chat_id, s)
    elif data == "photo:new":
        s["step"] = WAIT_PHOTO
        save_session(chat_id, s)
        await q.message.reply_text(ASK_PHOTO)
    elif data == "restart":
        save_session(chat_id, {"step": CHOOSING})
        await q.message.reply_text(HELLO, reply_markup=_kb_start())


async def _photo_stage(msg, chat_id: int, s: dict):
    """Фото обязательно: в первый раз просим, дальше — прежнее или новое."""
    if s.get("photos"):
        s["step"] = CHOOSING_PHOTO
        save_session(chat_id, s)
        await msg.reply_text("Снимаем по вашему фото. Какому?", reply_markup=_kb_photo())
    else:
        s["step"] = WAIT_PHOTO
        save_session(chat_id, s)
        await msg.reply_text(ASK_PHOTO)


async def _voice_stage(msg, chat_id: int, s: dict):
    """Голос — один раз на человека."""
    if s.get("voice_id"):
        s["step"] = READY
        save_session(chat_id, s)
        save_client_profile(chat_id, s)
        await msg.reply_text(READY_MSG)
    else:
        s["step"] = WAIT_VOICE
        save_session(chat_id, s)
        await msg.reply_text(ASK_VOICE)


async def on_message(update, context):
    chat_id = update.effective_chat.id
    s = load_session(chat_id)
    step = s.get("step", CHOOSING)
    msg = update.message

    if step == WAIT_PHOTO:
        photo = (msg.photo[-1] if msg.photo else None) or msg.document
        if photo is None:
            await msg.reply_text("Жду фото — картинкой или файлом.")
            return
        try:
            path = await _download(context, photo, chat_id)
            asset_id = await asyncio.to_thread(step_photo, chat_id, path)
        except Exception as e:
            await msg.reply_text(f"Фото не принялось: {str(e)[:200]}")
            return
        s.setdefault("photos", []).append({"asset_id": asset_id, "file": str(path)})
        s["photo"] = len(s["photos"]) - 1
        save_session(chat_id, s)
        await msg.reply_text(PHOTO_SAVED)
        await _voice_stage(msg, chat_id, s)
        return

    if step == WAIT_VOICE:
        rec = msg.voice or msg.audio or msg.document
        if rec is None:
            await msg.reply_text("Жду запись голоса — голосовым или файлом.")
            return
        try:
            path = await _download(context, rec, chat_id)
            s["voice_id"] = await asyncio.to_thread(step_voice, chat_id, path)
        except Exception as e:
            await msg.reply_text(f"Голос не принялся: {str(e)[:200]}")
            return
        save_session(chat_id, s)
        await msg.reply_text(VOICE_SAVED)
        await _voice_stage(msg, chat_id, s)
        return

    text = (msg.text or msg.caption or "").strip()
    media = msg.voice or msg.audio or msg.video or msg.video_note or msg.document
    if media is not None and step in (WAIT_RAW, WAIT_TEXT):
        await msg.reply_text(TRANSCRIBING)
        try:
            path = await _download(context, media, chat_id)
            text = await asyncio.to_thread(transcribe, chat_id, path)
        except Exception as e:
            await msg.reply_text(f"Не смог разобрать запись: {str(e)[:200]}")
            return

    if not text:
        await msg.reply_text(NOT_NOW if step == CHOOSING else
                             "Жду текст сообщением или файлом.")
        return

    if step == WAIT_TEXT:
        await msg.reply_text(WORKING)
        try:
            sc = await asyncio.to_thread(step_verbatim, chat_id, clean_input(text))
        except (ScenarioError, RuntimeError) as e:
            await msg.reply_text(f"Не получилось разобрать текст: {e}")
            return
        s.update(step=REVIEW, scenario=sc)
        save_session(chat_id, s)
        await msg.reply_text(render_scenario(sc), reply_markup=_kb_review())

    elif step == WAIT_RAW:
        await msg.reply_text(WORKING)
        try:
            ideas = await asyncio.to_thread(step_ideas, chat_id, text)
        except (ScenarioError, RuntimeError) as e:
            await msg.reply_text(f"Не получилось вытащить идеи: {e}")
            return
        s.update(step=CHOOSING_IDEA, ideas=ideas)
        save_session(chat_id, s)
        await msg.reply_text(render_ideas(ideas), reply_markup=_kb_ideas(len(ideas)))

    elif step == WAIT_EDIT:
        try:
            sc = scenario_from_text(clean_input(text))
        except ScenarioError as e:
            await msg.reply_text(str(e))
            return
        s.update(step=REVIEW, scenario=sc)
        save_session(chat_id, s)
        await msg.reply_text(render_scenario(sc), reply_markup=_kb_review())

    else:
        await msg.reply_text(NOT_NOW)


async def _download(context, media, chat_id: int) -> Path:
    f = await context.bot.get_file(media.file_id)
    name = getattr(media, "file_name", None) or Path(f.file_path or "raw").name
    dest = session_dir(chat_id) / "input" / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    await f.download_to_drive(str(dest))
    return dest


def main():
    from telegram.ext import (ApplicationBuilder, CallbackQueryHandler,
                              CommandHandler, MessageHandler, filters)

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("Нет TELEGRAM_BOT_TOKEN в окружении")
    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(~filters.COMMAND, on_message))
    app.run_polling()


if __name__ == "__main__":
    main()
