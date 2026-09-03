"""Клиент HeyGen для аватара-ведущего.

Два пути, выбор автоматический:

1. **Digital Twin + Avatar V** (предпочтительный, включается, когда задан
   look_id) — аватар обучен на видео человека, поэтому модель не выдумывает
   зубы, мимику и пластику, а воспроизводит настоящие. Тело запроса:
   `type: "avatar"` + `avatar_id` (look id двойника) + `engine.type: "avatar_v"`.
   `expressiveness` и `motion_prompt` в этом API-пути НЕ шлются: актуальная
   request schema ограничивает оба поля Photo Avatar / Avatar IV.
2. **Photo Avatar (Avatar IV)** — путь по одному фото (`type: "image"`),
   когда двойника ещё нет. Слабое место: рот на фото закрыт, зубы модель
   домысливает.

Фолбэк на старый v2 `video/generate` убран целиком (задача 10): HeyGen
выводит v1/v2 из эксплуатации 1 ноября 2026 (endpoint-version-comparison —
до этой даты есть время переехать без спешки), а молчаливая деградация на
устаревший путь при 403/404 маскировала настоящие поломки (битый ключ,
опечатка в URL, протухший ресурс) под штатный сценарий. Теперь оба кода —
явная ошибка: 403 → HeyGenConfigError (чинится конфигом), 404 → обычная
ошибка с телом ответа.

generate() гонит НАШЕ аудио (ElevenLabs) в HeyGen: (1) загружает wav как
audio-ассет, (2) создаёт видео, (3) поллит статус, (4) скачивает готовый mp4.

cached_generate() переиспользует уже сгенерированный фрагмент (например CTA)
между рилсами по sha1-ключу от (sha1 файла аудио + avatar_id + look_id +
engine + resolution + motion_prompt + expressiveness).

render_covered_block() — не HeyGen: для блоков формата avatar, полностью
закрытых вставкой видеоряда (see pipeline.run_make), рендерит голос поверх
чёрного кадра локально через ffmpeg — платить HeyGen за невидимый кадр незачем.

api_key/avatar_id/look_id/motion_prompt/expressiveness/engine/resolution — из
аргументов или env (HEYGEN_API_KEY, HEYGEN_AVATAR_ID, HEYGEN_LOOK_ID,
HEYGEN_MOTION_PROMPT, HEYGEN_EXPRESSIVENESS, HEYGEN_ENGINE, HEYGEN_RESOLUTION;
дефолт expressiveness "low" — как и дефолт самого HeyGen; официальный
troubleshooting-гайд HeyGen советует именно понижать expressiveness при
галлюцинациях/лишних деталях в кадре). http/sleep — DI для тестов.

Двойник создаётся один раз на человека — см. модуль twin.py (использует тот
же heygen_request/_raise_for_status).

v3-запрос дополнительно закрепляет сцену вместо того, чтобы отдавать её на
волю генерации: `background` = то же фото аватара (мотив держится в кадре,
модель не "дорисовывает" случайный фон/людей) и `aspect_ratio: "9:16"` (поле
dimension в v3 игнорируется сервером — размер раньше действительно задавало
исходное фото, но актуальная схема API даёт явный контроль через
aspect_ratio, и раз плагин целиком про вертикальные рилсы — фиксируем 9:16).

Разбор ответов — в одном месте (задача 10, п.2): heygen_request() шлёт
запрос и повторяет его при 429/5xx (Retry-After, иначе 1000·2^attempt мс,
потолок 60с, до 5 попыток всего — схема HyperFrames
packages/core/src/figma/client.ts:296-303); опрос статуса (HeyGenClient._poll)
зовёт heygen_request с retry=False — тот же принцип, что у их
cloud/poll.ts:48 ("опрос статуса не ретраить"): цикл опроса и так повторяет
запрос секундами позже, вторая независимая система повторов не нужна.
Сетевой сбой БЕЗ ответа сервера (таймаут, обрыв) никогда не повторяется —
платный POST мог уже быть принят, и повтор рискует вторым заказом (тот же
довод — их cloud.md:151). 402 → HeyGenCreditsExhausted (код из тела:
insufficient_credit/subscription_required), 403 → HeyGenConfigError, 404 и
всё остальное — RuntimeError с HTTP-кодом, кодом ошибки и первыми 300
знаками тела.

ensure_balance_for_order() — задача 10, п.3: перед первым платным POST
заказа проверяет GET /v3/users/me → wallet.remaining_balance. Форма ответа —
по доке (https://developers.heygen.com/user-profile, снята 2026-09-03,
heygen-docs.md в scratchpad задачи): "Endpoint: GET
https://api.heygen.com/v3/users/me ... Returns the authenticated user's
profile, remaining credits or balance, and billing details", ответ ветвится
по billing_type, и у "wallet" — "wallet.currency — 'usd' or 'credits';
wallet.remaining_balance — Current balance." У self-serve/API-ключа это
billing_type "wallet", валюта usd — пересчитывать из кредитов не нужно.
Дока НЕ даёт пример тела ответа для этого эндпоинта (обёрнут ли `wallet` в
`data`, как это точно видно на /v3/videos/{id} — heygen-docs.md §3, `.json()
["data"]`, — или лежит на верхнем уровне, не показано); код и тест поэтому
читают обе формы (`payload.get("data") or payload`), а не гадают. Ниже
HEYGEN_LOW_BALANCE_USD — алерт Васе (см. alerts.py; зовётся один раз на
сборку — это гарантирует сама точка вызова: render_avatar_islands/
_run_plain_avatar зовут её один раз до цикла заказа шотов, а не на каждый
шот). Ниже оценки именно этого заказа (секунды × ставка HeyGen из
billing.BILLING_DEFAULTS, не новая константа) — отказ до POST:
HeyGenCreditsExhausted. Сбой самой проверки остатка (сеть/5xx после
исчерпанных повторов, клиент без http/sleep/api_key в тестах) не должен
становиться новой причиной падения сборки — заказ идёт, в лог только
предупреждение.

pause_heygen_orders()/heygen_orders_paused()/clear_heygen_pause() — задача
10, п.4: файл-флаг в WORK_ROOT (общий на весь сервис — кошелёк HeyGen один на
всех клиентов, а не на job). HeyGenCreditsExhausted ставит флаг при
возникновении (что 402 от HeyGen, что наш предварительный отказ по оценке) и
тут же шлёт алерт Васе через _alert_pause_if_due() — не чаще раза в час,
метка последнего алерта в самом файле флага, а не в памяти процесса (см.
докстринг у _alert_pause_if_due: _credits_exhausted исполняется в подпроцессе
рендера, у каждого своя память). Следующая же успешная проверка остатка выше
порога снимает флаг сама — ручных кнопок нет. bot.py читает
heygen_orders_paused() на экране цены, до списания: без этого чтения платный
тап всё равно уходил бы в HeyGen, который откажет уже после того, как деньги
списаны с баланса клиента.
"""
import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path

