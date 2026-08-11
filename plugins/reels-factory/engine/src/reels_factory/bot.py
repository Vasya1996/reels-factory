"""Телеграм-бот фабрики: сырьё или готовый текст -> утверждённый сценарий.

Разговор: /start или /new -> язык ролика -> выбор пути -> материал -> сценарий
в чате -> правка текста руками или утверждение -> фото -> голос языка ролика
-> готовность.
После «Создать ролик» — экран с кнопкой «Новый ролик» (или команда /new):
разговор начинается заново с языка. Фото и отдельные голоса ru/kk остаются,
сценарий сбрасывается.

По кнопке «Создать ролик» бот зовёт сборку (движок Юли — чёрный ящик, только
через subprocess `python -m reels_factory make`) в отдельном потоке и присылает
готовый mp4 в чат.

Состояние чата — json-файл в <workdir>/bot/<chat_id>/session.json: перезапуск
бота не теряет разговор, а рядом лежат рабочие файлы движка этого же чата.

Токен бота — env TELEGRAM_BOT_TOKEN. Запуск: python -m reels_factory.bot
"""
import asyncio
import copy
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import uuid
from contextlib import suppress
from pathlib import Path

from reels_factory.billing import (
    LedgerStore, apply_markup, claude_cost_micro, estimate_micro,
)
from reels_factory.config import (
    OUT_H, OUT_W, WORK_ROOT, load_billing_config, load_config,
)
from reels_factory.jobs import BuildJob, JobStore
from reels_factory.language import (
    SUPPORTED_LANGUAGES,
    confident_mismatch,
    language_label,
    normalize_profile_language,
)
from reels_factory.llm import ClaudeSkillRunner
from reels_factory.scenario import (ScenarioError, run_generated_path, run_ideas,
                                    run_verbatim_path, split_verbatim)
from reels_factory.tribute import start_webhook_server

log = logging.getLogger(__name__)

# Шаги разговора.
CHOOSING_LANGUAGE = "choosing_language"  # язык нового ролика
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
BUILDING = "building"                # job стоит в очереди или исполняется
BUILD_FAILED = "build_failed"        # сборка/QA остановлены, видео не отправлено
DONE = "done"                        # ролик заказан, ждём новый цикл

ROLE_RU = {"hook": "хук", "context": "контекст", "development": "развитие",
           "payoff": "вывод", "cta": "призыв"}

HELLO = (
    "Пришлите идею или готовый сценарий с репликами — верну вертикальный "
    "ролик для Reels, Shorts и TikTok.\n\n"
    "В кадре будет ваш ИИ-аватар с вашим реалистичным голосом. Снимать и "
    "монтировать не придётся: нужны только фото и минутная запись голоса.\n\n"
    "С чего начнём?"
)
ASK_LANGUAGE = (
    "На каком языке хотите сделать ролик?"
)
LANGUAGE_SAVED = (
    "Делаем этот ролик на языке: {language}."
)
LANGUAGE_MISMATCH = (
    "Похоже, этот сценарий написан на языке: {detected}.\n\n"
    "Для этого ролика выбран язык: {selected}."
)
ASK_MATERIAL = "Что используем?"
ASK_TEXT = (
    "Пришлите текст ролика — ровно те слова, которые должны прозвучать.\n\n"
    "Для расстановки пауз используйте тире или многоточие — голос "
    "воспроизведёт паузы точно там, где вы расставили знаки."
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
    "Запишите свой голос — 1–2 минуты. Можно голосовым прямо сюда. Текст для "
    "чтения пришлю по кнопке ниже.\n\n"
    "— Тихая комната: без музыки, телевизора и эха. Только ваш голос.\n"
    "— Читайте живо, с интонацией — голос скопирует вашу манеру.\n"
    "— Не переигрывайте: держите один настрой и одну громкость всю запись, "
    "не переходите с шёпота на крик.\n"
    "— Микрофон на одном расстоянии, не отворачивайтесь."
)

# Образец для чтения на языке ролика: клон копирует манеру, поэтому текст
# заранее ведёт диктора через смену подачи — объяснение, подъём, вопрос,
# вывод. Длина под рекомендацию ElevenLabs: 1–2 минуты чтения.
VOICE_SAMPLE_TEXTS = {
    "ru": (
        "Смотрите, как устроен мозг человека. Каждую секунду он получает "
        "миллионы сигналов: свет, звук, запах, прикосновение к коже. Но "
        "осознанно мы замечаем лишь малую часть — всё остальное мозг тихо "
        "отбрасывает, даже не спрашивая нас. Это не слабость и не лень. Это "
        "защита. Если бы мы чувствовали абсолютно всё и сразу, мы бы не "
        "продержались и минуты.\n\n"
        "А теперь представьте: вы стоите в шумной толпе, вокруг десятки "
        "разговоров, музыка, смех. И вдруг где-то сбоку вы слышите своё имя! "
        "Вы не искали этот звук, вы вообще не думали ни о ком из этих людей. "
        "И всё же мозг мгновенно выхватил именно эти буквы из целого моря "
        "шума. Вот это по-настоящему поразительно — насколько точно работает "
        "внимание, когда дело касается лично нас.\n\n"
        "А теперь спросите себя: сколько раз за сегодняшний день ваш мозг "
        "отфильтровал что-то важное просто потому, что вы не обратили "
        "внимания? Может, рядом кто-то пытался с вами заговорить, а вы "
        "листали ленту? Может, хорошая мысль мелькнула и тут же пропала, "
        "потому что вы её не поймали?\n\n"
        "Одно я знаю точно: внимание — это не подарок судьбы, а обычный "
        "навык. Его можно тренировать, как мышцу. И тот, кто научится им "
        "управлять, получит не просто больше информации. Он получит контроль "
        "над собственной жизнью."
    ),
    "kk": (
        "Ми қалай жұмыс істейді? Ол секунд сайын миллиондаған сигнал "
        "қабылдайды: жарық, дыбыс, иіс, теріге тиген жел. Бірақ біз соның аз "
        "ғана бөлігін сеземіз — қалғанын ми бізден сұрамай-ақ ысырып "
        "тастайды. Бұл әлсіздік те, жалқаулық та емес. Бұл — қорғаныс. Бәрін "
        "бірден сезсек, бір минутқа да шыдамас едік.\n\n"
        "Ал енді елестетіп көрші. Сен қалың топтың ішінде тұрсың, айнала "
        "у-шу: әңгіме, музыка, күлкі. Кенет бір жерден өз атыңды естіп "
        "қаласың! Сен оны іздеп тұрған жоқсың, ойыңда мүлде басқа нәрсе. Ал "
        "ми сол дыбысты мыңдаған дыбыстың ішінен бірден тауып алады. Айнала "
        "баяғыдай шулы, бірақ сен енді тек сол бір дауысты естіп тұрсың. Ең "
        "таңғаларлығы осы: сөз өзіңе қатысты болса, зейін бірден оянады.\n\n"
        "Енді өзіңнен сұрап көрші: бүгін ми қаншама маңызды нәрсені елемей "
        "өткізіп жіберді? Мүмкін, қасыңдағы адам саған бірдеңе айтқысы келген "
        "шығар, ал сен телефоннан көз алмағансың? Мүмкін, өміріңнің бір жақсы "
        "сәті сол кезде жаныңнан өтіп кеткен шығар?\n\n"
        "Мен бір нәрсені нақты білемін: зейін — тағдырдың сыйы емес, жай ғана "
        "дағды. Оны бұлшық ет сияқты жаттықтыруға болады. Күніне бес минут "
        "зейін қойып көрші — бір айдан кейін айырмасын өзің сезесің. Оны "
        "басқаруды үйренген адам көбірек ақпарат алып қана қоймайды. Ол өз "
        "өмірін өз қолына алады."
    ),
}


