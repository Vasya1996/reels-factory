"""Build reproducible 30/60/90s Visual Director timelines without providers.

The fixtures go through the production ``build_edit_plan`` path. No LLM, TTS,
HeyGen, HyperFrames render, deployment or network request is made.
"""
from __future__ import annotations

import html
import json
from pathlib import Path

from reels_factory.editplan import build_edit_plan


ROOT = Path(__file__).resolve().parents[4]
OUTPUT_ROOT = ROOT / "docs" / "visual-director-demo"


def _block(role: str, start: float, end: float, speech: str) -> dict:
    return {
        "role": role,
        "start": start,
        "end": end,
        "speech": speech,
    }


COMPLEXITY = (
    "Мы усложняем продажи. Учим хитрые приёмы. Зубрим скрипты. "
    "Ищем волшебные фразы. А в основе — три вопроса."
)
PERSONA = (
    "Первый: кому продаём? Кто этот человек, чем живёт, какая у него боль."
)
VALUE = (
    "Второй: что продаём? Что человек на самом деле у нас покупает."
)
BUBBLE = (
    "Третий: как продаём? Где встречаемся с клиентом, "
    "какими словами говорим, в каком виде предлагаем."
)
FOUNDATION = "Всё остальное — надстройка над этими тремя."
ORDER = "Сначала кто, потом что, и только потом как."


def _scenario(duration: int) -> dict:
    if duration == 30:
        blocks = [
            _block(
                "hook", 0, 4,
                "Продажи держатся на трёх вопросах, и порядок решает всё.",
            ),
            _block("development", 4, 12, COMPLEXITY),
            _block("development", 12, 19.5, BUBBLE),
            _block("payoff", 19.5, 26, ORDER),
            _block(
                "cta", 26, 30,
                "Сохрани схему и проверь свой продукт сегодня.",
            ),
        ]
    elif duration == 60:
        blocks = [
            _block(
                "hook", 0, 5,
                "Все продажи сводятся к трём вопросам, но порядок важнее списка.",
            ),
            _block("development", 5, 13, COMPLEXITY),
            _block("development", 13, 21, PERSONA),
            _block(
                "development", 21, 26,
                "Ответ на него задаёт весь контекст предложения.",
            ),
            _block("development", 26, 34, VALUE),
            _block(
                "development", 34, 39,
                "Теперь можно выбирать канал и формулировку.",
            ),
            _block("development", 39, 46.5, BUBBLE),
            _block("development", 46.5, 52, FOUNDATION),
            _block(
                "development", 52, 53.5,
                "Теперь фиксируем порядок.",
            ),
            _block("payoff", 53.5, 57.5, ORDER),
            _block(
                "cta", 57.5, 60,
                "Сохрани и прогони свой продукт по схеме.",
            ),
        ]
    elif duration == 90:
        blocks = [
            _block(
                "hook", 0, 5,
                "Девяносто секунд не должны превращаться в одну говорящую голову.",
            ),
            _block("development", 5, 13, COMPLEXITY),
            _block(
                "development", 13, 19,
                "Сначала отделим стратегию от набора случайных приёмов.",
            ),
            _block("development", 19, 27, PERSONA),
            _block(
                "development", 27, 33,
                "Портрет клиента возвращает разговор к реальной задаче.",
            ),
            _block("development", 33, 41, VALUE),
            _block(
                "development", 41, 47,
                "Ценность должна быть понятна раньше выбора канала.",
            ),
            _block("development", 47, 54.5, BUBBLE),
            _block("development", 54.5, 60.5, FOUNDATION),
            _block(
                "development", 60.5, 67,
                "После этого система снова становится простой и проверяемой.",
            ),
            _block(
                "development", 67, 75,
                "Команды опять усложняют процесс. Добавляют хитрые приёмы. "
                "Переписывают скрипты. Ищут новые фразы. "
                "А в основе остаются три вопроса.",
            ),
            _block(
                "development", 75, 81,
                "Возвращаем лицо, чтобы зафиксировать главный вывод.",
            ),
            _block("payoff", 81, 87, ORDER),
            _block(
                "cta", 87, 90,
                "Сохрани схему и используй её сегодня.",
            ),
        ]
    else:
        raise ValueError(f"unsupported duration: {duration}")
    return {
        "format_version": 1,
        "mode": "offline_visual_director_fixture",
        "language": "ru",
        "theme": "три вопроса продаж",
        "target_duration_s": duration,
        "title": f"Visual Director timeline — {duration} секунд",
        "blocks": blocks,
    }


