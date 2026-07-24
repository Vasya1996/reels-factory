"""Библиотека b-roll + семантическое ядро (Модуль B, часть 1).

Здесь всё, что общее у индексации и подбора: где лежит библиотека, формат
`index.json`, извлечение кадров из клипа (ffmpeg), CLIP-эмбеддинги (open_clip,
ViT-B/32, CPU) и косинусная близость. Тяжёлый импорт open_clip/torch — ленивый:
подбор по готовому индексу и чтение метаданных работают без установленной модели,
модель поднимается только когда реально надо посчитать эмбеддинг.

Формат `index.json` (см. docs/TZ_pipeline_v6.md):
    { "clip_042.mp4": {
        "caption": "руки печатают на клавиатуре, блокнот с заметками",
        "tags": ["работа", "клавиатура", "заметки"],
        "embedding": [0.01, -0.23, ...],   # 512-мерный L2-нормированный вектор
        "duration": 12.2, "res": [1080, 1920] } }
"""
from __future__ import annotations

import json
import math
import subprocess
import tempfile
from pathlib import Path

from reels_factory.config import FFMPEG

# Библиотека клипов живёт рядом с движком. Сами клипы тяжёлые и не коммитятся
# (см. .gitignore), в git попадает только index.json.
LIBRARY_DIR = Path(__file__).resolve().parents[2] / "broll_library"
INDEX_NAME = "index.json"

# Мультиязычный CLIP: image-энкодер ViT-B/32 + текстовый XLM-RoBERTa. Критично —
# ниша русскоязычная, а англоязычный laion2b русские запросы почти не различает
# (все близости слипаются ~0.2). Эта модель понимает русский напрямую, без
# перевода запросов. Лёгкая, честно работает на CPU. Пространство 512-мерное.
_CLIP_MODEL_NAME = "xlm-roberta-base-ViT-B-32"
_CLIP_PRETRAINED = "laion5b_s13b_b90k"
_CLIP_DIM = 512

# Сколько кадров берём из клипа для усреднённого эмбеддинга. 4 — компромисс между
# «репрезентативно» и «быстро»; первый/последний кадр часто чёрные, поэтому берём
# из внутренней части клипа.
FRAMES_PER_CLIP = 4

FFPROBE = str(Path(FFMPEG).with_name("ffprobe" + Path(FFMPEG).suffix))

# ---------------------------------------------------------------------------
# ленивый CLIP
# ---------------------------------------------------------------------------
_clip_cache: dict = {}


def _load_clip():
    """Поднять модель один раз за процесс. Возвращает (model, preprocess, tokenizer)."""
    if "model" not in _clip_cache:
        import open_clip  # тяжёлый импорт — только когда реально нужен эмбеддинг
        import torch

        model, _, preprocess = open_clip.create_model_and_transforms(
            _CLIP_MODEL_NAME, pretrained=_CLIP_PRETRAINED
        )
        model.eval()
        _clip_cache.update(
            model=model,
            preprocess=preprocess,
            tokenizer=open_clip.get_tokenizer(_CLIP_MODEL_NAME),
            torch=torch,
        )
    return _clip_cache["model"], _clip_cache["preprocess"], _clip_cache["tokenizer"]


def embed_text(text: str) -> list[float]:
    """CLIP-эмбеддинг текстового запроса → L2-нормированный вектор (list, 512)."""
    model, _, tokenizer = _load_clip()
    torch = _clip_cache["torch"]
    with torch.no_grad():
        feats = model.encode_text(tokenizer([text]))
        feats = feats / feats.norm(dim=-1, keepdim=True)
    return feats[0].tolist()


def embed_frames(frame_paths: list[Path]) -> list[float]:
    """Усреднённый по кадрам CLIP-эмбеддинг клипа → L2-нормированный (list, 512)."""
    if not frame_paths:
        raise ValueError("нет кадров для эмбеддинга")
    from PIL import Image

    model, preprocess, _ = _load_clip()
    torch = _clip_cache["torch"]
    batch = torch.stack([preprocess(Image.open(p).convert("RGB")) for p in frame_paths])
    with torch.no_grad():
        feats = model.encode_image(batch)
        feats = feats / feats.norm(dim=-1, keepdim=True)
        mean = feats.mean(dim=0)
        mean = mean / mean.norm()  # усреднение сбивает норму — вернуть на сферу
    return mean.tolist()


# ---------------------------------------------------------------------------
# ffmpeg: длительность, разрешение, кадры
# ---------------------------------------------------------------------------
def probe(clip: Path) -> tuple[float, list[int]]:
    """(duration_s, [w, h]) через ffprobe. При сбое — (0.0, [0, 0])."""
    try:
        out = subprocess.run(
            [FFPROBE, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height:format=duration",
             "-of", "json", str(clip)],
            capture_output=True, text=True, check=True,
        ).stdout
        data = json.loads(out)
        stream = (data.get("streams") or [{}])[0]
        dur = float(data.get("format", {}).get("duration") or 0.0)
        w, h = int(stream.get("width") or 0), int(stream.get("height") or 0)
        return dur, [w, h]
    except Exception:
        return 0.0, [0, 0]


def extract_frames(clip: Path, out_dir: Path, n: int = FRAMES_PER_CLIP,
                   duration: float | None = None) -> list[Path]:
    """Достать n равномерных кадров из внутренней части клипа (5%..95%)."""
    if duration is None:
        duration, _ = probe(clip)
    duration = duration or 1.0
    out_dir.mkdir(parents=True, exist_ok=True)
    lo, hi = duration * 0.05, duration * 0.95
    times = [lo + (hi - lo) * (k + 0.5) / n for k in range(n)] if n > 1 else [duration / 2]
    frames: list[Path] = []
    for k, t in enumerate(times):
        fp = out_dir / f"{clip.stem}_f{k}.jpg"
        try:
            subprocess.run(
                [FFMPEG, "-y", "-ss", f"{t:.3f}", "-i", str(clip),
                 "-frames:v", "1", "-q:v", "3", str(fp)],
                capture_output=True, check=True,
            )
            if fp.exists() and fp.stat().st_size > 0:
                frames.append(fp)
        except subprocess.CalledProcessError:
            continue
    return frames


# ---------------------------------------------------------------------------
# index.json I/O
# ---------------------------------------------------------------------------
def index_path(library_dir: Path | str | None = None) -> Path:
    return Path(library_dir or LIBRARY_DIR) / INDEX_NAME


def load_index(library_dir: Path | str | None = None) -> dict:
    p = index_path(library_dir)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def save_index(index: dict, library_dir: Path | str | None = None) -> Path:
    p = index_path(library_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# косинус (по готовым L2-нормированным векторам это просто скалярное произведение)
# ---------------------------------------------------------------------------
def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    # векторы в индексе нормированы; на всякий случай нормируем и тут
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def frame_workdir() -> Path:
    """Временная папка под кадры (в системном temp, чистится ОС)."""
    return Path(tempfile.mkdtemp(prefix="broll_frames_"))