def _ask_voice_text(language: str) -> str:
    """Инструкция явно называет язык: клон не считается мультиязычным."""
    return (
        f"Для ролика на языке {language_label(language)} нужен отдельный "
        f"голос.\n\n{ASK_VOICE}"
    )


PHOTO_SAVED = "Фото принял."
VOICE_SAVED = "Голос принял."
READY_MSG = "Всё на месте: сценарий, фото и голос. Жмите «Создать ролик», когда готовы."
DONE_MSG = (
    "Ролик заказан. Когда будет что снять ещё — жмите «Новый ролик» или "
    "пришлите /new."
)
NOT_NOW = "Сначала выберите, с чего начать: /start"

BUILDING_MSG = "Задание поставлено в очередь. Напишу, когда начну сборку."
RUNNING_MSG = "Начинаю сборку ролика. Это займёт несколько минут…"
BUSY_MSG = "Уже собираю ролик — дождитесь, пришлю, как будет готово."
CLIENT_NOT_FOUND_MSG = (
    "Не нашёл ваш профиль для сборки — похоже, что-то не сохранилось (например, "
    "не удалось склонировать голос). Пройдите шаги фото и голоса заново."
)
QA_FAIL_MSG = (
    "Ролик собран, но проверка качества не пройдена. Я не отправляю брак "
    "автоматически; результат сохранён для диагностики."
)
MISSING_FILE_MSG = "Сборка отчиталась об успехе, но файла ролика не нашлось — гляньте руками."
INTERRUPTED_MSG = (
    "Сборка была остановлена перезапуском сервиса. Автоматически повторять её "
    "не буду, чтобы исключить повторную оплату генерации."
)

MAX_TG_VIDEO_BYTES = 50 * 1024 * 1024  # лимит Bot API на видео/документ


def render_scenario(sc: dict) -> str:
    """Сценарий человеку: заголовок, блоки по ролям, оценка длительности."""
    lines = []
    language = sc.get("language")
    if language in SUPPORTED_LANGUAGES:
        lines.append(f"Язык ролика: {language_label(language)}\n")
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


def scenario_from_text(text: str, language: str | None = None) -> dict:
    """Правка пользователя — закон: слова его, движок только режет на блоки."""
    scenario = {"mode": "verbatim", "blocks": split_verbatim(text)}
    if language:
        scenario["language"] = normalize_profile_language(language)
    return scenario


# Фото и голоса по языкам переживают новый цикл («Новый ролик»).
_PROFILE_KEYS = (
    "photo",
    "voices",
    "voice_id",          # active voice текущего языка; legacy-compatible
    "voice_language",
    "pending_previous_voice",
    "source",            # откуда пришёл: переживает и /start, и новый ролик
)
_LOOP_KEYS = _PROFILE_KEYS


def _preserved_profile(s: dict, keys=_PROFILE_KEYS) -> dict:
    """Сохранить медиа и безопасно отменить незавершённую замену голоса."""
    profile = {k: s[k] for k in keys if k in (s or {})}
    pending = profile.get("pending_previous_voice") or {}
    pending_language = pending.get("language")
    pending_voice = pending.get("voice_id")
    voices = dict(profile.get("voices") or {})
    if (
        pending_language in SUPPORTED_LANGUAGES
        and pending_voice
        and pending_language not in voices
    ):
        # Новый clone ещё не создан: /start или /new означает отмену замены.
        voices[pending_language] = pending_voice
        profile["voices"] = voices
        profile.pop("pending_previous_voice", None)
    return profile


def fresh_session(s: dict) -> dict:
    """/start: язык и сценарий заново, фото и голос сохраняются."""
    return {"step": CHOOSING, **_preserved_profile(s)}


def loop_session(s: dict) -> dict:
    """Новый ролик: сбросить язык/сценарий, сохранить профильные медиа."""
    return {"step": CHOOSING, **_preserved_profile(s, _LOOP_KEYS)}


def _keep_all(s: dict) -> dict:
    """«Назад» на стартовый экран: меняем только шаг, данные не трогаем —
    в отличие от /start (fresh_session) это не новый заход, а просто просмотр
    экрана выбора пути."""
    return {**(s or {}), "step": CHOOSING}


_job_wakeup: asyncio.Event | None = None
_worker_task: asyncio.Task | None = None
_job_store_cache: tuple[Path, JobStore] | None = None


def session_dir(chat_id: int) -> Path:
    return WORK_ROOT / "bot" / str(chat_id)


def _job_store() -> JobStore:
    global _job_store_cache
    db_path = (WORK_ROOT / "jobs.sqlite3").resolve()
    if _job_store_cache is None or _job_store_cache[0] != db_path:
        _job_store_cache = (
            db_path,
            JobStore(db_path, WORK_ROOT / "jobs"),
        )
    return _job_store_cache[1]


_ledger_cache: tuple[Path, LedgerStore] | None = None


def _ledger() -> LedgerStore:
    """Журнал трат и балансов. Кэшируем как _job_store: путь зависит от cwd."""
    global _ledger_cache
    db_path = (WORK_ROOT / "billing.sqlite3").resolve()
    if _ledger_cache is None or _ledger_cache[0] != db_path:
        _ledger_cache = (db_path, LedgerStore(db_path))
    return _ledger_cache[1]


def _billing() -> dict:
    return load_billing_config()


def format_usd(micro: int) -> str:
    """Микродоллары -> строка для пользователя."""
    sign = "-" if micro < 0 else ""
    return f"{sign}${abs(micro) / 1_000_000:.2f}"


class InsufficientBalance(Exception):
    """Баланса не хватает на оценку сборки — платный рендер не начинаем."""

    def __init__(self, *, need: int, have: int):
        super().__init__(f"нужно {need}, есть {have}")
        self.need = need
        self.have = have


def _charge_claude(chat_id: int, runner: ClaudeSkillRunner) -> None:
    """Списать стоимость вызовов Клода за подготовку сценария.

    Списываем сумму по runner, а не последний вызов: за один проход скиллов
    отрабатывают генерация, хуманизатор и судья.

    job_id=None — сборки ещё нет и может не быть вовсе (человек передумает).
    Деньги при этом уже потрачены, поэтому запись всё равно нужна.
    entry_id случайный: каждое нажатие — новая генерация, склеивать нечего.
    """
    billing = _billing()
    if not billing["enabled"] or not runner.total_cost_usd:
        return
    cost = claude_cost_micro(runner.total_cost_usd)
    _ledger().charge(
        chat_id,
        entry_id=f"claude:{uuid.uuid4().hex}",
        job_id=None,
        provider="claude",
        unit="usd",
        quantity=runner.total_cost_usd,
        unit_price_micro=0,
        cost_micro=cost,
        charged_micro=apply_markup(cost, billing["markup"]),
    )


