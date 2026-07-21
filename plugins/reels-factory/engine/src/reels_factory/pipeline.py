"""Оркестрация сборки рилса (этап make): голос -> (split: аватар) -> видеоряд
-> сборка -> QA. Сценарий берётся из workdir/scenario.json (после валидации
пользователем на этапе script).

run_make() гонит стадии подряд; при исключении на любой стадии останавливается и
возвращает {"ok": False, "workdir", "mp4": None, "qa_pass": False, "stage",
"error"}. DI на внешние ресурсы (synth/ingest/avatar/assemble/covered_block) —
тестируемо без сети/ffmpeg. verify_reel не параметр (детерминированная QA-логика).

Для формата avatar блок, чья роль на 100% закрыта вставкой видеоряда
(broll_plan segments с "insert": true — plan_avatar_inserts берёт вставку
строго на весь [start,end] блока), не рендерится через HeyGen: аватар всё
равно не виден под вставкой, поэтому вместо avatar_client.generate() идёт
дешёвый локальный render_covered_block() (голос поверх чёрного кадра).
"""
import json
import sys
from pathlib import Path

from reels_factory.config import WORK_ROOT
from reels_factory.avatar import HeyGenClient, cached_generate, render_covered_block
from reels_factory.tts import synth_voice as _synth_voice
from reels_factory.ingest import ingest as _ingest
from reels_factory.compose import assemble as _assemble, build_caption_fixes
from reels_factory.verify import verify_reel

AVATAR_CACHE_DIRNAME = "avatar_cache"


def _log(stage: str) -> None:
    print(f"[make] {stage}", file=sys.stderr)


def _fixes_hypothesis(config: dict) -> dict:
    product = config.get("product") or {}
    return {
        "theme": config.get("theme"),
        "theme_spoken": config.get("theme_spoken"),
        "theme_captions": config.get("theme_captions"),
        "brand_captions": product.get("brand_captions"),
    }


def run_make(config: dict, broll_source: str, broll_offset_s: float, workdir,
             broll_plan: dict | None = None, scenario: dict | None = None,
             avatar_client=None, synth_fn=None, ingest_fn=None, assemble_fn=None,
             covered_block_fn=None) -> dict:
    fmt = config.get("format", "split")
    wd = Path(workdir)
    wd.mkdir(parents=True, exist_ok=True)

    synth_fn = synth_fn or _synth_voice
    ingest_fn = ingest_fn or _ingest
    assemble_fn = assemble_fn or _assemble
    covered_block_fn = covered_block_fn or render_covered_block

    def fail(stage, e):
        return {"ok": False, "workdir": str(wd), "mp4": None, "qa_pass": False,
                "stage": stage, "error": str(e)[:500]}

    if scenario is None:
        try:
            scenario = json.loads((wd / "scenario.json").read_text(encoding="utf-8"))
        except Exception as e:
            return fail("scenario", e)

    voice_id = config.get("voice_id")
    product = config.get("product") or {}
    avatar_cfg = config.get("avatar") or {}
    caption_fixes = build_caption_fixes(_fixes_hypothesis(config))
    broll_segments = broll_plan.get("segments") if broll_plan else None
    punch_windows = broll_plan.get("punch") if broll_plan else None

    if fmt in ("split", "avatar") and avatar_client is None:
        avatar_client = HeyGenClient(
            avatar_id=avatar_cfg.get("heygen_asset_id"),
            look_id=avatar_cfg.get("heygen_look_id"),
            motion_prompt=avatar_cfg.get("motion_prompt"),
            expressiveness=avatar_cfg.get("expressiveness"),
            engine=avatar_cfg.get("engine"),
            resolution=avatar_cfg.get("resolution"),
        )

    # avatar: роли, чей блок целиком уходит под вставку видеоряда — HeyGen для
    # них не нужен (см. docstring модуля и plan_avatar_inserts в compose.py).
    insert_roles = set()
    if fmt == "avatar" and broll_segments:
        insert_roles = {s["role"] for s in broll_segments if s.get("insert")}

    _log("voice")
    try:
        avatar_mp4s, voice_wavs = [], []
        cache_dir = WORK_ROOT / AVATAR_CACHE_DIRNAME
        for i, b in enumerate(scenario["blocks"]):
            text = b.get("speech")
            if not text:
                raise RuntimeError(f"блок {i} ({b.get('role')}): пустой speech")
            wav = wd / f"voice_{i}.wav"
            synth_fn(text, wav, voice_id=voice_id)
            if fmt in ("split", "avatar"):
                role = b.get("role")
                if role == "cta":
                    mp4 = cached_generate(avatar_client, wav, cache_dir)
                elif role in insert_roles:
                    mp4 = covered_block_fn(wav, wd / f"avatar_{i}.mp4")
                else:
                    mp4 = avatar_client.generate(wav, wd / f"avatar_{i}.mp4")
                avatar_mp4s.append(mp4)
            else:
                voice_wavs.append(wav)
    except Exception as e:
        return fail("voice", e)

    _log("ingest")
    try:
        # для avatar-формата видеоряд опционален (вставки); без --broll — нет низа
        if broll_source:
            meta = ingest_fn(broll_source, wd)
            broll_mp4 = meta["video_path"]
        else:
            broll_mp4 = None
    except Exception as e:
        return fail("ingest", e)

    _log("assemble")
    try:
        out_mp4 = wd / "reel.mp4"
        res = assemble_fn(wd, scenario, broll_mp4, broll_offset_s, out_mp4,
                          format=fmt, avatar_mp4s=avatar_mp4s or None,
                          voice_wavs=voice_wavs or None,
                          broll_segments=broll_segments, punch_windows=punch_windows,
                          caption_fixes=caption_fixes)
        mp4 = res["mp4"]
        timed = res["timed_scenario"]
        words = res.get("words_fixed")
    except Exception as e:
        return fail("assemble", e)

    _log("verify")
    try:
        qa = verify_reel(Path(mp4), timed, words=words,
                         hypothesis=_fixes_hypothesis(config), format=fmt)
    except Exception as e:
        return fail("verify", e)

    return {"ok": True, "workdir": str(wd), "mp4": mp4, "qa_pass": qa["all_pass"],
            "gates": qa["gates"], "stage": None, "error": None}
