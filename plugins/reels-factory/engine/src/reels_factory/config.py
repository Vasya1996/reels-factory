"""Пути, константы рендера и чтение пользовательского конфига.

ffmpeg/ffprobe: сначала ищем в PATH (`shutil.which`), затем — фолбэк на winget-
сборку Gyan.FFmpeg (Windows). WORK_ROOT — рабочая папка ПОЛЬЗОВАТЕЛЯ (cwd проекта,
не пакет); туда движок кладёт `work/` и читает `factory/config.yaml`.
"""
import os
import shutil
from pathlib import Path

import yaml

from reels_factory.language import SUPPORTED_LANGUAGES


def _resolve(exe: str) -> str:
    """Путь к ffmpeg/ffprobe: PATH первичен, winget-сборка — фолбэк, иначе имя."""
    found = shutil.which(exe)
    if found:
        return found
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    try:
        if base.exists():
            for cand in base.glob(f"Gyan.FFmpeg*/**/{exe}.exe"):
                return str(cand)
    except PermissionError:
        # Restricted worker/test accounts may see LOCALAPPDATA but cannot stat
        # another user's WinGet package directory. PATH/final executable name
        # remain valid fallbacks.
        pass
    return exe


FFMPEG = _resolve("ffmpeg")
FFPROBE = _resolve("ffprobe")


def cli_env() -> dict:
    """Окружение для их CLI и их скриптов подбора.

    Телеметрию гасим их же выключателем: и CLI, и `resolve` шлют события в
    PostHog, а после входа в HeyGen события связываются с почтой аккаунта, чьи
    ключи стоят у пользователя. Переменная — их канон, ей же они глушат
    телеметрию в своём CI (`.github/workflows/ci.yml:10`, документирована в
    `docs/guides/feedback.mdx:209` и `hyperframes-cli/references/
    upgrade-info-misc.md:60`). Значение из окружения уважаем: включить обратно
    можно осознанно, поставив `HYPERFRAMES_NO_TELEMETRY=0`.

    `~/.local/bin` дописываем в `PATH` сами: их установщик кладёт `heygen`
    именно туда, а systemd даёт службе голый путь без него. Мы зовём CLI по
    имени и ловим только ненулевой код возврата — отсутствие бинарника летит
    исключением, и первый же подбор картинки роняет сборку. В консоли и в WSL
    этого не видно: там путь в `PATH` есть, и разница вылезала бы только на
    сервере.
    """
    env = {"HYPERFRAMES_NO_TELEMETRY": "1", **os.environ}
    local_bin = Path.home() / ".local" / "bin"
    parts = env.get("PATH", "").split(os.pathsep)
    if local_bin.is_dir() and str(local_bin) not in parts:
        env["PATH"] = os.pathsep.join([str(local_bin), *parts])
    return env

# Рабочая папка проекта пользователя (cwd), НЕ каталог пакета.
WORK_ROOT = Path.cwd() / "work"
# Пользовательская память фабрики (markdown/yaml, в git проекта пользователя).
FACTORY_DIR = Path.cwd() / "factory"
CONFIG_PATH = FACTORY_DIR / "config.yaml"

# Корень плагина (skills/, .claude-plugin/) — для вызова скиллов движком
# через `claude -p --plugin-dir`. engine/src/reels_factory/ -> вверх 3 уровня.
PLUGIN_DIR = Path(__file__).resolve().parents[3]

# Константы рендера — не менять без причины.
OUT_W, OUT_H = 1080, 1920
FPS = 30
LUFS_TARGET = -14.0