def load_session(chat_id: int) -> dict:
    p = session_dir(chat_id) / "session.json"
    if not p.exists():
        return {"step": CHOOSING}
    data = json.loads(p.read_text(encoding="utf-8"))
    if "photos" in data:
        # старый формат: photos — список, photo — int-индекс в него.
        # Новый код ждёт словарь в photo.
        photos = data.pop("photos") or []
        idx = data.get("photo")
        idx = idx if isinstance(idx, int) else -1
        try:
            data["photo"] = photos[idx]
        except IndexError:
            data.pop("photo", None)
    # Миграция старой сессии с одним voice_id. До языкового routing фабрика
    # работала на языке общего config (обычно ru), поэтому именно к нему
    # безопасно привязываем legacy voice. Ключи оставляем для совместимости,
    # но новая логика всегда читает карту voices.
    if data.get("voice_id"):
        language = data.get("voice_language")
        if language not in SUPPORTED_LANGUAGES:
            try:
                language = normalize_profile_language(
                    load_config().get("language", "ru")
                )
            except Exception:
                language = "ru"
        voices = dict(data.get("voices") or {})
        voices.setdefault(language, data["voice_id"])
        data["voices"] = voices
        data["voice_language"] = language
    return data


def save_session(chat_id: int, data: dict) -> None:
    d = session_dir(chat_id)
    d.mkdir(parents=True, exist_ok=True)
    target = d / "session.json"
    tmp = d / "session.json.tmp"
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    tmp.replace(target)


# --- шаги движка (синхронные и небыстрые — в боте зовутся через to_thread) ---

def _reel_language(session: dict, *, required: bool = True) -> str | None:
    """Выбранный язык текущего сценария/ролика."""
    raw = (session or {}).get("language")
    if raw:
        try:
            return normalize_profile_language(raw)
        except ValueError:
            pass
    if required:
        # Совместимость только для уже начатых pre-MVP разговоров. Новый
        # пользователь проходит _show_start(required=False) и обязательно
        # выбирает язык; после этого глобальный fallback больше не участвует.
        try:
            return normalize_profile_language(load_config().get("language", "ru"))
        except Exception:
            return "ru"
    return None


def _voice_for_language(session: dict, language: str) -> str | None:
    language = normalize_profile_language(language)
    voice_id = str(((session or {}).get("voices") or {}).get(language) or "").strip()
    return voice_id or None


def _activate_language_voice(session: dict, language: str) -> str | None:
    """Синхронизировать legacy active fields с выбранным языковым голосом."""
    language = normalize_profile_language(language)
    voice_id = _voice_for_language(session, language)
    if voice_id:
        session["voice_id"] = voice_id
        session["voice_language"] = language
    else:
        session.pop("voice_id", None)
        session.pop("voice_language", None)
    return voice_id


def step_verbatim(chat_id: int, text: str, language: str) -> dict:
    runner = ClaudeSkillRunner()
    # Ретраи, исчерпанные без успеха (ScenarioError), жгут Клода не меньше
    # успеха — списываем и на исключении, иначе трата не попадёт в журнал.
    try:
        res = run_verbatim_path(session_dir(chat_id), text, runner,
                                language=normalize_profile_language(language))
    finally:
        _charge_claude(chat_id, runner)
    return res["scenario"]


def step_ideas(chat_id: int, text: str, language: str) -> list:
    runner = ClaudeSkillRunner()
    # См. step_verbatim: провал тоже платный, списываем в finally.
    try:
        res = run_ideas(
            session_dir(chat_id),
            text,
            runner,
            normalize_profile_language(language),
        )
    finally:
        _charge_claude(chat_id, runner)
    return res["ideas"]


def step_scenario(chat_id: int, idea: dict, language: str) -> dict:
    runner = ClaudeSkillRunner()
    # См. step_verbatim: провал тоже платный, списываем в finally.
    try:
        res = run_generated_path(session_dir(chat_id), idea, runner,
                                 language=normalize_profile_language(language))
    finally:
        _charge_claude(chat_id, runner)
    return res["scenario"]


def step_photo(chat_id: int, photo: Path) -> str:
    """Фото -> asset_id в HeyGen (бесплатно, платит только рендер)."""
    from reels_factory.avatar import upload_photo_asset

    return upload_photo_asset(photo)


def step_voice(chat_id: int, audio: Path, language: str) -> str:
    """Запись -> клон голоса в ElevenLabs -> voice_id."""
    from reels_factory.tts import create_voice_clone

    language = normalize_profile_language(language)
    return create_voice_clone(str(audio), f"tg-{chat_id}-{language}")


def step_delete_voice(voice_id: str) -> None:
    """Старый клон долой — на тарифе лимит числа голосов в ElevenLabs."""
    from reels_factory.tts import delete_voice

    delete_voice(voice_id)


def clear_client_voice_profile(chat_id: int, language: str) -> None:
    """Убрать заменяемый языковой voice из профиля до paid build.

    Сам provider-клон удаляется только после успешной записи и сохранения
    нового; голоса остальных языков не затрагиваются.
    """
    from reels_factory.clients import clear_client_voice

    clear_client_voice(str(chat_id), language=language)


def save_client_profile(chat_id: int, session: dict) -> None:
    """Сохранить профиль и активировать голос языка текущего ролика."""
    from reels_factory.clients import register_client

    photo = session.get("photo")
    language = _reel_language(session)
    voices = {
        code: str(voice_id).strip()
        for code, voice_id in dict(session.get("voices") or {}).items()
        if code in SUPPORTED_LANGUAGES and str(voice_id).strip()
    }
    voice_id = voices.get(language)
    if not (photo and voice_id):
        return
    session["voices"] = voices
    session["voice_id"] = voice_id
    session["voice_language"] = language
    base = copy.deepcopy(load_config())
    base["language"] = language
    base["voice_language"] = language
    base["voices"] = voices
    tts = dict(base.get("tts") or {})
    tts["language_code"] = language
    base["tts"] = tts
    register_client(
        str(chat_id),
        base,
        name=f"tg-{chat_id}",
        voice_id=voice_id,
        asset_id=photo["asset_id"],
        overwrite=True,
    )


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
    language = str(cfg.get("language") or "").strip().lower()
    voices = cfg.get("voices") or {}
    voice_id = str(cfg.get("voice_id") or "").strip()
    return (
        language in SUPPORTED_LANGUAGES
        and cfg.get("voice_language") == language
        and isinstance(voices, dict)
        and str(voices.get(language) or "").strip() == voice_id
        and bool(voice_id)
        and bool(avatar.get("heygen_asset_id"))
    )


