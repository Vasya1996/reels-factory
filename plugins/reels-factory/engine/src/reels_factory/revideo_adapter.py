"""Pure projection from canonical ``edit_plan.json`` to Revideo ``tz.json``.

Этот модуль больше не принимает творческих решений. Coverage, asset,
HyperFrames block, CTA, camera и transitions уже зафиксированы в edit plan до
платных генераций. Adapter только переводит versioned contract в runtime shape.
"""
from __future__ import annotations

import copy
import re

from reels_factory.editplan import (
    before_after_from_text as _before_after_from_text,
    broll_query as _broll_query,
    build_edit_plan,
    finalize_edit_plan,
    stat_from_phrase as _stat_from_phrase,
    validate_edit_plan,
)


def _keywords_from_config(config: dict) -> list[str]:
    keywords: list[str] = list(config.get("keywords") or [])
    product = config.get("product") or {}
    for source in (product.get("brand_captions"), config.get("theme_captions")):
        if source:
            keywords += re.findall(r"[A-Za-zА-Яа-яЁё]{4,}", str(source))
    seen, result = set(), []
    for keyword in keywords:
        normalized = keyword.lower()
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result[:8]


def edit_plan_to_tz(
    edit_plan: dict,
    config: dict,
    *,
    base_video: str = "base.mp4",
    face: dict | None = None,
) -> dict:
    """Project an already-final plan. No CLIP, heuristics or re-planning."""
    report = validate_edit_plan(
        edit_plan, require_final=True, require_asset_files=False
    )
    if not report["all_pass"]:
        raise ValueError(
            "canonical edit plan нельзя проецировать: "
            + "; ".join(report["errors"][:5])
        )

    brand = {
        "keyword_color": "#FFE500",
        "font": "Unbounded",
        "captions_style": "accumulate",
        "progress_bar": True,
        "watermark": config.get("watermark") or config.get("handle") or "",
        "watermark_from": 2.0,
    }
    captions = {
        "base_style": "accumulate",
        "font_size": 46,
        "position_pct_from_bottom": 40,
        "keywords": _keywords_from_config(config),
    }
    phrase_by_id = {
        phrase["id"]: phrase for phrase in edit_plan.get("phrases") or []
    }
    segments = []
    for window in edit_plan.get("windows") or []:
        timing = window["final_timing"]
        effect = copy.deepcopy(window.get("effect") or {"type": "none"})
        bubble = effect.get("bubble")
        if bubble and face:
            bubble["face"] = {
                "cx": face["cx"],
                "cy": face["cy"],
                "h": face["h"],
            }
            bubble["face_zoom"] = face.get("face_zoom", 3.1)
            bubble["face_dy"] = face.get("face_dy", 45)
        phrases = [phrase_by_id[item] for item in window["phrase_ids"]]
        role = window.get("role")
        intensity = {
            "hook": 2,
            "context": 2,
            "development": 2,
            "payoff": 1,
            "cta": 2,
        }.get(role, 2)
        if effect.get("type") in {
            "chart_bars",
            "broll_bg_particles",
            "complexity_cloud",
            "persona_card",
            "value_layers",
            "concept_nodes",
            "sequence_flow",
        }:
            intensity = 3
        segments.append({
            "id": len(segments) + 1,
            "start": round(float(timing["start"]), 3),
            "end": round(float(timing["end"]), 3),
            "phrase": " ".join(phrase["text"] for phrase in phrases),
            "phrase_ids": list(window["phrase_ids"]),
            "edit_window_id": window["id"],
            "coverage": window["coverage"],
            "beat": role,
            "intensity": intensity,
            "camera": copy.deepcopy(window.get("camera") or {"type": "hold"}),
            "transition_in": window.get("transition_in") or "none",
            "effect": effect,
            "caption": window.get("caption") or "bottom",
        })

    return {
        "_generated_by": "revideo_adapter.edit_plan_to_tz (projection only)",
        "meta": {
            "duration": round(
                float(edit_plan["timeline"]["final_duration_seconds"]), 3
            ),
            "fps": 30,
            "size": [1080, 1920],
            "language": edit_plan.get("script", {}).get("language")
            or config.get("language", "ru"),
            "base_video": base_video,
            "words": "words.json",
            "edit_plan": "edit_plan.json",
            "edit_plan_format_version": edit_plan["format_version"],
        },
        "brand": brand,
        "captions": captions,
        "segments": segments,
    }


def plan_to_tz(
    timed: dict,
    broll_segments: list | None,
    config: dict,
    words: list | None = None,
    base_video: str = "base.mp4",
    broll_file: str = "broll.mp4",
    face: dict | None = None,
) -> dict:
    """Compatibility wrapper for callers not yet passing ``edit_plan``.

    Even in this path all creative decisions are delegated to the canonical
    planner once; this adapter still only projects the resulting final plan.
    """
    legacy = {"segments": copy.deepcopy(broll_segments or [])}
    for segment in legacy["segments"]:
        if not segment.get("clip"):
            segment.setdefault("clip", None)
            segment.setdefault("source", broll_file)
    compat_config = dict(config)
    if any(item.get("insert") for item in legacy["segments"]):
        compat_config.setdefault("format", "avatar")
    plan = build_edit_plan(
        timed,
        compat_config,
        index={},
        legacy_broll_plan=legacy,
        require_asset_files=False,
    )
    plan = finalize_edit_plan(
        plan,
        timed,
        words or [],
        require_asset_files=False,
    )
    return edit_plan_to_tz(plan, compat_config, base_video=base_video, face=face)
