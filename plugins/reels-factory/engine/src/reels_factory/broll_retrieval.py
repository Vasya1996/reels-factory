"""Семантический подбор b-roll (Модуль B, часть 3).

Модуль A (адаптер) пишет в сегмент `effect.broll_query` — что нужно показать.
Здесь по этому запросу достаём самый близкий клип из библиотеки и проставляем
`effect.src` (+ `offset`). Раскладка (когда/как) и материал (какой клип)
разделены, как в docs/TZ_pipeline_v6.md.

Алгоритм (на каждый broll-сегмент):
  1. эмбеддим `broll_query` тем же CLIP;
  2. косинус ко всем клипам индекса → ранжируем;
  3. дедуп: клип, уже занятый в этом ролике, не берём повторно;
  4. учитываем длину: клип не короче окна сегмента (иначе видео замрёт);
  5. порог: лучший score < THRESHOLD → фолбэк (нейтральный клип / генерация),
     помечаем сегмент `broll_weak_match` и логируем;
  6. пишем `src` (имя файла в public/) и `offset`.

Возвращает список выбранных клипов (что скопировать в public/ движка) и лог.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from reels_factory import broll_library as lib

# Порог косинуса: ниже — «слабое совпадение» (фолбэк). Откалибровано под
# мультиязычный CLIP xlm-roberta-base-ViT-B-32: у него абсолютные близости ниже,
# чем у англоязычного laion2b (осмысленный матч ~0.22-0.26, мусор <0.12).
# В docs/TZ_pipeline_v6.md стоял 0.24 под англ-модель — для M-CLIP это отсекало бы
# верные матчи. Занижать рискованно (нерелевантный клип хуже паузы), завышать —
# частый фолбэк на дефолтный клип.
THRESHOLD = 0.18

# Типы эффектов, которым нужен видеоряд-источник.
_BROLL_EFFECTS = {"broll", "broll_bg_particles"}


@dataclass
class BrollPick:
    seg_id: int
    query: str
    clip: str | None          # имя файла в библиотеке/public, None если фолбэк
    score: float
    offset: float
    weak: bool = False        # score ниже порога → помечен на фолбэк/генерацию


@dataclass
class RetrievalResult:
    tz: dict
    picks: list = field(default_factory=list)      # BrollPick по каждому сегменту
    used_clips: list = field(default_factory=list)  # уникальные клипы для public/
    log: list = field(default_factory=list)


def _needs_broll(effect: dict) -> bool:
    return isinstance(effect, dict) and effect.get("type") in _BROLL_EFFECTS


def _query_for(seg: dict) -> str:
    eff = seg.get("effect") or {}
    return (eff.get("broll_query") or seg.get("phrase") or "").strip()


def _rank(query_emb: list[float], index: dict, seg_window: float,
          used: set[str]) -> list[tuple[str, float]]:
    """Отсортированные (clip_name, score), с учётом дедупа и длины окна."""
    scored: list[tuple[str, float]] = []
    for name, meta in index.items():
        if name in used:
            continue
        dur = float(meta.get("duration") or 0.0)
        # клип короче окна → видео замрёт на последнем кадре; пропускаем,
        # если есть из чего выбирать (мягко: 0.3с допуска на неточность probe).
        if dur and seg_window and dur + 0.3 < seg_window:
            continue
        scored.append((name, lib.cosine(query_emb, meta.get("embedding") or [])))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def resolve_broll(tz: dict, *, library_dir: Path | str | None = None,
                  index: dict | None = None, threshold: float = THRESHOLD,
                  fallback_clip: str | None = None) -> RetrievalResult:
    """Проставить `src` во все broll-сегменты tz по семантике `broll_query`.

    `fallback_clip` — имя нейтрального клипа (в библиотеке) на случай слабого
    матча; если None — сегмент помечается `broll_weak_match: True` и `src`
    оставляется как есть (валидатор/генерация решат дальше).
    """
    index = index if index is not None else lib.load_index(library_dir)
    result = RetrievalResult(tz=tz)
    used: set[str] = set()

    broll_segs = [s for s in tz.get("segments", []) if _needs_broll(s.get("effect"))]
    if not broll_segs:
        return result
    if not index:
        result.log.append("index.json пуст — b-roll не подобран (нужна индексация)")
        for s in broll_segs:
            s["effect"]["broll_weak_match"] = True
        return result

    query_cache: dict[str, list[float]] = {}
    for seg in broll_segs:
        eff = seg["effect"]
        query = _query_for(seg)
        window = float(seg.get("end", 0)) - float(seg.get("start", 0))
        if not query:
            eff["broll_weak_match"] = True
            result.log.append(f"seg#{seg.get('id')}: пустой broll_query")
            continue

        if query not in query_cache:
            query_cache[query] = lib.embed_text(query)
        ranked = _rank(query_cache[query], index, window, used)

        best = ranked[0] if ranked else (None, 0.0)
        name, score = best
        weak = (name is None) or (score < threshold)

        if weak and fallback_clip and fallback_clip in index:
            name = fallback_clip

        pick = BrollPick(seg_id=seg.get("id"), query=query, clip=name,
                         score=round(float(score), 4),
                         offset=float(eff.get("offset", 0.0)), weak=weak)
        result.picks.append(pick)

        if name is None:
            eff["broll_weak_match"] = True
            result.log.append(f"seg#{pick.seg_id} «{query[:32]}»: нет кандидата → фолбэк")
            continue

        eff["src"] = name
        eff.setdefault("offset", 0.0)
        if weak:
            eff["broll_weak_match"] = True
            result.log.append(
                f"seg#{pick.seg_id} «{query[:32]}»: слабо ({score:.3f}<{threshold}) → {name}")
        else:
            result.log.append(f"seg#{pick.seg_id} «{query[:32]}»: {name} ({score:.3f})")

        used.add(name)
        if name not in result.used_clips:
            result.used_clips.append(name)

    return result
