"""Generate reproducible 30/60/90s Stage 3 plans and SVG timelines.

This script is deliberately offline: no TTS, HeyGen, network or video render.
It creates approved-scenario/final-edit-plan fixtures, runs the production
avatar-islands planner, and writes inspectable artifacts under
``docs/avatar-islands-demo``.
"""
from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path

from reels_factory.avatar_islands import (
    build_avatar_render_plan,
    save_avatar_render_plan,
)
from reels_factory.editplan import (
    EDIT_PLAN_FORMAT_VERSION,
    validate_edit_plan,
)


ROOT = Path(__file__).resolve().parents[4]
OUTPUT_ROOT = ROOT / "docs" / "avatar-islands-demo"

_PHRASE_LIBRARY = [
    "Контент тормозит не из-за идей.",
    "Обычно время съедают повторяющиеся операции.",
    "Сначала фиксируем единый сценарий.",
    "Потом голос создаётся одной дорожкой.",
    "Таймкоды приходят вместе с озвучкой.",
    "Монтаж больше ничего не угадывает.",
    "Ведущий остаётся в ключевых местах.",
    "На доказательства ставим понятный визуал.",
    "Невидимый аватар не отправляем в генерацию.",
    "Соседние спокойные фразы объединяем.",
    "Сильную смену подачи сохраняем отдельно.",
    "Короткие handles защищают точный стык.",
    "Финальный голос остаётся только один.",
    "Повторный запуск использует тот же cache.",
    "Так качество растёт без лишних секунд.",
]

_HIDDEN_RANGES = {
    30: [(10, 18)],
    60: [(14, 20), (36, 42)],
    90: [(14, 20), (38, 44), (64, 70)],
}


def _json(path: Path, value) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _timing(start: float, end: float) -> dict:
    return {
        "start": round(start, 3),
        "end": round(end, 3),
        "duration": round(end - start, 3),
    }


def _phrases(duration: int) -> list[str]:
    count = duration // 2
    values = []
    for index in range(count):
        base = _PHRASE_LIBRARY[index % len(_PHRASE_LIBRARY)]
        if index >= len(_PHRASE_LIBRARY):
            cycle = index // len(_PHRASE_LIBRARY) + 1
            base = f"{base[:-1]} — проход {cycle}."
        values.append(base)
    values[0] = "Девяносто секунд не должны означать девяносто секунд аватара."
    if duration == 30:
        values[0] = "Тридцать секунд тоже не требуют сплошного аватара."
    elif duration == 60:
        values[0] = "Минута ролика не должна становиться одним плоским дублем."
    values[-2] = "Результат — связная речь и управляемая пластика."
    values[-1] = "Сохрани схему и проверь свой следующий ролик."
    return values


def _role(index: int, count: int) -> str:
    if index == 0:
        return "hook"
    if index == count - 1:
        return "cta"
    if index == count - 2:
        return "payoff"
    return "development"


def _performance(role: str, start: float, duration: float) -> dict:
    if role == "hook":
        value = (
            "medium",
            "Looks at the camera and leans in slightly, confident and engaged.",
            "Хук требует быстрого зрительного контакта без переигрывания.",
        )
    elif role == "cta":
        value = (
            "medium",
            "Looks at the camera and makes one inviting open-hand gesture.",
            "CTA — одно ясное приглашающее движение.",
        )
    elif role == "payoff":
        value = (
            "low",
            "Looks at the camera and nods gently, sincere and confident.",
            "Вывод лучше звучит спокойно и достоверно.",
        )
    elif start / duration < 0.34:
        value = (
            "low",
            "Looks at the camera with a calm expression and subtle gestures.",
            "Первая часть объяснения — стабильная спокойная подача.",
        )
    elif start / duration < 0.67:
        value = (
            "medium",
            "Looks at the camera and gestures lightly with one hand.",
            "Середина получает умеренный акцент на механике.",
        )
    else:
        value = (
            "low",
            "Looks at the camera and nods subtly, calm and clear.",
            "Финальная часть объяснения замедляет подачу перед выводом.",
        )
    return {
        "expressiveness": value[0],
        "motion_prompt": value[1],
        "prompt_language": "en",
        "source": "offline_demo_llm_recommendation",
        "rationale": value[2],
        "engine_scope": "photo_avatar_iv",
    }


