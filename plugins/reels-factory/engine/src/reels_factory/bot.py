"""Телеграм-бот фабрики: сырьё или готовый текст -> утверждённый сценарий.

Разговор: /start (пример ролика) -> язык -> пол -> фото -> запись голоса ->
бесплатное демо «Это я. Твой аватар!» -> выбор пути -> материал -> экран
цены -> оплата -> сценарий в чате -> правка текста руками или утверждение ->
готовность.

Порядок держится на одном правиле: до экрана цены человек НЕ платит. Фото
загружается в HeyGen бесплатно, запись голоса просто лежит файлом, материал
принимается как есть. Единственные наши затраты до цены — бесплатное для
человека демо (клон голоса + 2-3 секунды HeyGen): оно показывает новичку его
двойника до разговора о деньгах и потому окупается конверсией. Сценарий
(Клод) и рендер ролика — платные шаги за экраном цены; клон, сделанный ради
демо, там переиспользуется.

По кнопке «Создать ролик» durable worker сначала создаёт только master audio и
присылает его на проверку. Подтверждение продолжает ту же immutable job без
повторного TTS. Отказ переводит job в ожидание одного Telegram voice со всем
сценарием; эта запись становится master audio только текущего ролика и не
заменяет языковой voice clone в профиле. Лишь после выбора дорожки worker зовёт
`python -m reels_factory make` и присылает готовый mp4.

После готового ролика экран с кнопкой «Новый ролик» (или команда /new) начинает
разговор заново с языка. Фото и отдельные голоса ru/kk остаются, сценарий
сбрасывается.

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
import time
import uuid
from contextlib import suppress
from pathlib import Path

from reels_factory.analytics import EventStore, render_funnel
from reels_factory.billing import (
    LedgerStore, apply_markup, claude_cost_micro, estimate_micro,
)
from reels_factory.config import (
    OUT_H, OUT_W, WORK_ROOT, load_billing_config, load_config,
)
from reels_factory.feedback import FeedbackStore
from reels_factory.jobs import BuildJob, JobStore
from reels_factory.language import (
    SUPPORTED_LANGUAGES,
    confident_mismatch,
    language_label,
    normalize_profile_language,
)
from reels_factory.llm import ClaudeSkillRunner
from reels_factory.scenario import (DEFAULT_MAX_DURATION_S, ScenarioError,
                                    run_generated_path, run_ideas,
                                    run_verbatim_path, split_verbatim)
from reels_factory.tribute import start_webhook_server
from reels_factory.tts import tts_model_for_language

log = logging.getLogger(__name__)

# Шаги разговора. Порядок: всё бесплатное для человека (язык, пол, фото,
# запись голоса, демо, материал) идёт ДО экрана цены; Клод и рендер — после.
CHOOSING_LANGUAGE = "choosing_language"  # язык нового ролика
CHOOSING_GENDER = "choosing_gender"  # пол ведущего нового ролика
WAIT_PHOTO = "wait_photo"
WAIT_VOICE = "wait_voice"            # ждём запись голоса; клон здесь не делаем
VIEWING_STAGE = "viewing_stage"      # пройденный этап: вперёд, назад, изменить
CHOOSING = "choosing"                # ждём выбора пути
CHOOSING_MATERIAL = "choosing_material"  # legacy: экран «Что используем?» убран
WAIT_TEXT = "wait_text"              # ждём готовый текст реплик
WAIT_RAW = "wait_raw"                # ждём сырьё (мысли, отрывок, запись)
CONFIRM_PRICE = "confirm_price"      # оценка показана, ждём «Поехали» или оплату
CHOOSING_IDEA = "choosing_idea"
REVIEW = "review"                    # сценарий показан, ждём решения
WAIT_EDIT = "wait_edit"              # ждём отредактированный текст
READY = "ready"                      # сценарий утверждён, фото и голос собраны
WAIT_WISH = "wait_wish"              # ждём пожелание к недоделанной функции
AUDIO_PREPARING = "audio_preparing"  # master TTS стоит в очереди или создаётся
AUDIO_REVIEW = "audio_review"        # TTS отправлено, ждём approve/reject
WAIT_FINAL_AUDIO = "wait_final_audio"  # ждём весь сценарий Telegram voice
BUILDING = "building"                # утверждённое audio идёт в video render
BUILD_FAILED = "build_failed"        # сборка/QA остановлены, видео не отправлено
DONE = "done"                        # ролик заказан, ждём новый цикл

# Версия порядка шагов. Сессии, записанные прежним порядком (фото и голос
# после сценария), помечены её отсутствием и переводятся на новый порядок в
# load_session — с сохранением фото, голосов и всего, за что уже заплачено.
FLOW_VERSION = 2

# Этапы, где человек что-то даёт. Пройденный этап показывается сводкой с
# навигацией в обе стороны: возвращаться к нему приходится часто (ушёл на
# оплату, передумал), а переспрашивать уже собранное — терять его работу.
STAGE_LANGUAGE = "language"
STAGE_GENDER = "gender"
STAGE_PHOTO = "photo"
STAGE_VOICE = "voice"
STAGE_MATERIAL = "material"
STAGE_ORDER = (STAGE_LANGUAGE, STAGE_GENDER, STAGE_PHOTO, STAGE_VOICE,
               STAGE_MATERIAL)

# Пол ведущего. Сервис не видит пола по сырью и в сгенерированном тексте пишет
# «сделала» мужчине. Спрашиваем каждый ролик, как язык, и до генерации
# сценария: человек меняет ведущего от ролика к ролику, а профильным полем это
# значило бы один раз выбранный пол на все будущие ролики.
GENDERS = ("male", "female")
GENDER_LABELS = {"male": "Мужской", "female": "Женский"}

# Сколько знаков материала показываем в сводке: целиком он в экран не влезет.
MATERIAL_EXCERPT_CHARS = 150

# Шаги, привязанные к оплаченной job: их миграция не трогает, иначе разговор
# отвяжется от уже запущенной сборки.
_JOB_BOUND_STEPS = frozenset({
    AUDIO_PREPARING, AUDIO_REVIEW, WAIT_FINAL_AUDIO, BUILDING,
    BUILD_FAILED, DONE,
})

ROLE_RU = {"hook": "хук", "context": "контекст", "development": "развитие",
           "payoff": "вывод", "cta": "призыв"}

HELLO = (
    "Привет! Я делаю ролики с вашим ИИ-двойником: ваше лицо + ваш голос = "
    "готовое видео с монтажом для социальных сетей.\n\n"
    "Вот пример, какой результат вы получите 👆\n\n"
    "Как это работает:\n\n"
    "1. Отправляете свое фото и пример своего голоса\n"
    "2. Получаете ваш оживший аватар\n"
    "3. Если аватар понравился: присылаете сценарий и мы генерируем готовое "
    "видео для вас"
)

# Ассеты онбординга: пример готового ролика (в приветствии) и образец
# правильного фото (на экране фото). Лежат в репо рядом с движком; их
# отсутствие не должно ронять разговор — тогда экран уходит просто текстом.
_ASSETS_DIR = Path(__file__).resolve().parents[2] / "assets"
DEMO_EXAMPLE_MP4 = _ASSETS_DIR / "demo_example.mp4"
PHOTO_EXAMPLE_PNG = _ASSETS_DIR / "photo_example.png"

# Telegram file_id уже залитых ассетов: повторная отправка по file_id
# мгновенна, а 20-мегабайтный пример не гоняется на каждый /start.
_ASSET_FILE_ID_CACHE = "asset_file_ids.json"
ASK_PATH = (
    "Пришлите сценарий или просто идею о чем будет рассказывать ваш аватар.\n\n"
    "➡️\"У меня готовый сценарий\" если хотите чтобы аватар дословно следовал "
    "вашим репликам.\n\n"
    "➡️\"Сгенерировать сценарий\" если хотите чтобы мы написали сценарий по "
    "вашему материалу (идея, отрывок из книги/статьи, конспекты и просто ваши "
    "мысли)"
)
ASK_LANGUAGE = (
    "На каком языке хотите сделать ролик?"
)
ASK_GENDER = "Выберите пол аватара"
LANGUAGE_SAVED = (
    "Делаем этот ролик на языке: {language}."
)
LANGUAGE_MISMATCH = (
    "Похоже, этот сценарий написан на языке: {detected}.\n\n"
    "Для этого ролика выбран язык: {selected}."
)
ASK_TEXT = (
    "Пришлите текст ролика — ровно те слова, которые должны прозвучать.\n\n"
    "Для расстановки пауз используйте тире или многоточие — голос "
    "воспроизведёт паузы точно там, где вы расставили знаки."
)
ASK_RAW = (
    "Пришлите материал — из него соберу качественный сценарий.\n\n"
    "Подойдёт что угодно: ваши мысли текстом, конспект, отрывок из книги, "
    "голосовое, видео или аудиозапись. Чем конкретнее и живее исходник, тем "
    "меньше воды в ролике."
)
WORKING = "Работаю, это займёт минуту-другую…"
TRANSCRIBING = "Распознаю запись, это дольше обычного…"
ASK_EDIT = (
    "Пришлите свой вариант текста целиком — запомню его как итоговый и "
    "покажу, как он ляжет в блоки."
)
APPROVED_MSG = "Сценарий утверждён и сохранён."
ASK_PHOTO = (
    "Шаг 1 из 2. Пришлите своё фото, по нему соберу вашего двойника.\n\n"
    "Это фото оживёт: двойник будет в этой одежде и в этом месте говорить в "
    "камеру. Выбирайте фото так, как будто уже записываете в нём ролик для "
    "своего блога.\n\n"
    "Как правильно сделать фото (пример выше 👆):\n"
    "— по пояс, чтобы руки были в кадре: тогда ведущий будет жестикулировать;\n"
    "— смотрите в камеру, ровный свет, без тёмных очков и без чужих лиц в "
    "кадре;\n"
    "— нейтральное выражение лица, без улыбки, с закрытым ртом.\n\n"
    "Важно.\n"
    "Всё, что должно выглядеть настоящим, должно быть видно на фото: ногти, "
    "кольца, часы, одежда. Чего на фото нет, то модель додумает по-своему."
)
ASK_VOICE = (
    "Шаг 2 из 2. Теперь голос: двойник будет говорить точно как вы.\n\n"
    "Как записать:\n"
    "— зажмите микрофон 🎤 справа от поля ввода и читайте, не отпуская, "
    "минимум 2 минуты;\n"
    "— тихая комната: без музыки, телевизора и эха. Только ваш голос;\n"
    "— читайте живо, с интонацией — мы скопируем вашу манеру. Не "
    "переигрывайте: держите один настрой и одну громкость всю запись;\n"
    "— микрофон на одном расстоянии, не отворачивайтесь.\n\n"
    "Текст для прочтения вслух пришлю по кнопке ниже.\n\n"
    "Не бойтесь ошибиться: перед созданием ролика дам послушать озвучку, "
    "запись можно будет переделать."
)

# --- Демо «оживший аватар»: бесплатный шаг между голосом и материалом ---
# Показываем человеку его двойника ДО разговора о деньгах: 2-3 секунды,
# фиксированная фраза. Фраза не настраивается пользователем, чтобы демо
# нельзя было использовать как бесплатный генератор роликов.
DEMO_PHRASES = {
    "ru": "Привет! Это я! Твой аватар.",
    "kk": "Сәлем! Бұл мен! Сенің аватарың.",
}
# По гайду HeyGen: один жест плюс характер, коротко. Уверенный оратор, без
# махания руками и дежурной улыбки — как в полном ролике.
DEMO_MOTION_PROMPT = (
    "Looks straight at the camera with subtle natural hand gestures, "
    "confident and composed."
)
DEMO_EXPRESSIVENESS = "medium"
DEMO_BUILDING_MSG = (
    "Всё на месте! Оживляю ваше фото и клонирую голос.\n\n"
    "Через минуту пришлю сюда вашего двойника, никуда не уходите 👇"
)
DEMO_READY_MSG = (
    "👆 Ваш двойник готов. Лицо с вашего фото, голос с вашей записи.\n\n"
    "Дальше он озвучит ваш сценарий, я добавлю субтитры и соберу ролик для "
    "публикации."
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


PHOTO_SAVED = "✅ Фото получено"
PHOTO_SUMMARY_CAPTION = (
    "✅ Это фото у меня уже сохранено 👆 Из него соберу вашего двойника.\n"
    "Хотите другое: жмите «Изменить»."
)
VOICE_SAVED = "✅ Запись голоса получена"
CLONING_VOICE_MSG = "Делаю голос по вашей записи, это займёт минуту…"
PRICE_ENOUGH_MSG = (
    "Материал принял. Ролик обойдётся примерно в {need}, на балансе {have}.\n\n"
    "Спишется по факту — обычно меньше оценки. Жмите «Поехали»: напишу "
    "сценарий, сделаю голос и покажу озвучку на проверку."
)
PRICE_SHORT_MSG = (
    "Материал принял. Ролик обойдётся примерно в {need}, на балансе {have} — "
    "не хватает {gap}.\n\n"
    "Пополните баланс кнопкой ниже и нажмите «Проверить баланс» — продолжим "
    "с этого места, ничего заново присылать не нужно."
)
PRICE_STILL_SHORT_MSG = "Баланс: {have}. Не хватает {gap}"
PAID_ENOUGH_MSG = "✅ Оплата получена. Баланс: {have}"
READY_MSG = "Всё на месте: сценарий, фото и голос. Жмите «Создать ролик», когда готовы."
MONTAGE_WIP_MSG = (
    "Монтаж пока в разработке — ролик с ним я собрать ещё не могу.\n\n"
    "Расскажите, чего вы от него ждёте: какие вставки, темп, титры, примеры "
    "роликов. Постараюсь сделать именно это — напишите одним сообщением.\n\n"
    "А собрать ролик прямо сейчас можно кнопкой «Без монтажа»."
)
WISH_THANKS = "Записал, спасибо. Учту, когда буду доделывать монтаж."
WISH_SKIPPED = "Хорошо, без пожеланий."
WISH_EMPTY = "Жду пожелание текстом — одним сообщением."
MONTAGE_TOPIC = "montage"
BUILD_FAILED_HINT = (
    "Прошлый ролик остановлен и не отправлен. Начнём новый — кнопкой ниже "
    "или командой /new."
)
DONE_MSG = "Ролик уже создан. Чтобы снять ещё один — жмите «Новый ролик»."
NOT_NOW = "Сначала выберите, с чего начать: /start"

BUILDING_MSG = (
    "Готовлю озвучку для проверки. Сам ролик начну собирать только после "
    "вашего подтверждения."
)
PREPARING_AUDIO_MSG = "Создаю озвучку утверждённого сценария…"
AUDIO_REVIEW_MSG = (
    "Озвучка готова. Прослушайте её целиком — именно эта аудиодорожка "
    "попадёт в ролик."
)
ASK_FINAL_AUDIO = (
    "Запишите весь утверждённый сценарий одним голосовым сообщением прямо "
    "в Telegram и отправьте его сюда.\n\n"
    "Читайте в своём темпе и с живой интонацией. Запись попадёт в ролик "
    "именно в таком виде — без нейроозвучки, склеек и дозаписей."
)
PROCESSING_FINAL_AUDIO = (
    "Запись принял. Проверяю, что сценарий записан целиком, и готовлю тайминги…"
)
FINAL_AUDIO_ACCEPTED = (
    "Использую именно это голосовое как финальную озвучку. Запускаю сборку ролика."
)
RENDER_QUEUED_MSG = (
    "Озвучка утверждена. Запускаю генерацию ролика — повторно голос создавать не буду."
)
AUDIO_ACTION_STALE = "Эта кнопка уже не относится к текущему этапу ролика."
RUNNING_MSG = "Начинаю сборку ролика. Это займёт несколько минут…"
BUSY_MSG = "Предыдущий ролик ещё не завершён — сначала закончим его текущий этап."
CANCELLED_PENDING_MSG = (
    "Предыдущий ролик ждал вашего решения — отменил его. Начинаем новый."
)
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


# Фото, записи голоса и готовые клоны переживают новый цикл («Новый ролик»).
_PROFILE_KEYS = (
    "photo",
    "voice_samples",     # записи по языкам: из них делается клон после оплаты
    "voice_pending",     # записи, клон по которым ещё не сделан
    "voices",
    "voice_id",          # active voice текущего языка; legacy-compatible
    "voice_language",
    "pending_previous_voice",
    "pay_currency",      # валюта счёта: выбрана человеком, спрашиваем один раз
    "pending_order",     # неоплаченный счёт: /new не должен его терять
    "demo",              # ключ и файл показанного демо: не генерить повторно
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


_events_cache: tuple[Path, EventStore] | None = None


def _events() -> EventStore:
    """Журнал событий: путь зависит от cwd, поэтому кэшируем как _ledger."""
    global _events_cache
    db_path = (WORK_ROOT / "events.sqlite3").resolve()
    if _events_cache is None or _events_cache[0] != db_path:
        _events_cache = (db_path, EventStore(db_path))
    return _events_cache[1]


def _track(chat_id: int, s: dict, event: str, detail: str | None = None) -> None:
    """Записать шаг воронки. Никогда не мешает разговору: аналитика важнее
    молча пропущенной строки, чем упавшего ответа человеку."""
    try:
        _events().record(chat_id, int((s or {}).get("cycle") or 1), event, detail)
    except Exception as e:  # pragma: no cover — защита от неожиданного
        log.warning("событие %s чата %s не записалось: %s", event, chat_id, e)


def _ledger() -> LedgerStore:
    """Журнал трат и балансов. Кэшируем как _job_store: путь зависит от cwd."""
    global _ledger_cache
    db_path = (WORK_ROOT / "billing.sqlite3").resolve()
    if _ledger_cache is None or _ledger_cache[0] != db_path:
        _ledger_cache = (db_path, LedgerStore(db_path))
    return _ledger_cache[1]


_feedback_cache: tuple[Path, FeedbackStore] | None = None


def _feedback() -> FeedbackStore:
    """Журнал пожеланий. Кэшируем как _ledger: путь зависит от cwd."""
    global _feedback_cache
    db_path = (WORK_ROOT / "feedback.sqlite3").resolve()
    if _feedback_cache is None or _feedback_cache[0] != db_path:
        _feedback_cache = (db_path, FeedbackStore(db_path))
    return _feedback_cache[1]


def _billing() -> dict:
    return load_billing_config()


def format_usd(micro: int) -> str:
    """Микродоллары -> строка для пользователя."""
    sign = "-" if micro < 0 else ""
    return f"{sign}${abs(micro) / 1_000_000:.2f}"


def estimate_material_micro(session: dict, billing: dict) -> int:
    """Во сколько обойдётся ролик по принятому материалу — до генерации.

    В режиме готового текста символы уже известны: это ровно те слова, что
    уйдут в озвучку. В режиме сырья сценария ещё нет, поэтому берём верхнюю
    границу длины ролика (DEFAULT_MAX_DURATION_S) — оценка сверху честнее,
    чем приятная снизу.

    Долю аватара в кадре (avatar islands) здесь НЕ применяем, хотя
    enqueue_build умеет: оценка на экране цены должна быть не ниже той, что
    посчитает очередь, иначе человек заплатит ровно по экрану и упрётся в
    отказ уже после генерации сценария.
    """
    rates = billing["rates"]
    chars = 0
    if (session or {}).get("material_mode") == "text":
        chars = len(clean_input((session or {}).get("material_text") or ""))
    if chars <= 0:
        chars = int(DEFAULT_MAX_DURATION_S * float(rates["chars_per_second"]))
    return estimate_micro(chars, rates, billing["markup"])


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
    if data.get("flow") != FLOW_VERSION:
        data = _migrate_flow(data)
    return data


def _migrate_flow(data: dict) -> dict:
    """Сессия прежнего порядка шагов (фото и голос после сценария).

    Трогаем только позицию в разговоре: фото, клоны голоса, сценарий и всё,
    за что уже заплачено, остаются на месте. Разговор, привязанный к job,
    не сдвигаем — иначе оплаченная сборка потеряет своего собеседника.
    """
    if data.get("current_job_id") or data.get("step") in _JOB_BOUND_STEPS:
        return data
    data["step"] = CHOOSING_LANGUAGE if not data.get("language") else CHOOSING
    return data


def save_session(chat_id: int, data: dict) -> None:
    data["flow"] = FLOW_VERSION
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


def _voice_sample_for_language(session: dict, language: str) -> Path | None:
    """Запись голоса, из которой делается (или уже сделан) клон этого языка."""
    language = normalize_profile_language(language)
    raw = ((session or {}).get("voice_samples") or {}).get(language)
    if not raw:
        return None
    path = Path(str(raw))
    return path if path.exists() else None


def _pending_voice_sample(session: dict, language: str) -> Path | None:
    """Запись, по которой клон ещё не заказан: её и превращаем в голос."""
    language = normalize_profile_language(language)
    raw = ((session or {}).get("voice_pending") or {}).get(language)
    if not raw:
        return None
    path = Path(str(raw))
    return path if path.exists() else None


def _has_voice_material(session: dict, language: str) -> bool:
    """Есть чем озвучивать: готовый клон или ещё не оплаченная запись."""
    return bool(
        _voice_for_language(session, language)
        or _voice_sample_for_language(session, language)
    )


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


def step_scenario(chat_id: int, idea: dict, language: str,
                  gender: str | None = None) -> dict:
    runner = ClaudeSkillRunner()
    # См. step_verbatim: провал тоже платный, списываем в finally.
    try:
        res = run_generated_path(session_dir(chat_id), idea, runner,
                                 language=normalize_profile_language(language),
                                 gender=gender)
    finally:
        _charge_claude(chat_id, runner)
    return res["scenario"]


def step_photo(chat_id: int, photo: Path) -> str:
    """Фото -> asset_id в HeyGen (бесплатно, платит только рендер)."""
    from reels_factory.avatar import upload_photo_asset

    return upload_photo_asset(photo)


def step_demo(chat_id: int, photo_asset_id: str, voice_id: str,
              language: str) -> Path:
    """Демо «Это я. Твой аватар!»: TTS фразы клоном + оживление фото в HeyGen.

    Единственная генерация до экрана цены. Фраза 2-3 секунды, поэтому
    себестоимость копеечная, а человек впервые видит СВОЁ лицо и голос —
    ради этого демо и существует.
    """
    from reels_factory.avatar import HeyGenClient
    from reels_factory.tts import synth_voice

    workdir = session_dir(chat_id) / "demo"
    workdir.mkdir(parents=True, exist_ok=True)
    phrase = DEMO_PHRASES.get(language) or DEMO_PHRASES["ru"]
    wav = workdir / f"demo_{language}.wav"
    synth_voice(phrase, wav, voice_id=voice_id,
                model_id=tts_model_for_language(language))
    client = HeyGenClient(
        avatar_id=photo_asset_id,
        motion_prompt=DEMO_MOTION_PROMPT,
        expressiveness=DEMO_EXPRESSIVENESS,
    )
    return client.generate(wav, workdir / f"demo_{language}.mp4")


def step_voice(chat_id: int, audio: Path, language: str) -> str:
    """Запись -> клон голоса в ElevenLabs -> voice_id."""
    from reels_factory.tts import create_voice_clone

    language = normalize_profile_language(language)
    return create_voice_clone(str(audio), f"tg-{chat_id}-{language}")


def step_delete_voice(voice_id: str) -> None:
    """Старый клон долой — на тарифе лимит числа голосов в ElevenLabs."""
    from reels_factory.tts import delete_voice

    delete_voice(voice_id)


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
    tts["model_id"] = tts_model_for_language(language)
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
    montage: bool = True,
) -> BuildJob:
    """Подготовить immutable scenario/config и лишь затем показать job worker.

    ``montage=False`` — ролик собирается одним проходом HeyGen без монтажного
    слоя (edit_plan, B-roll, субтитры, Revideo). Флаг зашивается в snapshot job.
    """
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
                montage
                and avatar_islands_enabled(profile_for_estimate)
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
        master_audio = dict(config.get("master_audio") or {})
        master_audio["enabled"] = True
        # Bot jobs обязаны пройти human audio review. Ручные/legacy make
        # сохраняют прежний контракт, пока этот flag отсутствует.
        master_audio["review_required"] = True
        config["master_audio"] = master_audio
        tts = dict(config.get("tts") or {})
        tts["language_code"] = language
        # Модель озвучки выбирается по языку: ru -> multilingual v2, kk -> v3
        # (v2 не поддерживает казахский). Пишем в snapshot, чтобы модель попала
        # в детерминированный cache_key/audio_manifest.
        tts["model_id"] = tts_model_for_language(language)
        config["tts"] = tts
        # Монтаж/без монтажа фиксируется в immutable snapshot: pipeline.run_make
        # читает config["montage"] и выбирает полный путь либо один проход HeyGen.
        config["montage"] = bool(montage)
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
        return store.enqueue_prepared(
            chat_id,
            job_id=job_id,
            workdir=workdir,
            initial_status="audio_queued",
            initial_stage="audio_preview",
        )
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


def _job_meter(chat_id: int, job_id: str):
    """Meter preview-TTS тем же ledger/job_id, что и будущий render subprocess."""
    from reels_factory.billing import JobMeter

    billing = _billing()
    if not billing["enabled"]:
        return None
    return JobMeter(
        _ledger(),
        chat_id=chat_id,
        job_id=job_id,
        rates=billing["rates"],
        markup=billing["markup"],
    )


def run_audio_preview(chat_id: int, workdir: Path) -> dict:
    """Сделать только ElevenLabs master audio, не вызывая HeyGen/render."""
    from reels_factory.master_audio import build_master_audio

    workdir = Path(workdir)
    scenario = json.loads(
        (workdir / "scenario.json").read_text(encoding="utf-8")
    )
    config = load_config(workdir / "build-config.yaml")
    artifact_dir = workdir / "audio" / "tts"
    meter = _job_meter(chat_id, workdir.name)
    try:
        artifacts = build_master_audio(
            scenario,
            config,
            artifact_dir,
            voice_id=config.get("voice_id"),
            meter=(meter.elevenlabs if meter is not None else None),
        )
    except Exception as exc:
        return {
            "ok": False,
            "stage": "audio_preview",
            "error": str(exc)[:500],
        }
    return {
        "ok": True,
        "stage": "audio_review",
        "audio": str(artifacts.mp3),
        "duration_seconds": artifacts.manifest.get("duration_seconds"),
        "input_sha256": artifacts.canonical.get("text_sha256"),
    }


def approve_tts_audio(workdir: Path) -> dict:
    from reels_factory.master_audio import approve_master_audio

    workdir = Path(workdir)
    return approve_master_audio(
        workdir,
        workdir / "audio" / "tts",
        source="elevenlabs_approved",
    )


def prepare_user_audio(workdir: Path, source_audio: Path) -> dict:
    """Превратить Telegram voice в утверждённый master текущей immutable job."""
    from reels_factory.master_audio import (
        approve_master_audio,
        build_user_master_audio,
    )

    workdir = Path(workdir)
    scenario = json.loads(
        (workdir / "scenario.json").read_text(encoding="utf-8")
    )
    config = load_config(workdir / "build-config.yaml")
    artifact_dir = workdir / "audio" / "user"
    artifacts = build_user_master_audio(
        scenario,
        config,
        artifact_dir,
        source_audio,
    )
    approval = approve_master_audio(
        workdir,
        artifact_dir,
        source="telegram_user_audio",
    )
    return {
        "ok": True,
        "audio": str(artifacts.wav),
        "approval": approval,
        "duration_seconds": artifacts.manifest.get("duration_seconds"),
        "transcript_match_ratio":
            artifacts.manifest.get("transcript_match_ratio"),
    }


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
        [InlineKeyboardButton("Сгенерировать сценарий", callback_data="mode:raw")],
    ])


def _kb_language(selected: str | None = None):
    """Выбранный язык помечаем галочкой прямо на кнопке и добавляем движение
    дальше: отдельное сообщение «язык такой-то» для этого не нужно."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    rows = []
    for code, label in (("ru", "🇷🇺 Русский"), ("kk", "🇰🇿 Қазақша")):
        mark = " ✅" if code == selected else ""
        rows.append([InlineKeyboardButton(
            f"{label}{mark}", callback_data=f"reel_language:{code}"
        )])
    if selected:
        rows.append([InlineKeyboardButton("Продолжить →", callback_data="stage:next")])
    return InlineKeyboardMarkup(rows)