from reels_factory.config import BILLING_DEFAULTS, WORK_ROOT

log = logging.getLogger(__name__)

UPLOAD_URL = "https://api.heygen.com/v3/assets"
CREATE_URL = "https://api.heygen.com/v3/videos"
STATUS_URL = "https://api.heygen.com/v3/videos"
USER_PROFILE_URL = "https://api.heygen.com/v3/users/me"

_AUDIO_MIME_BY_SUFFIX = {".wav": "audio/wav", ".mp3": "audio/mpeg"}

# Дефолт для аватара-ведущего: говорит прямо в камеру, живо, без переигрывания.
DEFAULT_MOTION_PROMPT = (
    "Looks at the camera and gestures lightly with one hand, calm and confident."
)

# Один motion_prompt на весь ролик даёт ровную, «дикторскую» подачу: хук просит
# энергии, а CTA — прямого обращения, и это разная пластика. Ключ — role блока
# сценария (hook/context/development/payoff/cta), остальное берёт дефолт.
MOTION_PROMPT_BY_ROLE = {
    "hook": (
        "Looks at the camera and leans in slightly, confident and engaged."
    ),
    "context": (
        "Looks at the camera with a calm expression and subtle natural gestures."
    ),
    "development": (
        "Looks at the camera and gestures lightly with one hand, confident and clear."
    ),
    "payoff": (
        "Looks at the camera and nods gently, sincere and confident."
    ),
    "cta": (
        "Looks at the camera and makes one inviting open-hand gesture, warm and direct."
    ),
}

