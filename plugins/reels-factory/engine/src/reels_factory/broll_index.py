"""Индексация b-roll библиотеки (Модуль B, часть 2) — разовый шаг.

Проходит по клипам в `broll_library/`, для каждого:
  1. достаёт 3-5 кадров (ffmpeg),
  2. получает короткое описание caption + tags (VLM/ручное — см. `describe_fn`),
  3. считает усреднённый CLIP-эмбеддинг,
  4. пишет запись в `index.json`.

Инкрементально: уже проиндексированные клипы (по имени файла) пропускаются, если
не задан `force`. Это даёт «добавил клипов → переиндексировал только новые».

Описание клипа (`describe_fn`) намеренно вынесено за скобки — источников три:
  * `describe_from_sidecar` — читать `<clip>.txt`/`.json` рядом с клипом (ручной
    путь: подписи кладёт человек или ассистент, полностью офлайн);
  * `make_llm_describer(runner)` — VLM через Claude (прод-путь: кадры + промпт);
  * фолбэк — пустое описание (эмбеддинг всё равно считается по картинке).
Семантический подбор работает и без caption (по CLIP-эмбеддингу картинки);
caption/tags нужны для читаемости индекса и tag-фолбэка.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Callable

from reels_factory import broll_library as lib

# Что считаем клипом.
VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}

# Тип: (clip_path, frame_paths) -> {"caption": str, "tags": [str, ...]}
DescribeFn = Callable[[Path, list], dict]


# ---------------------------------------------------------------------------
# провайдеры описания
# ---------------------------------------------------------------------------
def describe_empty(clip: Path, frames: list) -> dict:
    """Фолбэк: без текста. Подбор пойдёт по CLIP-эмбеддингу картинки."""
    return {"caption": "", "tags": []}


def describe_from_sidecar(clip: Path, frames: list) -> dict:
    """Прочитать описание из соседнего файла `<clip>.txt` или `<clip>.json`.

    .json: {"caption": "...", "tags": ["...", ...]}
    .txt : первая строка — caption; строка, начинающаяся с 'tags:' — теги через
           запятую. Если тегов нет — берём значимые слова из caption.
    """
    j = clip.with_suffix(clip.suffix + ".json")
    if not j.exists():
        j = clip.with_suffix(".json")
    if j.exists():
        data = json.loads(j.read_text(encoding="utf-8"))
        return {"caption": str(data.get("caption", "")),
                "tags": [str(t) for t in (data.get("tags") or [])]}

    t = clip.with_suffix(clip.suffix + ".txt")
    if not t.exists():
        t = clip.with_suffix(".txt")
    if t.exists():
        caption, tags = "", []
        for line in t.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.lower().startswith("tags:"):
                tags = [x.strip() for x in line.split(":", 1)[1].split(",") if x.strip()]
            elif line and not caption:
                caption = line
        if not tags:
            tags = _tags_from_caption(caption)
        return {"caption": caption, "tags": tags}

    return describe_empty(clip, frames)


def make_llm_describer(runner, lang: str = "ru") -> DescribeFn:
    """Прод-путь: описать клип через Claude по извлечённым кадрам.

    `runner` — объект с `.run(prompt) -> str` (см. reels_factory.llm.ClaudeCliRunner;
    Claude Code CLI умеет читать переданные пути к изображениям). Ждём JSON
    {"caption", "tags"}; при неудаче — мягкий фолбэк на пустое описание.
    """
    def _describe(clip: Path, frames: list) -> dict:
        frame_list = "\n".join(f"- {p}" for p in frames)
        prompt = (
            "Ты видео-редактор. По кадрам ниже опиши b-roll клип для семантического "
            "поиска. Верни СТРОГО JSON без пояснений: "
            '{"caption": "<одна фраза что происходит в кадре, ' + lang + '>", '
            '"tags": ["<3-6 ключевых слов-предметов/действий>"]}\n'
            f"Кадры (пути к изображениям):\n{frame_list}"
        )
        try:
            raw = runner.run(prompt)
            m = re.search(r"\{.*\}", raw, re.S)
            data = json.loads(m.group(0) if m else raw)
            return {"caption": str(data.get("caption", "")),
                    "tags": [str(t) for t in (data.get("tags") or [])]}
        except Exception:
            return describe_empty(clip, frames)

    return _describe


def _tags_from_caption(caption: str) -> list[str]:
    words = re.findall(r"[A-Za-zА-Яа-яЁё]{4,}", caption.lower())
    seen, out = set(), []
    for w in words:
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out[:6]


# ---------------------------------------------------------------------------
# индексация
# ---------------------------------------------------------------------------
def list_clips(library_dir: Path) -> list[Path]:
    return sorted(p for p in Path(library_dir).iterdir()
                  if p.is_file() and p.suffix.lower() in VIDEO_EXTS)


def index_library(library_dir: Path | str | None = None, *,
                  describe_fn: DescribeFn = describe_from_sidecar,
                  force: bool = False, on_progress=None) -> dict:
    """Построить/обновить index.json. Возвращает индекс. Инкрементально."""
    library_dir = Path(library_dir or lib.LIBRARY_DIR)
    library_dir.mkdir(parents=True, exist_ok=True)
    index = lib.load_index(library_dir)
    clips = list_clips(library_dir)

    for clip in clips:
        name = clip.name
        if name in index and not force:
            continue
        duration, res = lib.probe(clip)
        work = lib.frame_workdir()
        try:
            frames = lib.extract_frames(clip, work, duration=duration)
            if not frames:
                if on_progress:
                    on_progress(name, "skip: нет кадров (перекодировать в 30fps +faststart)")
                continue
            desc = describe_fn(clip, frames)
            embedding = lib.embed_frames(frames)
        finally:
            shutil.rmtree(work, ignore_errors=True)

        index[name] = {
            "caption": desc.get("caption", ""),
            "tags": desc.get("tags", []),
            "embedding": embedding,
            "duration": round(duration, 2),
            "res": res,
        }
        if on_progress:
            on_progress(name, f"ok: {desc.get('caption', '')[:48]}")

    lib.save_index(index, library_dir)
    return index


def import_clip(src: Path | str, library_dir: Path | str | None = None,
                new_name: str | None = None) -> Path:
    """Скопировать клип в библиотеку под каноничным именем (для даунлоадеров)."""
    src = Path(src)
    library_dir = Path(library_dir or lib.LIBRARY_DIR)
    library_dir.mkdir(parents=True, exist_ok=True)
    dst = library_dir / (new_name or src.name)
    if src.resolve() != dst.resolve():
        shutil.copy(str(src), str(dst))
    return dst


def main(argv=None) -> int:
    """CLI: python -m reels_factory.broll_index [--force] [--library PATH]"""
    import argparse

    ap = argparse.ArgumentParser(description="Индексация b-roll библиотеки (кадры → CLIP → index.json)")
    ap.add_argument("--library", default=None, help="путь к broll_library")
    ap.add_argument("--force", action="store_true", help="переиндексировать всё, а не только новое")
    args = ap.parse_args(argv)

    idx = index_library(library_dir=args.library, describe_fn=describe_from_sidecar,
                        force=args.force, on_progress=lambda n, s: print(f"  {n}: {s}"))
    print(f"проиндексировано клипов: {len(idx)} → {lib.index_path(args.library)}")
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))
