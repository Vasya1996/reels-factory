"""CLI движка: python -m reels_factory script|make|verify|edit.

Весь вывод — JSON (ensure_ascii=False). exit-код 2 = провал QA-гейта (make/verify).
Тема/продукт/формат/ключи берутся из factory/config.yaml (load_config).
"""
import argparse
import json
import sys
from pathlib import Path

from reels_factory.config import WORK_ROOT, load_config, ConfigError
from reels_factory.clients import load_client


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
        "target_duration_s":
            ((cfg.get("limits") or {}).get("target_duration_s")),
    }
    wd = _resolve_workdir(args.workdir)
    wd.mkdir(parents=True, exist_ok=True)
    try:
        sc = generate_scenario(wd, hypothesis, ClaudeCliRunner())
    except ScenarioError as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        sys.exit(1)
    print(json.dumps(sc, ensure_ascii=False))


def _build_meter(wd):
    """Учёт трат для этой сборки — или None, если считать не для кого.

    chat_id и job_id лежат в job.input.json, который бот кладёт в workdir перед
    постановкой в очередь (bot.py:enqueue_build). Ручной прогон движка из
    консоли этого файла не имеет — там учёта нет, и это правильно: платит
    разработчик, а не пользователь.
    """
    from reels_factory.billing import JobMeter, LedgerStore
    from reels_factory.config import load_billing_config
    # WORK_ROOT уже импортирован в __main__.py на уровне модуля (строка 11).

    billing = load_billing_config()
    if not billing["enabled"]:
        return None
    input_path = Path(wd) / "job.input.json"
    try:
        doc = json.loads(input_path.read_text(encoding="utf-8"))
        chat_id = int(doc["user_id"])
        job_id = str(doc["job_id"])
    except FileNotFoundError:
        # Ручной прогон разработчика без job.input.json — платить некому,
        # тишина здесь ожидаема и должна остаться такой.
        return None
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as e:
        # Файл ЕСТЬ, но нечитаем/битый: это чужая job, а не ручной прогон —
        # render всё равно продолжится и спишет реальные деньги без журнала.
        # Молчание здесь было основной находкой ревью — печатаем в stderr,
        # чтобы попасть в journalctl.
        print(f"[make] job.input.json повреждён, учёт трат отключён: {e}",
              file=sys.stderr)
        return None
    return JobMeter(
        LedgerStore(WORK_ROOT / "billing.sqlite3"),
        chat_id=chat_id, job_id=job_id,
        rates=billing["rates"], markup=billing["markup"],
    )