DEFAULT_EXPRESSIVENESS = "low"

# Движок рендера. avatar_v — высшая точность идентичности, но существует только
# для двойника; фото-аватар рендерит avatar_iv. Дефолт выбирается по тому, есть
# ли look_id, — вместо того чтобы молча полагаться на серверный дефолт HeyGen.
DEFAULT_ENGINE_TWIN = "avatar_v"
DEFAULT_ENGINE_PHOTO = "avatar_iv"
DEFAULT_RESOLUTION = "1080p"

# API request schema ограничивает оба performance controls Avatar IV.
_ENGINES_WITH_PERFORMANCE_CONTROLS = ("avatar_iv",)

# Растущий интервал опроса (задача 10, п.5). Их дока не называет ни
# рекомендованного интервала, ни типичного времени рендера (heygen-docs.md
# §3) — профиль опроса берём у их же облачного рендера (cloud/poll.ts):
# часто, пока заказ обычно ещё не готов, реже, когда он определённо не
# мгновенный, и потолок ожидания час — как у них.
POLL_STAGE_1_S = 10
POLL_STAGE_1_UNTIL_S = 120       # первые 2 минуты — интервал 10с
POLL_STAGE_2_S = 30
POLL_STAGE_2_UNTIL_S = 300       # до 5 минут — интервал 30с
POLL_STAGE_3_S = 60              # дальше — интервал 60с
POLL_MAX_WAIT_S = 3600           # потолок ожидания, как у их облачного рендера

# Порог алерта об остатке кошелька (задача 10, п.3). При ставке $0.05/сек
# (Avatar IV и Avatar V — обе 0.1 credit/сек, heygen-docs.md §7) это ещё
# около 200 секунд ведущей: несколько сборок форы, чтобы Вася долил баланс
# до первого настоящего отказа по 402.
HEYGEN_LOW_BALANCE_USD = 10.0

# Схема повтора платных запросов (задача 10, п.2) — фиксированные числа из
# клона HyperFrames (packages/core/src/figma/client.ts:296-303), а не наша
# отдельная политика: Retry-After, иначе экспонента с потолком 60с, до пяти
# попыток всего.
_RETRY_MAX_ATTEMPTS = 5
_RETRY_BASE_MS = 1000
_RETRY_CAP_MS = 60_000

_HEYGEN_PAUSE_FLAG_FILENAME = "heygen_paused.json"

_CACHE_LOCKS: dict[str, threading.Lock] = {}
_CACHE_LOCKS_GUARD = threading.Lock()


class HeyGenRenderTimeout(RuntimeError):
    """Ждать перестали мы, а не HeyGen отказал.

    Отдельный тип, потому что случаи стоят разного. Отказ рендера
    (`status: failed`) — заказ не состоялся, и повторять его придётся. Наш
    таймаут — заказ на их стороне жив и оплачен, и на пересборке его можно
    дождаться, а не заказывать второй раз. Пока оба случая приходили одним
    `RuntimeError`, отличить их вызывающему было нечем.

    `video_id` — по нему заказ и находится у HeyGen.
    """

    def __init__(self, message: str, video_id: str):
        super().__init__(message)
        self.video_id = video_id


class HeyGenConfigError(RuntimeError):
    """403 — ключ валиден, но доступа нет (не тот тариф/scope на v3). Чинится
    конфигом (ключ/права), не кодом; никакого молчаливого фолбэка на v2."""


class HeyGenCreditsExhausted(RuntimeError):
    """Кредиты HeyGen исчерпаны — либо реальный 402 (insufficient_credit /
    subscription_required, код в ``.code``), либо наш собственный
    предварительный отказ до POST, когда остатка кошелька не хватает даже
    на оценку заказа."""

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        self.code = code


def _is_retryable_status(status: int) -> bool:
    return status == 429 or 500 <= status < 600