def _kb_gender(selected: str | None = None):
    """Та же механика, что у языка: галочка на выбранном и шаг дальше."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    rows = []
    for code in GENDERS:
        mark = " ✅" if code == selected else ""
        rows.append([InlineKeyboardButton(
            f"{GENDER_LABELS[code]}{mark}", callback_data=f"reel_gender:{code}"
        )])
    if selected:
        rows.append([InlineKeyboardButton("Продолжить →", callback_data="stage:next")])
    return InlineKeyboardMarkup(rows)


async def _edit_or_reply(msg, text: str, markup=None):
    """Заменить экран на месте, а не плодить сообщения.

    edit_text недоступен, когда сообщение прислал не бот (человек написал
    текстом) и падает, если текст с разметкой не изменились — в обоих случаях
    честнее прислать новое сообщение, чем потерять экран.
    """
    edit = getattr(msg, "edit_text", None)
    if edit is not None:
        try:
            await edit(text, reply_markup=markup)
            return
        except Exception:
            pass
    await msg.reply_text(text, reply_markup=markup)


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


def _kb_ideas(n: int):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(str(i + 1), callback_data=f"idea:{i}")]
         for i in range(n)] +
        [[InlineKeyboardButton("← Назад", callback_data="back")]])




def _kb_review():
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Утвердить", callback_data="ok")],
        [InlineKeyboardButton("Изменить текст", callback_data="edit")],
        [InlineKeyboardButton("← Назад", callback_data="back")],
    ])


def _kb_ready():
    """Монтаж пока заглушка: кнопка есть, но она собирает пожелания, а не ролик."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🎥 Создать ролик (аватар без монтажа)", callback_data="build:plain"
        )],
        [InlineKeyboardButton(
            "🎬 С монтажом — в разработке", callback_data="build:montage"
        )],
        [InlineKeyboardButton("← Назад", callback_data="back")],
    ])


