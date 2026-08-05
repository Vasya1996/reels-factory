# -*- coding: utf-8 -*-
"""Планы камеры (зумы + вспышки) и субтитры из word-timings.

Делает три вещи:
  1. Режет речь на ПЛАНЫ 1.2–3.9с по самой сильной паузе в окне (не по таймеру,
     фраза не рвётся посередине).
  2. Каждому плану назначает масштаб: push_in (наезд 100→118% за ≤1.5с) или
     static (100 / 108 / 110 / 112%), соседние отличаются минимум на 8%.
  3. Генерирует ASS-субтитры в утверждённом стиле: белый текст без обводки,
     под ним чёрная копия с blur 18 (мягкое тёмное сияние), 1–2 слова в реплике.

Выход: zoom_expr.txt (выражение z для ffmpeg zoompan), flash_expr.txt (выражение
brightness для eq), caps.ass, plan.json.

Запуск:
    python camera_plan.py --words words.json --duration 32.4 --out-dir out/

ГРАБЛИ (стоили целой итерации):
  * два вызова pow() в одном выражении z ломают zoompan МОЛЧА: ошибки нет,
    рендер проходит, зум схлопывается в 1.0. Поэтому ease-out здесь p*(2-p).
  * дельта меньше 14 п.п. глазом не читается; наезд длиннее ~2с не ощущается.
  * зум проверять measure_zoom.py, а не глазами: спикер сам наклоняется к камере
    и на стоп-кадрах это выглядит как несуществующий наезд.
"""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

# план: (тип, масштаб_от, масштаб_до)
PATTERN = [("in", 1.00, 1.18), ("static", 1.00, 1.00), ("static", 1.10, 1.10),
           ("static", 1.00, 1.00), ("static", 1.12, 1.12), ("in", 1.02, 1.16),
           ("static", 1.00, 1.00), ("static", 1.08, 1.08)]
RAMP_MAX = 1.5          # наезд укладывается в 1.5с, дальше кадр держится
TARGET_MIN, TARGET_MAX = 1.2, 3.9
FLASH_LEN = 0.11        # длина вспышки, с
FLASH_MAX = 2           # максимум вспышек за ролик
CAPS_FONT, CAPS_SIZE, CAPS_MARGIN_V, CAPS_BLUR = "Arial", 104, 300, 18


def cut_into_plans(words, duration):
    """Планы 1.2–3.9с; граница — самая сильная пауза в окне (точка > запятой > пауза)."""
    segs, i = [], 0
    while i < len(words):
        t0 = words[i]["start"]
        cands = []
        for j in range(i, len(words)):
            w = words[j]
            nxt = words[j + 1] if j + 1 < len(words) else None
            cut_at = nxt["start"] if nxt else duration
            length = cut_at - t0
            if length < TARGET_MIN:
                continue
            if length > TARGET_MAX:
                break
            gap = (nxt["start"] - w["end"]) if nxt else 9
            last = w["text"].rstrip()[-1:]
            weight = gap + (0.6 if last in ".!?" else 0.25 if last in ",…" else 0)
            cands.append((weight, j, cut_at))
        if cands:
            _, j, cut_at = max(cands)
        else:                                    # окно без границ — режем по длине
            j = i
            while j + 1 < len(words) and words[j + 1]["start"] - t0 < TARGET_MAX:
                j += 1
            cut_at = words[j + 1]["start"] if j + 1 < len(words) else duration
        segs.append(dict(start=t0, end=cut_at,
                         text=" ".join(x["text"] for x in words[i:j + 1])))
        i = j + 1
    segs[-1]["end"] = duration
    return segs


