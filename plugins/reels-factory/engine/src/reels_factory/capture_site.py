"""Снимок сайта как источник достоверной вставки.

Движок снимает страницу: кадры по мере прокрутки, саму страницу, шрифты и
цвета. Ключей и денег это не требует. Кэшируем по адресу — иначе на популярной
теме мы пойдём на один сайт сотни раз.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

from reels_factory.hf_render import _cli


def cache_key(url: str) -> str:
    return hashlib.sha1(url.strip().rstrip("/").lower().encode("utf-8")).hexdigest()[:16]


def _result(out_dir: Path) -> dict:
    shots = sorted((out_dir / "screenshots").glob("scroll-*.png"))
    return {"dir": str(out_dir), "screenshots": [str(p) for p in shots],
            "page": str(out_dir / "extracted" / "page.html")}


def capture(url: str, out_dir) -> dict:
    """Снять сайт. Возвращает кадры прокрутки и сохранённую страницу."""
    out_dir = Path(out_dir)
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    _cli("capture", url, "-o", str(out_dir), "--timeout", "120000",
         "--max-screenshots", "8", cwd=out_dir.parent)
    return _result(out_dir)


def cached_capture(url: str, cache_dir, max_age_days: int = 7) -> dict:
    """Снять сайт, если свежего снимка нет."""
    target = Path(cache_dir) / cache_key(url)
    shots = sorted((target / "screenshots").glob("scroll-*.png")) if target.exists() else []
    if shots and (time.time() - shots[0].stat().st_mtime) / 86400 <= max_age_days:
        return _result(target)
    return capture(url, target)