def _kb_wish():
    """Экран пожелания: писать необязательно."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Пропустить", callback_data="wish:skip")],
    ])


def _kb_audio_review(job_id: str):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "✅ Аудио подходит",
            callback_data=f"audio_ok:{job_id}",
        )],
        [InlineKeyboardButton(
            "🎙 Не подходит — запишу сам(а)",
            callback_data=f"audio_self:{job_id}",
        )],
    ])


def _kb_final_audio(job_id: str):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "📄 Показать текст сценария",
            callback_data=f"audio_script:{job_id}",
        )
    ]])


def _kb_price(enough: bool):
    """Экран цены. Хватает баланса — одна кнопка «Поехали»; не хватает —
    кнопки пополнения Tribute и проверка баланса, чтобы вернуться сюда же."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    if enough:
        rows = [[InlineKeyboardButton("🚀 Поехали", callback_data="pay:go")]]
    else:
        rows = [
            [InlineKeyboardButton(
                "💳 Пополнить баланс", callback_data="topup:start"
            )],
            [InlineKeyboardButton("Проверить баланс", callback_data="pay:check")],
        ]
    rows.append([InlineKeyboardButton("← Назад", callback_data="back")])
    return InlineKeyboardMarkup(rows)


def _kb_done():
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([[InlineKeyboardButton("Новый ролик", callback_data="new_reel")]])


async def _show_start(msg, chat_id: int, s: dict, session_builder=fresh_session):
    """Начало разговора: язык -> фото -> голос -> выбор пути. Всё бесплатно."""
    next_session = session_builder(s)
    cycle = int((s or {}).get("cycle") or 0)
    if session_builder is not _keep_all:
        # /start и «Новый ролик» — новый цикл: иначе второй ролик человека
        # смешается с первым и воронка покажет «оплат больше, чем стартов».
        # Возврат на стартовый экран кнопкой «Назад» новым заходом не считаем.
        cycle += 1
        next_session["cycle"] = cycle
        # detail = метка источника (реферальная ссылка): воронку можно резать
        # по источникам прямо из events, не поднимая файлы сессий.
        _track(chat_id, next_session, "start", next_session.get("source"))
    else:
        next_session["cycle"] = cycle or 1
    if not _reel_language(next_session, required=False):
        next_session["step"] = CHOOSING_LANGUAGE
        save_session(chat_id, next_session)
        if session_builder is fresh_session or not next_session.get("photo"):
            # Приветствие с примером готового ролика: человек сначала ВИДИТ
            # продукт и честные условия, а уже потом отдаёт фото и голос.
            # Уходит на каждый /start, включая повторные (команда — явный
            # «покажи сначала»), и любому совсем новому чату. А вот кнопка
            # «Новый ролик» (loop_session) промо не повторяет: клиент между
            # роликами и так всё видел.
            if not await _reply_media_asset(
                msg, "video", DEMO_EXAMPLE_MP4, HELLO
            ):
                await msg.reply_text(HELLO)
        await msg.reply_text(ASK_LANGUAGE, reply_markup=_kb_language())
        return
    save_session(chat_id, next_session)
    await _profile_stage(msg, chat_id, next_session)


async def _show_language_choice(msg, chat_id: int, s: dict):
    s["step"] = CHOOSING_LANGUAGE
    s.pop("language", None)
    s.pop("scenario", None)
    s.pop("ideas", None)
    s.pop("material_mode", None)
    # Материал написан на прежнем языке — держать его в сводке нового ролика
    # значит показывать человеку «✅ принято» о том, что уже не подходит.
    s.pop("material_text", None)
    save_session(chat_id, s)
    await msg.reply_text(ASK_LANGUAGE, reply_markup=_kb_language())


async def _select_reel_language(msg, chat_id: int, s: dict, language: str):
    """Язык отмечается галочкой в том же сообщении.

    Новичку сразу показываем следующий шаг — он всё равно ещё ничего не дал;
    у повторного экран остаётся на месте, чтобы он мог передумать и уйти
    вперёд кнопкой, а не получить ещё одно сообщение.
    """
    language = normalize_profile_language(language)
    s["language"] = language
    s["step"] = VIEWING_STAGE
    s["stage"] = STAGE_LANGUAGE
    _track(chat_id, s, "stage:language", language)
    _activate_language_voice(s, language)
    save_session(chat_id, s)
    await _edit_or_reply(msg, ASK_LANGUAGE, _kb_language(language))
    if not _stage_filled(s, STAGE_GENDER):
        await _next_stage(msg, chat_id, s, STAGE_LANGUAGE)


