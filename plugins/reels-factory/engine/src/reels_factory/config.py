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
        "chars_per_second": 14.0,
        "claude_flat_usd_per_reel": 0.05,
        # Ожидаемая доля ролика, где аватар в кадре, при включённых avatar
        # islands. Только для предварительной оценки перед сборкой — не
        # источник биллинга.
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
