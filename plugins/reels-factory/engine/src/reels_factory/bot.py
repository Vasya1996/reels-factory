"""Телеграм-бот фабрики: сырьё или готовый текст -> утверждённый сценарий.

Разговор: /start -> выбор пути -> материал (прежний или новый) -> сценарий в
чате -> правка текста руками или утверждение -> фото -> голос -> готовность.
После «Создать ролик» — экран с кнопкой «Новый ролик» (или команда /new):
разговор начинается заново на шаге выбора пути, но фото, голос и утверждённый
сценарий остаются — цикл можно повторять без повторного онбординга.

По кнопке «Создать ролик» бот зовёт сборку (движок Юли — чёрный ящик, только
через subprocess `python -m reels_factory make`) в отдельном потоке и присылает
готовый mp4 в чат.

Состояние чата — json-файл в <workdir>/bot/<chat_id>/session.json: перезапуск
бота не теряет разговор, а рядом лежат рабочие файлы движка этого же чата.

Токен бота — env TELEGRAM_BOT_TOKEN. Запуск: python -m reels_factory.bot
"""
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from reels_factory.config import WORK_ROOT, load_config
from reels_factory.llm import ClaudeSkillRunner
from reels_factory.scenario import (ScenarioError, run_generated_path, run_ideas,
                                    run_verbatim_path, split_verbatim)

# Шаги разговора.
CHOOSING = "choosing"                # ждём выбора пути
CHOOSING_MATERIAL = "choosing_material"  # прежний материал или новый
WAIT_TEXT = "wait_text"              # ждём готовый текст реплик
WAIT_RAW = "wait_raw"                # ждём сырьё (мысли, отрывок, запись)
CHOOSING_IDEA = "choosing_idea"
REVIEW = "review"                    # сценарий показан, ждём решения
WAIT_EDIT = "wait_edit"              # ждём отредактированный текст
CHOOSING_PHOTO = "choosing_photo"    # фото уже есть: прежнее или новое
WAIT_PHOTO = "wait_photo"
CHOOSING_VOICE = "choosing_voice"    # голос уже есть: прежний или новый
WAIT_VOICE = "wait_voice"
READY = "ready"                      # сценарий утверждён, фото и голос собраны
DONE = "done"                        # ролик заказан, ждём новый цикл

ROLE_RU = {"hook": "хук", "context": "контекст", "development": "развитие",
           "payoff": "вывод", "cta": "призыв"}

HELLO = (
    "Это фабрика рилсов. Сделаю вертикальный ролик, где вашим голосом и лицом "
    "говорят ваши мысли.\n\nС чего начнём?"
)
ASK_MATERIAL = "Что используем?"
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
    "Снимите по пояс, чтобы руки были в кадре: тогда ведущий будет "
    "жестикулировать, а не говорить одной головой. Смотрите в камеру, ровный "
    "свет, без тёмных очков и без чужих лиц в кадре.\n\n"
    "Важно: всё, что должно выглядеть настоящим, должно быть видно на фото. "
    "Кисти рук — чтобы ногти были ваши, кольца, часы, одежда. Чего на фото "
    "нет, то модель додумает по-своему."
)
ASK_VOICE = (
    "Запишите свой голос — читайте вслух сценарий рилса или любой другой "
    "материал 1–2 минуты.\n\n"
    "Как записать:\n"
    "— Тихая комната без эха, годится голосовое прямо в чат.\n"
    "— Говорите без запинок и лишних пауз.\n"
    "— Меняйте подачу по ходу: спокойное объяснение, азарт на подъёме, "
    "вопрос собеседнику, уверенный вывод."
)
PHOTO_SAVED = "Фото принял."
VOICE_SAVED = "Голос принял."
READY_MSG = "Всё на месте: сценарий, фото и голос. Жмите «Создать ролик», когда готовы."
DONE_MSG = (
    "Ролик заказан. Когда будет что снять ещё — жмите «Новый ролик» или "
    "пришлите /new."
)
NOT_NOW = "Сначала выберите, с чего начать: /start"

