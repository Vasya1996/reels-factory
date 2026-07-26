"""Deprecated compatibility facade for the canonical edit plan.

До format version 1 этот модуль независимо решал, какие целые блоки закрывать
B-roll, и писал ``segment_plan.json``. Теперь все решения принимает
``reels_factory.editplan`` и единственный job artifact называется
``edit_plan.json``. Facade оставлен для старых CLI/tests/imports на время
миграции; новой логики здесь нет.
"""
from __future__ import annotations

from pathlib import Path

from reels_factory import broll_library as lib
from reels_factory.editplan import (
    ASSET_DURATION_SAFETY as DUR_SAFETY,
    FULL_COVER_ROLES,
    FULL_COVER_THRESHOLD as PLAN_THRESHOLD,
    MAX_FACE_ABSENCE_S as RHYTHM_MAX_AVATAR_S,
    build_edit_plan,
    save_edit_plan,
)

COVERABLE_ROLES = tuple(sorted(FULL_COVER_ROLES))


def plan_precut(
    scenario: dict,
    config: dict,
    *,
    index: dict | None = None,
    library_dir: Path | str | None = None,
    threshold: float = PLAN_THRESHOLD,
) -> dict:
    """Вернуть старую shape-проекцию из canonical draft.

    ``threshold`` сохранён в сигнатуре. Канонический контракт использует
    versioned quality threshold; отличающееся legacy-значение не может ослабить
    gate, поэтому допускается только более строгий порог через фильтрацию.
    """
    injected_index = index is not None
    legacy_config = {**config, "format": "avatar"}
    plan = build_edit_plan(
        scenario,
        legacy_config,
        index=index,
        library_dir=library_dir,
        embed_fn=lib.embed_text,
        require_asset_files=not injected_index,
    )
    segments = []
    for window in plan.get("windows") or []:
        if not window.get("safe_to_skip_avatar"):
            continue
        asset = window.get("asset") or {}
        if float(asset.get("confidence") or 0.0) < float(threshold):
            continue
        segments.append({
            "role": window.get("role"),
            "insert": True,
            "offset": float(asset.get("offset") or 0.0),
            "clip": asset.get("src"),
            "query": asset.get("query"),
            "score": asset.get("confidence"),
            "est_dur": round(
                float(window["estimated_timing"]["end"])
                - float(window["estimated_timing"]["start"]),
                2,
            ),
        })
    return {
        "segments": segments,
        "est": {
            "covered_s": plan["summary"]["full_broll_seconds"],
            "total_s": plan["timeline"]["estimated_duration_seconds"],
        },
        "log": list(plan.get("log") or []),
        "_canonical_edit_plan": plan,
    }


def save_plan(plan: dict, workdir: Path | str) -> Path:
    """Сохранить только canonical ``edit_plan.json``.

    При передаче старой precut shape используем вложенный canonical document.
    """
    canonical = plan.get("_canonical_edit_plan") if isinstance(plan, dict) else None
    return save_edit_plan(canonical or plan, workdir)
