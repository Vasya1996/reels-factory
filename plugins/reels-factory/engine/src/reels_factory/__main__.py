"""CLI движка: python -m reels_factory script|make|verify.

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


def _cmd_script_text(args, cfg):
    from reels_factory.scenario import run_verbatim_path, ScenarioError
    from reels_factory.llm import ClaudeSkillRunner

    wd = _resolve_workdir(args.workdir)
    wd.mkdir(parents=True, exist_ok=True)
    if args.text_file:
        text = Path(args.text_file).read_text(encoding="utf-8")
    else:
        from reels_factory.transcribe import transcribe_file
        meta = transcribe_file(args.audio, wd, language=cfg.get("language", "ru"))
        words = json.loads(Path(meta["out"]).read_text(encoding="utf-8"))["words"]
        text = " ".join(w["text"] for w in words)
    try:
        res = run_verbatim_path(wd, text, ClaudeSkillRunner(),
                                language=cfg.get("language", "ru"))
    except (ScenarioError, Exception) as e:
        print(json.dumps({"ok": False, "error": str(e)[:500]}, ensure_ascii=False))
        sys.exit(1)
    print(json.dumps(res, ensure_ascii=False))


def _cmd_script_idea(args, cfg):
    from reels_factory.scenario import run_generated_path
    from reels_factory.llm import ClaudeSkillRunner

    wd = _resolve_workdir(args.workdir)
    wd.mkdir(parents=True, exist_ok=True)
    idea = json.loads(Path(args.idea_file).read_text(encoding="utf-8"))
    try:
        res = run_generated_path(wd, idea, ClaudeSkillRunner(),
                                 language=cfg.get("language", "ru"))
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)[:500]}, ensure_ascii=False))
        sys.exit(1)
    print(json.dumps(res, ensure_ascii=False))
    sys.exit(0 if res["verdict"]["pass"] else 2)


def _cmd_ideas(args, cfg):
    from reels_factory.scenario import run_ideas
    from reels_factory.llm import ClaudeSkillRunner

    wd = _resolve_workdir(args.workdir)
    wd.mkdir(parents=True, exist_ok=True)
    if args.source_file:
        text = Path(args.source_file).read_text(encoding="utf-8")
    else:
        from reels_factory.transcribe import transcribe_file
        meta = transcribe_file(args.audio, wd, language=cfg.get("language", "ru"))
        words = json.loads(Path(meta["out"]).read_text(encoding="utf-8"))["words"]
        text = " ".join(w["text"] for w in words)
    try:
        res = run_ideas(wd, text, ClaudeSkillRunner(), cfg.get("language", "ru"))
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)[:500]}, ensure_ascii=False))
        sys.exit(1)
    print(json.dumps(res, ensure_ascii=False))


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

    p_v = sub.add_parser("verify", help="перепроверить готовый рилс (7 QA-гейтов)")
    p_v.add_argument("--workdir", required=True)
    p_v.add_argument("--mp4", default=None, help="путь к mp4 (по умолчанию <workdir>/reel.mp4)")

    p_st = sub.add_parser("script-text",
                          help="путь «дословно»: текст/аудио пользователя -> scenario.json без правок")
    p_st.add_argument("--workdir", required=True)
    g = p_st.add_mutually_exclusive_group(required=True)
    g.add_argument("--text-file", dest="text_file", help="файл с готовым текстом")
    g.add_argument("--audio", help="аудио/видео с речью (локальная расшифровка)")

    p_si = sub.add_parser("script-idea",
                          help="путь «из сырья»: задание-идея -> генерация+хуманизация+судья")
    p_si.add_argument("--workdir", required=True)
    p_si.add_argument("--idea-file", required=True, dest="idea_file",
                      help="JSON: {idea, length_s, quotes[], persona?}")

    p_i = sub.add_parser("ideas", help="извлечь 2-3 идеи рилсов из сырья (текст/аудио)")
    p_i.add_argument("--workdir", required=True)
    gi = p_i.add_mutually_exclusive_group(required=True)
    gi.add_argument("--source-file", dest="source_file", help="файл с текстом-сырьём")
    gi.add_argument("--audio", help="аудио/видео сырьё (локальная расшифровка)")

    args = ap.parse_args()
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
    elif args.cmd == "script-text":
        _cmd_script_text(args, cfg)
    elif args.cmd == "script-idea":
        _cmd_script_idea(args, cfg)
    elif args.cmd == "ideas":
        _cmd_ideas(args, cfg)


if __name__ == "__main__":
    main()
