"""Адаптер плана монтажа -> формат tz.json движка Revideo.

Единственное место, где решения пайплайна (ретаймленные блоки + broll-план +
конфиг) переводятся в план для Revideo-рендера. Их `editplan`/`timed_scenario` и
наш `tz` — одна сущность (что и когда происходит), адаптер тонкий.

Гранулярность: один сегмент tz = один блок сценария (hook/development/payoff/
cta). Эффект и тип зума назначаются по роли и правилам ротации (каждый зум ≤1
раз). Субтитры accumulate идут пословно из words.json независимо от сегментов.
"""
from __future__ import annotations

import re

# пул зумов — каждый используется не больше раза за ролик (правило зум-раз)
_ZOOM_POOL = ["punch", "snap_zoom", "push", "ken_burns", "shake_zoom"]


def _keywords_from_config(config: dict) -> list:
    """Ключевые слова для подсветки: явные из конфига + бренд/тема."""
    kws: list[str] = []
    kws += list(config.get("keywords") or [])
    product = config.get("product") or {}
    for src in (product.get("brand_captions"), config.get("theme_captions")):
        if src:
            kws += re.findall(r"[A-Za-zА-Яа-яЁё]{4,}", str(src))
    seen, out = set(), []
    for k in kws:
        kl = k.lower()
        if kl not in seen:
            seen.add(kl)
            out.append(kl)
    return out[:8]


def plan_to_tz(timed: dict, broll_segments: list | None, config: dict,
               base_video: str = "base.mp4", broll_file: str = "broll.mp4",
               face: dict | None = None) -> dict:
    """timed_scenario + broll-план + конфиг -> dict формата tz.json.

    timed: {"blocks":[{"role","start","end","speech"?}], "total"}
    broll_segments: [{"role","offset","slow"?,"insert"?}] — один источник видеоряда,
        offset задаёт точку входа для роли блока.
    """
    blocks = timed["blocks"]
    total = float(timed.get("total") or (blocks[-1]["end"] if blocks else 0))
    seg_by_role = {s["role"]: s for s in (broll_segments or [])}
    product = config.get("product") or {}
    fmt = config.get("format", "avatar")

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

    zoom_pool = list(_ZOOM_POOL)
    segments = []
    for i, b in enumerate(blocks):
        role = b.get("role")
        start, end = float(b["start"]), float(b["end"])
        has_broll = role in seg_by_role
        offset = float(seg_by_role[role]["offset"]) if has_broll else 0.0

        # камера/зум по роли, каждый тип не больше раза
        if role == "hook":
            camera = {"type": "zoom_out"}
        elif role == "cta":
            camera = {"type": "pulse"}
        elif not has_broll and zoom_pool:
            camera = {"type": zoom_pool.pop(0)}
        else:
            camera = {"type": "hold"}

        # эффект по роли/наличию видеоряда
        caption = "bottom"
        if role == "cta":
            effect = {"type": "cta_endcard", "button": (product.get("cta_button") or "ПОДПИСАТЬСЯ")}
        elif role == "payoff" and has_broll:
            # ключевой личный момент: аватар в кружке поверх фуллскрин-видеоряда
            bubble = {"shape": "circle", "position": "bottom_left"}
            if face:
                bubble["face"] = {"cx": face["cx"], "cy": face["cy"], "h": face["h"]}
                bubble["face_zoom"] = face.get("face_zoom", 3.1)
                bubble["face_dy"] = face.get("face_dy", 45)
            effect = {"type": "broll", "style": "fullscreen", "src": broll_file,
                      "offset": offset, "bubble": bubble}
            caption = "top"
        elif has_broll:
            # вставка видеоряда: для avatar-формата — поверх (fullscreen), иначе pip
            style = "fullscreen" if (fmt == "avatar" and seg_by_role[role].get("insert")) else "pip"
            effect = {"type": "broll", "style": style, "src": broll_file, "offset": offset}
            caption = "top" if style == "fullscreen" else "bottom"
        else:
            effect = {"type": "none"}

        # драматургия: кривая насыщенности по роли
        beat_intensity = {"hook": 2, "development": 2, "payoff": 1, "cta": 2}
        segments.append({
            "id": i + 1, "start": round(start, 3), "end": round(end, 3),
            "phrase": b.get("speech", ""),
            "beat": role, "intensity": beat_intensity.get(role, 2),
            "camera": camera, "transition_in": "none",
            "effect": effect, "caption": caption,
        })

    return {
        "_generated_by": "revideo_adapter.plan_to_tz",
        "meta": {"duration": round(total, 3), "fps": 30, "size": [1080, 1920],
                 "language": config.get("language", "ru"),
                 "base_video": base_video, "words": "words.json"},
        "brand": brand,
        "captions": captions,
        "segments": segments,
    }
