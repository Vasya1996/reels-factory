"""Сток и генерация медиа через скил media-use.

Планировщик уже решил, ЧТО показать (запрос). Здесь узкая агентская сессия
находит или генерирует один вертикальный файл. Кэш — по запросу: одна тема
не должна оплачиваться и искаться дважды.
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

_MEDIA_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".mp4", ".webm")

PROMPT = """/media-use

Найди или сгенерируй ОДИН вертикальный медиафайл (изображение или короткое
видео) под кадр 1080×1920 по запросу: «{query}».

Требования:
- файл сохрани в текущую папку; ровно один файл, никаких превью и вариантов;
- без текста и водяных знаков в кадре;
- ничего не спрашивай, реши сам и закончи.
"""


def stock_cache_dir() -> Path:
    return Path.home() / ".reels-factory" / "stock-cache"


def _cache_key(query: str) -> str:
    normalized = " ".join(str(query or "").lower().split())
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]


def _find_media(directory: Path) -> Path | None:
    files = [
        path
        for path in sorted(directory.iterdir())
        if path.is_file() and path.suffix.lower() in _MEDIA_SUFFIXES
    ]
    return files[0] if files else None


def resolve_stock(query: str, work_dir, *, runner=None) -> Path:
    """Вернуть файл по запросу: из кэша либо новой media-use-сессией."""
    from reels_factory.hf_agent import HeyGenAgentRunner

    query = " ".join(str(query or "").split())
    if not query:
        raise ValueError("media-use требует непустой запрос")

    key = _cache_key(query)
    cache = stock_cache_dir() / key
    cached = _find_media(cache) if cache.exists() else None
    if cached is not None:
        return cached

    session_dir = Path(work_dir) / f"stock-{key}"
    session_dir.mkdir(parents=True, exist_ok=True)
    runner = runner or HeyGenAgentRunner()
    runner.run(PROMPT.format(query=query), cwd=session_dir)

    found = _find_media(session_dir)
    if found is None:
        raise RuntimeError(
            f"media-use не вернул файла по запросу «{query}» в {session_dir}"
        )
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / found.name
    shutil.copyfile(found, target)
    return target