def _config() -> dict:
    return {
        "format": "avatar",
        "language": "ru",
        "avatar": {
            "engine": "avatar_iv",
            "heygen_asset_id": "offline-photo-avatar-iv-fixture",
        },
        "edit_plan": {
            "visual_director": {
                "enabled": True,
                "min_seconds": 3.0,
                "max_seconds": 9.5,
                "max_per_30_seconds": 4,
                "max_llm_windows": 3,
                "llm": {"enabled": False},
            },
            "bubble": {
                "enabled": True,
                "min_seconds": 3.0,
                "max_seconds": 6.0,
                "max_per_45_seconds": 1,
                "shape": "circle",
                "position": "bottom_left",
            },
        },
        "product": {"cta_button": "СОХРАНИТЬ"},
    }


def _json(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _visual_label(window: dict) -> tuple[str, str]:
    effect = window.get("effect") or {}
    if effect.get("visual_director"):
        template = effect["visual_director"]["template"]
        labels = {
            "complexity_cloud": "COMPLEXITY",
            "persona_card": "PERSONA",
            "value_layers": "VALUE",
            "concept_nodes": "NODES",
            "sequence_flow": "SEQUENCE",
        }
        return labels[template], template
    if effect.get("bubble"):
        return "BUBBLE", "bubble"
    if window["role"] == "cta":
        return "AVATAR + CTA", "cta"
    return "AVATAR", "avatar"


def _max_avatar_only(plan: dict) -> float:
    current = maximum = 0.0
    for window in plan["windows"]:
        timing = window["estimated_timing"]
        duration = float(timing["end"]) - float(timing["start"])
        if (
            window["coverage"] == "avatar"
            and (window.get("effect") or {}).get("type") == "none"
        ):
            current += duration
            maximum = max(maximum, current)
        else:
            current = 0.0
    return round(maximum, 3)


def _svg(duration: int, plan: dict) -> str:
    width, height = 1520, 410
    left, right = 120, 40
    usable = width - left - right
    scale = usable / duration
    colors = {
        "avatar": "#2563EB",
        "cta": "#0F766E",
        "bubble": "#7C3AED",
        "complexity_cloud": "#DC2626",
        "persona_card": "#EA580C",
        "value_layers": "#CA8A04",
        "concept_nodes": "#16A34A",
        "sequence_flow": "#0891B2",
    }
    short = {
        "complexity_cloud": "CLOUD",
        "persona_card": "PERSONA",
        "value_layers": "VALUE",
        "concept_nodes": "NODES",
        "sequence_flow": "FLOW",
        "bubble": "BUBBLE",
        "avatar": "AVATAR",
        "cta": "CTA",
    }

    ticks = []
    tick_step = 5 if duration == 30 else 10
    for second in range(0, duration + 1, tick_step):
        x = left + second * scale
        ticks.append(
            f'<line x1="{x:.1f}" y1="70" x2="{x:.1f}" y2="285" '
            'stroke="#CBD5E1" stroke-width="1"/>'
            f'<text x="{x:.1f}" y="310" text-anchor="middle" '
            f'class="tick">{second}s</text>'
        )

    states = []
    face = []
    legend = []
    seen = set()
    for window in plan["windows"]:
        start = float(window["estimated_timing"]["start"])
        end = float(window["estimated_timing"]["end"])
        x = left + start * scale
        w = max(1.0, (end - start) * scale)
        label, key = _visual_label(window)
        display = label if w >= 84 else short[key] if w >= 42 else ""
        states.append(
            f'<rect x="{x:.1f}" y="92" width="{w:.1f}" height="68" '
            f'rx="8" fill="{colors[key]}"/>'
            + (
                f'<text x="{x + w / 2:.1f}" y="133" text-anchor="middle" '
                f'class="seg">{html.escape(display)}</text>'
                if display else ""
            )
        )
        visible = window["coverage"] in {"avatar", "mixed"}
        face.append(
            f'<rect x="{x:.1f}" y="198" width="{w:.1f}" height="42" '
            f'rx="7" fill="{"#60A5FA" if visible else "#E2E8F0"}"/>'
            + (
                f'<text x="{x + w / 2:.1f}" y="225" text-anchor="middle" '
                f'class="face">{"VISIBLE" if visible else "HIDDEN"}</text>'
                if w >= 54 else ""
            )
        )
        if key not in seen:
            seen.add(key)
            legend.append(
                f'<rect x="{left + (len(legend) % 6) * 215}" '
                f'y="{340 + (len(legend) // 6) * 28}" width="18" height="18" '
                f'rx="4" fill="{colors[key]}"/>'
                f'<text x="{left + 26 + (len(legend) % 6) * 215}" '
                f'y="{354 + (len(legend) // 6) * 28}" '
                f'class="legend">{html.escape(label)}</text>'
            )
    summary = plan["summary"]
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<style>
  .title {{ font: 700 25px Arial, sans-serif; fill: #0F172A; }}
  .subtitle {{ font: 14px Arial, sans-serif; fill: #475569; }}
  .row {{ font: 700 14px Arial, sans-serif; fill: #334155; }}
  .seg {{ font: 700 12px Arial, sans-serif; fill: white; }}
  .face {{ font: 700 11px Arial, sans-serif; fill: #0F172A; }}
  .tick {{ font: 12px Arial, sans-serif; fill: #64748B; }}
  .legend {{ font: 12px Arial, sans-serif; fill: #334155; }}
</style>
<rect width="100%" height="100%" fill="#F8FAFC"/>
<text x="{left}" y="34" class="title">Canonical Visual Director · {duration}s</text>
<text x="{left}" y="57" class="subtitle">built-in: {summary['built_in_visual_windows']} windows / {summary['built_in_visual_seconds']}s · bubble: {summary['bubble_windows']} · max avatar-only: {_max_avatar_only(plan)}s</text>
{''.join(ticks)}
<text x="18" y="132" class="row">VISUAL</text>
{''.join(states)}
<text x="18" y="225" class="row">FACE</text>
{''.join(face)}
{''.join(legend)}
</svg>
"""


def main() -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    rows = []
    for duration in (30, 60, 90):
        scenario = _scenario(duration)
        plan = build_edit_plan(
            scenario,
            _config(),
            index={},
            require_asset_files=False,
        )
        if not plan["validation"]["all_pass"]:
            raise RuntimeError("; ".join(plan["validation"]["errors"]))
        output = OUTPUT_ROOT / f"{duration}s"
        output.mkdir(parents=True, exist_ok=True)
        _json(output / "scenario.json", scenario)
        _json(output / "edit_plan.json", plan)
        (output / "timeline.svg").write_text(
            _svg(duration, plan),
            encoding="utf-8",
        )
        rows.append(
            f"| {duration}s | {plan['summary']['windows']} | "
            f"{plan['summary']['built_in_visual_windows']} | "
            f"{plan['summary']['built_in_visual_seconds']}s | "
            f"{plan['summary']['bubble_windows']} | {_max_avatar_only(plan)}s |"
        )
    readme = """# Visual Director — offline 30/60/90 demo

Production `build_edit_plan()` был запущен по трём approved-scenario fixtures.
LLM, ElevenLabs, HeyGen, HyperFrames render, deploy и production services не
вызывались.

| Timeline | Windows | Built-in windows | Built-in seconds | Bubble | Max avatar-only |
|---:|---:|---:|---:|---:|---:|
""" + "\n".join(rows) + """

В каждой папке находятся `scenario.json`, `edit_plan.json` и `timeline.svg`.
"""
    (OUTPUT_ROOT / "README.md").write_text(readme, encoding="utf-8")
    print(OUTPUT_ROOT)


if __name__ == "__main__":
    main()
