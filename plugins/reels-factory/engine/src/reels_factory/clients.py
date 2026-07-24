"""Реестр клиентов — несколько профилей config под разных людей.

Зачем: базовый движок работает с ОДНИМ клиентом через factory/config.yaml
(его voice_id + avatar.heygen_look_id/heygen_asset_id). Для потока клиентов
этого мало — нужен способ держать много профилей и переключаться по id.

Решение в их же парадигме: каждый клиент — свой файл factory/clients/<id>.yaml
ТОГО ЖЕ формата и с той же валидацией (load_config). Команды script/make/verify
с флагом --client <id> берут профиль клиента вместо дефолтного config.yaml —
двойник и голос подставляются по id, ничего не хардкодя.

Режим клиента определяется тем, что задано в avatar:
  heygen_look_id  -> video  (Digital Twin, Avatar V — качество выше);
  heygen_asset_id -> photo  (Photo Avatar, Avatar IV — без consent и слотов).

Онбординг самого аватара остаётся в twin.py (видео -> Digital Twin -> look_id):
получив look_id (или asset_id залитого фото), кладём его в профиль клиента через
register_client(..., look_id=... | asset_id=...). Сетевой логики тут нет — только
профили; поэтому модуль полностью юнит-тестируем.
"""
import copy
from pathlib import Path

import yaml

from reels_factory.config import FACTORY_DIR, load_config, ConfigError

# Каталог профилей клиентов внутри пользовательской factory/ (в git проекта).
CLIENTS_DIR = FACTORY_DIR / "clients"


def _safe_id(client_id: str) -> str:
    """id идёт в имя файла — без слэшей и точек-в-начале, чтобы не выйти из папки."""
    cid = str(client_id or "").strip()
    if not cid or "/" in cid or "\\" in cid or cid.startswith("."):
        raise ConfigError(f"Недопустимый client_id: {client_id!r}")
    return cid


def client_path(client_id: str) -> Path:
    return CLIENTS_DIR / f"{_safe_id(client_id)}.yaml"


def avatar_mode(cfg: dict) -> str:
    """Режим по содержимому avatar: look_id -> video, asset_id -> photo."""
    avatar = (cfg or {}).get("avatar") or {}
    if str(avatar.get("heygen_look_id") or "").strip():
        return "video"
    if str(avatar.get("heygen_asset_id") or "").strip():
        return "photo"
    return "unknown"


def load_client(client_id: str) -> dict:
    """Профиль клиента с ТОЙ ЖЕ валидацией, что и обычный конфиг."""
    path = client_path(client_id)
    if not path.exists():
        raise ConfigError(
            f"Клиент {client_id!r} не найден ({path}). "
            f"Заведи его: python -m reels_factory clients add {client_id} ..."
        )
    return load_config(path)


def list_clients() -> list:
    """Краткая сводка по каждому профилю: id, имя, режим, голос, аватар-id.
    Битые/невалидные yaml не роняют список — попадают с mode='unknown'."""
    if not CLIENTS_DIR.exists():
        return []
    out = []
    for p in sorted(CLIENTS_DIR.glob("*.yaml")):
        try:
            cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            if not isinstance(cfg, dict):
                cfg = {}
        except (OSError, yaml.YAMLError):
            cfg = {}
        avatar = cfg.get("avatar") or {}
        out.append({
            "id": p.stem,
            "name": cfg.get("name") or (cfg.get("persona") or {}).get("name"),
            "mode": avatar_mode(cfg),
            "voice_id": cfg.get("voice_id"),
            "look_id": avatar.get("heygen_look_id"),
            "asset_id": avatar.get("heygen_asset_id"),
        })
    return out


def register_client(client_id: str, base: dict, *, name=None, voice_id=None,
                    look_id=None, asset_id=None, overwrite=False) -> Path:
    """Создать/обновить профиль клиента из базового конфига с переопределением
    голоса и аватара. Записанное валидируется тем же load_config. Возвращает путь.

    base   — обычно уже прочитанный factory/config.yaml (шаблон бренда/продукта:
             theme/persona/product тянутся оттуда, чтобы не задавать заново).
    look_id / asset_id — двойник (video) ИЛИ фото (photo). look_id главнее:
             если задан, heygen_asset_id из базы убираем, чтобы режим был явным.
    """
    cid = _safe_id(client_id)
    path = client_path(cid)
    if path.exists() and not overwrite:
        raise ConfigError(
            f"Клиент {cid!r} уже есть ({path}). Передай overwrite=True для замены."
        )
    if not (look_id or asset_id):
        # без аватара профиль бесполезен и не пройдёт валидацию формата avatar/split
        base_avatar = (base or {}).get("avatar") or {}
        if not (base_avatar.get("heygen_look_id") or base_avatar.get("heygen_asset_id")):
            raise ConfigError(
                "Нужен аватар клиента: передай look_id (Digital Twin) или "
                "asset_id (фото). Двойник создаётся отдельно — см. twin.py."
            )

    cfg = copy.deepcopy(base or {})
    if name:
        cfg["name"] = name
    if voice_id:
        cfg["voice_id"] = voice_id
    if look_id or asset_id:
        avatar = dict(cfg.get("avatar") or {})
        if look_id:
            avatar["heygen_look_id"] = look_id
            avatar.pop("heygen_asset_id", None)  # video-режим: убираем фото из базы
        else:
            avatar["heygen_asset_id"] = asset_id
            avatar.pop("heygen_look_id", None)   # photo-режим: убираем двойника из базы
        cfg["avatar"] = avatar

    CLIENTS_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")

    # записанный профиль обязан проходить тот же валидатор, что и обычный конфиг;
    # если нет — не оставляем битый файл в реестре
    try:
        load_config(path)
    except ConfigError:
        path.unlink(missing_ok=True)
        raise
    return path


def clear_client_voice(client_id: str) -> None:
    """Убрать voice_id из профиля клиента — когда клон в ElevenLabs удалён,
    профиль не должен молча ссылаться на несуществующий голос. Без voice_id
    load_config/load_client честно упадёт («поле обязательно»), а не 404 при
    сборке. Файла нет — тихо ничего не делаем."""
    path = client_path(client_id)
    if not path.exists():
        return
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(cfg, dict) or "voice_id" not in cfg:
        return
    cfg.pop("voice_id", None)
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
