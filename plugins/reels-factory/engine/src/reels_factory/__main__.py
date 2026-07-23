"""CLI движка: python -m reels_factory script|make|verify|edit.

Весь вывод — JSON (ensure_ascii=False). exit-код 2 = провал QA-гейта (make/verify).
Тема/продукт/формат/ключи берутся из factory/config.yaml (load_config).
"""
import argparse
import json
import sys
from pathlib import Path

from reels_factory.config import WORK_ROOT, load_config, ConfigError


def _resolve_workdir(name: str) -> Path:
    p = Path(name)
    return p if p.is_absolute() else WORK_ROOT / name


def _fixes_hypothesis(cfg: dict) -> dict:
    product = cfg.get("product") or {}
    return {
        "theme": cfg.get("theme"),
        "theme_spoken": cfg.get("theme_spoken"),
        "theme_captions": cfg.get("theme_captions"),
        "brand_captions": product.get("brand_captions"),
    }


def _cmd_script(args, cfg):
    from reels_factory.scenario import generate_scenario, ScenarioError
    from reels_factory.llm import ClaudeCliRunner

    product = cfg.get("product") or {}
    theme = args.theme or cfg.get("theme")
    hypothesis = {
        "theme": theme,
        "theme_spoken": args.theme_spoken or cfg.get("theme_spoken") or theme,
        "hook_type": args.hook_type or "",
        "case": args.case,
        "insight": args.insight,
        "legend": product.get("legend"),
        "cta_phrase": product.get("cta_phrase"),
        "product_name": product.get("name"),
        "persona": cfg.get("persona"),
    }
    wd = _resolve_workdir(args.workdir)
    wd.mkdir(parents=True, exist_ok=True)
    try:
        sc = generate_scenario(wd, hypothesis, ClaudeCliRunner())
    except ScenarioError as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        sys.exit(1)
    print(json.dumps(sc, ensure_ascii=False))


def _cmd_make(args, cfg):
    from reels_factory.pipeline import run_make

    fmt = cfg.get("format", "split")
    if fmt != "avatar" and not args.broll:
        print(json.dumps(
            {"ok": False, "error": f"нужен --broll: формат {fmt!r} требует "
             "непрерывный видеоряд (обязателен для split/fullscreen)"},
            ensure_ascii=False))
        sys.exit(1)

    broll_plan = None
    if args.broll_plan:
        broll_plan = json.loads(Path(args.broll_plan).read_text(encoding="utf-8"))
    offset = args.offset
    if offset is None:
        # avatar собирается и без низового видеоряда (вставки — по broll-plan);
        # split/fullscreen нужен непрерывный низ, значит offset или broll-plan
        if fmt != "avatar" and broll_plan is None:
            print(json.dumps({"ok": False, "error": "нужен --offset либо --broll-plan"},
                             ensure_ascii=False))
            sys.exit(1)
        offset = 0.0

    wd = _resolve_workdir(args.workdir)
    result = run_make(cfg, args.broll, offset, wd, broll_plan=broll_plan)
    print(json.dumps(result, ensure_ascii=False))
    if not result["ok"]:
        sys.exit(1)
    sys.exit(0 if result["qa_pass"] else 2)


