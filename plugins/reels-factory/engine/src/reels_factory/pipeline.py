"""Оркестрация сборки рилса (этап make): голос -> (split: аватар) -> видеоряд
-> сборка -> QA. Сценарий берётся из workdir/scenario.json (после валидации
пользователем на этапе script).

run_make() гонит стадии подряд; при исключении на любой стадии останавливается и
возвращает {"ok": False, "workdir", "mp4": None, "qa_pass": False, "stage",
"error"}. DI на внешние ресурсы (synth/avatar/assemble/covered_block) —
тестируемо без сети/ffmpeg. verify_reel не параметр (детерминированная QA-логика).

При ``RF_MASTER_AUDIO_ENABLED=1`` (либо ``master_audio.enabled: true``) весь
утверждённый сценарий озвучивается одним ElevenLabs request. По alignment из
master WAV режутся технические block WAV только для переходного HeyGen-пути;
финальный render проигрывает исключительно master WAV.

До TTS/HeyGen строится единственный versioned ``edit_plan.json``. После master
alignment в нём уточняются только тайминги и явные safety-fallbacks. Только
validator-approved full B-roll window может пометить блок ``avatar_required:
false`` и заменить невидимый HeyGen дешёвым локальным placeholder. Revideo
получает тот же документ и только проецирует его в runtime ``tz.json``.
"""
import hashlib
import json
import sys
from pathlib import Path

from reels_factory.config import WORK_ROOT, edit_settings
from reels_factory.billing import billable_seconds
from reels_factory.avatar import (
    HeyGenClient, avatar_cache_key, cached_generate, render_covered_block,
)
from reels_factory.tts import synth_voice as _synth_voice
from reels_factory.master_audio import (
    build_master_audio as _build_master_audio,
    master_audio_enabled,
)
from reels_factory.compose import build_caption_fixes
# Рендер-слой: Revideo (единственный рендерер). Совместим по контракту с
# compose.assemble ({"mp4","timed_scenario","words_fixed"}).
from reels_factory.revideo_render import assemble_revideo as _assemble
from reels_factory.edit import jump_cut_fragments as _jump_cut_fragments
from reels_factory.editplan import (
    build_edit_plan as _build_edit_plan,
    covered_block_indexes,
    enrich_performance_with_llm,
    enrich_visuals_with_llm,
    ensure_assetless_visual_coverage,
    finalize_edit_plan as _finalize_edit_plan,
    save_edit_plan,
)
from reels_factory.avatar_islands import (
    avatar_islands_enabled,
    build_avatar_render_plan as _build_avatar_render_plan,
    render_avatar_islands as _render_avatar_islands,
    save_avatar_render_plan,
    validate_photo_avatar_iv_config,
)
from reels_factory.llm import ClaudeCliRunner
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