def _retry_delay(resp, attempt: int) -> float:
    """attempt — 0-based номер уже случившегося отказа."""
    headers = getattr(resp, "headers", None) or {}
    try:
        retry_after = headers.get("Retry-After")
    except AttributeError:
        retry_after = None
    if retry_after not in (None, ""):
        try:
            return float(retry_after)
        except (TypeError, ValueError):
            pass
    return min(_RETRY_CAP_MS, _RETRY_BASE_MS * (2 ** attempt)) / 1000.0


def _pause_flag_path() -> Path:
    return WORK_ROOT / _HEYGEN_PAUSE_FLAG_FILENAME


def pause_heygen_orders(reason: str) -> None:
    """Задача 10, п.4: остановить приём платных заказов HeyGen до тех пор,
    пока баланс не подтвердится восстановленным. Флаг общий на сервис —
    кошелёк один на всех клиентов бота, а не на конкретный job."""
    import datetime

    path = _pause_flag_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "reason": reason[:500],
                "since": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def heygen_orders_paused() -> dict | None:
    """None — приём открыт. Иначе {"reason", "since"} для сообщения/алерта."""
    path = _pause_flag_path()
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"reason": "флаг паузы повреждён — считаем приём приостановленным"}


def clear_heygen_pause() -> None:
    _pause_flag_path().unlink(missing_ok=True)


# Тот же часовой троттлинг, что и у алерта про тап человека по уже
# приостановленной цене (bot.py: _alert_heygen_pause_tap), но не через
# process-локальную переменную: эта пауза ставится из _credits_exhausted,
# который исполняется в подпроцессе рендера (`python -m reels_factory make`,
# см. docstring модуля и _send_alert_sync) — у каждого запуска своя память,
# и in-memory троттлинг обнулялся бы на каждом новом 402. Метка последнего
# алерта живёт в самом файле флага паузы — его читают и пишут все процессы.
_PAUSE_ALERT_INTERVAL_S = 3600


def _pause_and_alert_if_due(reason: str) -> None:
    """Ставит флаг паузы (pause_heygen_orders) и, не чаще раза в час, шлёт
    Васе алерт про сам момент постановки (независимая проверка пачки 08-10,
    п. b): раньше он уходил только при низком остатке кошелька
    (ensure_balance_for_order) и при тапе человека по уже приостановленной
    цене (bot.py) — сам момент установки флага молчал.

    Метку last_alerted_at читаем ДО pause_heygen_orders: та безусловно
    перезаписывает файл флага свежими reason/since на каждый 402 (в том
    числе повторный, пока пауза уже висит) — прочитать метку ПОСЛЕ записи
    значило бы каждый раз находить пустой файл и слать алерт заново.
    """
    path = _pause_flag_path()
    last_alerted_at = None
    if path.is_file():
        try:
            last_alerted_at = json.loads(path.read_text(encoding="utf-8")).get(
                "last_alerted_at"
            )
        except Exception:
            last_alerted_at = None
    now = time.time()
    due = last_alerted_at is None or now - float(last_alerted_at) >= _PAUSE_ALERT_INTERVAL_S

    pause_heygen_orders(reason)

    if not due:
        return
    _send_alert_sync(
        "HeyGen: приём заказов поставлен на паузу\n"
        f"Причина: {reason[:500]}"
    )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["last_alerted_at"] = now
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as exc:
        # Флаг паузы уже стоит (pause_heygen_orders отработал строкой выше)
        # — несохранённая метка алерта означает лишь чуть более частые
        # повторы уведомления, не потерю самой паузы.
        log.warning("не удалось записать last_alerted_at в флаг паузы: %s", exc)


def _credits_exhausted(message: str, *, code: str | None = None) -> HeyGenCreditsExhausted:
    _pause_and_alert_if_due(message)
    return HeyGenCreditsExhausted(message, code=code)