#: Насколько громкость готового ролика может разойтись с целью, чтобы гейт D3
#: всё ещё считал звук исправным. Три децибела, а не полтора, потому что за
#: нас доигрывает площадка: Ютуб держит ту же ссылку -14 LUFS и приглушает всё,
#: что громче, а тихое оставляет как есть — «some sites (including YouTube and
#: TIDAL) don't turn quieter songs up» (MeterPlugs,
#: https://www.meterplugs.com/blog/2019/09/18/youtube-changes-loudness-reference-to-14-lufs.html).
#: У Инстаграма и ТикТока ссылка та же -14, а в ленте они жмут ещё сильнее, и
#: практика доставки туда идёт около -14…-10. То есть коридор -17…-11 — это
#: «звучит чуть иначе», и промах в полдецибела ролика не портит: боевой ролик
#: на -15.93 падал на 0.43 дБ впустую и теперь проходит.
#: Гейт держим ради настоящей поломки, и её он ловит с запасом: прогон на
#: -34.9 (почти тишина) и раздавленные -5 остаются за коридором.
LUFS_TOLERANCE = 3.0

#: Потолок веса готового ролика. Telegram Bot API не берёт ни видео, ни
#: документ тяжелее 50 МБ (https://core.telegram.org/bots/api#sending-files),
#: а ролик, который в него не влез, доставить нечем: пересборка веса не меняет,
#: и кнопки продолжения на этой стадии нет (`delivery_too_big` в bot.py).
#: Поэтому вес ограничивает сама сборка — `_fit_delivery_size` в hf_render.py.
MAX_DELIVERY_BYTES = 50 * 1024 * 1024

TP_TARGET = -1.5
CAPTION_FONT = "Arial Black"

FORMATS = ("split", "fullscreen", "avatar")

# Монтажный слой (edit.* в config.yaml). Шаги с внешними зависимостями или
# меняющие картинку целиком (jump_cuts, grade, grain) выключены по умолчанию.
# Чисто ffmpeg-овые монтажные приёмы (zoom, flash) включены: без них ролик
# читается как несмонтированный — статичная голова без движения и переходов;
# откатываются тем же флагом без правки кода.
EDIT_DEFAULTS = {
    "jump_cuts": False,   # вырезать паузы внутри фрагментов (нужен auto-editor)
    "grade": False,       # единый цвет на весь ролик
    "grain": False,       # микро-зерно: снимает стерильность генерации
    "keep_raw": True,     # рядом с out.mp4 класть out_raw.mp4 — сравнить до/после
    "zoom": True,         # наезды по фразам (push/punch/pulse, лицо) + ритм-добивка
    "flash": True,        # световой переход на границах блоков + свуш
}


def edit_settings(cfg: dict) -> dict:
    """Флаги монтажа с дефолтами. Неизвестные ключи игнорируются молча —
    конфиг пользователя не должен падать из-за опечатки в необязательной секции.
    """
    user = (cfg or {}).get("edit") or {}
    return {k: user.get(k, v) for k, v in EDIT_DEFAULTS.items()}


class ConfigError(Exception):
    pass