def _scenario_and_plan(duration: int) -> tuple[dict, dict]:
    phrase_texts = _phrases(duration)
    count = len(phrase_texts)
    block_groups = [
        phrase_texts[:1],
        phrase_texts[1:-2],
        phrase_texts[-2:-1],
        phrase_texts[-1:],
    ]
    block_roles = ["hook", "development", "payoff", "cta"]
    block_times = [
        (0.0, 2.0),
        (2.0, float(duration - 4)),
        (float(duration - 4), float(duration - 2)),
        (float(duration - 2), float(duration)),
    ]
    scenario = {
        "format_version": 1,
        "mode": "offline_stage3_fixture",
        "language": "ru",
        "theme": "автоматизация контент-производства",
        "target_duration_s": duration,
        "title": f"Адаптивный Avatar IV timeline — {duration} секунд",
        "blocks": [
            {
                "id": f"block-{index}",
                "role": role,
                "start": timing[0],
                "end": timing[1],
                "speech": " ".join(group),
            }
            for index, (role, timing, group) in enumerate(
                zip(block_roles, block_times, block_groups)
            )
        ],
    }
    canonical_text = "\n".join(
        block["speech"] for block in scenario["blocks"]
    )
    block_offsets = []
    cursor = 0
    for block in scenario["blocks"]:
        start = cursor
        end = start + len(block["speech"])
        block_offsets.append((start, end))
        cursor = end + 1

    phrases = []
    search_cursor = 0
    for index, text in enumerate(phrase_texts):
        char_start = canonical_text.find(text, search_cursor)
        if char_start < 0:
            raise RuntimeError(f"phrase text not found: {text}")
        char_end = char_start + len(text)
        search_cursor = char_end
        start, end = index * 2.0, (index + 1) * 2.0
        role = _role(index, count)
        block_index = block_roles.index(role) if role != "development" else 1
        hidden = any(
            left <= start and end <= right
            for left, right in _HIDDEN_RANGES[duration]
        )
        phrases.append({
            "id": f"phrase-{index:03d}",
            "index": index,
            "block_id": f"block-{block_index}",
            "block_index": block_index,
            "role": role,
            "text": text,
            "character_start": char_start,
            "character_end": char_end,
            "estimated_timing": _timing(start, end),
            "final_timing": _timing(start, end),
            "speech_timing": _timing(start + 0.08, end - 0.08),
            "visual_intent": (
                "Показать схему/доказательство."
                if hidden else "Сохранить зрительный контакт с ведущим."
            ),
            "coverage": "hyperframes" if hidden else "avatar",
            "asset": None,
            "fallback": {
                "coverage": "avatar",
                "reason": "Ведущий — безопасный fallback.",
            },
            "decision_reason": "Offline fixture Stage 3.",
            "window_id": None,
            "avatar_performance": _performance(role, start, duration),
        })

    groups: list[list[dict]] = []
    for phrase in phrases:
        if groups and groups[-1][0]["coverage"] == phrase["coverage"]:
            groups[-1].append(phrase)
        else:
            groups.append([phrase])
    windows = []
    for index, group in enumerate(groups):
        window_id = f"window-{index:03d}"
        coverage = group[0]["coverage"]
        for phrase in group:
            phrase["window_id"] = window_id
        windows.append({
            "id": window_id,
            "index": index,
            "block_id": group[0]["block_id"],
            "block_index": group[0]["block_index"],
            "role": group[0]["role"],
            "phrase_ids": [phrase["id"] for phrase in group],
            "visual_intent": group[0]["visual_intent"],
            "coverage": coverage,
            "asset": None,
            "fallback": {
                "coverage": "avatar",
                "reason": "Ведущий — безопасный fallback.",
            },
            "safe_to_skip_avatar": False,
            "estimated_timing": _timing(
                group[0]["final_timing"]["start"],
                group[-1]["final_timing"]["end"],
            ),
            "final_timing": _timing(
                group[0]["final_timing"]["start"],
                group[-1]["final_timing"]["end"],
            ),
            "effect": (
                {
                    "type": "chart_bars",
                    "hyperframes": {
                        "block": "stat_number",
                        "variables": {"value": "SOURCE OF TRUTH"},
                    },
                }
                if coverage == "hyperframes"
                else {"type": "none"}
            ),
        })

    blocks = []
    for index, (source, offsets, timing) in enumerate(
        zip(scenario["blocks"], block_offsets, block_times)
    ):
        own = [phrase for phrase in phrases if phrase["block_index"] == index]
        blocks.append({
            "id": source["id"],
            "index": index,
            "role": source["role"],
            "character_start": offsets[0],
            "character_end": offsets[1],
            "estimated_timing": _timing(*timing),
            "final_timing": _timing(*timing),
            "phrase_ids": [phrase["id"] for phrase in own],
            "window_ids": list(dict.fromkeys(
                phrase["window_id"] for phrase in own
            )),
            "avatar_required": True,
        })
    plan = {
        "format_version": EDIT_PLAN_FORMAT_VERSION,
        "status": "final",
        "generated_by": "offline_stage3_demo_fixture",
        "script": {
            "language": "ru",
            "text": canonical_text,
            "text_sha256":
                hashlib.sha256(canonical_text.encode("utf-8")).hexdigest(),
            "character_count": len(canonical_text),
        },
        "timeline": {
            "estimated_duration_seconds": duration,
            "final_duration_seconds": duration,
        },
        "constraints": {
            "coverage_values": [
                "avatar", "full_broll", "hyperframes", "mixed"
            ],
            "max_face_absence_seconds": 10,
            "min_fullscreen_seconds": 3,
        },
        "blocks": blocks,
        "phrases": phrases,
        "windows": windows,
        "events": {"punch": []},
        "revisions": [],
        "log": ["Offline fixture; no paid provider calls."],
    }
    report = validate_edit_plan(
        plan, require_final=True, require_asset_files=False
    )
    plan["validation"] = report
    if not report["all_pass"]:
        raise RuntimeError("; ".join(report["errors"]))
    return scenario, plan