async def _show_gender_choice(msg, chat_id: int, s: dict):
    s["step"] = CHOOSING_GENDER
    s.pop("gender", None)
    save_session(chat_id, s)
    await msg.reply_text(ASK_GENDER, reply_markup=_kb_gender())


async def _select_reel_gender(msg, chat_id: int, s: dict, gender: str):
    """Пол отмечается галочкой в том же сообщении — как язык.

    Дальше сам не уводим: пол выбирают перед фото, а фото у постоянного
    пользователя уже есть, и лишний прыжок мимо экрана только сбивает.
    """
    if gender not in GENDERS:
        return
    s["gender"] = gender
    s["step"] = VIEWING_STAGE
    s["stage"] = STAGE_GENDER
    _track(chat_id, s, "stage:gender", gender)
    # Сценарий пишется под род ведущего: сменили пол — прежний текст уже не
    # про этого человека.
    s.pop("scenario", None)
    s.pop("ideas", None)
    save_session(chat_id, s)
    await _edit_or_reply(msg, ASK_GENDER, _kb_gender(gender))
    if not _stage_filled(s, STAGE_PHOTO):
        await _next_stage(msg, chat_id, s, STAGE_GENDER)


async def _ask(msg, chat_id: int, s: dict, step: str, text: str):
    """Экран ожидания ввода — с кнопкой «Назад»."""
    s["step"] = step
    save_session(chat_id, s)
    await msg.reply_text(text, reply_markup=_kb_back())


def _asset_ids_path() -> Path:
    return WORK_ROOT / "bot" / _ASSET_FILE_ID_CACHE


