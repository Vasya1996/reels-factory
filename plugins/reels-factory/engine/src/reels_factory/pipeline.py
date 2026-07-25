"""Оркестрация сборки рилса (этап make): голос -> (split: аватар) -> видеоряд
-> сборка -> QA. Сценарий берётся из workdir/scenario.json (после валидации
пользователем на этапе script).

run_make() гонит стадии подряд; при исключении на любой стадии останавливается и
возвращает {"ok": False, "workdir", "mp4": None, "qa_pass": False, "stage",
"error"}. DI на внешние ресурсы (synth/ingest/avatar/assemble/covered_block) —
тестируемо без сети/ffmpeg. verify_reel не параметр (детерминированная QA-логика).

При ``RF_MASTER_AUDIO_ENABLED=1`` (либо ``master_audio.enabled: true``) весь
утверждённый сценарий озвучивается одним ElevenLabs request. По alignment из
master WAV режутся технические block WAV только для переходного HeyGen-пути;
финальный render проигрывает исключительно master WAV.

Для формата avatar блок, чья роль на 100% закрыта вставкой видеоряда
(broll_plan segments с "insert": true — plan_avatar_inserts берёт вставку
строго на весь [start,end] блока), не рендерится через HeyGen: аватар всё
равно не виден под вставкой, поэтому вместо avatar_client.generate() идёт
дешёвый локальный render_covered_block() (голос поверх чёрного кадра).
"""
import json
import sys
from pathlib import Path