def _raise_for_status(status: int, resp) -> None:
    try:
        payload = resp.json() or {}
    except Exception:
        payload = {}
    error = payload.get("error") if isinstance(payload, dict) else None
    code = (error or {}).get("code")
    if payload:
        body = str(payload)[:300]
    else:
        body = str(getattr(resp, "content", ""))[:300]
    if status == 402:
        raise _credits_exhausted(
            f"HeyGen: кредиты исчерпаны ({code or 'без кода'}): {body}",
            code=code,
        )
    if status == 403:
        raise HeyGenConfigError(f"HeyGen отказал в доступе (403): {body}")
    if status == 404:
        raise RuntimeError(f"HeyGen: ресурс не найден (404): {body}")
    raise RuntimeError(f"HeyGen HTTP {status} ({code or 'без кода'}): {body}")


def heygen_request(http, sleep, method: str, url: str, *, headers: dict,
                    retry: bool = True, **kwargs):
    """Единая точка входа для всех вызовов HeyGen API (задача 10, п.2) —
    используется и HeyGenClient (avatar.py), и TwinClient (twin.py), и
    upload_photo_asset(). ``retry=False`` — для опроса статуса (см.
    docstring модуля)."""
    attempts = 0
    while True:
        attempts += 1
        try:
            resp = getattr(http, method)(url, headers=headers, **kwargs)
        except Exception as exc:
            # Сетевой сбой без ответа сервера — повторять нельзя: платный
            # запрос мог быть принят, повтор рискует вторым заказом.
            raise RuntimeError(
                f"HeyGen {method.upper()} {url}: сетевой сбой без ответа "
                f"сервера ({exc}); не повторяем"
            ) from exc
        status = getattr(resp, "status_code", 200)
        if status < 400:
            return resp
        if retry and _is_retryable_status(status) and attempts < _RETRY_MAX_ATTEMPTS:
            sleep(_retry_delay(resp, attempts - 1))
            continue
        _raise_for_status(status, resp)


def _poll_interval(elapsed: float) -> int:
    if elapsed < POLL_STAGE_1_UNTIL_S:
        return POLL_STAGE_1_S
    if elapsed < POLL_STAGE_2_UNTIL_S:
        return POLL_STAGE_2_S
    return POLL_STAGE_3_S


def _send_alert_sync(text: str) -> None:
    """avatar.py/pipeline.py работают синхронно в отдельном подпроцессе (без
    event loop бота — bot.py зовёт run_build через subprocess.Popen), а
    alerts.send_alert асинхронный. Свой короткий event loop — как у любой
    sync-точки входа в асинхронный код."""
    import asyncio

    from reels_factory import alerts

    try:
        asyncio.run(alerts.send_alert(text))
    except Exception as exc:
        log.warning("алерт HeyGen не отправился: %s", exc)


def ensure_balance_for_order(client, seconds_estimate: float) -> None:
    """Задача 10, п.3 — зовётся один раз в точке, где заказываются шоты,
    до первого платного POST (render_avatar_islands / _run_plain_avatar)."""
    try:
        http, sleep, api_key = client.http, client.sleep, client.api_key
    except AttributeError:
        # Клиент без http/sleep/api_key (лёгкие test doubles) — проверка
        # молча не выполняется, заказ идёт как и раньше.
        return
    try:
        resp = heygen_request(
            http, sleep, "get", USER_PROFILE_URL,
            headers={"X-Api-Key": api_key}, timeout=30,
        )
    except (HeyGenConfigError, HeyGenCreditsExhausted):
        raise
    except Exception as exc:
        log.warning(
            "HeyGen: проверка остатка кошелька не удалась (%s) — заказ идёт "
            "без неё", exc,
        )
        return
    try:
        payload = resp.json()
        wallet = (payload.get("data") or payload).get("wallet") or {}
        balance = float(wallet["remaining_balance"])
    except Exception as exc:
        log.warning(
            "HeyGen: /v3/users/me без wallet.remaining_balance (%s) — заказ "
            "идёт без проверки остатка", exc,
        )
        return
    estimated_cost = (
        float(seconds_estimate) * BILLING_DEFAULTS["rates"]["heygen_usd_per_second"]
    )
    if balance < estimated_cost:
        raise _credits_exhausted(
            f"HeyGen: остаток кошелька ${balance:.2f} ниже оценки заказа "
            f"${estimated_cost:.2f} ({float(seconds_estimate):.1f} с ведущей)"
        )
    if balance < HEYGEN_LOW_BALANCE_USD:
        _send_alert_sync(
            f"HeyGen: остаток кошелька ${balance:.2f} ниже порога "
            f"${HEYGEN_LOW_BALANCE_USD:.0f}. Пополни, пока сборки не начали "
            "падать по 402."
        )
    else:
        clear_heygen_pause()