def _load_asset_ids() -> dict:
    try:
        data = json.loads(_asset_ids_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_asset_id(key: str, file_id: str) -> None:
    path = _asset_ids_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    ids = _load_asset_ids()
    ids[key] = file_id
    path.write_text(json.dumps(ids, ensure_ascii=False), encoding="utf-8")


async def _reply_media_asset(msg, kind: str, path: Path, caption: str,
                             markup=None) -> bool:
    """Отправить ассет онбординга (пример ролика/фото) с кэшем file_id.

    Первый раз файл заливается с диска, дальше летит мгновенный file_id.
    False — ассета нет и отправить нечем: экран уходит просто текстом,
    разговор из-за картинки не падает.
    """
    key = f"{kind}:{path.name}"
    send = getattr(msg, "reply_video" if kind == "video" else "reply_photo",
                   None)
    if send is None:
        # Сообщение без медиа-методов (например, урезанный дубль в тестах) —
        # экран уходит текстом.
        return False
    cached = _load_asset_ids().get(key)
    if cached:
        try:
            await send(cached, caption=caption, reply_markup=markup)
            return True
        except Exception as e:
            # file_id живёт в рамках токена бота: сменили бота — перезальём.
            log.warning("ассет %s не ушёл по file_id: %s", key, e)
    if not path.exists():
        return False
    try:
        with path.open("rb") as fh:
            sent = await send(fh, caption=caption, reply_markup=markup)
    except Exception as e:
        log.warning("ассет %s не загрузился: %s", key, e)
        return False
    try:
        media = sent.video if kind == "video" else (
            sent.photo[-1] if sent.photo else None)
        file_id = getattr(media, "file_id", None)
        if file_id:
            _save_asset_id(key, file_id)
    except Exception:
        pass
    return True


async def _ask_voice(msg, chat_id: int, s: dict, language: str):
    """Экран записи голоса: к инструкции добавлен образец для чтения."""
    s["step"] = WAIT_VOICE
    save_session(chat_id, s)
    await msg.reply_text(
        _ask_voice_text(language), reply_markup=_kb_voice_sample()
    )


async def _ask_photo_screen(msg, chat_id: int, s: dict):
    """Экран фото: образец правильного кадра и инструкция одной карточкой."""
    s["step"] = WAIT_PHOTO
    save_session(chat_id, s)
    if not await _reply_media_asset(
        msg, "photo", PHOTO_EXAMPLE_PNG, ASK_PHOTO, _kb_back()
    ):
        await msg.reply_text(ASK_PHOTO, reply_markup=_kb_back())


async def _profile_stage(msg, chat_id: int, s: dict):
    """Первый незаполненный этап — или просмотр первого, если всё уже есть."""
    for stage in STAGE_ORDER:
        if not _stage_filled(s, stage):
            await _ask_stage(msg, chat_id, s, stage)
            return
    await _show_stage(msg, chat_id, s, STAGE_ORDER[0])


def _stage_filled(s: dict, stage: str) -> bool:
    """Данные этапа уже собраны — переспрашивать их незачем."""
    if stage == STAGE_LANGUAGE:
        return bool(_reel_language(s, required=False))
    if stage == STAGE_GENDER:
        return (s or {}).get("gender") in GENDERS
    if stage == STAGE_PHOTO:
        return bool(s.get("photo"))
    if stage == STAGE_VOICE:
        return _has_voice_material(s, _reel_language(s))
    return bool(str(s.get("material_text") or "").strip())


def _stage_summary(s: dict, stage: str) -> str:
    """Короткая сводка пройденного этапа: что именно человек уже дал."""
    if stage == STAGE_LANGUAGE:
        return f"✅ Язык ролика: {language_label(_reel_language(s))}"
    if stage == STAGE_GENDER:
        return f"✅ Пол аватара: {GENDER_LABELS[s['gender']].lower()}"
    if stage == STAGE_PHOTO:
        return "✅ Фото загружено."
    if stage == STAGE_VOICE:
        language = _reel_language(s)
        if _voice_for_language(s, language):
            return f"✅ Голос для языка {language_label(language)} уже создан."
        return "✅ Запись голоса принята."
    material = str(s.get("material_text") or "").strip()
    excerpt = material[:MATERIAL_EXCERPT_CHARS]
    if len(material) > MATERIAL_EXCERPT_CHARS:
        excerpt += "…"
    return f"✅ Материал принят:\n\n«{excerpt}»"


def _kb_stage(stage: str):
    """Пройденный этап: вперёд, назад и явная замена. Присланное без
    «Изменить» прежние данные не затирает."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    nav = []
    if STAGE_ORDER.index(stage) > 0:
        nav.append(InlineKeyboardButton("← Назад", callback_data="stage:prev"))
    nav.append(InlineKeyboardButton("Вперёд →", callback_data="stage:next"))
    return InlineKeyboardMarkup([
        nav,
        [InlineKeyboardButton("✏️ Изменить", callback_data="stage:edit")],
    ])


def _current_stage(s: dict) -> str:
    """Этап, экран которого сейчас перед человеком. Кнопка из истории чата
    может прийти когда угодно — тогда честнее отдать первый этап, чем упасть."""
    stage = (s or {}).get("stage")
    return stage if stage in STAGE_ORDER else STAGE_ORDER[0]


async def _show_stage(msg, chat_id: int, s: dict, stage: str):
    """Экран этапа: заполненный — сводка с навигацией, пустой — ввод."""
    if not _stage_filled(s, stage):
        await _ask_stage(msg, chat_id, s, stage)
        return
    s["step"] = VIEWING_STAGE
    s["stage"] = stage
    save_session(chat_id, s)
    # Этап пройден и на готовых данных: у постоянного пользователя фото и
    # голос остались с прошлого ролика, и без этой записи воронка проваливалась
    # на них, а следующий шаг оказывался «шире» предыдущего.
    _track(chat_id, s, f"stage:{stage}", "reused")
    if stage == STAGE_LANGUAGE:
        # У языка выбор и есть содержимое: те же кнопки с галочкой, менять
        # его отдельной кнопкой «Изменить» незачем.
        await msg.reply_text(
            ASK_LANGUAGE, reply_markup=_kb_language(_reel_language(s))
        )
        return
    if stage == STAGE_GENDER:
        await msg.reply_text(ASK_GENDER, reply_markup=_kb_gender(s.get("gender")))
        return
    if stage == STAGE_PHOTO:
        # Показываем само сохранённое фото: голое «✅ Фото загружено» рядом с
        # примером читалось как «бот засчитал пример за моё фото».
        raw = (s.get("photo") or {}).get("file")
        photo_path = Path(str(raw)) if raw else None
        reply_photo = getattr(msg, "reply_photo", None)
        if photo_path and photo_path.exists() and reply_photo is not None:
            try:
                with photo_path.open("rb") as fh:
                    await reply_photo(
                        fh,
                        caption=PHOTO_SUMMARY_CAPTION,
                        reply_markup=_kb_stage(stage),
                    )
                return
            except Exception as e:
                log.warning("сохранённое фото чата %s не ушло: %s", chat_id, e)
    await msg.reply_text(_stage_summary(s, stage), reply_markup=_kb_stage(stage))


async def _ask_stage(msg, chat_id: int, s: dict, stage: str):
    """Экран ввода данных этапа."""
    if stage == STAGE_LANGUAGE:
        await _show_language_choice(msg, chat_id, s)
    elif stage == STAGE_GENDER:
        await _show_gender_choice(msg, chat_id, s)
    elif stage == STAGE_PHOTO:
        await _ask_photo_screen(msg, chat_id, s)
    elif stage == STAGE_VOICE:
        await _ask_voice(msg, chat_id, s, _reel_language(s))
    elif s.get("material_mode"):
        await _ask_material(msg, chat_id, s, s["material_mode"])
    else:
        await _choose_path_stage(msg, chat_id, s)


async def _next_stage(msg, chat_id: int, s: dict, stage: str):
    """Вперёд: следующий этап, а после последнего — экран цены."""
    idx = STAGE_ORDER.index(stage)
    for nxt in STAGE_ORDER[idx + 1:]:
        await _show_stage(msg, chat_id, s, nxt)
        return
    await _show_price(msg, chat_id, s)


async def _prev_stage(msg, chat_id: int, s: dict, stage: str):
    """Назад: предыдущий этап; с первого уходить некуда."""
    idx = STAGE_ORDER.index(stage)
    await _show_stage(msg, chat_id, s, STAGE_ORDER[max(idx - 1, 0)])


async def _ask_material(msg, chat_id: int, s: dict, mode: str):
    """Экран ввода материала в выбранном режиме."""
    if mode == "raw":
        await _ask(msg, chat_id, s, WAIT_RAW, ASK_RAW)
    else:
        await _ask(msg, chat_id, s, WAIT_TEXT, ASK_TEXT)


async def _choose_path_stage(msg, chat_id: int, s: dict):
    """Выбор пути открыт, только когда собрано всё бесплатное."""
    language = _reel_language(s)
    if not s.get("photo") or not _has_voice_material(s, language):
        await _profile_stage(msg, chat_id, s)
        return
    # Фото и запись могли остаться с прежнего захода, когда демо ещё не
    # существовало, — такой человек демо не видел. Лимиты внутри
    # _maybe_send_demo: одно демо на человека и ни одного клиентам.
    await _maybe_send_demo(msg, chat_id, s)
    s["step"] = CHOOSING
    save_session(chat_id, s)
    await msg.reply_text(ASK_PATH, reply_markup=_kb_start())


async def _pick_material_mode(msg, chat_id: int, s: dict, mode: str):
    """Выбран путь — сразу просим материал.

    Промежуточного экрана «Что используем?» больше нет: для новичка он был
    загадкой («прислать новое сырьё» вместо чего?), а замену прежнего
    материала теперь делает навигация по этапам.
    """
    language = _reel_language(s)
    if not s.get("photo") or not _has_voice_material(s, language):
        # Кнопка из истории чата или сессия прежнего порядка шагов: сначала
        # фото и голос, иначе человек упрётся в них уже после оплаты.
        await _profile_stage(msg, chat_id, s)
        return
    s["material_mode"] = mode
    save_session(chat_id, s)
    await _ask_material(msg, chat_id, s, mode)


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
    _track(chat_id, s, "scenario_shown")
    await msg.reply_text(render_scenario(s["scenario"]), reply_markup=_kb_review())


async def _show_price(msg, chat_id: int, s: dict, *, checked: bool = False):
    """Экран цены — единственная точка, где человек соглашается платить.

    До него не сделано ни одного платного вызова: фото уже в HeyGen (бесплатно),
    запись голоса лежит файлом, материал принят как есть. checked=True — человек
    вернулся сюда кнопкой после пополнения, ему нужен свежий баланс, а не
    повтор длинного текста.
    """
    billing = _billing()
    if not billing["enabled"]:
        # Биллинг выключен — спрашивать не о чем, сразу за работу.
        await _start_generation(msg, chat_id, s)
        return
    need = estimate_material_micro(s, billing)
    have = _ledger().balance(chat_id)
    s["step"] = CONFIRM_PRICE
    s["price_need"] = need
    save_session(chat_id, s)
    if not checked:
        _track(chat_id, s, "price_shown", format_usd(need))
    if have >= need:
        await msg.reply_text(
            PRICE_ENOUGH_MSG.format(need=format_usd(need), have=format_usd(have)),
            reply_markup=_kb_price(True),
        )
        return
    gap = format_usd(need - have)
    if checked:
        # Человек вернулся кнопкой: длинный текст он уже читал, ему нужны
        # только свежие цифры — и в том же сообщении, без нового экрана.
        await _edit_or_reply(
            msg,
            PRICE_STILL_SHORT_MSG.format(have=format_usd(have), gap=gap),
            _kb_price(False),
        )
        return
    await msg.reply_text(
        PRICE_SHORT_MSG.format(
            need=format_usd(need), have=format_usd(have), gap=gap
        ),
        reply_markup=_kb_price(False),
    )


async def _clone_pending_voice(chat_id: int, s: dict, language: str) -> bool:
    """Сделать клон по pending-записи, если она есть. True — рабочий голос
    языка существует (создали сейчас или был готов раньше).

    Прежний клон удаляем только после того, как новый создан и сохранён:
    упавший клон не должен оставить человека вообще без голоса. Ошибки
    ElevenLabs летят наружу — колеры сами решают, как о них говорить.
    """
    sample = _pending_voice_sample(s, language)
    if sample is None:
        return bool(_voice_for_language(s, language))
    voice_id = await asyncio.to_thread(step_voice, chat_id, sample, language)
    previous = _voice_for_language(s, language)
    voices = dict(s.get("voices") or {})
    voices[language] = voice_id
    s["voices"] = voices
    s["voice_id"] = voice_id
    s["voice_language"] = language
    pending = dict(s.get("voice_pending") or {})
    pending.pop(language, None)
    s["voice_pending"] = pending
    s.pop("pending_previous_voice", None)
    save_session(chat_id, s)
    try:
        save_client_profile(chat_id, s)
        save_session(chat_id, s)
    except Exception as e:
        log.warning("профиль клиента %s не сохранился после клона: %s", chat_id, e)
    if previous and previous != voice_id:
        try:
            await asyncio.to_thread(step_delete_voice, previous)
        except Exception as e:
            # Новый голос уже сохранён. Уборка старого клона — best effort,
            # из-за неё человек ждать не должен.
            log.warning("не удалось удалить старый клон голоса %s: %s", previous, e)
    return True


async def _ensure_voice_clone(msg, chat_id: int, s: dict) -> bool:
    """Голос по записи с разговором об ошибках — путь платной генерации."""
    language = _reel_language(s)
    if _pending_voice_sample(s, language) is None:
        if _voice_for_language(s, language):
            return True
        await _ask_voice(msg, chat_id, s, language)
        return False
    await msg.reply_text(CLONING_VOICE_MSG)
    try:
        return await _clone_pending_voice(chat_id, s, language)
    except Exception as e:
        _track(chat_id, s, "error:voice_clone", str(e)[:120])
        await msg.reply_text(f"Голос не принялся: {str(e)[:200]}")
        await _ask_voice(msg, chat_id, s, language)
        return False


def _demo_key(s: dict, language: str) -> str | None:
    """Отпечаток входа демо: то же фото и та же запись — тот же результат,
    генерить заново нечего. Замена любого из них даёт новый ключ."""
    photo = ((s or {}).get("photo") or {}).get("asset_id")
    sample = _voice_sample_for_language(s, language)
    if not photo or sample is None:
        return None
    try:
        sample_sha1 = hashlib.sha1(sample.read_bytes()).hexdigest()
    except OSError:
        return None
    return hashlib.sha1(
        f"{photo}|{language}|{sample_sha1}".encode("utf-8")
    ).hexdigest()[:16]


async def _maybe_send_demo(msg, chat_id: int, s: dict) -> None:
    """Бесплатное демо двойника: 2-3 секунды «Это я. Твой аватар!».

    Живёт между голосом и материалом — человек впервые видит своё лицо и
    голос ДО разговора о деньгах. Ради демо клон голоса делается раньше
    экрана цены; для платной части он потом переиспользуется как готовый.
    Демо — подарок, а не ворота: любая ошибка здесь молча пропускает шаг,
    разговор продолжается без демо.
    """
    language = _reel_language(s)
    key = _demo_key(s, language)
    if key is None or (s.get("demo") or {}).get("key") == key:
        return
    if s.get("demo") or _job_store().latest_for_chat(chat_id) is not None:
        # Демо — только для тех, кто сервисом ещё не пользовался: одно на
        # человека, и ни одного тому, кто уже заказывал ролик. Клиент и так
        # знает, как выглядит его аватар, а каждая генерация стоит денег.
        return
    await msg.reply_text(DEMO_BUILDING_MSG)
    _track(chat_id, s, "demo_started")
    photo = (s.get("photo") or {}).get("asset_id")
    try:
        if not await _clone_pending_voice(chat_id, s, language):
            return
        mp4 = await asyncio.to_thread(
            step_demo, chat_id, photo, _voice_for_language(s, language),
            language,
        )
    except Exception as e:
        # Клон остаётся pending и будет сделан заново на платном пути —
        # человека ошибкой демо не останавливаем.
        _track(chat_id, s, "error:demo", str(e)[:120])
        log.warning("демо чата %s не собралось: %s", chat_id, e)
        return
    s["demo"] = {"key": key, "file": str(mp4)}
    save_session(chat_id, s)
    try:
        with Path(mp4).open("rb") as fh:
            await msg.reply_video(fh, caption=DEMO_READY_MSG)
    except Exception as e:
        _track(chat_id, s, "error:demo_send", str(e)[:120])
        log.warning("демо чата %s не отправилось: %s", chat_id, e)
        return
    _track(chat_id, s, "demo_sent")


async def _start_paid_part(msg, chat_id: int, s: dict):
    """«Поехали» с экрана цены. Кнопка живёт в истории чата, поэтому баланс
    сверяем заново: между показом экрана и нажатием могло пройти что угодно."""
    if s.get("step") not in (CONFIRM_PRICE, VIEWING_STAGE):
        # Тап по старому «Продолжить» после готового ролика заново запустил бы
        # платную генерацию по прежнему материалу. Отправляем на текущий экран.
        await _reshow(msg, chat_id, s)
        return
    billing = _billing()
    if billing["enabled"]:
        need = estimate_material_micro(s, billing)
        if _ledger().balance(chat_id) < need:
            await _show_price(msg, chat_id, s)
            return
    # Шаг воронки — «денег хватило», а не «оплатил»: у постоянного клиента
    # баланс уже есть, и он идёт в работу без единого платежа.
    _track(chat_id, s, "balance_ok")
    await _start_generation(msg, chat_id, s)


async def _start_generation(msg, chat_id: int, s: dict):
    """Платная часть: голос по записи, затем сценарий Клодом."""
    language = _reel_language(s)
    _track(chat_id, s, "generation_started")
    if not await _ensure_voice_clone(msg, chat_id, s):
        return
    material = str(s.get("material_text") or "")
    if not material.strip():
        await _ask_material(msg, chat_id, s, s.get("material_mode", "text"))
        return
    await msg.reply_text(WORKING)
    if s.get("material_mode") == "raw":
        try:
            ideas = await asyncio.to_thread(step_ideas, chat_id, material, language)
        except (ScenarioError, RuntimeError) as e:
            _track(chat_id, s, "error:scenario", str(e)[:120])
            await msg.reply_text(f"Не получилось вытащить идеи: {e}")
            return
        s["ideas"] = ideas
        await _show_ideas(msg, chat_id, s)
        return
    try:
        sc = await asyncio.to_thread(
            step_verbatim, chat_id, clean_input(material), language
        )
    except (ScenarioError, RuntimeError) as e:
        _track(chat_id, s, "error:scenario", str(e)[:120])
        await msg.reply_text(f"Не получилось разобрать текст: {e}")
        return
    s["scenario"] = sc
    await _show_review(msg, chat_id, s)


async def _show_ready_screen(msg, chat_id: int, s: dict):
    s["step"] = READY
    save_session(chat_id, s)
    await msg.reply_text(READY_MSG, reply_markup=_kb_ready())


async def _ready_stage(msg, chat_id: int, s: dict):
    """Сценарий утверждён, фото и голос собраны раньше — остаётся сборка."""
    s["step"] = READY
    save_session(chat_id, s)
    try:
        save_client_profile(chat_id, s)
        save_session(chat_id, s)
    except Exception as e:
        log.warning("профиль клиента %s не сохранился: %s", chat_id, e)
    await _show_ready_screen(msg, chat_id, s)


async def _ask_wish(msg, chat_id: int, s: dict, topic: str, text: str):
    """Функция ещё не готова: вместо отказа собираем, чего от неё ждут."""
    s["step"] = WAIT_WISH
    s["wish_topic"] = topic
    save_session(chat_id, s)
    await msg.reply_text(text, reply_markup=_kb_wish())


async def _reshow(msg, chat_id: int, s: dict):
    """Показать экран текущего шага заново.

    Человек пишет текстом там, где бот ждёт кнопку — чаще всего потому, что
    кнопки уехали вверх по переписке. Повторить экран полезнее, чем отписаться
    «нажмите /start».
    """
    step = s.get("step", CHOOSING)
    if not _reel_language(s, required=False):
        # Разговора ещё не было (или он сброшен) — начинаем с начала.
        await _show_start(msg, chat_id, s, _keep_all)
        return
    if step == CHOOSING:
        await _choose_path_stage(msg, chat_id, s)
    elif step == VIEWING_STAGE:
        # Присланное на экране пройденного этапа прежние данные не затирает:
        # замена — только через «Изменить».
        await _show_stage(msg, chat_id, s, _current_stage(s))
    elif step == CONFIRM_PRICE:
        await _show_price(msg, chat_id, s, checked=True)
    elif step == CHOOSING_IDEA and s.get("ideas"):
        await _show_ideas(msg, chat_id, s)
    elif step == REVIEW and s.get("scenario"):
        await _show_review(msg, chat_id, s)
    elif step == READY and s.get("scenario"):
        await _show_ready_screen(msg, chat_id, s)
    elif step == DONE:
        await msg.reply_text(DONE_MSG, reply_markup=_kb_done())
    elif step == BUILD_FAILED:
        await msg.reply_text(BUILD_FAILED_HINT, reply_markup=_kb_done())
    else:
        # Шаги внутри сборки: там своё расписание, звать заново нечего.
        await msg.reply_text(NOT_NOW)


async def _go_back(msg, chat_id: int, s: dict):
    """Шаг назад — на предыдущий экран, ничего не теряя."""
    step = s.get("step", CHOOSING)
    if step in (WAIT_EDIT, READY):
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
    elif step == CONFIRM_PRICE:
        # Материал уже принят: возвращаем к его сводке, а не к пустому вводу.
        # Оттуда «Вперёд →» вернёт сюда же, ничего не пересылая.
        await _show_stage(msg, chat_id, s, STAGE_MATERIAL)
    elif step == VIEWING_STAGE:
        await _prev_stage(msg, chat_id, s, _current_stage(s))
    elif step in (WAIT_TEXT, WAIT_RAW):
        # Пришли сюда по «Изменить» — возвращаем к прежнему материалу, а не
        # к выбору пути: иначе замена превращается в путь без отмены.
        if _stage_filled(s, STAGE_MATERIAL):
            await _show_stage(msg, chat_id, s, STAGE_MATERIAL)
        else:
            await _choose_path_stage(msg, chat_id, s)
    elif step == CHOOSING:
        await _show_stage(msg, chat_id, s, STAGE_VOICE)
    elif step == WAIT_VOICE:
        await _show_stage(
            msg, chat_id, s,
            STAGE_VOICE if _stage_filled(s, STAGE_VOICE) else STAGE_PHOTO,
        )
    elif step == WAIT_PHOTO:
        await _show_stage(
            msg, chat_id, s,
            STAGE_PHOTO if _stage_filled(s, STAGE_PHOTO) else STAGE_GENDER,
        )
    elif step == CHOOSING_GENDER:
        await _show_stage(msg, chat_id, s, STAGE_LANGUAGE)
    else:  # первый заход: дальше только выбор языка
        await _show_language_choice(msg, chat_id, s)


async def _ready_for_new_reel(msg, chat_id: int) -> bool:
    """Можно ли начинать новый ролик?

    Если предыдущий стоит на паузе и ждёт решения пользователя (озвучка на
    подтверждении, ожидание голосового, ещё не начатый синтез) — тихо
    отменяем его и разрешаем старт. Если идёт реальная работа (синтез/рендер)
    — блокируем, её нельзя бросать на полпути. CAS-отмена сама отсекает гонку с
    worker: если он только что взял job, отмена не пройдёт и мы честно блокируем.
    """
    job = _job_store().active_for_chat(chat_id)
    if job is None:
        return True
    cancelled = _job_store().cancel_waiting(job.job_id)
    if cancelled is None:
        await msg.reply_text(BUSY_MSG)
        return False
    await msg.reply_text(CANCELLED_PENDING_MSG)
    return True


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
    if not await _ready_for_new_reel(update.message, chat_id):
        return
    await _show_start(update.message, chat_id, session)


async def cmd_new(update, context):
    """/new — новый язык и сценарий; фото и языковые голоса остаются."""
    chat_id = update.effective_chat.id
    if not await _ready_for_new_reel(update.message, chat_id):
        return
    await _show_start(update.message, chat_id, load_session(chat_id), loop_session)


_JOB_STATUS_RU = {
    "audio_queued": "озвучка ждёт своей очереди",
    "audio_running": "создаётся озвучка",
    "awaiting_audio_approval": "озвучка ждёт вашего подтверждения",
    "awaiting_user_audio": "ждёт ваше голосовое",
    "user_audio_processing": "проверяется ваше голосовое",
    "queued": "в очереди на генерацию видео",
    "running": "собирается видео",
    "completed": "готов и отправлен",
    "qa_failed": "остановлен проверкой качества",
    "failed": "сборка завершилась ошибкой",
    "interrupted": "остановлен перезапуском сервиса",
    "delivery_failed": "готов, но не отправлен в Telegram",
    "cancelled": "отменён — начат новый ролик",
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


def _callback_job(chat_id: int, session: dict, callback_data: str) -> BuildJob | None:
    job_id = callback_data.split(":", 1)[1] if ":" in callback_data else ""
    if not job_id or session.get("current_job_id") != job_id:
        return None
    job = _job_store().get(job_id)
    if job is None or job.chat_id != int(chat_id):
        return None
    return job


def _scenario_speech(job: BuildJob) -> str:
    scenario = json.loads(
        (job.workdir / "scenario.json").read_text(encoding="utf-8")
    )
    return "\n\n".join(
        str(block.get("speech") or "").strip()
        for block in scenario.get("blocks") or []
        if str(block.get("speech") or "").strip()
    )


async def on_button(update, context):
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    s = load_session(chat_id)
    data = q.data

    if data.startswith("reel_gender:"):
        await _select_reel_gender(q.message, chat_id, s, data.split(":", 1)[1])
    elif data.startswith("reel_language:"):
        value = data.split(":", 1)[1]
        await _select_reel_language(q.message, chat_id, s, value)
    elif data == "mismatch:change":
        await _show_language_choice(q.message, chat_id, s)
    elif data == "mismatch:retry":
        await _ask(q.message, chat_id, s, WAIT_TEXT, ASK_TEXT)
    elif data == "mode:text":
        await _pick_material_mode(q.message, chat_id, s, "text")
    elif data == "mode:raw":
        await _pick_material_mode(q.message, chat_id, s, "raw")
    elif data == "back":
        await _go_back(q.message, chat_id, s)
    elif data in ("material:new", "material:edit"):
        # Кнопки убранного экрана «Что используем?» — из истории чата.
        await _ask_material(q.message, chat_id, s, s.get("material_mode", "text"))
    elif data == "topup:start":
        _track(chat_id, s, "topup_opened")
        await _show_currency_choice(q.message, chat_id, s)
    elif data == "topup:cancel":
        # Возврат к прежним кнопкам того же сообщения, без новых экранов.
        text = q.message.text or topup_text(None, _ledger().balance(chat_id))
        await _edit_or_reply(
            q.message, text,
            _kb_price(False) if s.get("step") == CONFIRM_PRICE
            else _kb_topup_entry(),
        )
    elif data.startswith("topup:cur:"):
        currency = data.rsplit(":", 1)[1]
        if currency not in TOPUP_PRESETS:
            await q.message.reply_text(NOT_NOW)
            return
        await _show_amounts(q.message, chat_id, s, currency)
    elif data.startswith("topup:amt:"):
        _, _, currency, amount = data.split(":")
        if currency not in TOPUP_PRESETS or not amount.isdigit():
            await q.message.reply_text(NOT_NOW)
            return
        await _create_topup_order(q.message, chat_id, s, currency, int(amount))
    elif data == "topup:check":
        await _check_topup_order(q.message, chat_id, s)
    elif data == "pay:go":
        # Тот же случай: платить за второй ролик, пока идёт первый, нельзя —
        # это две параллельные генерации на один профиль.
        if _job_store().active_for_chat(chat_id):
            await q.message.reply_text(BUSY_MSG)
            return
        await _start_paid_part(q.message, chat_id, s)
    elif data == "pay:check":
        # Возврат после пополнения: показываем тот же экран со свежим балансом.
        await _show_price(q.message, chat_id, s, checked=True)
    elif data.startswith("idea:"):
        idea = (s.get("ideas") or [])[int(data.split(":")[1])]
        # Экран цены человек уже прошёл, деньги на ролик проверены там. Здесь
        # ловим только уход в минус: между экраном и выбором идеи баланс мог
        # просесть на самих идеях.
        if await _blocked_by_negative_balance(q.message, chat_id):
            return
        await q.message.reply_text(WORKING)
        try:
            sc = await asyncio.to_thread(
                step_scenario, chat_id, idea, _reel_language(s), s.get("gender")
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
        _track(chat_id, s, "scenario_approved")
        await q.message.reply_text(APPROVED_MSG)
        await _ready_stage(q.message, chat_id, s)
    elif data.startswith("stage:"):
        # Кнопки живут в истории чата вечно: тап по старому экрану посреди
        # уже оплаченной сборки не должен уводить разговор с её этапа.
        if _job_store().active_for_chat(chat_id):
            await q.message.reply_text(BUSY_MSG)
            return
        if s.get("step") in (DONE, BUILD_FAILED):
            # Ролик уже сделан: навигация по его этапам вела бы к экрану цены
            # и оттуда — к повторной платной генерации по тому же материалу.
            await _reshow(q.message, chat_id, s)
            return
        stage = _current_stage(s)
        if data == "stage:next":
            await _next_stage(q.message, chat_id, s, stage)
        elif data == "stage:prev":
            await _prev_stage(q.message, chat_id, s, stage)
        else:
            await _ask_stage(q.message, chat_id, s, stage)
    elif data in ("profile:keep", "photo:old", "voice:old"):
        # Кнопки прежних версий экрана: живут в истории чата вечно.
        await _choose_path_stage(q.message, chat_id, s)
    elif data in ("profile:photo", "photo:new"):
        await _ask_photo_screen(q.message, chat_id, s)
    elif data in ("profile:voice", "voice:new"):
        await _ask_voice(q.message, chat_id, s, _reel_language(s))
    elif data == "voice_sample":
        # Образец идёт отдельным сообщением: так его удобно держать на экране,
        # пока человек читает вслух.
        language = _reel_language(s)
        await q.message.reply_text(
            VOICE_SAMPLE_TEXTS.get(language) or VOICE_SAMPLE_TEXTS["ru"]
        )
    elif data.startswith("audio_ok:"):
        job = _callback_job(chat_id, s, data)
        if job is None or job.status != "awaiting_audio_approval":
            await q.message.reply_text(AUDIO_ACTION_STALE)
            return
        try:
            await asyncio.to_thread(approve_tts_audio, job.workdir)
            _job_store().transition(
                job.job_id,
                "queued",
                expected="awaiting_audio_approval",
                stage="build",
            )
        except Exception as exc:
            await q.message.reply_text(
                f"Не удалось утвердить озвучку: {str(exc)[:200]}"
            )
            return
        s["step"] = BUILDING
        save_session(chat_id, s)
        if _job_wakeup is not None:
            _job_wakeup.set()
        await q.message.reply_text(RENDER_QUEUED_MSG)
    elif data.startswith("audio_self:"):
        job = _callback_job(chat_id, s, data)
        if job is None or job.status != "awaiting_audio_approval":
            await q.message.reply_text(AUDIO_ACTION_STALE)
            return
        try:
            _job_store().transition(
                job.job_id,
                "awaiting_user_audio",
                expected="awaiting_audio_approval",
                stage="user_audio",
            )
        except RuntimeError:
            await q.message.reply_text(AUDIO_ACTION_STALE)
            return
        s["step"] = WAIT_FINAL_AUDIO
        save_session(chat_id, s)
        await q.message.reply_text(
            ASK_FINAL_AUDIO,
            reply_markup=_kb_final_audio(job.job_id),
        )
    elif data.startswith("audio_script:"):
        job = _callback_job(chat_id, s, data)
        if job is None or job.status != "awaiting_user_audio":
            await q.message.reply_text(AUDIO_ACTION_STALE)
            return
        await q.message.reply_text(_scenario_speech(job))
    elif data == "wish:skip":
        await q.message.reply_text(WISH_SKIPPED)
        await _show_ready_screen(q.message, chat_id, s)
    elif data == "build" or data.startswith("build:"):
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
        if not data.endswith(":plain"):
            # Монтаж ещё не сделан. Старый callback "build" тоже монтажный,
            # поэтому и он ведёт сюда, а не в платную сборку.
            await _ask_wish(q.message, chat_id, s, MONTAGE_TOPIC, MONTAGE_WIP_MSG)
            return
        s["montage"] = False
        save_session(chat_id, s)
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
        if _job_store().active_for_chat(chat_id):
            await q.message.reply_text(BUSY_MSG)
            return
        await _show_start(q.message, chat_id, s, loop_session)


async def _photo_stage(msg, chat_id: int, s: dict):
    """Фото — второй шаг после языка. Загрузка в HeyGen бесплатна."""
    await _ask_photo_screen(msg, chat_id, s)


# Суммы пополнения. Товаров в дашборде больше нет: счёт создаётся запросом в
# Shop API на выбранную сумму (см. tribute_shop). Валюта — выбор человека, а не
# догадка по языку: страну Телеграм боту не сообщает, в User есть только
# language_code (core.telegram.org/bots/api#user), а он у половины Казахстана
# русский.
TOPUP_PRESETS = {
    "usd": ((10_00, "$10"), (25_00, "$25"), (50_00, "$50")),
    "rub": ((1000_00, "1000 ₽"), (2500_00, "2500 ₽"), (5000_00, "5000 ₽")),
}

ASK_AMOUNT_MSG = "Баланс: {have}\n\nВыберите сумму для пополнения"
ORDER_READY_MSG = (
    "Счёт на {amount} готов. Нажмите «Оплатить» — Tribute предложит карту или "
    "СБП.\n\nПосле оплаты баланс пополнится сам; если этого не случилось за "
    "минуту, нажмите «Проверить оплату»."
)
ORDER_FAILED_MSG = (
    "Не получилось выставить счёт: {error}\n\nПопробуйте ещё раз через минуту."
)
ORDER_PENDING_MSG = "Оплата пока не дошла. Баланс: {have}"


def _tribute_key() -> str:
    return (os.environ.get("TRIBUTE_API_KEY") or "").strip()


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


def _kb_topup_entry():
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Пополнить баланс", callback_data="topup:start")],
    ])


def _kb_currency():
    """Выбор валюты подменяет кнопки в том же сообщении, поэтому «Назад»
    возвращает прежние — иначе человек теряет экран цены из виду."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Оплатить в RUB", callback_data="topup:cur:rub")],
        [InlineKeyboardButton("Оплатить в USD", callback_data="topup:cur:usd")],
        [InlineKeyboardButton("← Назад", callback_data="topup:cancel")],
    ])