def _write_scenario(workdir: Path, scenario: dict) -> None:
    workdir.mkdir(parents=True, exist_ok=True)
    target = workdir / "scenario.json"
    tmp = workdir / "scenario.json.tmp"
    tmp.write_text(json.dumps(scenario, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(target)


def _write_yaml_atomic(path: Path, payload: dict) -> None:
    import yaml

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    tmp.replace(path)


def enqueue_build(
    chat_id: int,
    scenario: dict,
    *,
    language: str | None = None,
    voice_id: str | None = None,
) -> BuildJob:
    """Подготовить immutable scenario/config и лишь затем показать job worker."""
    from reels_factory.avatar_islands import avatar_islands_enabled
    from reels_factory.clients import load_client
    from reels_factory.master_audio import master_audio_enabled

    billing = _billing()
    if billing["enabled"]:
        # Оценка ДО первого платного шага: после него деньги уже не вернуть.
        # Символы берём из тех же блоков, что уйдут в синтез речи
        # (pipeline.run_make озвучивает scenario["blocks"][i]["speech"]).
        chars = sum(
            len(b.get("speech") or "") for b in (scenario.get("blocks") or [])
        )
        # Профиль клиента может отсутствовать/быть битым (например, в этом же
        # вызове дальше это честно всплывёт своей ошибкой), а его настройки
        # avatar_islands — вне допустимого диапазона (avatar_islands_enabled
        # зовёт avatar_islands_settings, который для этого поднимает голый
        # ValueError — конфиг-лоадер такое не проверяет). Это лишь оценка ДО
        # платного шага — она не должна быть причиной, по которой сборку не
        # удаётся поставить в очередь, поэтому ловим широко и откатываемся на
        # консервативную оценку по полной цене.
        estimate_kwargs = {}
        try:
            profile_for_estimate = load_client(str(chat_id))
            # run_make берёт island-путь только когда включены оба флага —
            # avatar_islands и master_audio; тем же условием сверяем и здесь,
            # чтобы не показывать урезанную оценку для пути, который не
            # запустится.
            use_islands_estimate = (
                avatar_islands_enabled(profile_for_estimate)
                and master_audio_enabled(profile_for_estimate)
            )
        except Exception:
            use_islands_estimate = False
        if use_islands_estimate:
            # С островами HeyGen в кадре не весь ролик — без доли оценка
            # завышена и может отказать в сборке тем, кому денег хватало.
            estimate_kwargs["avatar_share"] = billing["rates"]["avatar_visible_share"]
        need = estimate_micro(
            chars, billing["rates"], billing["markup"], **estimate_kwargs
        )
        have = _ledger().balance(chat_id)
        if have < need:
            raise InsufficientBalance(need=need, have=have)

    store = _job_store()
    job_id = store.new_id()
    workdir = store.workdir_for(job_id)
    workdir.mkdir(parents=True, exist_ok=False)
    try:
        config = copy.deepcopy(load_client(str(chat_id)))
        language = normalize_profile_language(
            language or scenario.get("language") or config.get("language")
        )
        voice_id = str(voice_id or config.get("voice_id") or "").strip()
        if not voice_id:
            raise RuntimeError("voice_id отсутствует в профиле пользователя")
        config_language = str(config.get("language") or "").strip().lower()
        if config_language != language:
            raise RuntimeError(
                f"активный язык профиля {config_language!r} не совпадает с "
                f"языком job {language!r}"
            )
        if config.get("voice_language") != language:
            raise RuntimeError(
                "активный голос профиля записан не для языка текущего ролика"
            )
        config_voices = config.get("voices") or {}
        if (
            not isinstance(config_voices, dict)
            or str(config_voices.get(language) or "").strip() != voice_id
        ):
            raise RuntimeError(
                f"в профиле нет подходящего голоса для языка {language!r}"
            )
        immutable_scenario = copy.deepcopy(scenario)
        scenario_language = immutable_scenario.get("language")
        if scenario_language and scenario_language != language:
            raise RuntimeError(
                f"язык сценария {scenario_language!r} не совпадает с языком job "
                f"{language!r}"
            )
        immutable_scenario["language"] = language
        _write_scenario(workdir, immutable_scenario)

        config["language"] = language
        config["voice_id"] = voice_id
        config["voice_language"] = language
        # Job получает только голос своего языка: поздняя смена профиля и
        # наличие второго голоса не могут повлиять на уже созданный snapshot.
        config["voices"] = {language: voice_id}
        tts = dict(config.get("tts") or {})
        tts["language_code"] = language
        config["tts"] = tts
        config_path = workdir / "build-config.yaml"
        _write_yaml_atomic(config_path, config)

        scenario_bytes = (workdir / "scenario.json").read_bytes()
        input_doc = {
            "format_version": 1,
            "job_id": job_id,
            "user_id": int(chat_id),
            "language": language,
            "voice_language": language,
            "voice_id_sha256": hashlib.sha256(voice_id.encode("utf-8")).hexdigest(),
            "scenario_sha256": hashlib.sha256(scenario_bytes).hexdigest(),
            "config_path": config_path.name,
        }
        input_path = workdir / "job.input.json"
        input_path.write_text(
            json.dumps(input_doc, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        return store.enqueue_prepared(chat_id, job_id=job_id, workdir=workdir)
    except Exception:
        # Не удаляем непустую папку автоматически: scenario/input могут быть
        # полезны для диагностики. В БД такой job нет, worker её не увидит.
        raise


def run_build(chat_id: int, workdir: Path) -> dict:
    """Сборка ролика — чёрный ящик Юли: `python -m reels_factory make` тем же
    питоном, что и бот, cwd не задаём — наследуем cwd бота (корень рабочей
    площадки), как и требует движок. Разбираем JSON из stdout; если разобрать
    не вышло (сбой на середине без валидного ответа) — честная ошибка из
    stderr/stdout."""
    config_path = Path(workdir) / "build-config.yaml"
    config_args = (
        ["--config", str(config_path)]
        if config_path.exists()
        else ["--client", str(chat_id)]  # queued job старого формата
    )
    p = subprocess.run(
        [sys.executable, "-m", "reels_factory", "make",
         "--workdir", str(workdir), *config_args],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.stderr:
        # Движок пишет туда и штатные stage-логи, и предупреждения о деньгах
        # без учёта (job.input.json нечитаем, сбой замера длительности для
        # HeyGen). Раньше при успешной сборке этот stderr никто не читал —
        # предупреждения терялись. warning, а не info: без настроенных
        # хендлеров logging по умолчанию печатает только WARNING и выше —
        # иначе строка снова не попадёт в journalctl. Хвост достаточно
        # длинный, чтобы не обрезать сообщение, но не раздувать журнал.
        log.warning("движок (chat_id=%s): %s", chat_id, p.stderr[-2000:])
    # node-рендер (vite) пишет свой прогресс в stdout движка, поэтому JSON-ответ
    # make — не весь stdout, а последняя разбираемая строка-объект
    for line in reversed((p.stdout or "").splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return {"ok": False, "error": (p.stderr or p.stdout or "пустой ответ движка")[:500]}


def transcribe(chat_id: int, media: Path, language: str) -> str:
    """Речь из записи в текст — локально, без сети и без денег."""
    from reels_factory.transcribe import transcribe_file

    meta = transcribe_file(
        str(media),
        str(session_dir(chat_id)),
        language=normalize_profile_language(language),
    )
    words = json.loads(Path(meta["out"]).read_text(encoding="utf-8"))["words"]
    return " ".join(w["text"] for w in words)


# --- слой телеграма ---------------------------------------------------------

def _kb_start():
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("У меня готовый сценарий", callback_data="mode:text")],
        [InlineKeyboardButton("Предложи сценарий", callback_data="mode:raw")],
    ])


def _kb_language():
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🇷🇺 Русский", callback_data="reel_language:ru")],
        [InlineKeyboardButton("🇰🇿 Қазақша", callback_data="reel_language:kk")],
    ])


def _kb_language_mismatch():
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "Изменить язык ролика", callback_data="mismatch:change"
        )],
        [InlineKeyboardButton(
            "Прислать другой сценарий", callback_data="mismatch:retry"
        )],
    ])