BUILDING_MSG = "Собираю ролик, это займёт несколько минут…"
BUSY_MSG = "Уже собираю ролик — дождитесь, пришлю, как будет готово."
CLIENT_NOT_FOUND_MSG = (
    "Не нашёл ваш профиль для сборки — похоже, что-то не сохранилось (например, "
    "не удалось склонировать голос). Пройдите шаги фото и голоса заново."
)
QA_FAIL_MSG = (
    "Ролик собран, но проверка качества не пройдена — посмотрите внимательно.\n\n"
    "Когда будет что снять ещё — жмите «Новый ролик» или пришлите /new."
)
MISSING_FILE_MSG = "Сборка отчиталась об успехе, но файла ролика не нашлось — гляньте руками."

MAX_TG_VIDEO_BYTES = 50 * 1024 * 1024  # лимит Bot API на видео/документ


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


# Фото, голос и утверждённый сценарий переживают новый цикл («Новый ролик»).
_PROFILE_KEYS = ("photo", "voice_id")
_LOOP_KEYS = _PROFILE_KEYS + ("scenario",)


def fresh_session(s: dict) -> dict:
    """/start: заново нужен сценарий, а фото и голос — нет."""
    return {"step": CHOOSING, **{k: s[k] for k in _PROFILE_KEYS if k in (s or {})}}


def loop_session(s: dict) -> dict:
    """Новый цикл после готового ролика: ничего не стирается, кроме шага."""
    return {"step": CHOOSING, **{k: s[k] for k in _LOOP_KEYS if k in (s or {})}}


def _keep_all(s: dict) -> dict:
    """«Назад» на стартовый экран: меняем только шаг, данные не трогаем —
    в отличие от /start (fresh_session) это не новый заход, а просто просмотр
    экрана выбора пути."""
    return {**(s or {}), "step": CHOOSING}


# Чаты, для которых сборка сейчас идёт — не даём запустить вторую поверх.
_building: set[int] = set()


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
    from reels_factory.avatar import upload_photo_asset

    return upload_photo_asset(photo)


def step_voice(chat_id: int, audio: Path) -> str:
    """Запись -> клон голоса в ElevenLabs -> voice_id."""
    from reels_factory.tts import create_voice_clone

    return create_voice_clone(str(audio), f"tg-{chat_id}")


def step_delete_voice(voice_id: str) -> None:
    """Старый клон долой — на тарифе лимит числа голосов в ElevenLabs."""
    from reels_factory.tts import delete_voice

    delete_voice(voice_id)


def clear_client_voice_profile(chat_id: int) -> None:
    """Клон в ElevenLabs удалён — тем же движением чистим voice_id в
    зарегистрированном профиле клиента, чтобы `make --client` честно сказал
    «профиль неполон», а не упал 404 на несуществующий голос."""
    from reels_factory.clients import clear_client_voice

    clear_client_voice(str(chat_id))


def save_client_profile(chat_id: int, session: dict) -> None:
    """Профиль клиента в реестре — с ним сборка идёт как `make --client <id>`."""
    from reels_factory.clients import register_client

    photo = session.get("photo")
    if not (photo and session.get("voice_id")):
        return
    register_client(str(chat_id), load_config(), name=f"tg-{chat_id}",
                    voice_id=session["voice_id"], asset_id=photo["asset_id"],
                    overwrite=True)


def client_profile_ready(chat_id: int) -> bool:
    """Профиль клиента есть и полон (voice_id + heygen_asset_id) — иначе честно
    «клиент не найден». Общий config.yaml НЕ подставляем: в нём заведомо
    неверная заглушка heygen_asset_id именно на случай такой ошибки."""
    import yaml
    from reels_factory.clients import client_path

    path = client_path(str(chat_id))
    if not path.exists():
        return False
    try:
        cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return False
    if not isinstance(cfg, dict):
        return False
    avatar = cfg.get("avatar") or {}
    return bool(cfg.get("voice_id")) and bool(avatar.get("heygen_asset_id"))


def _new_build_dir(chat_id: int) -> Path:
    return WORK_ROOT / f"bot-{chat_id}-{int(time.time())}"


def _write_scenario(workdir: Path, scenario: dict) -> None:
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "scenario.json").write_text(
        json.dumps(scenario, ensure_ascii=False, indent=1), encoding="utf-8")


