"""Наполнение b-roll библиотеки со стоков (Pexels Video API).

Скачивает вертикальные клипы под нишевые запросы и готовит их к рендеру:
перекодирует в 30fps H.264 с `+faststart` — иначе headless-Chromium Revideo не
читает длительность («max timestamp 0», см. memory revideo-gotchas). Клипы
кладутся в `broll_library/` под каноничными именами; описание/эмбеддинги —
следующий шаг (`broll_index.index_library`).

Ключ: переменная окружения `PEXELS_API_KEY` (бесплатный, https://www.pexels.com/api/).
Без ключа модуль не делает сетевых запросов — поднимает понятную ошибку.
Лицензия Pexels — свободное коммерческое использование без атрибуции.

Запуск:  python -m reels_factory.broll_fetch --per-query 3
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

from reels_factory import broll_library as lib
from reels_factory.config import FFMPEG

PEXELS_SEARCH = "https://api.pexels.com/videos/search"

# Нишевые запросы под контент @julia.agents (ИИ-агенты, автоматизация, продукт).
# По-английски — Pexels индексирует стоки в основном английскими тегами.
NICHE_QUERIES = [
    "typing keyboard closeup", "laptop working desk", "artificial intelligence",
    "robot technology", "data dashboard screen", "programming code screen",
    "smartphone app scrolling", "writing notes notebook", "team meeting office",
    "abstract technology background", "server data center", "hands using phone",
    "business handshake deal", "charts graphs analytics", "gears mechanism",
    "digital network connection", "video call remote work", "coffee desk laptop",
    "person thinking idea", "startup office people",
]


def _require_key() -> str:
    key = os.environ.get("PEXELS_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "нет PEXELS_API_KEY. Заведи бесплатный ключ на https://www.pexels.com/api/ "
            "и задай переменную окружения PEXELS_API_KEY, затем повтори."
        )
    return key


def search(query: str, key: str, per_query: int = 3,
           orientation: str = "portrait") -> list[dict]:
    """Вернуть до per_query видео-результатов Pexels по запросу."""
    params = urllib.parse.urlencode({
        "query": query, "orientation": orientation,
        "per_page": per_query, "size": "medium",
    })
    # User-Agent обязателен — без него WAF Pexels отдаёт 403.
    req = urllib.request.Request(
        f"{PEXELS_SEARCH}?{params}",
        headers={"Authorization": key, "User-Agent": "Mozilla/5.0 (reels-factory-broll)"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode("utf-8"))
    return data.get("videos", [])


def _best_file(video: dict) -> str | None:
    """Выбрать вертикальный HD-вариант (портрет, высота 1280-1920)."""
    files = video.get("video_files", [])
    portrait = [f for f in files if (f.get("height") or 0) >= (f.get("width") or 0)]
    pool = portrait or files
    pool = [f for f in pool if f.get("link")]
    if not pool:
        return None
    # ближе всего к 1920 по высоте, но не 4K (тяжело перекодировать на CPU)
    pool.sort(key=lambda f: abs((f.get("height") or 0) - 1600))
    return pool[0]["link"]


def _download(url: str, dst: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "reels-factory-broll/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(dst, "wb") as f:
        while chunk := r.read(1 << 16):
            f.write(chunk)


def _transcode(src: Path, dst: Path) -> bool:
    """30fps H.264 +faststart — обязательное условие чтения в headless-рендере."""
    try:
        subprocess.run(
            [FFMPEG, "-y", "-i", str(src), "-r", "30", "-c:v", "libx264",
             "-preset", "veryfast", "-crf", "23", "-an",
             "-movflags", "+faststart", str(dst)],
            capture_output=True, check=True,
        )
        return dst.exists() and dst.stat().st_size > 0
    except subprocess.CalledProcessError:
        return False


def fetch(queries: list[str] | None = None, *, per_query: int = 3,
          library_dir: Path | str | None = None, on_progress=None) -> list[Path]:
    """Скачать и подготовить клипы под запросы. Возвращает пути добавленных клипов."""
    key = _require_key()
    library_dir = Path(library_dir or lib.LIBRARY_DIR)
    library_dir.mkdir(parents=True, exist_ok=True)
    queries = queries or NICHE_QUERIES
    added: list[Path] = []
    tmp = Path(tempfile.mkdtemp(prefix="broll_dl_"))

    for q in queries:
        try:
            vids = search(q, key, per_query=per_query)
        except Exception as e:
            if on_progress:
                on_progress(q, f"поиск не удался: {e}")
            continue
        slug = "".join(c if c.isalnum() else "_" for c in q).strip("_")[:24]
        for k, v in enumerate(vids):
            url = _best_file(v)
            if not url:
                continue
            name = f"pexels_{slug}_{v.get('id', k)}.mp4"
            dst = library_dir / name
            if dst.exists():
                continue
            raw = tmp / f"raw_{v.get('id', k)}.mp4"
            try:
                _download(url, raw)
            except Exception as e:
                if on_progress:
                    on_progress(name, f"скачивание не удалось: {e}")
                continue
            if _transcode(raw, dst):
                added.append(dst)
                if on_progress:
                    on_progress(name, "ok")
            elif on_progress:
                on_progress(name, "перекодировка не удалась")
            raw.unlink(missing_ok=True)

    return added


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Наполнить b-roll библиотеку со стоков (Pexels)")
    ap.add_argument("--per-query", type=int, default=3, help="клипов на запрос")
    ap.add_argument("--query", action="append", help="свой запрос (можно несколько)")
    ap.add_argument("--library", default=None, help="путь к broll_library")
    args = ap.parse_args(argv)
    added = fetch(args.query, per_query=args.per_query, library_dir=args.library,
                  on_progress=lambda n, s: print(f"  {n}: {s}"))
    print(f"добавлено клипов: {len(added)}. Дальше: python -m reels_factory.broll_index")
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))