def _kb_paid_continue():
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Продолжить ➡️", callback_data="pay:go")],
    ])


def _kb_amounts(currency: str):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    rows = [
        [InlineKeyboardButton(
            label, callback_data=f"topup:amt:{currency}:{minor}"
        )]
        for minor, label in TOPUP_PRESETS[currency]
    ]
    rows.append([InlineKeyboardButton("← Назад", callback_data="topup:start")])
    return InlineKeyboardMarkup(rows)


def _kb_pay(url: str):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Оплатить", url=url)],
        [InlineKeyboardButton("Проверить оплату", callback_data="topup:check")],
        [InlineKeyboardButton("← Назад", callback_data="topup:start")],
    ])


async def _show_topup(msg, chat_id: int, *, need: int | None = None,
                      have: int | None = None, exhausted: bool = False) -> None:
    """Экран пополнения. Принимает telegram-сообщение, а не update/context:
    зовётся и из обработчика команды, и из _enqueue_build, где есть только msg."""
    balance = _ledger().balance(chat_id) if have is None else have
    await msg.reply_text(
        topup_text(need, balance, exhausted=exhausted),
        reply_markup=_kb_topup_entry(),
    )


async def _show_currency_choice(msg, chat_id: int, s: dict) -> None:
    """Кнопки валюты встают на место «Пополнить баланс» в том же сообщении:
    новых экранов «В какой валюте платить?» человек не видит."""
    # Текст сообщения может быть пустым (например, кнопка висела под фото) —
    # пустой текст Telegram не примет, поэтому подставляем экран баланса.
    text = msg.text or topup_text(None, _ledger().balance(chat_id))
    await _edit_or_reply(msg, text, _kb_currency())