def _svg(duration: int, render_plan: dict) -> str:
    width, height = 1440, 310
    left, right = 120, 40
    usable = width - left - right
    scale = usable / duration
    colors = {
        "avatar": "#5B8DEF",
        "mixed": "#7B61FF",
        "hyperframes": "#FFB703",
        "full_broll": "#FB8500",
        "low": "#79B8FF",
        "medium": "#7B61FF",
        "high": "#EF476F",
    }

    def rect(start, end, y, h, color, label):
        x = left + start * scale
        w = max(1, (end - start) * scale)
        display_label = (
            label if w > 80
            else label.split(" ·", 1)[0] if w > 25
            else ""
        )
        safe = html.escape(display_label)
        text = (
            f'<text x="{x + w / 2:.1f}" y="{y + h / 2 + 5:.1f}" '
            f'text-anchor="middle" class="seg">{safe}</text>'
            if display_label else ""
        )
        return (
            f'<rect x="{x:.1f}" y="{y}" width="{w:.1f}" height="{h}" '
            f'rx="8" fill="{color}"/>{text}'
        )

    visual = []
    for segment in render_plan["visual_timeline"]:
        label = (
            "Avatar"
            if segment["coverage"] in {"avatar", "mixed"}
            else "Motion / B-roll"
        )
        visual.append(rect(
            segment["start"],
            segment["end"],
            82,
            52,
            colors[segment["coverage"]],
            label,
        ))
    shots = []
    for shot in render_plan["shots"]:
        timing = shot["visible_timing"]
        exp = shot["avatar_performance"]["expressiveness"]
        shots.append(rect(
            timing["start"],
            timing["end"],
            166,
            48,
            colors[exp],
            f"S{shot['index'] + 1} · {exp}",
        ))
    tick_step = 5 if duration == 30 else 10
    ticks = []
    for second in range(0, duration + 1, tick_step):
        x = left + second * scale
        ticks.append(
            f'<line x1="{x:.1f}" y1="54" x2="{x:.1f}" y2="232" '
            'stroke="#CBD5E1" stroke-width="1"/>'
            f'<text x="{x:.1f}" y="252" text-anchor="middle" '
            f'class="tick">{second}s</text>'
        )
    summary = render_plan["summary"]
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<style>
  .title {{ font: 700 24px Arial, sans-serif; fill: #0F172A; }}
  .label {{ font: 700 15px Arial, sans-serif; fill: #334155; }}
  .seg {{ font: 700 13px Arial, sans-serif; fill: white; }}
  .tick {{ font: 12px Arial, sans-serif; fill: #64748B; }}
  .meta {{ font: 14px Arial, sans-serif; fill: #334155; }}
</style>
<rect width="100%" height="100%" fill="#F8FAFC"/>
<text x="{left}" y="34" class="title">Photo Avatar IV · adaptive timeline · {duration}s</text>
{''.join(ticks)}
<text x="18" y="112" class="label">VISUAL</text>
{''.join(visual)}
<text x="18" y="195" class="label">SHOTS</text>
{''.join(shots)}
<text x="{left}" y="286" class="meta">Islands: {summary['island_count']} · Shots: {summary['shot_count']} · visible: {summary['avatar_visible_seconds']}s · requested with handles: {summary['avatar_requested_seconds']}s · saved vs full avatar: {summary['saved_vs_full_avatar_seconds']}s</text>
</svg>
"""


def main() -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    rows = []
    for duration in (30, 60, 90):
        output = OUTPUT_ROOT / f"{duration}s"
        output.mkdir(parents=True, exist_ok=True)
        scenario, edit_plan = _scenario_and_plan(duration)
        render_plan = build_avatar_render_plan(
            edit_plan,
            {
                "format": "avatar",
                "avatar": {
                    "heygen_asset_id": "offline-photo-avatar-iv-fixture",
                    "engine": "avatar_iv",
                    "resolution": "1080p",
                },
                "master_audio": {"enabled": True},
                "avatar_islands": {
                    "enabled": True,
                    "max_parallel": 2,
                    "estimated_cost_per_second_usd": 0.05,
                },
            },
            master_audio_sha256=f"offline-master-{duration}s",
        )
        _json(output / "scenario.json", scenario)
        _json(output / "edit_plan.json", edit_plan)
        save_avatar_render_plan(render_plan, output)
        (output / "timeline.svg").write_text(
            _svg(duration, render_plan), encoding="utf-8"
        )
        summary = render_plan["summary"]
        rows.append(
            f"| {duration}s | {summary['island_count']} | "
            f"{summary['shot_count']} | {summary['avatar_visible_seconds']}s | "
            f"{summary['avatar_requested_seconds']}s | "
            f"{summary['saved_vs_full_avatar_seconds']}s |"
        )
    readme = """# Avatar islands — offline 30/60/90 demo

Ни ElevenLabs, ни HeyGen не вызывались. Это воспроизводимый прогон production
planner по трём final canonical edit plans.

| Timeline | Islands | Shots | Avatar visible | Requested + handles | Saved vs full avatar |
|---:|---:|---:|---:|---:|---:|
""" + "\n".join(rows) + """

В каждой папке: `scenario.json`, `edit_plan.json`,
`avatar_render_plan.json`, `timeline.svg`.
"""
    (OUTPUT_ROOT / "README.md").write_text(readme, encoding="utf-8")
    print(OUTPUT_ROOT)


if __name__ == "__main__":
    main()
