"""Precut-план: какие блоки закрыть фуллскрин-бироллом ДО генерации аватара.

Решение о фуллскрин-вставках принимается по scenario.json ещё до TTS и HeyGen:
блок, целиком закрытый вставкой (insert: true), не рендерится аватаром — вместо
HeyGen идёт дешёвый локальный render_covered_block (голос поверх чёрного кадра,
под вставкой его всё равно не видно). Экономия = длительность покрытых блоков.

Покрываем блок только когда уверены в материале: семантический матч в
CLIP-библиотеке (Модуль B) не ниже PLAN_THRESHOLD И клип не короче блока с
запасом. Иначе блок остаётся аватарным — лишний аватар дешевле, чем слабый
b-roll на весь блок. Без CLIP/индекса план пустой (пайплайн работает как раньше).

Бест-практис ритма: говорящая голова без перебивки не дольше RHYTHM_MAX_AVATAR_S
(~10с). Планировщик выбирает покрытия так, чтобы длинные аватарные отрезки
разбивались фуллскринами; что не покрылось материалом — доберёт адаптер лёгкими
приёмами (pip/график/эмодзи), но уже без экономии HeyGen.
"""
from __future__ import annotations

import json
from pathlib import Path

from reels_factory import broll_library as lib
from reels_factory.revideo_adapter import _broll_query

# Порог уверенности для отказа от аватара. Строже, чем THRESHOLD=0.18 у
# retrieval: там слабый матч просто даёт фолбэк-клип, здесь же мы необратимо
# не генерируем аватар — цена ошибки выше. Под мультиязычный CLIP
# (осмысленный матч ~0.22-0.26) берём 0.20.
PLAN_THRESHOLD = 0.20

# Клип должен перекрывать блок с запасом: оценка длительности блока в
# scenario.json — прикидка LLM, реальная озвучка бывает длиннее.
DUR_SAFETY = 1.25

# Ритм: максимум секунд говорящей головы подряд без фуллскрин-перебивки.
RHYTHM_MAX_AVATAR_S = 10.0

# Какие роли можно закрывать целиком. hook — первое впечатление, лицо
# обязательно; payoff — личный момент (фирменный пузырь рисуется из base,
# под покрытием он был бы чёрным); cta — эндкард поверх живого аватара.
COVERABLE_ROLES = ("context", "development")


def _est_dur(block: dict) -> float:
    return max(0.0, float(block.get("end", 0)) - float(block.get("start", 0)))


def _best_clip(query: str, est_dur: float, index: dict, used: set,
               threshold: float) -> tuple[str | None, float]:
    """Лучший клип библиотеки под запрос: не занят, длиннее блока с запасом."""
    emb = lib.embed_text(query)
    best_name, best_score = None, 0.0
    need = est_dur * DUR_SAFETY
    for name, meta in index.items():
        if name in used:
            continue
        dur = float(meta.get("duration") or 0.0)
        if dur and dur < need:
            continue
        score = lib.cosine(emb, meta.get("embedding") or [])
        if score > best_score:
            best_name, best_score = name, score
    if best_name is None or best_score < threshold:
        return None, best_score
    return best_name, best_score


def plan_precut(scenario: dict, config: dict, *, index: dict | None = None,
                library_dir: Path | str | None = None,
                threshold: float = PLAN_THRESHOLD) -> dict:
    """Построить precut-план по сценарию (до TTS/HeyGen).

    Возвращает broll_plan-совместимый dict:
    {"segments": [{"role", "insert": True, "offset": 0.0, "clip", "query",
                   "score", "est_dur"}], "est": {...}, "log": [...]}.
    Пустые segments = покрывать нечем/нечего, пайплайн работает как раньше.
    """
    log: list[str] = []
    blocks = scenario.get("blocks") or []
    total = sum(_est_dur(b) for b in blocks)

    if index is None:
        try:
            index = lib.load_index(library_dir)
        except Exception as e:
            index = {}
            log.append(f"библиотека b-roll недоступна ({e}) — без precut-покрытия")
    if not index:
        log.append("index.json пуст — precut-покрытие не планируется")
        return {"segments": [], "est": {"covered_s": 0.0, "total_s": total}, "log": log}

    # кандидаты: только покрываемые роли, с уверенным клипом подходящей длины
    candidates = []  # (block_idx, role, clip, score, est_dur)
    used: set[str] = set()
    for i, b in enumerate(blocks):
        role = b.get("role")
        if role not in COVERABLE_ROLES:
            continue
        est = _est_dur(b)
        if est <= 0:
            continue
        query = _broll_query(b.get("speech") or "")
        try:
            clip, score = _best_clip(query, est, index, used, threshold)
        except Exception as e:
            log.append(f"CLIP недоступен ({str(e)[:120]}) — без precut-покрытия")
            return {"segments": [], "est": {"covered_s": 0.0, "total_s": total},
                    "log": log}
        if clip is None:
            log.append(f"{role}: нет уверенного клипа (score={score:.3f}"
                       f"<{threshold}) — блок остаётся аватарным")
            continue
        candidates.append((i, role, clip, score, est))
        used.add(clip)  # предварительная бронь, финальная — при отборе

    # отбор: не покрываем два соседних блока (лицо должно возвращаться в кадр);
    # приоритет — длинные блоки (больше экономия и сильнее ломают ритм 10с)
    candidates.sort(key=lambda c: c[4], reverse=True)
    chosen: list[tuple] = []
    chosen_idx: set[int] = set()
    for cand in candidates:
        i = cand[0]
        if (i - 1) in chosen_idx or (i + 1) in chosen_idx:
            log.append(f"{cand[1]}: пропущен — соседний блок уже покрыт "
                       "(аватар должен возвращаться в кадр)")
            continue
        chosen.append(cand)
        chosen_idx.add(i)

    segments = []
    covered_s = 0.0
    for i, role, clip, score, est in sorted(chosen, key=lambda c: c[0]):
        segments.append({"role": role, "insert": True, "offset": 0.0,
                         "clip": clip, "query": _broll_query(blocks[i].get("speech") or ""),
                         "score": round(score, 4), "est_dur": round(est, 2)})
        covered_s += est
        log.append(f"{role}: покрыт '{clip}' (score={score:.3f}, ~{est:.1f}с) — "
                   "HeyGen для блока не нужен")

    # ритм-аудит по оценочным таймингам: где аватар всё ещё дольше лимита
    stretch = 0.0
    for i, b in enumerate(blocks):
        if i in chosen_idx:
            stretch = 0.0
            continue
        stretch += _est_dur(b)
        if stretch > RHYTHM_MAX_AVATAR_S:
            log.append(f"ритм: к блоку '{b.get('role')}' аватар без перебивки "
                       f"~{stretch:.1f}с (>{RHYTHM_MAX_AVATAR_S:.0f}с) — "
                       "адаптер добавит лёгкие приёмы, но HeyGen-экономии тут нет")
            stretch = 0.0

    if covered_s:
        log.append(f"итого покрыто ~{covered_s:.1f}с из ~{total:.1f}с "
                   f"({100 * covered_s / total:.0f}% генерации HeyGen сэкономлено)")
    return {"segments": segments,
            "est": {"covered_s": round(covered_s, 2), "total_s": round(total, 2)},
            "log": log}


def save_plan(plan: dict, workdir: Path | str) -> Path:
    out = Path(workdir) / "segment_plan.json"
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