async def _show_amounts(msg, chat_id: int, s: dict, currency: str) -> None:
    s["pay_currency"] = currency
    save_session(chat_id, s)
    have = format_usd(_ledger().balance(chat_id))
    await msg.reply_text(
        ASK_AMOUNT_MSG.format(have=have), reply_markup=_kb_amounts(currency)
    )


async def _create_topup_order(msg, chat_id: int, s: dict, currency: str,
                              amount_minor: int) -> None:
    """Счёт на выбранную сумму. customerId = chat_id, поэтому вебхук всегда
    знает, кому зачислять — в отличие от прежних цифровых товаров."""
    from reels_factory import tribute_shop

    label = dict(
        (minor, text) for minor, text in TOPUP_PRESETS.get(currency, ())
    ).get(amount_minor, str(amount_minor))
    try:
        order = await asyncio.to_thread(
            tribute_shop.create_order,
            api_key=_tribute_key(),
            amount_minor=amount_minor,
            currency=currency,
            customer_id=str(chat_id),
            title=f"Пополнение баланса {label}",
            description="Депозит на генерацию рилсов",
        )
    except Exception as e:
        log.warning("счёт для чата %s не создан: %s", chat_id, e)
        _track(chat_id, s, "error:invoice", str(e)[:120])
        await msg.reply_text(ORDER_FAILED_MSG.format(error=str(e)[:200]))
        return
    sent = await msg.reply_text(
        ORDER_READY_MSG.format(amount=label),
        reply_markup=_kb_pay(tribute_shop.payment_link(order)),
    )
    s["pending_order"] = {
        "uuid": order.get("uuid"),
        "amount": amount_minor,
        "currency": currency,
        # id сообщения со счётом: когда деньги дойдут, его же и правим —
        # так и вебхук, и кнопка проверки дают один экран, а не два подряд.
        "message_id": getattr(sent, "message_id", None),
    }
    save_session(chat_id, s)
    _track(chat_id, s, "invoice_created", f"{amount_minor} {currency}")


def _paid_screen_text_kb(chat_id: int, s: dict):
    """Экран после зачисления: хватает — «Продолжить», нет — сколько добавить.

    Один и тот же вид для обоих путей (вебхук и кнопка проверки), поэтому
    человек не получает двух сообщений об одной оплате.
    """
    have = _ledger().balance(chat_id)
    billing = _billing()
    need = estimate_material_micro(s, billing) if billing["enabled"] else 0
    if not billing["enabled"] or have >= need:
        return PAID_ENOUGH_MSG.format(have=format_usd(have)), _kb_paid_continue()
    return (
        PRICE_STILL_SHORT_MSG.format(
            have=format_usd(have), gap=format_usd(need - have)
        ),
        _kb_price(False),
    )


async def _show_paid_screen(msg, chat_id: int, s: dict) -> None:
    text, kb = _paid_screen_text_kb(chat_id, s)
    await _edit_or_reply(msg, text, kb)


async def _check_topup_order(msg, chat_id: int, s: dict) -> None:
    """Сверка по статусу заказа — чтобы потерянный вебхук не стоил человеку
    денег и нашей ручной правки базы."""
    from reels_factory import tribute_shop

    order = s.get("pending_order") or {}
    order_uuid = order.get("uuid")
    if not order_uuid:
        await _show_currency_choice(msg, chat_id, s)
        return
    try:
        status = await asyncio.to_thread(
            tribute_shop.order_status,
            api_key=_tribute_key(), order_uuid=order_uuid,
        )
    except Exception as e:
        log.warning("статус заказа %s не получен: %s", order_uuid, e)
        await msg.reply_text(ORDER_PENDING_MSG.format(
            have=format_usd(_ledger().balance(chat_id))
        ))
        return
    if status == "paid":
        # credit идемпотентен: если вебхук уже зачислил, второй записи не
        # будет, а экран всё равно покажем актуальный.
        _credit_paid_order(chat_id, order)
        _track(chat_id, s, "payment_received", str(order.get("uuid") or ""))
        s.pop("pending_order", None)
        save_session(chat_id, s)
        await _show_paid_screen(msg, chat_id, s)
        return
    await msg.reply_text(ORDER_PENDING_MSG.format(
        have=format_usd(_ledger().balance(chat_id))
    ))


def _credit_paid_order(chat_id: int, order: dict) -> bool:
    """Зачислить оплаченный счёт при сверке.

    Ключ тот же, что у вебхука (`shop:<uuid>`), поэтому гонка «вебхук пришёл,
    и человек нажал проверку» не удваивает баланс.
    """
    from reels_factory.tribute import credited_micro

    billing = _billing()
    try:
        micro = credited_micro(
            order.get("amount") or 0, order.get("currency") or "usd", billing["fx"]
        )
    except Exception as e:
        log.warning("сверка заказа %s: сумма не пересчиталась: %s", order, e)
        return False
    return _ledger().credit(
        chat_id, micro,
        purchase_id=f"shop:{order.get('uuid')}",
        amount_minor=int(order.get("amount") or 0),
        currency=str(order.get("currency") or "usd"),
        raw={"source": "status_check", "order": order},
    )


async def cmd_balance(update, context) -> None:
    await _show_topup(update.message, update.effective_chat.id)


def _admin_chats() -> set[int]:
    """Кому показывать воронку. Список в env, через запятую."""
    raw = os.environ.get("ADMIN_CHAT_IDS") or ""
    out = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part.isdigit():
            out.add(int(part))
    return out


async def cmd_stats(update, context) -> None:
    """Воронка за период: /stats, /stats 30 — за столько дней.

    Команда служебная: обычному пользователю она не отвечает вовсе, чтобы не
    объяснять в чате, почему цифры не для него.
    """
    chat_id = update.effective_chat.id
    if chat_id not in _admin_chats():
        return
    days = 7
    parts = (update.message.text or "").split()
    if len(parts) > 1 and parts[1].isdigit():
        days = max(1, min(int(parts[1]), 365))
    since = time.time() - days * 86400
    text = await asyncio.to_thread(
        render_funnel, _events(), since, title=f"Воронка за {days} дн."
    )
    await update.message.reply_text(text)


async def _blocked_by_negative_balance(msg, chat_id: int) -> bool:
    """Страховка внутри уже оплаченного цикла (выбор идеи -> step_scenario).

    Основной гейт — экран цены: там сверяется, что баланса хватает на весь
    ролик, и без этого платная часть не начинается. Здесь порог другой,
    «строго меньше нуля»: человек уже согласился и заплатил, добивать его
    вторым экраном на каждой мелочи незачем — ловим только реальный минус.
    """
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
            montage=bool(s.get("montage", True)),
        )
    except InsufficientBalance as exc:
        # Раньше общего except: иначе нехватка баланса покажется как
        # техническая ошибка, без кнопок пополнения.
        await _show_topup(msg, chat_id, need=exc.need, have=exc.have)
        return None
    except Exception as e:
        await msg.reply_text(f"Не удалось поставить ролик в очередь: {str(e)[:200]}")
        return None

    s["step"] = AUDIO_PREPARING
    s["current_job_id"] = job.job_id
    save_session(chat_id, s)
    _track(chat_id, s, "build_queued", job.job_id[:8])
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


def _update_active_session_step(chat_id: int, job_id: str, step: str) -> None:
    """Обновить паузу внутри job, не очищая current_job_id."""
    s = load_session(chat_id)
    if s.get("current_job_id") != job_id:
        return
    s["step"] = step
    save_session(chat_id, s)


def _track_job(job: BuildJob, event: str, detail: str | None = None) -> None:
    """Событие из воркера: сессию читаем только ради номера цикла."""
    _track(job.chat_id, load_session(job.chat_id), event, detail)


async def _safe_job_message(bot_api, chat_id: int, text: str) -> None:
    try:
        await bot_api.send_message(chat_id=chat_id, text=text)
    except Exception as e:
        log.warning("не удалось отправить статус job в чат %s: %s", chat_id, e)