def _kb_back():
    """Шаг ожидания ввода — из него тоже должен быть выход назад."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([[InlineKeyboardButton("← Назад", callback_data="back")]])


def _kb_voice_sample():
    """Экран записи голоса: образец для чтения по кнопке, плюс выход назад."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Отправить текст", callback_data="voice_sample")],
        [InlineKeyboardButton("← Назад", callback_data="back")],
    ])


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
    next_session = session_builder(s)
    if not _reel_language(next_session, required=False):
        next_session["step"] = CHOOSING_LANGUAGE
        save_session(chat_id, next_session)
        await msg.reply_text(ASK_LANGUAGE, reply_markup=_kb_language())
        return
    save_session(chat_id, next_session)
    await msg.reply_text(HELLO, reply_markup=_kb_start())


async def _show_language_choice(msg, chat_id: int, s: dict):
    s["step"] = CHOOSING_LANGUAGE
    s.pop("language", None)
    s.pop("scenario", None)
    s.pop("ideas", None)
    s.pop("material_mode", None)
    save_session(chat_id, s)
    await msg.reply_text(ASK_LANGUAGE, reply_markup=_kb_language())


async def _select_reel_language(msg, chat_id: int, s: dict, language: str):
    language = normalize_profile_language(language)
    s["language"] = language
    _activate_language_voice(s, language)
    s["step"] = CHOOSING
    save_session(chat_id, s)
    await msg.reply_text(LANGUAGE_SAVED.format(language=language_label(language)))
    await msg.reply_text(HELLO, reply_markup=_kb_start())


async def _ask(msg, chat_id: int, s: dict, step: str, text: str):
    """Экран ожидания ввода — с кнопкой «Назад»."""
    s["step"] = step
    save_session(chat_id, s)
    await msg.reply_text(text, reply_markup=_kb_back())


async def _ask_voice(msg, chat_id: int, s: dict, language: str):
    """Экран записи голоса: к инструкции добавлен образец для чтения."""
    s["step"] = WAIT_VOICE
    save_session(chat_id, s)
    await msg.reply_text(
        _ask_voice_text(language), reply_markup=_kb_voice_sample()
    )


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


#: Сколько знаков метки источника храним и что в ней допустимо. Метку ставит
#: не пользователь, а ссылка (`t.me/бот?start=anadeko`), но прийти по ссылке
#: может кто угодно с чем угодно — значит это чужой ввод: он едет в файл
#: сессии, поэтому лишнее отсекаем.
SOURCE_MAX = 32
_SOURCE_OK = re.compile(r"^[a-z0-9_-]+$")


def parse_source(args) -> str | None:
    """Метка источника из ссылки `t.me/бот?start=<метка>`.

    Телеграм отдаёт хвост ссылки первым аргументом команды `/start`. Регистр
    приводим к нижнему: ссылку могут написать как угодно, а считать переходы
    удобнее по одному написанию.
    """
    mark = str((args or [None])[0] or "").strip().lower()
    if not mark or len(mark) > SOURCE_MAX or not _SOURCE_OK.match(mark):
        # Не обрезаем длинное до годного: обрезок — уже другая метка, и в
        # отчёте он выглядел бы настоящим источником.
        return None
    return mark


async def cmd_start(update, context):
    chat_id = update.effective_chat.id
    session = load_session(chat_id)
    source = parse_source(getattr(context, "args", None))
    # Первая метка и остаётся: человек мог прийти по одной ссылке, а потом
    # нажать /start ещё раз или зайти по чужой — источник у него один.
    if source and not session.get("source"):
        session["source"] = source
        save_session(chat_id, session)
        log.info("источник перехода: chat=%s source=%s", chat_id, source)
    await _show_start(update.message, chat_id, session)


async def cmd_new(update, context):
    """/new — новый язык и сценарий; фото и языковые голоса остаются."""
    chat_id = update.effective_chat.id
    await _show_start(update.message, chat_id, load_session(chat_id), loop_session)


_JOB_STATUS_RU = {
    "queued": "в очереди",
    "running": "собирается",
    "completed": "готов и отправлен",
    "qa_failed": "остановлен проверкой качества",
    "failed": "сборка завершилась ошибкой",
    "interrupted": "остановлен перезапуском сервиса",
    "delivery_failed": "готов, но не отправлен в Telegram",
}


async def cmd_status(update, context):
    """Показать durable-статус последней job, а не состояние памяти процесса."""
    chat_id = update.effective_chat.id
    job = _job_store().latest_for_chat(chat_id)
    if job is None:
        await update.message.reply_text("У вас пока нет заданий на сборку.")
        return
    status = _JOB_STATUS_RU.get(job.status, job.status)
    detail = f"\nЭтап: {job.stage}" if job.stage else ""
    if job.error:
        detail += f"\nОшибка: {job.error[:200]}"
    await update.message.reply_text(
        f"Последнее задание {job.job_id[:8]}: {status}.{detail}"
    )