def run_make(config: dict, workdir,
             broll_plan: dict | None = None, scenario: dict | None = None,
             avatar_client=None, synth_fn=None, assemble_fn=None,
             covered_block_fn=None, jump_cut_fn=None, precut_fn=None,
             master_audio_fn=None, edit_plan_fn=None,
             finalize_edit_plan_fn=None, visual_runner=None,
             performance_runner=None,
             avatar_plan_fn=None, avatar_render_fn=None, meter=None) -> dict:
    fmt = config.get("format", "split")
    wd = Path(workdir)
    wd.mkdir(parents=True, exist_ok=True)

    synth_fn = synth_fn or _synth_voice
    assemble_fn = assemble_fn or _assemble
    covered_block_fn = covered_block_fn or render_covered_block
    jump_cut_fn = jump_cut_fn or _jump_cut_fragments
    edit_cfg = edit_settings(config)
    use_master_audio = master_audio_enabled(config)
    use_avatar_islands = False

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
    avatar_cfg = config.get("avatar") or {}
    caption_fixes = build_caption_fixes(_fixes_hypothesis(config))

    # Один canonical edit plan строится до любых TTS/HeyGen вызовов. Старый
    # injected precut_fn допускается только как источник legacy hints для
    # совместимости тестов/CLI; решения всё равно нормализует editplan.py.
    _log("plan")
    try:
        legacy_plan = broll_plan
        if legacy_plan is None and precut_fn is not None and fmt == "avatar":
            legacy_plan = precut_fn(scenario, config)
        edit_plan_fn = edit_plan_fn or _build_edit_plan
        edit_plan = edit_plan_fn(
            scenario,
            config,
            legacy_broll_plan=legacy_plan,
        )
        visual_cfg = (
            (((config.get("edit_plan") or {}).get("visual_director") or {})
             .get("llm") or {})
        )
        if visual_cfg.get("enabled"):
            runner = visual_runner or ClaudeCliRunner(
                timeout_s=int(visual_cfg.get("timeout_s") or 600)
            )
            edit_plan = enrich_visuals_with_llm(edit_plan, runner)
        # Даже при выключенном/недоступном Visual LLM длинный участок без
        # подходящего B-roll не должен оставаться одной talking head сценой.
        # Функция идемпотентна и заполняет только свободные avatar-only окна.
        edit_plan = ensure_assetless_visual_coverage(edit_plan)
        performance_cfg = (
            ((config.get("edit_plan") or {}).get("performance_llm") or {})
        )
        if performance_cfg.get("enabled"):
            runner = performance_runner or ClaudeCliRunner(
                timeout_s=int(performance_cfg.get("timeout_s") or 600)
            )
            edit_plan = enrich_performance_with_llm(edit_plan, runner)
        save_edit_plan(edit_plan, wd)
        for line in edit_plan.get("log") or []:
            print(f"[plan] {line}", file=sys.stderr)
        use_avatar_islands = avatar_islands_enabled(config)
        if use_avatar_islands:
            if fmt not in ("split", "avatar"):
                raise RuntimeError(
                    "avatar islands поддерживает только format=split|avatar"
                )
            if not use_master_audio:
                raise RuntimeError(
                    "avatar islands требует master_audio.enabled=true"
                )
            validate_photo_avatar_iv_config(config)
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

    # Только validator-approved full cover может отключить HeyGen. Решение
    # адресуется block index, а не ролью: повторяющиеся роли не конфликтуют.
    covered_blocks = covered_block_indexes(edit_plan) if fmt == "avatar" else set()

    _log("voice")
    try:
        avatar_mp4s, voice_wavs = [], []
        master = None
        avatar_render_plan = None
        avatar_render_manifest = None
        cache_dir = WORK_ROOT / AVATAR_CACHE_DIRNAME
        if use_master_audio:
            master_audio_fn = master_audio_fn or _build_master_audio
            master = master_audio_fn(
                scenario, config, wd, voice_id=voice_id,
                meter=(meter.elevenlabs if meter is not None else None),
            )
            block_wavs = list(master.block_wavs)
            if (
                not use_avatar_islands
                and len(block_wavs) != len(scenario["blocks"])
            ):
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
                synth_fn(
                    text, wav, voice_id=voice_id,
                    meter=(meter.elevenlabs if meter is not None else None),
                )
                block_wavs.append(wav)

        if master is not None:
            finalize_edit_plan_fn = finalize_edit_plan_fn or _finalize_edit_plan
            edit_plan = finalize_edit_plan_fn(
                edit_plan,
                master.timed_scenario,
                list(master.words),
            )
            save_edit_plan(edit_plan, wd)
            covered_blocks = (
                covered_block_indexes(edit_plan) if fmt == "avatar" else set()
            )

        if use_avatar_islands:
            avatar_plan_fn = avatar_plan_fn or _build_avatar_render_plan
            avatar_render_fn = avatar_render_fn or _render_avatar_islands
            master_sha256 = hashlib.sha256(Path(master.wav).read_bytes()).hexdigest()
            avatar_render_plan = avatar_plan_fn(
                edit_plan,
                config,
                master_audio_sha256=master_sha256,
            )
            save_avatar_render_plan(avatar_render_plan, wd)
            rendered = avatar_render_fn(
                master.wav,
                avatar_render_plan,
                avatar_client,
                wd,
                cache_dir,
                edit_plan=edit_plan,
                meter=(meter.heygen if meter is not None else None),
            )
            avatar_mp4s = list(
                rendered.clips if hasattr(rendered, "clips") else rendered
            )
            avatar_render_manifest = getattr(rendered, "manifest", None)
        else:
            for i, (b, wav) in enumerate(zip(scenario["blocks"], block_wavs)):
                if fmt in ("split", "avatar"):
                    role = b.get("role")
                    billable = True
                    if role == "cta":
                        # Попадание в кэш проверяем ДО вызова: сам
                        # cached_generate возвращает путь одинаково в обоих
                        # случаях, и по нему хит от промаха не отличить.
                        key = avatar_cache_key(avatar_client, wav, role=role)
                        billable = not (cache_dir / f"{key}.mp4").exists()
                        mp4 = cached_generate(
                            avatar_client, wav, cache_dir, role=role
                        )
                    elif i in covered_blocks:
                        # Локальный ffmpeg, HeyGen не вызывается — не платно.
                        billable = False
                        mp4 = covered_block_fn(wav, wd / f"avatar_{i}.mp4")
                    else:
                        # role задаёт пластику: хук энергичный, payoff спокойный
                        mp4 = avatar_client.generate(
                            wav, wd / f"avatar_{i}.mp4", role=role
                        )
                    if meter is not None and billable:
                        meter.heygen(
                            billable_seconds(mp4),
                            twin=bool(getattr(avatar_client, "look_id", None)),
                        )
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

    _log("assemble")
    try:
        out_mp4 = wd / "reel.mp4"
        # Непрерывный видеоряд-источник (ingest) убран: аватар — единственный
        # формат, низовое видео сборщик больше не получает.
        res = assemble_fn(wd, scenario, None, 0.0, out_mp4,
                          format=fmt, avatar_mp4s=avatar_mp4s or None,
                          voice_wavs=voice_wavs or None,
                          edit_plan=edit_plan,
                          caption_fixes=caption_fixes,
                          grade=edit_cfg["grade"], grain=edit_cfg["grain"],
                          zoom=edit_cfg["zoom"], flash=edit_cfg["flash"],
                          config=config,
                          master_audio=master.wav if master else None,
                          alignment_words=list(master.words) if master else None,
                          master_timed_scenario=master.timed_scenario if master else None,
                          avatar_render_plan=avatar_render_plan)
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

    return {
        "ok": True,
        "workdir": str(wd),
        "mp4": mp4,
        "qa_pass": qa["all_pass"],
        "gates": qa["gates"],
        "avatar_summary": (
            avatar_render_plan.get("summary")
            if avatar_render_plan is not None else None
        ),
        "avatar_render_manifest": avatar_render_manifest,
        "stage": None,
        "error": None,
    }