def upload_photo_asset(image_path, api_key=None, http=None, sleep=None) -> str:
    """Залить фото аватара в HeyGen /v3/assets, вернуть asset_id.

    Загрузка ассета бесплатна — платит только генерация видео. Нужна там, где
    фото приходит из кода (телеграм-бот), а не руками через мастер setup.
    """
    image_path = Path(image_path)
    if not image_path.exists():
        raise RuntimeError(f"файл фото не найден: {image_path}")
    api_key = api_key or os.environ.get("HEYGEN_API_KEY")
    if not api_key:
        raise RuntimeError(
            "HeyGen API key не задан: передайте api_key или "
            "установите env HEYGEN_API_KEY"
        )
    if http is None:
        import requests
        http = requests
    if sleep is None:
        import time
        sleep = time.sleep

    resp = heygen_request(
        http, sleep, "post", UPLOAD_URL, headers={"X-Api-Key": api_key},
        files={"file": (image_path.name, image_path.read_bytes())},
        timeout=120,
    )
    asset_id = ((resp.json() or {}).get("data") or {}).get("asset_id")
    if not asset_id:
        raise RuntimeError(f"HeyGen не вернул asset_id: {str(resp.json())[:200]}")
    return asset_id


class HeyGenClient:
    def __init__(self, api_key=None, avatar_id=None, motion_prompt=None,
                 http=None, sleep=None, expressiveness=None, look_id=None,
                 engine=None, resolution=None):
        self.api_key = api_key or os.environ.get("HEYGEN_API_KEY")
        self.avatar_id = avatar_id or os.environ.get("HEYGEN_AVATAR_ID")
        # look_id задан → идём путём Digital Twin (Avatar V), иначе — по фото
        self.look_id = look_id or os.environ.get("HEYGEN_LOOK_ID")
        explicit = motion_prompt or os.environ.get("HEYGEN_MOTION_PROMPT")
        self._motion_prompt_explicit = bool(explicit)
        self.motion_prompt = explicit or DEFAULT_MOTION_PROMPT
        self.expressiveness = expressiveness or os.environ.get(
            "HEYGEN_EXPRESSIVENESS", DEFAULT_EXPRESSIVENESS)
        self.engine = engine or os.environ.get("HEYGEN_ENGINE") or (
            DEFAULT_ENGINE_TWIN if self.look_id else DEFAULT_ENGINE_PHOTO)
        self.resolution = resolution or os.environ.get(
            "HEYGEN_RESOLUTION", DEFAULT_RESOLUTION)

        if http is None:
            import requests
            http = requests
        self.http = http

        if sleep is None:
            import time
            sleep = time.sleep
        self.sleep = sleep

    def motion_prompt_for(self, role=None) -> str:
        """Промпт движения под роль блока. Явно заданный клиенту motion_prompt
        (config/env) главнее ролевого: если человек прописал свою пластику,
        мы её не перебиваем."""
        if self._motion_prompt_explicit or not role:
            return self.motion_prompt
        return MOTION_PROMPT_BY_ROLE.get(role, self.motion_prompt)

    def generate(self, audio_wav: Path, out_mp4: Path, width: int = 1080,
                 height: int = 672, role=None, motion_prompt=None,
                 expressiveness=None) -> Path:
        if not self.api_key:
            raise RuntimeError(
                "HeyGen API key не задан: передайте api_key в HeyGenClient "
                "или установите env HEYGEN_API_KEY"
            )

        audio_wav = Path(audio_wav)
        out_mp4 = Path(out_mp4)
        headers = {"X-Api-Key": self.api_key}

        audio_asset_id = self._upload_audio(audio_wav, headers)
        video_url = self._create_video(
            audio_asset_id, headers, role=role,
            motion_prompt=motion_prompt, expressiveness=expressiveness,
        )

        dl_resp = self.http.get(video_url, timeout=30)
        dl_resp.raise_for_status()
        out_mp4.parent.mkdir(parents=True, exist_ok=True)
        out_mp4.write_bytes(dl_resp.content)
        return out_mp4

    def _upload_audio(self, audio_wav: Path, headers: dict) -> str:
        resp = heygen_request(
            self.http, self.sleep, "post", UPLOAD_URL, headers=headers,
            files={"file": (audio_wav.name, audio_wav.read_bytes())},
            timeout=60,
        )
        return resp.json()["data"]["asset_id"]

    def _create_video(self, audio_asset_id: str, headers: dict, *, role=None,
                      motion_prompt=None, expressiveness=None) -> str:
        motion_prompt = motion_prompt or self.motion_prompt_for(role)
        expressiveness = expressiveness or self.expressiveness
        body = (
            self._body_twin(audio_asset_id, motion_prompt, expressiveness)
            if self.look_id
            else self._body_photo(audio_asset_id, motion_prompt, expressiveness)
        )
        resp = heygen_request(
            self.http, self.sleep, "post", CREATE_URL, headers=headers,
            json=body, timeout=30,
        )
        video_id = resp.json()["data"]["video_id"]
        return self._poll(headers, video_id)

    def _body_twin(self, audio_asset_id: str, motion_prompt: str,
                   expressiveness: str | None = None) -> dict:
        """Digital Twin: идентичность держит сам аватар, сцену закреплять нечем
        и незачем (background от фото тут не нужен — фон уже снят на видео)."""
        body = {
            "type": "avatar",
            "avatar_id": self.look_id,
            "audio_asset_id": audio_asset_id,
            "engine": {"type": self.engine},
            "aspect_ratio": "9:16",
            "resolution": self.resolution,
        }
        # Оба поля IV-only по API schema; Avatar V отклоняет extra inputs.
        if self.engine in _ENGINES_WITH_PERFORMANCE_CONTROLS:
            body["motion_prompt"] = motion_prompt
            body["expressiveness"] = expressiveness or self.expressiveness
        return body

    def _body_photo(self, audio_asset_id: str, motion_prompt: str,
                    expressiveness: str | None = None) -> dict:
        body = {
            "type": "image",
            "image": {"type": "asset_id", "asset_id": self.avatar_id},
            "audio_asset_id": audio_asset_id,
            # для type:image движок НЕ шлём: HeyGen v3 отвечает 400 "Extra inputs
            # are not permitted" (param: engine). Avatar IV — серверный дефолт
            # для image, отдельного поля engine схема тут не принимает.
            "resolution": self.resolution,
            "motion_prompt": motion_prompt,
            # закрепляем сцену тем же фото — иначе модель вольна дорисовать
            # случайный фон (вплоть до посторонних людей в кадре)
            "background": {"type": "image", "asset_id": self.avatar_id},
            # dimension сервер не принимает; размер раньше задавало исходное
            # фото — теперь фиксируем явно, плагин целиком про 9:16-рилсы
            "aspect_ratio": "9:16",
        }
        if self.engine in _ENGINES_WITH_PERFORMANCE_CONTROLS:
            body["expressiveness"] = expressiveness or self.expressiveness
        return body

    def _fetch_status(self, video_id: str, headers: dict) -> tuple:
        # retry=False: опрос статуса не ретраится (см. docstring модуля) —
        # цикл ниже и так повторяет запрос секундами позже.
        resp = heygen_request(
            self.http, self.sleep, "get", f"{STATUS_URL}/{video_id}",
            headers=headers, timeout=30, retry=False,
        )
        payload = resp.json()
        data = payload.get("data", payload)
        return data["status"], data.get("video_url")

    def _poll(self, headers: dict, video_id: str) -> str:
        elapsed = 0.0
        while elapsed < POLL_MAX_WAIT_S:
            status, video_url = self._fetch_status(video_id, headers)
            if status == "completed":
                return video_url
            if status == "failed":
                raise RuntimeError(f"HeyGen video generation failed (video_id={video_id})")
            interval = _poll_interval(elapsed)
            self.sleep(interval)
            elapsed += interval
        raise HeyGenRenderTimeout(
            f"HeyGen video generation timed out after {POLL_MAX_WAIT_S} с "
            f"(video_id={video_id}); заказ на стороне HeyGen жив и оплачен",
            video_id,
        )