def run_build(chat_id: int, workdir: Path) -> dict:
    """Сборка ролика — чёрный ящик Юли: `python -m reels_factory make` тем же
    питоном, что и бот, cwd не задаём — наследуем cwd бота (корень рабочей
    площадки), как и требует движок. Разбираем JSON из stdout; если разобрать
    не вышло (сбой на середине без валидного ответа) — честная ошибка из
    stderr/stdout."""
    p = subprocess.run(
        [sys.executable, "-m", "reels_factory", "make",
         "--workdir", str(workdir), "--client", str(chat_id)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        return json.loads(p.stdout)
    except (json.JSONDecodeError, TypeError):
        return {"ok": False, "error": (p.stderr or p.stdout or "пустой ответ движка")[:500]}


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


def _kb_back():
    """Шаг ожидания ввода — из него тоже должен быть выход назад."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([[InlineKeyboardButton("← Назад", callback_data="back")]])


def _kb_material(mode: str, has_material: bool):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    send_label = "Прислать новый текст" if mode == "text" else "Прислать новое сырьё"
    rows = []
    if has_material:
        rows.append([InlineKeyboardButton("Редактировать существующий",
                                          callback_data="material:edit")])
    rows.append([InlineKeyboardButton(send_label, callback_data="material:new")])
    rows.append([InlineKeyboardButton("← Назад", callback_data="back")])
    return InlineKeyboardMarkup(rows)


def _kb_ideas(n: int):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(str(i + 1), callback_data=f"idea:{i}")]
         for i in range(n)] +
        [[InlineKeyboardButton("← Назад", callback_data="back")]])


def _kb_photo():
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Использовать загруженное фото", callback_data="photo:old")],
        [InlineKeyboardButton("Загрузить новое фото", callback_data="photo:new")],
        [InlineKeyboardButton("← Назад", callback_data="back")],
    ])


def _kb_voice():
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Использовать прежнюю запись", callback_data="voice:old")],
        [InlineKeyboardButton("Записать заново", callback_data="voice:new")],
        [InlineKeyboardButton("← Назад", callback_data="back")],
    ])


def _kb_review():
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Утвердить", callback_data="ok")],
        [InlineKeyboardButton("Изменить текст", callback_data="edit")],
        [InlineKeyboardButton("← Назад", callback_data="back")],
    ])


def _kb_ready():
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Создать ролик", callback_data="build")],
        [InlineKeyboardButton("← Назад", callback_data="back")],
    ])


def _kb_done():
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([[InlineKeyboardButton("Новый ролик", callback_data="new_reel")]])


async def _show_start(msg, chat_id: int, s: dict, session_builder=fresh_session):
    save_session(chat_id, session_builder(s))
    await msg.reply_text(HELLO, reply_markup=_kb_start())


async def _ask(msg, chat_id: int, s: dict, step: str, text: str):
    """Экран ожидания ввода — с кнопкой «Назад»."""
    s["step"] = step
    save_session(chat_id, s)
    await msg.reply_text(text, reply_markup=_kb_back())


async def _show_material(msg, chat_id: int, s: dict, mode: str):
    """Шаг 2: прежний материал уже есть — предлагаем взять его или прислать новый."""
    s["step"] = CHOOSING_MATERIAL
    s["material_mode"] = mode
    save_session(chat_id, s)
    has_material = bool(s.get("scenario"))
    await msg.reply_text(ASK_MATERIAL, reply_markup=_kb_material(mode, has_material))


async def _show_ideas(msg, chat_id: int, s: dict):
    s["step"] = CHOOSING_IDEA
    save_session(chat_id, s)
    ideas = s.get("ideas") or []
    await msg.reply_text(render_ideas(ideas), reply_markup=_kb_ideas(len(ideas)))


async def _show_review(msg, chat_id: int, s: dict):
    if not s.get("scenario"):
        await _show_start(msg, chat_id, s)
        return
    s["step"] = REVIEW
    save_session(chat_id, s)
    await msg.reply_text(render_scenario(s["scenario"]), reply_markup=_kb_review())


async def _go_back(msg, chat_id: int, s: dict):
    """Шаг назад — на предыдущий экран, ничего не теряя."""
    step = s.get("step", CHOOSING)
    if step == WAIT_EDIT:
        await _show_review(msg, chat_id, s)
    elif step == REVIEW:
        # из сценария — туда, откуда он взялся: к идеям или к вводу материала
        if s.get("ideas"):
            await _show_ideas(msg, chat_id, s)
        elif s.get("material_mode") == "raw":
            await _ask(msg, chat_id, s, WAIT_RAW, ASK_RAW)
        else:
            await _ask(msg, chat_id, s, WAIT_TEXT, ASK_TEXT)
    elif step == CHOOSING_IDEA:
        await _ask(msg, chat_id, s, WAIT_RAW, ASK_RAW)
    elif step in (WAIT_TEXT, WAIT_RAW):
        await _show_material(msg, chat_id, s, s.get("material_mode", "text"))
    elif step == CHOOSING_MATERIAL:
        await _show_start(msg, chat_id, s, _keep_all)
    elif step in (WAIT_PHOTO, CHOOSING_PHOTO):
        await _show_review(msg, chat_id, s)
    elif step in (CHOOSING_VOICE, WAIT_VOICE, READY):
        await _photo_stage(msg, chat_id, s)
    else:  # CHOOSING — дальше некуда, начало разговора
        await _show_start(msg, chat_id, s, _keep_all)


async def cmd_start(update, context):
    chat_id = update.effective_chat.id
    await _show_start(update.message, chat_id, load_session(chat_id))


async def cmd_new(update, context):
    """/new — то же, что кнопка «Новый ролик»: фото, голос и сценарий остаются."""
    chat_id = update.effective_chat.id
    await _show_start(update.message, chat_id, load_session(chat_id), loop_session)


async def on_button(update, context):
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    s = load_session(chat_id)
    data = q.data

    if data == "mode:text":
        await _show_material(q.message, chat_id, s, "text")
    elif data == "mode:raw":
        await _show_material(q.message, chat_id, s, "raw")
    elif data == "back":
        await _go_back(q.message, chat_id, s)
    elif data == "material:edit":
        await _show_review(q.message, chat_id, s)
    elif data == "material:new":
        if s.get("material_mode") == "raw":
            await _ask(q.message, chat_id, s, WAIT_RAW, ASK_RAW)
        else:
            await _ask(q.message, chat_id, s, WAIT_TEXT, ASK_TEXT)
    elif data.startswith("idea:"):
        idea = (s.get("ideas") or [])[int(data.split(":")[1])]
        await q.message.reply_text(WORKING)
        try:
            sc = await asyncio.to_thread(step_scenario, chat_id, idea)
        except (ScenarioError, RuntimeError) as e:
            await q.message.reply_text(f"Не получилось собрать сценарий: {e}")
            return
        s["scenario"] = sc
        await _show_review(q.message, chat_id, s)
    elif data == "edit":
        await _ask(q.message, chat_id, s, WAIT_EDIT, ASK_EDIT)
    elif data == "ok":
        await q.message.reply_text(APPROVED_MSG)
        await _photo_stage(q.message, chat_id, s)
    elif data == "photo:old":
        await _voice_stage(q.message, chat_id, s)
    elif data == "photo:new":
        await _ask(q.message, chat_id, s, WAIT_PHOTO, ASK_PHOTO)
    elif data == "voice:old":
        await _finish_voice(q.message, chat_id, s)
    elif data == "voice:new":
        old_voice = s.pop("voice_id", None)
        save_session(chat_id, s)
        if old_voice:
            clear_client_voice_profile(chat_id)  # профиль не должен ссылаться на удалённый голос
            try:
                await asyncio.to_thread(step_delete_voice, old_voice)
            except Exception:
                pass  # лучше дать перезаписать голос, чем застрять на ошибке чистки
        await _ask(q.message, chat_id, s, WAIT_VOICE, ASK_VOICE)
    elif data == "build":
        if chat_id in _building:
            await q.message.reply_text(BUSY_MSG)
            return
        save_client_profile(chat_id, s)
        if not client_profile_ready(chat_id):
            await q.message.reply_text(CLIENT_NOT_FOUND_MSG)
            return
        await _build_and_send(q.message, chat_id, s)
    elif data == "new_reel":
        await _show_start(q.message, chat_id, s, loop_session)


async def _photo_stage(msg, chat_id: int, s: dict):
    """Фото обязательно: в первый раз просим, дальше — прежнее или новое."""
    if s.get("photo"):
        s["step"] = CHOOSING_PHOTO
        save_session(chat_id, s)
        await msg.reply_text("Снимаем по вашему фото. Какому?", reply_markup=_kb_photo())
    else:
        await _ask(msg, chat_id, s, WAIT_PHOTO, ASK_PHOTO)


async def _voice_stage(msg, chat_id: int, s: dict):
    """Голос уже есть — прежний или перезаписать; иначе просим впервые."""
    if s.get("voice_id"):
        s["step"] = CHOOSING_VOICE
        save_session(chat_id, s)
        await msg.reply_text("Голос уже записан. Что делаем?", reply_markup=_kb_voice())
    else:
        await _ask(msg, chat_id, s, WAIT_VOICE, ASK_VOICE)


async def _finish_voice(msg, chat_id: int, s: dict):
    """Голос получен (прежний или новый) — сохраняем профиль и идём к готовности."""
    s["step"] = READY
    save_session(chat_id, s)
    save_client_profile(chat_id, s)
    await msg.reply_text(READY_MSG, reply_markup=_kb_ready())


async def _build_and_send(msg, chat_id: int, s: dict):
    """Сборка минутами — движок синхронный, зовём через поток, бот тем временем
    отвечает другим чатам. По готовности шлём mp4 в чат и показываем DONE."""
    _building.add(chat_id)
    await msg.reply_text(BUILDING_MSG)
    try:
        workdir = _new_build_dir(chat_id)
        _write_scenario(workdir, s["scenario"])
        result = await asyncio.to_thread(run_build, chat_id, workdir)
    except Exception as e:
        await msg.reply_text(f"Сборка сорвалась: {str(e)[:200]}")
        return
    finally:
        _building.discard(chat_id)

    if not result.get("ok"):
        await msg.reply_text(f"Не получилось собрать ролик: {result.get('error') or 'неизвестная ошибка'}")
        return

    mp4 = Path(result.get("mp4") or (workdir / "reel.mp4"))
    if not mp4.exists():
        await msg.reply_text(MISSING_FILE_MSG)
        return
    if mp4.stat().st_size > MAX_TG_VIDEO_BYTES:
        await msg.reply_text(f"Ролик собрался, но весит больше 50 МБ — Telegram такое "
                             f"не примет. Файл здесь: {mp4}")
        return

    caption = DONE_MSG if result.get("qa_pass") else QA_FAIL_MSG
    with mp4.open("rb") as f:
        await msg.reply_video(video=f, caption=caption, reply_markup=_kb_done())
    s["step"] = DONE
    save_session(chat_id, s)


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
        old = s.get("photo")
        if old and old.get("file") and old["file"] != str(path):
            Path(old["file"]).unlink(missing_ok=True)
        s["photo"] = {"asset_id": asset_id, "file": str(path)}
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
        await _finish_voice(msg, chat_id, s)
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
        s["scenario"] = sc
        await _show_review(msg, chat_id, s)

    elif step == WAIT_RAW:
        await msg.reply_text(WORKING)
        try:
            ideas = await asyncio.to_thread(step_ideas, chat_id, text)
        except (ScenarioError, RuntimeError) as e:
            await msg.reply_text(f"Не получилось вытащить идеи: {e}")
            return
        s["ideas"] = ideas
        await _show_ideas(msg, chat_id, s)

    elif step == WAIT_EDIT:
        try:
            sc = scenario_from_text(clean_input(text))
        except ScenarioError as e:
            await msg.reply_text(str(e))
            return
        s["scenario"] = sc
        await _show_review(msg, chat_id, s)

    else:
        await msg.reply_text(NOT_NOW)


async def _download(context, media, chat_id: int) -> Path:
    f = await context.bot.get_file(media.file_id)
    name = getattr(media, "file_name", None) or Path(f.file_path or "raw").name
    dest = session_dir(chat_id) / "input" / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    await f.download_to_drive(str(dest))
    return dest


async def _post_init(app):
    """Команда /new в меню бота — чтобы кнопка «Новый ролик» не терялась в переписке."""
    from telegram import BotCommand

    await app.bot.set_my_commands([BotCommand("new", "Новый ролик")])


def main():
    from telegram.ext import (ApplicationBuilder, CallbackQueryHandler,
                              CommandHandler, MessageHandler, filters)

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("Нет TELEGRAM_BOT_TOKEN в окружении")
    app = ApplicationBuilder().token(token).post_init(_post_init).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("new", cmd_new))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(~filters.COMMAND, on_message))
    app.run_polling()


if __name__ == "__main__":
    main()