async def on_button(update, context):
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    s = load_session(chat_id)
    data = q.data

    if data.startswith("reel_language:"):
        value = data.split(":", 1)[1]
        await _select_reel_language(q.message, chat_id, s, value)
    elif data == "mismatch:change":
        await _show_language_choice(q.message, chat_id, s)
    elif data == "mismatch:retry":
        await _ask(q.message, chat_id, s, WAIT_TEXT, ASK_TEXT)
    elif data == "mode:text":
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
        if await _blocked_by_negative_balance(q.message, chat_id):
            return
        await q.message.reply_text(WORKING)
        try:
            sc = await asyncio.to_thread(
                step_scenario, chat_id, idea, _reel_language(s)
            )
        except (ScenarioError, RuntimeError) as e:
            await q.message.reply_text(f"Не получилось собрать сценарий: {e}")
            return
        s["scenario"] = sc
        await _show_review(q.message, chat_id, s)
    elif data == "edit":
        await _ask(q.message, chat_id, s, WAIT_EDIT, ASK_EDIT)
    elif data == "ok":
        language = _reel_language(s)
        scenario_language = (s.get("scenario") or {}).get("language")
        if scenario_language and scenario_language != language:
            await q.message.reply_text(
                "Язык сценария не совпадает с выбранным языком ролика. "
                "Начните новый ролик через /new или вернитесь к тексту."
            )
            return
        s["scenario"]["language"] = language
        save_session(chat_id, s)
        await q.message.reply_text(APPROVED_MSG)
        await _photo_stage(q.message, chat_id, s)
    elif data == "photo:old":
        await _voice_stage(q.message, chat_id, s)
    elif data == "photo:new":
        await _ask(q.message, chat_id, s, WAIT_PHOTO, ASK_PHOTO)
    elif data == "voice_sample":
        # Образец идёт отдельным сообщением: так его удобно держать на экране,
        # пока человек читает вслух.
        language = _reel_language(s)
        await q.message.reply_text(
            VOICE_SAMPLE_TEXTS.get(language) or VOICE_SAMPLE_TEXTS["ru"]
        )
    elif data == "voice:old":
        await _finish_voice(q.message, chat_id, s)
    elif data == "voice:new":
        language = _reel_language(s)
        voices = dict(s.get("voices") or {})
        old_voice = voices.pop(language, None)
        s["voices"] = voices
        s.pop("voice_id", None)
        s.pop("voice_language", None)
        if old_voice:
            s["pending_previous_voice"] = {
                "voice_id": old_voice,
                "language": language,
            }
        save_session(chat_id, s)
        if old_voice:
            # Старый provider voice удалим только после успешного создания и
            # сохранения нового. Профиль уже не должен разрешать paid build.
            clear_client_voice_profile(chat_id, language)
        await _ask_voice(q.message, chat_id, s, language)
    elif data == "build":
        # инлайн-кнопки живут в истории чата вечно: тап по старому сообщению
        # READY после DONE не должен зазывать платную сборку заново
        if s.get("step") != READY:
            if _job_store().active_for_chat(chat_id):
                await q.message.reply_text(BUSY_MSG)
            else:
                await q.message.reply_text(NOT_NOW)
            return
        if _job_store().active_for_chat(chat_id):
            await q.message.reply_text(BUSY_MSG)
            return
        try:
            save_client_profile(chat_id, s)
        except Exception:
            await q.message.reply_text(CLIENT_NOT_FOUND_MSG)
            return
        if not client_profile_ready(chat_id):
            await q.message.reply_text(CLIENT_NOT_FOUND_MSG)
            return
        await _enqueue_build(q.message, chat_id, s)
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
    """Предложить голос выбранного языка или запросить его первую запись."""
    language = _reel_language(s)
    voice_id = _activate_language_voice(s, language)
    if voice_id:
        s["step"] = CHOOSING_VOICE
        save_session(chat_id, s)
        await msg.reply_text(
            f"Голос для языка {language_label(language)} уже записан. Что делаем?",
            reply_markup=_kb_voice(),
        )
    else:
        await _ask_voice(msg, chat_id, s, language)


async def _finish_voice(msg, chat_id: int, s: dict):
    """Голос получен (прежний или новый) — сохраняем профиль и идём к готовности."""
    language = _reel_language(s)
    voice_id = _activate_language_voice(s, language)
    if not voice_id:
        await _ask_voice(msg, chat_id, s, language)
        return
    s["step"] = READY
    save_session(chat_id, s)
    save_client_profile(chat_id, s)
    previous = s.get("pending_previous_voice")
    if previous and previous.get("language") == language:
        if previous.get("voice_id") != voice_id:
            try:
                await asyncio.to_thread(step_delete_voice, previous["voice_id"])
            except Exception as e:
                # Новый профиль уже сохранён и готов. Не блокируем пользователя
                # из-за best-effort уборки старого клона.
                log.warning(
                    "не удалось удалить старый клон голоса %s: %s",
                    previous["voice_id"],
                    e,
                )
        s.pop("pending_previous_voice", None)
        save_session(chat_id, s)
    await msg.reply_text(READY_MSG, reply_markup=_kb_ready())


# Ссылки на инфопродукты Tribute. Товары создаются вручную в дашборде —
# API для их создания у Tribute нет, поэтому список статичный.
#
# Берём поле link (оплата ОТКРЫВАЕТСЯ ВНУТРИ ТЕЛЕГРАМА), а не webLink
# (страница в браузере). Разница принципиальная: в браузере покупатель может
# войти по почте, тогда в вебхуке не будет telegram_user_id и зачислять будет
# некому. Внутри Телеграма пользователь опознан всегда.
# Актуальные значения обоих полей: GET /api/v1/products с ключом Tribute.
TOPUP_PRODUCTS = (
    ("$1 (тест)", "https://t.me/tribute/app?startapp=pAHq"),
    ("$10", "https://t.me/tribute/app?startapp=pAH1"),
    ("$25", "https://t.me/tribute/app?startapp=pAHh"),
    ("$50", "https://t.me/tribute/app?startapp=pAHj"),
    ("1000 ₽", "https://t.me/tribute/app?startapp=pAHm"),
    ("2500 ₽", "https://t.me/tribute/app?startapp=pAHn"),
    ("5000 ₽", "https://t.me/tribute/app?startapp=pAHo"),
)


def topup_keyboard():
    # Импорт локальный и аннотации возврата нет — в bot.py telegram-классы
    # везде импортируются внутри функций, на уровне модуля этих имён не существует.
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    rows = [
        [InlineKeyboardButton(label, url=url)]
        for label, url in TOPUP_PRODUCTS
    ]
    return InlineKeyboardMarkup(rows)


def topup_text(need: int | None, have: int, *, exhausted: bool = False) -> str:
    """Экран пополнения. need=None — пользователь открыл его сам, а не упёрся.
    exhausted=True — баланс ушёл в минус: до оценки стоимости рендера дело ещё
    не дошло, поэтому need тут не при чём, а строка своя."""
    lines = [f"Баланс: {format_usd(have)}"]
    if exhausted:
        lines.append("Баланс исчерпан, генерация сценария приостановлена.")
        lines.append("Пополните — и сможете продолжить с того же места.")
    elif need is not None:
        lines.append(
            f"На этот ролик не хватает — нужно примерно {format_usd(need)} "
            "(это ориентировочно, спишется по факту)."
        )
    lines.append("")
    lines.append("Пополнить — кнопкой ниже. Баланс обновится сам после оплаты.")
    return "\n".join(lines)


async def _show_topup(msg, chat_id: int, *, need: int | None = None,
                      have: int | None = None, exhausted: bool = False) -> None:
    """Экран пополнения. Принимает telegram-сообщение, а не update/context:
    зовётся и из обработчика команды, и из _enqueue_build, где есть только msg."""
    balance = _ledger().balance(chat_id) if have is None else have
    await msg.reply_text(
        topup_text(need, balance, exhausted=exhausted), reply_markup=topup_keyboard()
    )


async def cmd_balance(update, context) -> None:
    await _show_topup(update.message, update.effective_chat.id)