def _cmd_verify(args, cfg):
    from reels_factory.verify import verify_reel

    wd = _resolve_workdir(args.workdir)
    mp4 = Path(args.mp4) if args.mp4 else wd / "reel.mp4"
    timed_path = wd / "scenario.timed.json"
    try:
        timed = json.loads(timed_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(json.dumps(
            {"ok": False, "error": f"Не найден {timed_path}: сначала выполните "
             "'python -m reels_factory make' (сборка создаёт scenario.timed.json)."},
            ensure_ascii=False))
        sys.exit(1)
    words_path = wd / "words.fixed.json"
    words = json.loads(words_path.read_text(encoding="utf-8")) if words_path.exists() else None
    qa = verify_reel(mp4, timed, words=words, hypothesis=_fixes_hypothesis(cfg),
                     format=cfg.get("format", "split"))
    print(json.dumps(qa, ensure_ascii=False))
    sys.exit(0 if qa["all_pass"] else 2)


def _ensure_whoosh_asset():
    from reels_factory.compose import ensure_whoosh
    w = ensure_whoosh()
    return w if w.exists() else None


def _apply_brolls(src: Path, out: Path, brolls: list) -> Path:
    """Наложить вставки по ТЗ: у каждой окно [start, end] в таймлайне ролика и
    источник — файл (src) либо поиск в стоках (query -> Pexels/ytsearch).
    Скачанные клипы кэшируются рядом с результатом (broll_<i>.mp4)."""
    from reels_factory.broll import render_broll, FULL
    from reels_factory.sources import fetch_broll

    inserts = []
    for i, b in enumerate(brolls):
        clip = b.get("src")
        if not clip:
            clip = out.parent / f"broll_{i}.mp4"
            if not Path(clip).exists():
                fetch_broll(b["query"], clip)
        inserts.append({
            "kind": b.get("kind") or FULL,
            "start": float(b["start"]), "end": float(b["end"]),
            "src": str(clip), "offset": float(b.get("offset", 0)),
            **({"pos": b["pos"]} if b.get("pos") else {}),
        })
    return render_broll(src, inserts, out)


def _burn_captions(src: Path, out: Path, language: str,
                   style: str = "karaoke", keywords: list | None = None) -> Path:
    """Распознать речь ролика и прожечь субтитры выбранного пресета
    (karaoke/popword/boxed, см. captions.py). Кладёт caps.ass рядом."""
    from reels_factory.captions import build_ass
    from reels_factory.config import FFMPEG, CAPTION_FONT
    from reels_factory.render import load_words_file, probe_wh
    from reels_factory.transcribe import transcribe_file
    import subprocess

    rdir = out.parent
    transcribe_file(str(src), str(rdir), model_size="small", language=language)
    words = load_words_file(str(rdir / "words.json"))
    w, h = probe_wh(str(src))
    build_ass(words, str(rdir / "caps.ass"), font=CAPTION_FONT,
              play_w=w, play_h=h, pos=(int(w * 0.5), int(h * 0.78)),
              style=style, keywords=keywords)
    p = subprocess.run(
        [FFMPEG, "-y", "-i", str(src), "-vf", "ass=caps.ass",
         "-c:v", "libx264", "-crf", "19", "-preset", "medium", "-pix_fmt", "yuv420p",
         "-c:a", "copy", str(out)],
        cwd=str(rdir), capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    if p.returncode != 0 or not out.exists():
        raise RuntimeError(f"прожиг субтитров упал: {(p.stderr or '')[:500]}")
    return out


# Вспышка-переход ставится на старте фразы, но не чаще раза в FLASH_MIN_GAP_S:
# смена мысли — переход, каждая фраза — уже стробоскоп.
FLASH_MIN_GAP_S = 6.0


def _cmd_edit(args):
    """Монтажные шаги на произвольном ролике — чтобы оценить их на своём
    материале до включения в конвейере. Конфиг не нужен."""
    from reels_factory.edit import apply_finish, apply_plan, jump_cut, EditError
    from reels_factory.brief import BriefError
    from reels_factory.editplan import (
        detect_silences, plan_edit, validate_plan, speech_segments,
        fill_static_gaps,
    )
    from reels_factory.render import media_dur

    src = Path(args.input)
    out = Path(args.output)
    steps = []
    plan = qa = None
    try:
        cur = src
        if args.auto:
            # полный монтаж «как у монтажёра»: джамп-каты -> зумы по фразам ->
            # вспышки на сменах мысли -> ритм-добивка -> б-роллы по ТЗ ->
            # цвет/зерно -> субтитры
            from reels_factory.edit import jump_cut_ffmpeg
            from reels_factory.zoom import plan_zoom_segments, render_zoom
            from reels_factory.brief import load_brief, validate_brief

            brief = load_brief(args.brief) if args.brief else {}

            # ffmpeg-джамп-каты: auto-editor на HeyGen-материале отдавал
            # чёрное видео, поэтому в auto-режиме режем сами
            cur = jump_cut_ffmpeg(cur, out.with_name(out.stem + "_cut.mp4"),
                                  margin_s=args.margin)
            steps.append("jump_cuts")
            dur = media_dur(str(cur))
            brief = validate_brief(brief, dur)
            brolls = brief.get("brolls") or []
            silences = detect_silences(cur)
            segs = speech_segments(dur, silences)

            # зумы по фразам (push/punch/pulse с наведением на лицо)
            zsegs = plan_zoom_segments(segs)
            if zsegs:
                cur = render_zoom(cur, out.with_name(out.stem + "_zoom.mp4"),
                                  zsegs, duration=dur)
                steps.append("zoom")

            # вспышки-переходы: старты фраз, не чаще FLASH_MIN_GAP_S
            flash = []
            for s, _e in segs[1:]:
                if not flash or s - flash[-1] >= FLASH_MIN_GAP_S:
                    if 1.0 < s < dur - 1.0:
                        flash.append(round(s, 3))

            # ритм-добивка: статичные дыры длиннее 3с закрываются панчами;
            # окна вставок — тоже движение, панчи туда не ставим
            covered = [(zs, ze) for zs, ze, _k, _st in zsegs]
            covered += [(t - 0.15, t + 0.15) for t in flash]
            covered += [(b["start"], b["end"]) for b in brolls]
            punch = fill_static_gaps(covered, dur)

            # свуш и на входах вставок: появление б-ролла должно быть слышно
            whoosh_at = sorted(set(flash + [b["start"] for b in brolls]))
            plan = {"duration": round(dur, 3), "punch": punch,
                    "whoosh": whoosh_at, "flash": flash}
            # гейты ритма считают ВСЕ события: зумы, панчи, вспышки
            events = sorted([zs for zs, _e, _k, _st in zsegs] +
                            [t for t, _d in punch] + flash)
            qa = validate_plan({"duration": dur,
                                "punch": [(t, 0.3) for t in events]})
            whoosh = _ensure_whoosh_asset()
            music = args.music or brief.get("music")
            need_more = bool(args.captions or brolls)
            final = out.with_name(out.stem + "_nocap.mp4") if need_more else out
            cur = apply_plan(cur, final, plan, grade=True, grain=True,
                             whoosh_wav=whoosh, music=Path(music) if music else None)
            steps += ["punch", "flash", "whoosh", "grade", "grain"]
            if music:
                steps.append("music")
            if brolls:
                cur = _apply_brolls(cur, out.with_name(out.stem + "_broll.mp4"),
                                    brolls)
                steps.append("broll")
            if args.captions:
                caps = brief.get("captions") or {}
                cur = _burn_captions(
                    cur, out, brief.get("language") or args.language,
                    style=caps.get("style") or args.caption_style,
                    keywords=caps.get("keywords"))
                steps.append("captions")
            elif cur != out:
                cur = Path(cur).replace(out) or out
            print(json.dumps({"ok": True, "input": str(src), "output": str(out),
                              "steps": steps, "plan": plan, "qa": qa,
                              "brolls": brolls}, ensure_ascii=False))
            return
        if args.jump_cuts:
            cur = jump_cut(cur, out.with_name(out.stem + "_cut.mp4"),
                           threshold=args.threshold, margin_s=args.margin)
            steps.append("jump_cuts")
        if args.grade or args.grain:
            cur = apply_finish(cur, out, grade=args.grade, grain=args.grain)
            steps += [s for s, on in (("grade", args.grade), ("grain", args.grain)) if on]
        elif cur != src:
            cur = cur.replace(out)
        if not steps:
            print(json.dumps({"ok": False, "error": "нечего делать: включи "
                              "--jump-cuts и/или --grade/--grain"}, ensure_ascii=False))
            sys.exit(1)
    except (EditError, BriefError) as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        sys.exit(1)
    print(json.dumps({"ok": True, "input": str(src), "output": str(cur),
                      "steps": steps}, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(prog="reels_factory")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_s = sub.add_parser("script", help="сгенерировать сценарий -> scenario.json")
    p_s.add_argument("--workdir", required=True, help="имя папки в work/ или абсолютный путь")
    p_s.add_argument("--theme", default=None, help="переопределить тему из конфига")
    p_s.add_argument("--theme-spoken", default=None, dest="theme_spoken",
                     help="как тема звучит в речи (для склонений/сокращений)")
    p_s.add_argument("--hook-type", default=None, dest="hook_type")
    p_s.add_argument("--case", default=None, help="кейс/история ролика")
    p_s.add_argument("--insight", default=None, help="неочевидный факт")

    p_m = sub.add_parser("make", help="сборка рилса из scenario.json + QA-гейты")
    p_m.add_argument("--workdir", required=True)
    p_m.add_argument("--broll", default=None,
                     help="ссылка на видеоряд или локальный файл (для avatar-формата "
                          "без вставок можно опустить)")
    p_m.add_argument("--offset", type=float, default=None,
                     help="один offset на весь ролик (без --broll-plan)")
    p_m.add_argument("--broll-plan", default=None, dest="broll_plan",
                     help="JSON {segments:[{role,offset,slow?}], punch:[[start,dur],...], ...} "
                          "— мультисегментный низ + панч-окна (наезд на килл/пик-моментах)")

    p_e = sub.add_parser("edit", help="монтажные шаги на готовом ролике (без конфига)")
    p_e.add_argument("--input", required=True, help="исходный mp4")
    p_e.add_argument("--output", required=True, help="куда положить результат")
    p_e.add_argument("--jump-cuts", action="store_true", dest="jump_cuts",
                     help="вырезать паузы (нужен auto-editor)")
    p_e.add_argument("--grade", action="store_true", help="единый цвет")
    p_e.add_argument("--grain", action="store_true", help="микро-зерно")
    p_e.add_argument("--auto", action="store_true",
                     help="полный монтаж по правилам ритма: джамп-каты, зумы по "
                          "фразам, вспышки-переходы, свуши, цвет, зерно, субтитры")
    p_e.add_argument("--no-captions", action="store_false", dest="captions",
                     help="в --auto не распознавать речь и не жечь субтитры")
    p_e.add_argument("--language", default="ru",
                     help="язык распознавания для субтитров (по умолчанию ru)")
    p_e.add_argument("--brief", default=None,
                     help="JSON-ТЗ монтажа: окна б-роллов (start/end/query|src), "
                          "стиль субтитров, акцентные слова (см. brief.py)")
    p_e.add_argument("--caption-style", default="karaoke", dest="caption_style",
                     choices=["karaoke", "popword", "boxed"],
                     help="пресет субтитров (перекрывается ТЗ)")
    p_e.add_argument("--music", default=None, help="фоновый трек (с дакингом)")
    p_e.add_argument("--threshold", type=float, default=0.04,
                     help="порог тишины, доля от пика (по умолчанию 0.04)")
    p_e.add_argument("--margin", type=float, default=0.15,
                     help="запас вокруг речи в секундах (по умолчанию 0.15)")

    p_v = sub.add_parser("verify", help="перепроверить готовый рилс (7 QA-гейтов)")
    p_v.add_argument("--workdir", required=True)
    p_v.add_argument("--mp4", default=None, help="путь к mp4 (по умолчанию <workdir>/reel.mp4)")

    args = ap.parse_args()

    # edit работает на произвольном файле — factory/config.yaml ему не нужен
    if args.cmd == "edit":
        _cmd_edit(args)
        return

    try:
        cfg = load_config()
    except ConfigError as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        sys.exit(1)

    if args.cmd == "script":
        _cmd_script(args, cfg)
    elif args.cmd == "make":
        _cmd_make(args, cfg)
    elif args.cmd == "verify":
        _cmd_verify(args, cfg)


if __name__ == "__main__":
    main()