def _cmd_make(args, cfg):
    from reels_factory.pipeline import run_make

    fmt = cfg.get("format", "split")
    if fmt != "avatar":
        print(json.dumps(
            {"ok": False, "error": f"формат {fmt!r} не поддерживается: непрерывный "
             "видеоряд под всем роликом убран из движка, работает только "
             "format: avatar (см. ветку archive/console-broll-workflow)"},
            ensure_ascii=False))
        sys.exit(1)

    wd = _resolve_workdir(args.workdir)
    result = run_make(cfg, wd, meter=_build_meter(wd))
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
                   style: str = "karaoke", keywords: list | None = None,
                   stickers: list | None = None) -> Path:
    """Распознать речь ролика и прожечь субтитры выбранного пресета
    (karaoke/popword/boxed) + стикеры из ТЗ одним проходом. Кладёт caps.ass
    (и stickers.ass) рядом."""
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
    vf = "ass=caps.ass"
    if stickers:
        from reels_factory.stickers import build_stickers_ass
        build_stickers_ass(stickers, str(rdir / "stickers.ass"),
                           font=CAPTION_FONT, play_w=w, play_h=h)
        vf += ",ass=stickers.ass"
    p = subprocess.run(
        [FFMPEG, "-y", "-i", str(src), "-vf", vf,
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

            # зумы: лента приёмов из ТЗ (shots), иначе авто по фразам
            shots = brief.get("shots") or []
            if shots:
                from reels_factory.zoom import PUSH, PUNCH, PULSE, ZOOM_OUT
                kind_map = {"push": PUSH, "punch": PUNCH,
                            "pulse": PULSE, "zoom_out": ZOOM_OUT}
                zsegs = [
                    (s["start"], s["end"], kind_map[s["type"]],
                     float(s.get("strength",
                                 0.10 if s["type"] in ("punch", "zoom_out") else 0.08)))
                    for s in shots if s["type"] != "wide"]
            else:
                zsegs = plan_zoom_segments(segs)
            if zsegs:
                cur = render_zoom(cur, out.with_name(out.stem + "_zoom.mp4"),
                                  zsegs, duration=dur)
                steps.append("zoom")

            # вспышки-переходы: из ТЗ, иначе старты фраз не чаще FLASH_MIN_GAP_S
            if brief.get("transitions"):
                flash = list(brief["transitions"])
            else:
                flash = []
                for s, _e in segs[1:]:
                    if not flash or s - flash[-1] >= FLASH_MIN_GAP_S:
                        if 1.0 < s < dur - 1.0:
                            flash.append(round(s, 3))

            # ритм-добивка: статичные дыры длиннее 3с закрываются панчами;
            # окна вставок и стикеров — тоже движение, панчи туда не ставим
            stickers = brief.get("stickers") or []
            covered = [(zs, ze) for zs, ze, _k, _st in zsegs]
            covered += [(t - 0.15, t + 0.15) for t in flash]
            covered += [(b["start"], b["end"]) for b in brolls]
            covered += [(s["start"], s["end"]) for s in stickers]
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
                    keywords=caps.get("keywords"), stickers=stickers)
                steps.append("captions")
                if stickers:
                    steps.append("stickers")
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


def _cmd_clients(args):
    """Реестр клиентов: list — показать всех, add — завести/обновить профиль.
    Свой конфиг клиента = factory/clients/<id>.yaml; make/script с --client <id>
    берут его вместо дефолтного factory/config.yaml."""
    from reels_factory.clients import list_clients, register_client
    from reels_factory.config import CONFIG_PATH

    if args.clients_cmd == "list":
        print(json.dumps({"ok": True, "clients": list_clients()}, ensure_ascii=False))
        return

    # add: базовый конфиг (бренд/продукт/persona) + переопределение голоса и аватара
    base_path = Path(args.base) if args.base else CONFIG_PATH
    try:
        base = load_config(base_path)
        path = register_client(args.id, base, name=args.name, voice_id=args.voice_id,
                               look_id=args.look_id, asset_id=args.asset_id,
                               overwrite=args.overwrite)
    except ConfigError as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        sys.exit(1)
    print(json.dumps({"ok": True, "client": args.id, "path": str(path)}, ensure_ascii=False))


def _cmd_script_text(args, cfg):
    from reels_factory.scenario import run_verbatim_path
    from reels_factory.llm import ClaudeSkillRunner

    wd = _resolve_workdir(args.workdir)
    wd.mkdir(parents=True, exist_ok=True)
    try:
        if args.text_file:
            text = Path(args.text_file).read_text(encoding="utf-8")
        else:
            from reels_factory.transcribe import transcribe_file
            meta = transcribe_file(args.audio, wd, language=cfg.get("language", "ru"))
            words = json.loads(Path(meta["out"]).read_text(encoding="utf-8"))["words"]
            text = " ".join(w["text"] for w in words)
        res = run_verbatim_path(wd, text, ClaudeSkillRunner(),
                                language=cfg.get("language", "ru"))
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)[:500]}, ensure_ascii=False))
        sys.exit(1)
    print(json.dumps(res, ensure_ascii=False))


def _cmd_script_idea(args, cfg):
    from reels_factory.scenario import run_generated_path
    from reels_factory.llm import ClaudeSkillRunner

    wd = _resolve_workdir(args.workdir)
    wd.mkdir(parents=True, exist_ok=True)
    try:
        idea = json.loads(Path(args.idea_file).read_text(encoding="utf-8"))
        res = run_generated_path(wd, idea, ClaudeSkillRunner(),
                                 language=cfg.get("language", "ru"))
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)[:500]}, ensure_ascii=False))
        sys.exit(1)
    print(json.dumps(res, ensure_ascii=False))


def _cmd_ideas(args, cfg):
    from reels_factory.scenario import run_ideas
    from reels_factory.llm import ClaudeSkillRunner

    wd = _resolve_workdir(args.workdir)
    wd.mkdir(parents=True, exist_ok=True)
    try:
        if args.source_file:
            text = Path(args.source_file).read_text(encoding="utf-8")
        else:
            from reels_factory.transcribe import transcribe_file
            meta = transcribe_file(args.audio, wd, language=cfg.get("language", "ru"))
            words = json.loads(Path(meta["out"]).read_text(encoding="utf-8"))["words"]
            text = " ".join(w["text"] for w in words)
        res = run_ideas(wd, text, ClaudeSkillRunner(), cfg.get("language", "ru"))
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)[:500]}, ensure_ascii=False))
        sys.exit(1)
    print(json.dumps(res, ensure_ascii=False))