from reels_factory.config import WORK_ROOT, edit_settings
from reels_factory.avatar import HeyGenClient, cached_generate, render_covered_block
from reels_factory.tts import synth_voice as _synth_voice
from reels_factory.master_audio import (
    build_master_audio as _build_master_audio,
    master_audio_enabled,
)
from reels_factory.ingest import ingest as _ingest
from reels_factory.compose import build_caption_fixes
# Рендер-слой: Revideo (единственный рендерер). Совместим по контракту с
# compose.assemble ({"mp4","timed_scenario","words_fixed"}).
from reels_factory.revideo_render import assemble_revideo as _assemble
from reels_factory.edit import jump_cut_fragments as _jump_cut_fragments
from reels_factory.segment_plan import plan_precut as _plan_precut, save_plan
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
             covered_block_fn=None, jump_cut_fn=None, precut_fn=None,
             master_audio_fn=None) -> dict:
    fmt = config.get("format", "split")
    wd = Path(workdir)
    wd.mkdir(parents=True, exist_ok=True)

    synth_fn = synth_fn or _synth_voice
    ingest_fn = ingest_fn or _ingest
    assemble_fn = assemble_fn or _assemble
    covered_block_fn = covered_block_fn or render_covered_block
    jump_cut_fn = jump_cut_fn or _jump_cut_fragments
    edit_cfg = edit_settings(config)
    use_master_audio = master_audio_enabled(config)

    def fail(stage, e):
        return {"ok": False, "workdir": str(wd), "mp4": None, "qa_pass": False,
                "stage": stage, "error": str(e)[:500]}

    if scenario is None:
        try:
            scenario = json.loads((wd / "scenario.json").read_text(encoding="utf-8"))
        except Exception as e:
            return fail("scenario", e)

    voice_id = config.get("voice_id")
    config_language = str(config.get("language") or "").strip().lower()
    voice_language = str(config.get("voice_language") or "").strip().lower()
    voices = config.get("voices")
    scenario_language = str(scenario.get("language") or "").strip().lower()
    tts_language = str(
        ((config.get("tts") or {}).get("language_code") or config_language)
    ).strip().lower()
    if scenario_language and scenario_language != config_language:
        return fail(
            "language",
            RuntimeError(
                f"язык сценария {scenario_language!r} != язык job "
                f"{config_language!r}"
            ),
        )
    if tts_language and tts_language != config_language:
        return fail(
            "language",
            RuntimeError(
                f"TTS language_code {tts_language!r} != язык job "
                f"{config_language!r}"
            ),
        )
    if voice_language and voice_language != config_language:
        return fail(
            "language",
            RuntimeError(
                f"язык активного голоса {voice_language!r} != язык job "
                f"{config_language!r}"
            ),
        )
    if voices is not None and (
        not isinstance(voices, dict)
        or str(voices.get(config_language) or "").strip()
        != str(voice_id or "").strip()
    ):
        return fail(
            "language",
            RuntimeError(
                f"в профиле нет подходящего голоса для языка "
                f"{config_language!r}"
            ),
        )
    product = config.get("product") or {}
    avatar_cfg = config.get("avatar") or {}
    caption_fixes = build_caption_fixes(_fixes_hypothesis(config))
    broll_segments = broll_plan.get("segments") if broll_plan else None
    punch_windows = broll_plan.get("punch") if broll_plan else None

    # precut: без явного broll_plan строим план вставок ДО TTS/HeyGen — блоки,
    # целиком закрытые фуллскрин-бироллом, не тратят кредиты HeyGen.
    if fmt == "avatar" and broll_plan is None:
        _log("plan")
        try:
            precut_fn = precut_fn or _plan_precut
            plan = precut_fn(scenario, config)
            save_plan(plan, wd)
            for line in plan.get("log") or []:
                print(f"[plan] {line}", file=sys.stderr)
            if plan.get("segments"):
                broll_segments = plan["segments"]
        except Exception as e:
            return fail("plan", e)

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
        master = None
        cache_dir = WORK_ROOT / AVATAR_CACHE_DIRNAME
        if use_master_audio:
            master_audio_fn = master_audio_fn or _build_master_audio
            master = master_audio_fn(scenario, config, wd, voice_id=voice_id)
            block_wavs = list(master.block_wavs)
            if len(block_wavs) != len(scenario["blocks"]):
                raise RuntimeError(
                    f"master audio blocks {len(block_wavs)} != "
                    f"scenario blocks {len(scenario['blocks'])}"
                )
        else:
            block_wavs = []
            for i, b in enumerate(scenario["blocks"]):
                text = b.get("speech")
                if not text:
                    raise RuntimeError(f"блок {i} ({b.get('role')}): пустой speech")
                wav = wd / f"voice_{i}.wav"
                synth_fn(text, wav, voice_id=voice_id)
                block_wavs.append(wav)

        for i, (b, wav) in enumerate(zip(scenario["blocks"], block_wavs)):
            if fmt in ("split", "avatar"):
                role = b.get("role")
                if role == "cta":
                    mp4 = cached_generate(avatar_client, wav, cache_dir, role=role)
                elif role in insert_roles:
                    mp4 = covered_block_fn(wav, wd / f"avatar_{i}.mp4")
                else:
                    # role задаёт пластику: хук энергичный, payoff спокойный
                    mp4 = avatar_client.generate(wav, wd / f"avatar_{i}.mp4", role=role)
                avatar_mp4s.append(mp4)
            else:
                voice_wavs.append(wav)
    except Exception as e:
        return fail("voice", e)

    if edit_cfg["jump_cuts"] and avatar_mp4s and not use_master_audio:
        # режем паузы ДО assemble: media_dur померяет уже подрезанные фрагменты,
        # retime_scenario построит сетку по ним, и субтитры со вставками сами
        # встанут на новые времена
        _log("jump_cuts")
        try:
            avatar_mp4s = jump_cut_fn(avatar_mp4s, wd)
        except Exception as e:
            return fail("jump_cuts", e)
    elif edit_cfg["jump_cuts"] and use_master_audio:
        # Покадровое удаление пауз из HeyGen-клипов разрушило бы immutable
        # master timeline. Вернуть jump cuts можно после timeline-aware версии.
        print(
            "[make] jump_cuts отключены: master audio является source of truth",
            file=sys.stderr,
        )

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
                          caption_fixes=caption_fixes,
                          grade=edit_cfg["grade"], grain=edit_cfg["grain"],
                          zoom=edit_cfg["zoom"], flash=edit_cfg["flash"],
                          config=config,
                          master_audio=master.wav if master else None,
                          alignment_words=list(master.words) if master else None,
                          master_timed_scenario=master.timed_scenario if master else None)
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