async def _blocked_by_negative_balance(msg, chat_id: int) -> bool:
    """Гейт перед платной генерацией сценария (Клод в step_verbatim/step_ideas/
    step_scenario). Порог — строго «меньше нуля», а не «меньше либо равно»:
    свежий пользователь стартует с балансом 0 и должен пройти бесплатный
    пробный сценарий — иначе трейл сломан. Блокируем только когда баланс УЖЕ
    ушёл в минус, иначе получится бесконечный бесплатный цикл генераций
    в убыток заведению."""
    billing = _billing()
    if not billing["enabled"]:
        return False
    balance = _ledger().balance(chat_id)
    if balance >= 0:
        return False
    await _show_topup(msg, chat_id, have=balance, exhausted=True)
    return True


async def _enqueue_build(msg, chat_id: int, s: dict) -> BuildJob | None:
    """Поставить job в durable FIFO; платный pipeline здесь не запускается."""
    try:
        job = enqueue_build(
            chat_id,
            s["scenario"],
            language=_reel_language(s),
            voice_id=s.get("voice_id"),
        )
    except InsufficientBalance as exc:
        # Раньше общего except: иначе нехватка баланса покажется как
        # техническая ошибка, без кнопок пополнения.
        await _show_topup(msg, chat_id, need=exc.need, have=exc.have)
        return None
    except Exception as e:
        await msg.reply_text(f"Не удалось поставить ролик в очередь: {str(e)[:200]}")
        return None

    s["step"] = BUILDING
    s["current_job_id"] = job.job_id
    save_session(chat_id, s)
    ahead = _job_store().queued_ahead(job.job_id)
    suffix = f" Перед вами заданий: {ahead}." if ahead else ""
    if _job_wakeup is not None:
        _job_wakeup.set()
    try:
        await msg.reply_text(f"{BUILDING_MSG}{suffix}\nID: {job.job_id[:8]}")
    except Exception as e:
        # Job уже durable и worker разбужен. Сбой служебного Telegram-сообщения
        # не должен потерять задание или оставить очередь спящей.
        log.warning("job %s поставлена в очередь, но статус не отправлен: %s", job.job_id, e)
    return job


def _update_session_after_job(chat_id: int, job_id: str, step: str) -> None:
    """Не затирать более новую сессию, если пользователь уже начал другой цикл."""
    s = load_session(chat_id)
    if s.get("current_job_id") != job_id:
        return
    s["step"] = step
    s["last_job_id"] = job_id
    s.pop("current_job_id", None)
    save_session(chat_id, s)


async def _safe_job_message(bot_api, chat_id: int, text: str) -> None:
    try:
        await bot_api.send_message(chat_id=chat_id, text=text)
    except Exception as e:
        log.warning("не удалось отправить статус job в чат %s: %s", chat_id, e)


def _charged_but_undelivered_notice(job_id: str) -> str:
    """QA/размер/доставка провалились ПОСЛЕ платного рендера — баланс уже
    просел, а автоматических возвратов нет (осознанно вне плана). Пользователь
    должен узнать сумму из того же сообщения, а не заметить её сам в /balance.

    Вызывается вне защиты _safe_job_message — job уже завершён, повторов не
    будет, поэтому чтение бухгалтерии не должно уметь уронить обработчик:
    если SQLite заблокирован или битый, пользователь обязан получить хотя бы
    голый текст ошибки, а не остаться без всякого сообщения.
    """
    try:
        breakdown = _ledger().job_breakdown(job_id)
    except Exception as e:
        log.warning("не удалось прочитать breakdown для job %s: %s", job_id, e)
        return ""
    if not breakdown:
        return ""
    parts = ", ".join(
        f"{name} {format_usd(value)}" for name, value in sorted(breakdown.items())
    )
    total = sum(breakdown.values())
    # Как и в чеке успешной доставки: total — это стоимость самого рендера
    # (job_id проставлен), подготовка сценария Клодом сюда не входит и
    # списывается отдельно — не называем total «списано за попытку целиком».
    return (
        f"\n\nСам рендер уже стоил {format_usd(total)} ({parts}) — "
        "разберёмся вручную."
    )


async def _process_job(bot_api, job: BuildJob, build_fn=None) -> None:
    """Исполнить уже claimed job и доставить только результат с QA PASS."""
    store = _job_store()
    build_fn = build_fn or run_build
    await _safe_job_message(
        bot_api, job.chat_id, f"{RUNNING_MSG}\nID: {job.job_id[:8]}"
    )
    try:
        result = await asyncio.to_thread(build_fn, job.chat_id, job.workdir)
    except Exception as e:
        result = {"ok": False, "stage": "build", "error": str(e)[:500]}

    if not result.get("ok"):
        error = result.get("error") or "неизвестная ошибка"
        store.finish(
            job.job_id,
            "failed",
            result=result,
            stage=result.get("stage") or "build",
            error=error,
        )
        _update_session_after_job(job.chat_id, job.job_id, BUILD_FAILED)
        await _safe_job_message(
            bot_api,
            job.chat_id,
            f"Не получилось собрать ролик: {error}\nID: {job.job_id[:8]}",
        )
        return

    mp4 = Path(result.get("mp4") or (job.workdir / "reel.mp4"))
    if not mp4.exists():
        store.finish(
            job.job_id,
            "failed",
            result=result,
            stage="output",
            error=MISSING_FILE_MSG,
        )
        _update_session_after_job(job.chat_id, job.job_id, BUILD_FAILED)
        await _safe_job_message(bot_api, job.chat_id, MISSING_FILE_MSG)
        return

    if not result.get("qa_pass"):
        store.finish(
            job.job_id,
            "qa_failed",
            result=result,
            stage="verify",
            error="QA gates failed",
        )
        _update_session_after_job(job.chat_id, job.job_id, BUILD_FAILED)
        await _safe_job_message(
            bot_api, job.chat_id,
            f"{QA_FAIL_MSG}\nID: {job.job_id[:8]}"
            f"{_charged_but_undelivered_notice(job.job_id)}",
        )
        return

    if mp4.stat().st_size > MAX_TG_VIDEO_BYTES:
        error = (
            "Ролик собрался, но весит больше 50 МБ — Telegram его не примет. "
            f"Файл сохранён: {mp4}"
        )
        store.finish(
            job.job_id,
            "delivery_failed",
            result=result,
            stage="delivery",
            error=error,
        )
        _update_session_after_job(job.chat_id, job.job_id, BUILD_FAILED)
        await _safe_job_message(
            bot_api,
            job.chat_id,
            error + _charged_but_undelivered_notice(job.job_id),
        )
        return

    try:
        with mp4.open("rb") as f:
            await bot_api.send_video(
                chat_id=job.chat_id,
                video=f,
                caption=DONE_MSG,
                reply_markup=_kb_done(),
                width=OUT_W,
                height=OUT_H,
            )
    except Exception as e:
        store.finish(
            job.job_id,
            "delivery_failed",
            result=result,
            stage="delivery",
            error=str(e),
        )
        _update_session_after_job(job.chat_id, job.job_id, BUILD_FAILED)
        await _safe_job_message(
            bot_api,
            job.chat_id,
            "Ролик готов и прошёл QA, но Telegram не принял файл. "
            f"Он сохранён для повторной отправки.\nID: {job.job_id[:8]}"
            f"{_charged_but_undelivered_notice(job.job_id)}",
        )
        return

    store.finish(job.job_id, "completed", result=result, stage="delivery")
    # Чтение бухгалтерии вне защиты _safe_job_message — видео уже доставлено,
    # повторов не будет. Если SQLite заблокирован или битый, чтение не должно
    # уронить обновление сессии: доставленный ролик без чека — это приемлемая
    # потеря, а застрявшая сессия — это тикет в поддержку.
    try:
        breakdown = _ledger().job_breakdown(job.job_id)
    except Exception as e:
        log.warning("не удалось прочитать breakdown для job %s: %s", job.job_id, e)
        breakdown = None
    if breakdown:
        parts = ", ".join(
            f"{name} {format_usd(value)}" for name, value in sorted(breakdown.items())
        )
        total = sum(breakdown.values())
        # Это стоимость самого рендера (job_id проставлен): подготовка
        # сценария Клодом списывается отдельно, без job_id, и сюда не входит —
        # поэтому не называем total «списано за ролик», баланс ниже точнее.
        await _safe_job_message(
            bot_api,
            job.chat_id,
            f"Сам рендер стоил {format_usd(total)} ({parts}).\n"
            f"Баланс: {format_usd(_ledger().balance(job.chat_id))}",
        )
    _update_session_after_job(job.chat_id, job.job_id, DONE)


