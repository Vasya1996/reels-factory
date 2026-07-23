"""Монтажное ТЗ (brief): декларативный план монтажа для готового ролика.

Идея: отдельный этап воркфлоу (LLM по сценарию/транскрипту, либо человек)
пишет НЕ команды ffmpeg, а короткое ТЗ — «что показать и когда». Движок
исполняет. Это то же разделение, что в editplan: решения отдельно, исполнение
отдельно; brief — формат передачи решений.

Схема (JSON):
{
  "captions": {
    "style": "karaoke" | "popword" | "boxed",   // пресет субтитров
    "keywords": ["скилы", "бесплатно"]          // акцентные слова
  },
  "brolls": [
    {"start": 10.8, "end": 13.4,                // окно в таймлайне ролика
     "query": "typing laptop keyboard",         // поиск в стоках (Pexels)…
     "src": "clip.mp4",                         // …или готовый файл
     "offset": 5.0,                             // смещение внутри источника
     "kind": "full" | "third" | "split",
     "pos": "top" | "bottom"}                   // для third
  ],
  "language": "ru",
  "music": "track.mp3"                          // опционально, с дакингом
}

`validate_brief` держит правила монтажа (те же, что в editplan/broll):
вставки не на хук, 1-3 штуки, 1.5-6с, без пересечений. Ошибки — понятным
текстом: ТЗ пишет LLM, и текст ошибки возвращается ему на исправление.
"""
import json
from pathlib import Path

from reels_factory.captions import STYLES

HOOK_S = 3.0          # первые секунды — лицо, вставками не закрываем
MIN_INSERT_S = 1.5    # короче — не успевает прочитаться
MAX_INSERT_S = 6.0    # дольше — зритель забывает, чей это ролик
MAX_INSERTS = 3


class BriefError(ValueError):
    pass


def load_brief(path) -> dict:
    """Прочитать ТЗ из JSON-файла (без валидации окон — она требует
    длительности ролика, см. validate_brief)."""
    path = Path(path)
    if not path.exists():
        raise BriefError(f"нет файла ТЗ: {path}")
    try:
        brief = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise BriefError(f"ТЗ {path.name} — не валидный JSON: {e}") from e
    if not isinstance(brief, dict):
        raise BriefError(f"ТЗ {path.name} должно быть JSON-объектом")
    return brief


def validate_brief(brief: dict, duration: float) -> dict:
    """Проверить ТЗ по правилам монтажа. Возвращает нормализованную копию
    (числа приведены, brolls отсортированы). Нарушение — BriefError."""
    out = dict(brief)

    caps = brief.get("captions") or {}
    style = caps.get("style", "karaoke")
    if style not in STYLES:
        raise BriefError(
            f"captions.style {style!r} не существует, есть: {', '.join(STYLES)}")

    brolls = list(brief.get("brolls") or [])
    if len(brolls) > MAX_INSERTS:
        raise BriefError(
            f"вставок {len(brolls)} — больше {MAX_INSERTS} превращает ролик "
            "в слайдшоу, сократи до самых сильных")
    norm = []
    for i, b in enumerate(brolls):
        try:
            s, e = float(b["start"]), float(b["end"])
        except (KeyError, TypeError, ValueError):
            raise BriefError(f"brolls[{i}]: нужны числовые start и end")
        if not (b.get("query") or b.get("src")):
            raise BriefError(f"brolls[{i}]: нужен query (поиск в стоках) или src (файл)")
        if s < HOOK_S:
            raise BriefError(
                f"brolls[{i}]: start {s:.1f}с закрывает хук — первые {HOOK_S:.0f}с "
                "зритель должен видеть лицо, сдвинь вставку позже")
        if e <= s:
            raise BriefError(f"brolls[{i}]: end {e:.1f}с раньше start {s:.1f}с")
        if e - s < MIN_INSERT_S or e - s > MAX_INSERT_S:
            raise BriefError(
                f"brolls[{i}]: длительность {e - s:.1f}с вне коридора "
                f"{MIN_INSERT_S}-{MAX_INSERT_S}с")
        if duration and e > duration:
            raise BriefError(
                f"brolls[{i}]: end {e:.1f}с за концом ролика ({duration:.1f}с)")
        norm.append({**b, "start": s, "end": e})
    norm.sort(key=lambda b: b["start"])
    for a, b in zip(norm, norm[1:]):
        if b["start"] < a["end"]:
            raise BriefError(
                f"вставки пересекаются: [{a['start']:.1f}-{a['end']:.1f}] и "
                f"[{b['start']:.1f}-{b['end']:.1f}]")
    out["brolls"] = norm
    return out