def load_config(path=None) -> dict:
    """Прочитать и провалидировать factory/config.yaml.

    Обязательные поля: theme, format (split|fullscreen|avatar), voice_id,
    persona.description, product.name; для split и avatar
    дополнительно avatar.heygen_asset_id. Ошибки — понятным текстом на русском.
    """
    path = Path(path) if path else CONFIG_PATH
    if not path.exists():
        raise ConfigError(
            f"Конфиг не найден: {path}. Запусти мастер настройки /reels-factory:setup."
        )
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    if not isinstance(cfg, dict):
        raise ConfigError(f"Конфиг {path} должен быть YAML-объектом (ключ: значение).")

    fmt = cfg.get("format")
    if fmt not in FORMATS:
        raise ConfigError(
            f"Поле format должно быть одним из {FORMATS}, сейчас: {fmt!r}."
        )
    if not str(cfg.get("theme") or "").strip():
        raise ConfigError("Поле theme (тема рилсов) обязательно в config.yaml.")
    if not str(cfg.get("voice_id") or "").strip():
        raise ConfigError("Поле voice_id (голос ElevenLabs) обязательно в config.yaml.")

    persona = cfg.get("persona") or {}
    if not str(persona.get("description") or "").strip():
        raise ConfigError(
            "Поле persona.description (кто ведёт ролик — описание персонажа) "
            "обязательно в config.yaml."
        )

    product = cfg.get("product") or {}
    if not str(product.get("name") or "").strip():
        raise ConfigError("Поле product.name (имя продукта) обязательно в config.yaml.")
    # cta_phrase опционален: CTA в пути генерации пишется под каждый ролик,
    # в пути «дословно» не добавляется вовсе (см. spec 2026-07-21).

    lang = str(cfg.get("language") or "ru").strip().lower()
    if lang not in SUPPORTED_LANGUAGES:
        raise ConfigError(
            "Поле language должно быть одним из поддерживаемых языков "
            f"{tuple(SUPPORTED_LANGUAGES)}, сейчас: {cfg.get('language')!r}."
        )
    cfg["language"] = lang
    voice_language = str(cfg.get("voice_language") or "").strip().lower()
    if voice_language and voice_language != lang:
        raise ConfigError(
            f"voice_language ({voice_language!r}) должен совпадать с language "
            f"({lang!r})."
        )
    if voice_language:
        cfg["voice_language"] = voice_language

    voices = cfg.get("voices")
    if voices is not None:
        if not isinstance(voices, dict):
            raise ConfigError("Поле voices должно быть YAML-объектом: ru/kk -> voice_id.")
        normalized_voices = {}
        for code, voice_id in voices.items():
            normalized_code = str(code or "").strip().lower()
            normalized_id = str(voice_id or "").strip()
            if normalized_code not in SUPPORTED_LANGUAGES or not normalized_id:
                raise ConfigError(
                    "В voices разрешены только непустые voice_id для языков "
                    f"{tuple(SUPPORTED_LANGUAGES)}."
                )
            normalized_voices[normalized_code] = normalized_id
        active_voice = str(cfg.get("voice_id") or "").strip()
        if normalized_voices.get(lang) != active_voice:
            raise ConfigError(
                f"voices[{lang!r}] должен совпадать с активным voice_id."
            )
        cfg["voices"] = normalized_voices

    tts_language = str(((cfg.get("tts") or {}).get("language_code") or lang)).strip().lower()
    if tts_language != lang:
        raise ConfigError(
            f"tts.language_code ({tts_language!r}) должен совпадать с language "
            f"({lang!r})."
        )

    if fmt in ("split", "avatar"):
        avatar = cfg.get("avatar") or {}
        has_look = str(avatar.get("heygen_look_id") or "").strip()
        has_photo = str(avatar.get("heygen_asset_id") or "").strip()
        if not (has_look or has_photo):
            raise ConfigError(
                f"Для формата {fmt} нужен avatar.heygen_look_id "
                "(id лука Digital Twin — предпочтительно, качество выше) "
                "или avatar.heygen_asset_id (id фото-ассета аватара)."
            )
        islands = cfg.get("avatar_islands") or {}
        if islands.get("enabled"):
            if has_look:
                raise ConfigError(
                    "avatar_islands сейчас поддерживает только Photo Avatar IV: "
                    "убери avatar.heygen_look_id и задай heygen_asset_id."
                )
            if not has_photo:
                raise ConfigError(
                    "avatar_islands требует avatar.heygen_asset_id фото-аватара."
                )
            engine = str(avatar.get("engine") or "avatar_iv").strip().lower()
            if engine != "avatar_iv":
                raise ConfigError(
                    "avatar_islands сейчас поддерживает только engine: avatar_iv."
                )
    return cfg