async def _job_worker(bot_api) -> None:
    """Один последовательный worker; очередь и claim находятся в SQLite."""
    store = _job_store()
    while True:
        try:
            if _job_wakeup is not None:
                _job_wakeup.clear()
            job = await asyncio.to_thread(store.claim_next)
            if job is None:
                if _job_wakeup is None:
                    await asyncio.sleep(1)
                else:
                    await _job_wakeup.wait()
                continue
            await _process_job(bot_api, job)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("необработанная ошибка render worker")
            await asyncio.sleep(1)


async def on_message(update, context):
    chat_id = update.effective_chat.id
    s = load_session(chat_id)
    step = s.get("step", CHOOSING)
    msg = update.message

    if step == CHOOSING_LANGUAGE:
        await msg.reply_text(ASK_LANGUAGE, reply_markup=_kb_language())
        return

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
            language = _reel_language(s)
            voice_id = await asyncio.to_thread(
                step_voice, chat_id, path, language
            )
        except Exception as e:
            await msg.reply_text(f"Голос не принялся: {str(e)[:200]}")
            return
        voices = dict(s.get("voices") or {})
        voices[language] = voice_id
        s["voices"] = voices
        s["voice_id"] = voice_id
        s["voice_language"] = language
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
            text = await asyncio.to_thread(
                transcribe, chat_id, path, _reel_language(s)
            )
        except Exception as e:
            await msg.reply_text(f"Не смог разобрать запись: {str(e)[:200]}")
            return

    if not text:
        await msg.reply_text(NOT_NOW if step == CHOOSING else
                             "Жду текст сообщением или файлом.")
        return

    if step == WAIT_TEXT:
        language = _reel_language(s)
        cleaned = clean_input(text)
        mismatch = confident_mismatch(cleaned, language)
        if mismatch:
            await msg.reply_text(
                LANGUAGE_MISMATCH.format(
                    detected=language_label(mismatch.code),
                    selected=language_label(language),
                ),
                reply_markup=_kb_language_mismatch(),
            )
            return
        if await _blocked_by_negative_balance(msg, chat_id):
            return
        await msg.reply_text(WORKING)
        try:
            sc = await asyncio.to_thread(
                step_verbatim, chat_id, cleaned, language
            )
        except (ScenarioError, RuntimeError) as e:
            await msg.reply_text(f"Не получилось разобрать текст: {e}")
            return
        s["scenario"] = sc
        await _show_review(msg, chat_id, s)

    elif step == WAIT_RAW:
        if await _blocked_by_negative_balance(msg, chat_id):
            return
        await msg.reply_text(WORKING)
        try:
            ideas = await asyncio.to_thread(
                step_ideas, chat_id, text, _reel_language(s)
            )
        except (ScenarioError, RuntimeError) as e:
            await msg.reply_text(f"Не получилось вытащить идеи: {e}")
            return
        s["ideas"] = ideas
        await _show_ideas(msg, chat_id, s)

    elif step == WAIT_EDIT:
        language = _reel_language(s)
        cleaned = clean_input(text)
        mismatch = confident_mismatch(cleaned, language)
        if mismatch:
            await msg.reply_text(
                LANGUAGE_MISMATCH.format(
                    detected=language_label(mismatch.code),
                    selected=language_label(language),
                ),
                reply_markup=_kb_language_mismatch(),
            )
            return
        try:
            sc = scenario_from_text(cleaned, language)
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
    """Поднять durable worker и безопасно закрыть осиротевшие running jobs."""
    from telegram import BotCommand

    await app.bot.set_my_commands(
        [
            BotCommand("new", "Новый ролик"),
            BotCommand("status", "Статус сборки"),
            BotCommand("balance", "Баланс и пополнение"),
        ]
    )
    interrupted = await asyncio.to_thread(_job_store().mark_running_interrupted)
    for job in interrupted:
        _update_session_after_job(job.chat_id, job.job_id, BUILD_FAILED)
        await _safe_job_message(
            app.bot, job.chat_id, f"{INTERRUPTED_MSG}\nID: {job.job_id[:8]}"
        )

    tribute_key = os.environ.get("TRIBUTE_API_KEY")
    billing = _billing()
    if tribute_key:
        start_webhook_server(
            _ledger(), api_key=tribute_key, fx=billing["fx"],
            port=int(os.environ.get("TRIBUTE_WEBHOOK_PORT", "8099")),
            on_credit=lambda ev: None,
        )
    elif billing["enabled"]:
        # Кнопки пополнения остаются активны и без ключа: Tribute всё равно
        # спишет деньги и будет ретраить вебхук ~сутки против мёртвого
        # эндпоинта — без слушателя платёж потом виснет без автосверки.
        log.error(
            "TRIBUTE_API_KEY не задан: пополнения Tribute не будут "
            "зачисляться, хотя биллинг включён"
        )

    global _job_wakeup, _worker_task
    _job_wakeup = asyncio.Event()
    _worker_task = asyncio.create_task(_job_worker(app.bot), name="reels-render-worker")
    _job_wakeup.set()  # забрать queued jobs, пережившие перезапуск


async def _post_shutdown(app):
    global _job_wakeup, _worker_task
    if _worker_task is not None:
        _worker_task.cancel()
        with suppress(asyncio.CancelledError):
            await _worker_task
    _worker_task = None
    _job_wakeup = None


def main():
    from telegram.ext import (ApplicationBuilder, CallbackQueryHandler,
                              CommandHandler, MessageHandler, filters)

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("Нет TELEGRAM_BOT_TOKEN в окружении")
    app = (
        ApplicationBuilder()
        .token(token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("new", cmd_new))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(~filters.COMMAND, on_message))
    app.run_polling()


if __name__ == "__main__":
    main()