def render_covered_block(audio_wav: Path, out_mp4: Path, width: int = 1080, height: int = 1920) -> Path:
    """Замена HeyGen-рендера для блока формата avatar, который на 100% закрыт
    вставкой видеоряда (plan_avatar_inserts берёт вставку строго на весь
    [start,end] блока — под ней в принципе ничего не видно). Голос из
    audio_wav вшивается в чёрный кадр той же длительности одним локальным
    ffmpeg-проходом — без HeyGen, без сети, без затрат.
    """
    from reels_factory.config import FFMPEG
    from reels_factory.render import run, media_dur

    audio_wav = Path(audio_wav)
    out_mp4 = Path(out_mp4)
    dur = media_dur(str(audio_wav))
    cmd = [
        FFMPEG, "-y",
        "-f", "lavfi", "-i", f"color=c=black:s={width}x{height}:d={dur}",
        "-i", str(audio_wav),
        "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-pix_fmt", "yuv420p",
        "-video_track_timescale", "30000",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
        "-shortest", str(out_mp4),
    ]
    run(cmd)
    return out_mp4


def avatar_cache_key(client: HeyGenClient, audio_wav: Path, role=None,
                     motion_prompt=None, expressiveness=None) -> str:
    """Stable identity for one paid render input, including IV controls."""
    audio_wav = Path(audio_wav)
    audio_sha1 = hashlib.sha1(audio_wav.read_bytes()).hexdigest()
    # getattr — чтобы ключ считался и для облегчённых дублей клиента в тестах
    effective_prompt = motion_prompt or (
        client.motion_prompt_for(role)
        if hasattr(client, "motion_prompt_for")
        else client.motion_prompt
    )
    effective_expressiveness = expressiveness or getattr(
        client, "expressiveness", DEFAULT_EXPRESSIVENESS
    )
    supports_performance = (
        getattr(client, "engine", None) in _ENGINES_WITH_PERFORMANCE_CONTROLS
    )
    performance_key = (
        f"{effective_prompt}|{effective_expressiveness}"
        if supports_performance else "provider-default-performance"
    )
    return hashlib.sha1(
        f"{audio_sha1}|{client.avatar_id}|{getattr(client, 'look_id', None)}"
        f"|{getattr(client, 'engine', None)}|{getattr(client, 'resolution', None)}"
        f"|{performance_key}"
        .encode("utf-8")
    ).hexdigest()[:16]


def cached_generate(client: HeyGenClient, audio_wav: Path, cache_dir: Path,
                    role=None, motion_prompt=None, expressiveness=None) -> Path:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    audio_wav = Path(audio_wav)
    key = avatar_cache_key(
        client,
        audio_wav,
        role=role,
        motion_prompt=motion_prompt,
        expressiveness=expressiveness,
    )
    out_mp4 = cache_dir / f"{key}.mp4"
    with _CACHE_LOCKS_GUARD:
        lock = _CACHE_LOCKS.setdefault(str(out_mp4.resolve()), threading.Lock())
    with lock:
        if out_mp4.exists():
            return out_mp4
        kwargs = {"role": role}
        # Не передаём новые kwargs старым test doubles/legacy callers без нужды.
        if motion_prompt is not None:
            kwargs["motion_prompt"] = motion_prompt
        if expressiveness is not None:
            kwargs["expressiveness"] = expressiveness
        temporary = cache_dir / f".{key}.{os.getpid()}.tmp.mp4"
        try:
            generated = Path(client.generate(audio_wav, temporary, **kwargs))
            if not generated.is_file():
                raise RuntimeError(f"HeyGen не создал cache output: {generated}")
            generated.replace(out_mp4)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return out_mp4