def build_zoom(segs):
    terms, plan = [], []
    for i, s in enumerate(segs):
        kind, z0, z1 = PATTERN[i % len(PATTERN)]
        a, b = s["start"], s["end"]
        if kind == "static":
            terms.append(f"between(T,{a:.3f},{b:.3f})*{z0 - 1:.4f}")
        else:
            ramp = min(RAMP_MAX, max(0.4, b - a))
            pr = f"min(1,(T-{a:.3f})/{ramp:.3f})"
            # ease-out БЕЗ pow(): второй pow() в выражении ломает zoompan молча
            terms.append(f"between(T,{a:.3f},{b:.3f})*"
                         f"({z0 - 1:.4f}+{z1 - z0:.4f}*({pr}*(2-{pr})))")
        plan.append(dict(i=i, start=round(a, 2), end=round(b, 2), len=round(b - a, 2),
                         kind=kind, z_from=z0, z_to=z1, text=s["text"]))
    return ("1.0+" + "+".join(terms)).replace("T", "(on/25.0)"), plan


def build_flash(segs, plan):
    """Вспышка сопровождает возврат к 100% после крупного плана. Максимум FLASH_MAX."""
    at = [segs[1]["start"]] if len(segs) > 1 else []
    for p in plan[4:]:
        if len(at) >= FLASH_MAX:
            break
        if p["kind"] == "static" and p["z_from"] == 1.00:
            at.append(p["start"])
            break
    expr = "+".join(f"0.85*max(0,1-abs(t-{t:.3f})/{FLASH_LEN:.2f})" for t in at)
    return expr, at


def ts(t):
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def build_caps(words, duration, max_chars=15):
    """Группы по 1–2 слова; два слоя: чёрное размытое сияние + чистый белый текст."""
    groups, buf = [], []
    for w in words:
        cand = buf + [w]
        if len(" ".join(x["text"] for x in cand)) > max_chars and buf:
            groups.append(buf); buf = [w]
        elif len(cand) >= 2:
            groups.append(cand); buf = []
        else:
            buf = cand
    if buf:
        groups.append(buf)

    lines = []
    for i, g in enumerate(groups):
        text = " ".join(x["text"] for x in g).strip(" ,")
        start = g[0]["start"]
        nxt = groups[i + 1][0]["start"] if i + 1 < len(groups) else duration
        end = max(start + 0.25, min(nxt, g[-1]["end"] + 0.45))
        lines.append(f"Dialogue: 0,{ts(start)},{ts(end)},Glow,,0,0,0,,{{\\blur{CAPS_BLUR}}}{text}")
        lines.append(f"Dialogue: 1,{ts(start)},{ts(end)},Main,,0,0,0,,{text}")

    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Glow,{CAPS_FONT},{CAPS_SIZE},&H00000000,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,26,0,2,70,70,{CAPS_MARGIN_V},204
Style: Main,{CAPS_FONT},{CAPS_SIZE},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,0,0,2,70,70,{CAPS_MARGIN_V},204

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    return head + "\n".join(lines) + "\n", len(groups)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--words", required=True, help="words.json с пословным alignment")
    ap.add_argument("--duration", type=float, required=True)
    ap.add_argument("--out-dir", default=".")
    args = ap.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    words = json.load(io.open(args.words, encoding="utf-8"))["words"]

    segs = cut_into_plans(words, args.duration)
    zoom_expr, plan = build_zoom(segs)
    flash_expr, flash_at = build_flash(segs, plan)
    caps, n_caps = build_caps(words, args.duration)

    (out / "zoom_expr.txt").write_text(zoom_expr, encoding="utf-8")
    (out / "flash_expr.txt").write_text(flash_expr, encoding="utf-8")
    (out / "caps.ass").write_text(caps, encoding="utf-8")
    json.dump(dict(plans=plan, flash_at=flash_at),
              io.open(out / "plan.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"планов: {len(plan)}, средняя длина {sum(p['len'] for p in plan)/len(plan):.2f}с")
    for p in plan:
        z = (f"наезд {int(p['z_from']*100)}→{int(p['z_to']*100)}%" if p["kind"] == "in"
             else f"{int(p['z_from']*100)}%")
        print(f"  {p['start']:6.2f}-{p['end']:6.2f} ({p['len']:.2f}с) {z:16s} {p['text'][:50]}")
    print(f"вспышки: {[round(t, 2) for t in flash_at]}")
    print(f"субтитров: {n_caps} реплик -> {out/'caps.ass'}")


if __name__ == "__main__":
    main()