async def _process_audio_job(bot_api, job: BuildJob, preview_fn=None) -> None:
    """Создать и доставить только preview master audio, затем поставить job на паузу."""
    store = _job_store()
    preview_fn = preview_fn or run_audio_preview
    await _safe_job_message(
        bot_api,
        job.chat_id,
        f"{PREPARING_AUDIO_MSG}\nID: {job.job_id[:8]}",
    )
    try:
        result = await asyncio.to_thread(
            preview_fn, job.chat_id, job.workdir
        )
    except Exception as exc:
        result = {
            "ok": False,
            "stage": "audio_preview",
            "error": str(exc)[:500],
        }
    if not result.get("ok"):
        error = result.get("error") or "неизвестная ошибка"
        store.finish(
            job.job_id,
            "failed",
            result=result,
            stage="audio_preview",
            error=error,
        )
        _update_session_after_job(job.chat_id, job.job_id, BUILD_FAILED)
        await _safe_job_message(
            bot_api,
            job.chat_id,
            f"Не получилось создать озвучку: {error}\nID: {job.job_id[:8]}",
        )
        return

    audio = Path(result.get("audio") or "")
    if not audio.is_file():
        error = "Озвучка создана, но audio-файл не найден."
        store.finish(
            job.job_id,
            "failed",
            result=result,
            stage="audio_delivery",
            error=error,
        )
        _update_session_after_job(job.chat_id, job.job_id, BUILD_FAILED)
        await _safe_job_message(bot_api, job.chat_id, error)
        return

    try:
        with audio.open("rb") as file_obj:
            await bot_api.send_audio(
                chat_id=job.chat_id,
                audio=file_obj,
                caption=AUDIO_REVIEW_MSG,
                reply_markup=_kb_audio_review(job.job_id),
                title="Озвучка ролика",
            )
        _track_job(job, "audio_ready")
    except Exception as exc:
        store.finish(
            job.job_id,
            "delivery_failed",
            result=result,
            stage="audio_delivery",
            error=str(exc),
        )
        _update_session_after_job(job.chat_id, job.job_id, BUILD_FAILED)
        await _safe_job_message(
            bot_api,
            job.chat_id,
            "Озвучка готова, но Telegram не принял аудиофайл. "
            f"Он сохранён для диагностики.\nID: {job.job_id[:8]}",
        )
        return

    try:
        store.transition(
            job.job_id,
            "awaiting_audio_approval",
            expected="audio_running",
            stage="audio_review",
            result=result,
        )
    except RuntimeError:
        log.exception("не удалось поставить audio preview job на паузу")
        return
    _update_active_session_step(job.chat_id, job.job_id, AUDIO_REVIEW)


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
        _track_job(job, "error:build", "файла ролика нет")
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
        _track_job(job, "error:delivery", str(e)[:120])
        await _safe_job_message(
            bot_api,
            job.chat_id,
            "Ролик готов и прошёл QA, но Telegram не принял файл. "
            f"Он сохранён для повторной отправки.\nID: {job.job_id[:8]}"
            f"{_charged_but_undelivered_notice(job.job_id)}",
        )
        return

    store.finish(job.job_id, "completed", result=result, stage="delivery")
    _track_job(job, "reel_delivered")
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
            if job.status == "audio_running":
                await _process_audio_job(bot_api, job)
            else:
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

    if step == WAIT_FINAL_AUDIO:
        job_id = s.get("current_job_id")
        job = _job_store().get(job_id) if job_id else None
        if (
            job is None
            or job.chat_id != int(chat_id)
            or job.status != "awaiting_user_audio"
        ):
            await msg.reply_text(AUDIO_ACTION_STALE)
            return
        if msg.voice is None:
            await msg.reply_text(
                "Жду одно голосовое сообщение Telegram с полным текстом сценария.",
                reply_markup=_kb_final_audio(job.job_id),
            )
            return
        try:
            _job_store().transition(
                job.job_id,
                "user_audio_processing",
                expected="awaiting_user_audio",
                stage="user_audio",
            )
        except RuntimeError:
            await msg.reply_text(AUDIO_ACTION_STALE)
            return
        await msg.reply_text(PROCESSING_FINAL_AUDIO)
        try:
            path = await _download(context, msg.voice, chat_id)
            await asyncio.to_thread(prepare_user_audio, job.workdir, path)
            _job_store().transition(
                job.job_id,
                "queued",
                expected="user_audio_processing",
                stage="build",
            )
        except Exception as exc:
            try:
                _job_store().transition(
                    job.job_id,
                    "awaiting_user_audio",
                    expected="user_audio_processing",
                    stage="user_audio",
                    error=str(exc),
                )
            except RuntimeError:
                log.warning(
                    "job %s сменила status во время обработки user audio",
                    job.job_id,
                )
            await msg.reply_text(
                f"Не могу использовать эту запись: {str(exc)[:240]}\n\n"
                "Запишите весь сценарий ещё раз одним голосовым.",
                reply_markup=_kb_final_audio(job.job_id),
            )
            return
        s["step"] = BUILDING
        save_session(chat_id, s)
        if _job_wakeup is not None:
            _job_wakeup.set()
        await msg.reply_text(FINAL_AUDIO_ACCEPTED)
        return

    if step == WAIT_WISH:
        wish = (msg.text or msg.caption or "").strip()
        if not wish:
            await msg.reply_text(WISH_EMPTY, reply_markup=_kb_wish())
            return
        user = getattr(update, "effective_user", None)
        try:
            _feedback().add(
                chat_id,
                topic=s.get("wish_topic") or MONTAGE_TOPIC,
                text=wish,
                username=getattr(user, "username", None),
            )
        except Exception as e:
            # Пожелание — не деньги и не сборка: молча роняем разговор из-за
            # него нельзя, но и делать вид, что всё записано, тоже.
            log.warning("пожелание чата %s не записалось: %s", chat_id, e)
        await msg.reply_text(WISH_THANKS)
        await _show_ready_screen(msg, chat_id, s)
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
        _track(chat_id, s, "stage:photo")
        await msg.reply_text(PHOTO_SAVED)
        # Голос мог быть принят раньше фото (правка этапа) — тогда оба входа
        # демо собрались только сейчас. Лимиты внутри: одно демо на человека.
        await _maybe_send_demo(msg, chat_id, s)
        await _next_stage(msg, chat_id, s, STAGE_PHOTO)
        return

    if step == WAIT_VOICE:
        rec = msg.voice or msg.audio or msg.document
        if rec is None:
            await msg.reply_text("Жду запись голоса — голосовым или файлом.")
            return
        language = _reel_language(s)
        try:
            path = await _download(context, rec, chat_id)
        except Exception as e:
            await msg.reply_text(f"Запись не принялась: {str(e)[:200]}")
            return
        # Клон здесь не делаем: его создаст демо-шаг ниже (_maybe_send_demo
        # -> _ensure_voice_clone). Файл запоминаем как исходник, прежний клон
        # этого языка не трогаем — он останется рабочим, если новый клон
        # не получится.
        old_sample = _voice_sample_for_language(s, language)
        samples = dict(s.get("voice_samples") or {})
        samples[language] = str(path)
        pending = dict(s.get("voice_pending") or {})
        pending[language] = str(path)
        s["voice_samples"] = samples
        s["voice_pending"] = pending
        save_session(chat_id, s)
        _track(chat_id, s, "stage:voice", language)
        if old_sample and str(old_sample) != str(path):
            Path(old_sample).unlink(missing_ok=True)
        await msg.reply_text(VOICE_SAVED)
        # Оба входа демо собраны — показываем человеку его двойника до
        # экрана цены.
        await _maybe_send_demo(msg, chat_id, s)
        await _next_stage(msg, chat_id, s, STAGE_VOICE)
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
        if step in (WAIT_TEXT, WAIT_RAW, WAIT_EDIT):
            await msg.reply_text("Жду текст сообщением или файлом.")
        else:
            await _reshow(msg, chat_id, s)
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
        # Текст только запоминаем: Клод к нему подойдёт после экрана цены.
        s["material_mode"] = "text"
        s["material_text"] = cleaned
        s.pop("ideas", None)
        save_session(chat_id, s)
        _track(chat_id, s, "stage:material", "text")
        await _show_price(msg, chat_id, s)

    elif step == WAIT_RAW:
        s["material_mode"] = "raw"
        s["material_text"] = text
        s.pop("ideas", None)
        save_session(chat_id, s)
        _track(chat_id, s, "stage:material", "raw")
        await _show_price(msg, chat_id, s)

    elif step == CONFIRM_PRICE:
        # Человек пишет вместо нажатия — показываем тот же экран со свежим
        # балансом, а не молчим и не теряем уже принятый материал.
        await _show_price(msg, chat_id, s, checked=True)

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
        await _reshow(msg, chat_id, s)


async def _download(context, media, chat_id: int) -> Path:
    f = await context.bot.get_file(media.file_id)
    name = getattr(media, "file_name", None) or Path(f.file_path or "raw").name
    dest = session_dir(chat_id) / "input" / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    await f.download_to_drive(str(dest))
    return dest


async def _apply_credit_to_chat(bot_api, chat_id: int) -> None:
    """Показать зачисление в том же сообщении со счётом.

    Правим сообщение, а не шлём новое: иначе на одну оплату приходит два
    сообщения — от вебхука и от кнопки «Проверить оплату».
    """
    s = load_session(chat_id)
    order = s.get("pending_order") or {}
    message_id = order.get("message_id")
    text, kb = _paid_screen_text_kb(chat_id, s)
    _track(chat_id, s, "payment_received", str(order.get("uuid") or ""))
    if order:
        s.pop("pending_order", None)
        save_session(chat_id, s)
    if message_id:
        try:
            await bot_api.edit_message_text(
                chat_id=chat_id, message_id=message_id, text=text, reply_markup=kb
            )
            return
        except Exception as e:
            # Сообщение могли удалить или оно уже с этим текстом — тогда
            # лучше прислать новое, чем промолчать про деньги.
            log.info("счёт чата %s не поправился (%s), шлём сообщение", chat_id, e)
    await bot_api.send_message(chat_id=chat_id, text=text, reply_markup=kb)


def _notify_credited(bot_api, loop, event: dict) -> None:
    """Зовётся из потока вебхук-сервера, поэтому корутину кладём в петлю бота
    через run_coroutine_threadsafe — иначе она просто не выполнится."""
    chat_id = event.get("chat_id")
    if not chat_id:
        return
    try:
        asyncio.run_coroutine_threadsafe(
            _apply_credit_to_chat(bot_api, int(chat_id)), loop
        )
    except Exception as e:
        log.warning("не удалось сообщить о пополнении чату %s: %s", chat_id, e)


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
    recovered_user_audio = await asyncio.to_thread(
        _job_store().recover_user_audio_processing
    )
    for job in recovered_user_audio:
        _update_active_session_step(job.chat_id, job.job_id, WAIT_FINAL_AUDIO)
        await _safe_job_message(
            app.bot,
            job.chat_id,
            "Проверка голосового прервалась из-за перезапуска сервиса. "
            "Пришлите весь сценарий одним голосовым ещё раз.\n"
            f"ID: {job.job_id[:8]}",
        )

    tribute_key = os.environ.get("TRIBUTE_API_KEY")
    billing = _billing()
    if tribute_key:
        loop = asyncio.get_running_loop()
        start_webhook_server(
            _ledger(), api_key=tribute_key, fx=billing["fx"],
            port=int(os.environ.get("TRIBUTE_WEBHOOK_PORT", "8099")),
            on_credit=lambda ev: _notify_credited(app.bot, loop, ev),
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
    # /stats в меню бота не показываем: она служебная и отвечает
    # только чатам из ADMIN_CHAT_IDS.
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(~filters.COMMAND, on_message))
    app.run_polling()


if __name__ == "__main__":
    main()