# Биллинг: ставки провайдеров и наценка. Обновляются руками при смене прайса
# провайдера — автоматического источника цен для HeyGen/ElevenLabs не существует.
BILLING_DEFAULTS = {
    "enabled": True,
    "markup": 2.0,
    "rates": {
        "heygen_usd_per_second": 0.05,
        "heygen_twin_usd_per_second": 0.0667,
        "elevenlabs_usd_per_1k_chars": 0.10,
        # Замер по 8 прод-заданиям (2026-09-03, метод — как у WORDS_PER_SEC в
        # scenario.py:66): знаков/с легли в 13.62-20.26 (ru p25=16.40,
        # медиана=16.68, p75=17.39; kk n=1: 15.12). Расходится с 14.0 больше
        # чем на 10%, но не в опасную сторону: 14.0 НИЖЕ всего измеренного,
        # значит seconds = chars/14.0 уже переоценивает длительность (и цену)
        # относительно факта — тот же принцип «запас вверх», что и у
        # claude_flat_usd_per_reel ниже. Поднять до замера значило бы снять
        # запас, а не найти баг: здесь не он. Оставляем 14.0.
        "chars_per_second": 14.0,
        # Работа Клода в предварительной оценке. claude_flat_usd_per_reel —
        # подготовка сценария (генерация, хуманизатор, судья), по журналу
        # списаний $0,07…$0,14 за проход, с запасом вверх: оценка на экране
        # цены не должна оказаться ниже того, что спишется по факту.
        "claude_flat_usd_per_reel": 0.15,
        # claude_montage_usd_per_reel/attempts — себестоимость агента монтажа
        # (план + отбор бироллов). С этой задачи (Task 7, квота с кнопки
        # списывается одной строкой, JobMeter только считает себестоимость)
        # эти два числа больше не защищают баланс клиента от минуса — это
        # делает quoted_micro — а определяют маржу: заниженные, они и дали
        # Артёма/Nagimash в минус при старой схеме факта.
        #
        # Замер по 7 доставленным монтажным job из копии billing.sqlite3
        # (2026-09-03, root@134.209.80.75, метод и таблица — scratchpad
        # billing-measure.md той же сессии; cost_micro, не charged_micro —
        # без наценки 2.0х). Себестоимость ролика (все сессии job), n=7:
        #   медиана $2.85   среднее $3.02   p75 $4.39
        # (без выброса e00b740b — известный, частично устранённый баг темпа,
        # 4 сессии вместо обычной одной — p75 по оставшимся 6 всё ещё $4.00).
        #
        # С квоты (Task 7, quoted_micro списывается одной строкой с кнопки)
        # эти два числа больше не защищают баланс клиента от минуса — это
        # делает quoted_micro — они определяют маржу: названная цена и есть
        # цена, а перерасход агента сверх провизии съедает нашу маржу, не
        # клиентский баланс. Поэтому ориентир — не медиана и не среднее (обе
        # ниже показывают, что от них зависла бы примерно половина job в
        # минус маржи), а p75: провизия должна закрывать верхнюю четверть
        # факта, а не типичный случай.
        #
        # Решение Васи 03.09.2026: в цену закладывается $2 на ролик; разница с
        # фактом (медиана $2,85, p75 $4,39) — наша маржа, названная цена
        # окончательна (см. billing.py JobMeter).
        "claude_montage_usd_per_reel": 1.00,
        # Сколько раз агент монтажа отрабатывает за один ролик. Проверка плана
        # до заказа аватара даёт агенту одну пересдачу, и пересдача — это
        # второй полный проход: заново план и заново отбор бироллов. Пересдача
        # штатна, а не аварийна, поэтому она заложена в цену: иначе каждая
        # уводит маржу в минус, а человеку названа цифра, которая её не
        # покрывает. Замер (выше) не даёт оснований поднимать дальше 2: 6 из 7
        # доставленных job обошлись одной сессией, а единственная с четырьмя —
        # известный частично устранённый баг, не типичный случай. Ставка
        # одного прохода рядом остаётся сверяемой с журналом списаний, потому
        # что проходы считаются отдельным множителем.
        "claude_montage_attempts": 2,
        # Запасной счёт работы Клода — на случай, когда CLI прислал нулевую
        # стоимость (так бывает под подпиской). Токены умножаются на публичный
        # прайс API (platform.claude.com/docs/en/about-claude/models/overview,
        # сверено 14.08.2026), доллары за миллион токенов.
        "claude_models_usd_per_mtok": {
            "claude-opus-5": {"input": 5.0, "output": 25.0},
            "claude-opus-4-8": {"input": 5.0, "output": 25.0},
            "claude-sonnet-5": {"input": 3.0, "output": 15.0},
            "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
            "claude-haiku-4-5": {"input": 1.0, "output": 5.0},
        },
        # Модель, по прайсу которой считаем, когда сессия не назвала свою:
        # headless берёт модель профиля, и в ответе её имени может не быть.
        "claude_default_model": "claude-sonnet-5",
        # Кэш промпта: запись дороже обычного входа, чтение — почти даром.
        # Множители их же (build-with-claude/prompt-caching): запись 1,25× при
        # пятиминутном сроке жизни и 2× при часовом, чтение 0,1×. Сессия агента
        # живёт часами и пишет кэш на час — на её счёте разница двукратная.
        "claude_cache_write_multiplier": 1.25,
        "claude_cache_write_1h_multiplier": 2.0,
        "claude_cache_read_multiplier": 0.1,
        # Ожидаемая доля ролика, где аватар в кадре, при включённых avatar
        # islands. Только для предварительной оценки перед сборкой — не
        # источник биллинга.
        #
        # Число то же самое, что `AVATAR_ON_SCREEN_HARD_MAX` в hf_montage.py, —
        # ГРАНИЦА, выше которой план заворачивает гейт бюджета
        # (`D29_avatar_budget`), а не ориентир 60 %, куда целится агент.
        # Считать по ориентиру нельзя: план, вставший в разрешённую полосу
        # 60–70 %, доедет до заказа, и человеку было бы названо меньше, чем
        # спишется. Импортировать константу отсюда нельзя — цепочка
        # `hf_montage` → `hf_layout` → `config` замкнулась бы; равенство держит
        # `test_доля_ведущей_в_оценке_равна_границе_гейта` (tests/test_billing.py).
        #
        # Замер по тем же 7 job (scratchpad billing-measure.md, 2026-09-03,
        # heygen-секунды / оценка длительности по elevenlabs-символам):
        # среднее 0.635, медиана 0.666, диапазон 0.495–0.742 — в границе
        # 62–72 %, которую Вася называл после правок пачки 1. Оставлено 0.7:
        # число привязано к гейту выше, менять его отдельно от гейта нельзя.
        "avatar_visible_share": 0.7,
    },
    # xtr (Telegram Stars) намеренно НЕ в таблице: цифровые товары Tribute
    # покупаются только за звёзды, но в вебхуке приходит цена товара в валюте
    # прайса (в примере из их доки — usd/центы). Если событие всё же придёт в
    # звёздах, неизвестно, шлют их штуками или «минимальными единицами» —
    # ошибка в сто раз в любую сторону хуже, чем незачисленный платёж,
    # который виден в логе целиком и правится за минуту.
    "fx": {"usd": 1.0, "eur": 1.08, "rub": 0.011},
}


def load_billing_config() -> dict:
    """Секция billing из factory/config.yaml поверх дефолтов.

    Отсутствие файла — не ошибка: биллинг должен работать и на чистой машине.
    """
    merged = {
        "enabled": BILLING_DEFAULTS["enabled"],
        "markup": BILLING_DEFAULTS["markup"],
        "rates": dict(BILLING_DEFAULTS["rates"]),
        "fx": dict(BILLING_DEFAULTS["fx"]),
    }
    try:
        raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return merged
    section = raw.get("billing") or {}
    if "enabled" in section:
        merged["enabled"] = bool(section["enabled"])
    if "markup" in section:
        merged["markup"] = float(section["markup"])
    merged["rates"].update(section.get("rates") or {})
    merged["fx"].update(section.get("fx") or {})
    return merged
