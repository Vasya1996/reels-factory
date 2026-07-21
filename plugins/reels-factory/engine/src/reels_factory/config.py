"""Пути, константы рендера и чтение пользовательского конфига.

ffmpeg/ffprobe: сначала ищем в PATH (`shutil.which`), затем — фолбэк на winget-
сборку Gyan.FFmpeg (Windows). WORK_ROOT — рабочая папка ПОЛЬЗОВАТЕЛЯ (cwd проекта,
не пакет); туда движок кладёт `work/` и читает `factory/config.yaml`.
"""
import os
import shutil
from pathlib import Path

import yaml


def _resolve(exe: str) -> str:
    """Путь к ffmpeg/ffprobe: PATH первичен, winget-сборка — фолбэк, иначе имя."""
    found = shutil.which(exe)
    if found:
        return found
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    if base.exists():
        for cand in base.glob(f"Gyan.FFmpeg*/**/{exe}.exe"):
            return str(cand)
    return exe


FFMPEG = _resolve("ffmpeg")
FFPROBE = _resolve("ffprobe")

# Рабочая папка проекта пользователя (cwd), НЕ каталог пакета.
WORK_ROOT = Path.cwd() / "work"
# Пользовательская память фабрики (markdown/yaml, в git проекта пользователя).
FACTORY_DIR = Path.cwd() / "factory"
CONFIG_PATH = FACTORY_DIR / "config.yaml"

# Константы рендера — не менять без причины.
OUT_W, OUT_H = 1080, 1920
FPS = 30
LUFS_TARGET = -14.0
TP_TARGET = -1.5
CAPTION_FONT = "Arial Black"

FORMATS = ("split", "fullscreen", "avatar")


class ConfigError(Exception):
    pass


def load_config(path=None) -> dict:
    """Прочитать и провалидировать factory/config.yaml.

    Обязательные поля: theme, format (split|fullscreen|avatar), voice_id,
    persona.description, product.name, product.cta_phrase; для split и avatar
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
    if not str(product.get("cta_phrase") or "").strip():
        raise ConfigError(
            "Поле product.cta_phrase (дословная фраза призыва) обязательно в config.yaml."
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
    return cfg