def _cmd_upload_photo(args):
    """Фото ведущего -> HeyGen asset_id -> профиль клиента (photo-режим).

    Один вызов на одно фото: загрузка ассета бесплатна, генерации тут нет.
    Существующий профиль обновляется только с --overwrite, при этом его голос,
    persona и product сохраняются — меняется одно фото."""
    import yaml
    from reels_factory.avatar import upload_photo_asset
    from reels_factory.clients import client_path, register_client
    from reels_factory.config import CONFIG_PATH

    try:
        path = client_path(args.client)  # заодно проверяет допустимость id
        if path.exists() and not args.overwrite:
            raise ConfigError(f"клиент {args.client!r} уже есть — передай "
                              "--overwrite, чтобы заменить фото")
        if path.exists():
            # база — сам профиль, читаем сырым yaml: старый профиль мог стать
            # невалидным, а мы всего лишь меняем в нём фото
            base = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        else:
            base = load_config(Path(args.base) if args.base else CONFIG_PATH)
        asset_id = upload_photo_asset(args.image)
        out = register_client(args.client, base, name=args.name,
                              voice_id=args.voice_id, asset_id=asset_id,
                              overwrite=True)
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)[:500]}, ensure_ascii=False))
        sys.exit(1)
    print(json.dumps({"ok": True, "client": args.client, "asset_id": asset_id,
                      "mode": "photo", "path": str(out)}, ensure_ascii=False))


def _cmd_clone_voice(args, cfg):
    from reels_factory.tts import create_voice_clone

    try:
        vid = create_voice_clone(args.audio, args.name)
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)[:500]}, ensure_ascii=False))
        sys.exit(1)
    print(json.dumps({"ok": True, "voice_id": vid}, ensure_ascii=False))


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
    p_s.add_argument("--client", default=None,
                     help="id клиента: взять factory/clients/<id>.yaml вместо config.yaml")

    p_m = sub.add_parser("make", help="сборка рилса из scenario.json + QA-гейты")
    p_m.add_argument("--workdir", required=True)
    make_profile = p_m.add_mutually_exclusive_group()
    make_profile.add_argument(
        "--client",
        default=None,
        help="id клиента: взять factory/clients/<id>.yaml вместо config.yaml",
    )
    make_profile.add_argument(
        "--config",
        dest="config_path",
        default=None,
        help="immutable config snapshot конкретной job",
    )

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
    p_v.add_argument("--client", default=None,
                     help="id клиента: взять factory/clients/<id>.yaml вместо config.yaml")

    p_c = sub.add_parser("clients", help="реестр клиентов: несколько профилей config")
    csub = p_c.add_subparsers(dest="clients_cmd", required=True)
    csub.add_parser("list", help="показать всех клиентов реестра")
    ca = csub.add_parser("add", help="завести/обновить профиль клиента")
    ca.add_argument("id", help="идентификатор клиента (имя файла профиля)")
    ca.add_argument("--name", default=None, help="человекочитаемое имя")
    ca.add_argument("--voice-id", dest="voice_id", default=None,
                    help="ElevenLabs voice_id клиента (его голос)")
    ca.add_argument("--look-id", dest="look_id", default=None,
                    help="HeyGen look_id Digital Twin -> режим video (Avatar V)")
    ca.add_argument("--asset-id", dest="asset_id", default=None,
                    help="HeyGen asset_id фото -> режим photo (Avatar IV)")
    ca.add_argument("--from", dest="base", default=None,
                    help="базовый config.yaml (по умолчанию factory/config.yaml)")
    ca.add_argument("--overwrite", action="store_true", help="заменить существующий профиль")

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

    p_up = sub.add_parser("upload-photo",
                          help="фото ведущего -> HeyGen asset_id -> профиль клиента")
    p_up.add_argument("--image", required=True, help="файл фото (jpg/png)")
    p_up.add_argument("--client", required=True, help="id клиента (имя файла профиля)")
    p_up.add_argument("--name", default=None, help="человекочитаемое имя")
    p_up.add_argument("--voice-id", dest="voice_id", default=None,
                      help="ElevenLabs voice_id клиента")
    p_up.add_argument("--from", dest="base", default=None,
                      help="базовый config.yaml (по умолчанию factory/config.yaml)")
    p_up.add_argument("--overwrite", action="store_true",
                      help="заменить фото у существующего профиля")

    p_cv = sub.add_parser("clone-voice",
                          help="клонировать голос пользователя в ElevenLabs -> voice_id")
    p_cv.add_argument("--audio", required=True, help="запись голоса (1-2 мин чистой речи)")
    p_cv.add_argument("--name", required=True, help="имя голоса в ElevenLabs")

    args = ap.parse_args()

    # edit работает на произвольном файле — factory/config.yaml ему не нужен
    if args.cmd == "edit":
        _cmd_edit(args)
        return

    # clients управляет реестром профилей и не требует активного конфига
    if args.cmd == "clients":
        _cmd_clients(args)
        return

    # upload-photo сам решает, какой конфиг брать за базу профиля
    if args.cmd == "upload-photo":
        _cmd_upload_photo(args)
        return

    # clone-voice не требует активного конфига
    if args.cmd == "clone-voice":
        _cmd_clone_voice(args, None)
        return

    try:
        # Bot передаёт immutable --config snapshot, чтобы queued job не менялась
        # при последующей смене языка/голоса в профиле пользователя.
        if getattr(args, "config_path", None):
            cfg = load_config(args.config_path)
        elif getattr(args, "client", None):
            cfg = load_client(args.client)
        else:
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
