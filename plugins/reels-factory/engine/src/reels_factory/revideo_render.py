"""Revideo как рендер-слой: drop-in замена compose.assemble.

Готовит вход для движка `engine/revideo` (base.mp4 из склейки аватар-фрагментов,
master audio/alignment либо legacy words.json, tz.json из адаптера, видеоряд),
запускает `node render.mjs` и
возвращает тот же контракт, что и compose.assemble:
{"mp4","timed_scenario","words_fixed"} — verify.py работает без изменений.

Переиспользует существующие модули движка (склейка, ретайминг, транскрипт,
caption-фиксы) — Revideo меняет только сам рендер, не upstream.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from reels_factory.config import FFMPEG, FPS, OUT_H, OUT_W, LUFS_TARGET
from reels_factory.render import media_dur
from reels_factory.compose import (
    _concat_avatars, retime_scenario, _pause_after,
    apply_caption_fixes, _default_transcribe, VENC,
)
from reels_factory.editplan import (
    build_edit_plan,
    finalize_edit_plan,
    save_edit_plan,
)
from reels_factory.revideo_adapter import edit_plan_to_tz
from reels_factory import broll_library as _broll_lib
from reels_factory import hyperframes_blocks as _hf
from reels_factory.tz_validator import validate_tz

# engine/revideo — самодостаточный Node-модуль рендера
REVIDEO_DIR = Path(__file__).resolve().parents[2] / "revideo"


def _prepare_render_workspace(rdir: Path, template_dir: Path | None = None) -> Path:
    """Создать изолированный Revideo workspace конкретной job.

    Код и node_modules остаются общими и только читаются. Все изменяемые входы
    (tz/words/media) и output живут в <job>/revideo, поэтому параллельные
    клиенты не могут перезаписать файлы друг друга.
    """
    template = Path(template_dir or REVIDEO_DIR)
    workspace = Path(rdir) / "revideo"
    src_dir = workspace / "src"
    public_dir = workspace / "public"
    output_dir = workspace / "output"
    src_dir.mkdir(parents=True, exist_ok=True)
    public_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    for name in ("project.tsx", "global.css"):
        source = template / "src" / name
        if not source.exists():
            raise RuntimeError(f"Revideo template не содержит src/{name}")
        shutil.copy2(source, src_dir / name)

    # Копируем только явно разрешённую статику. Нельзя copytree всего public:
    # на старом сервере там могут остаться base.mp4/broll.mp4 другого клиента.
    for name in ("emoji", "whoosh.wav", "type.wav", "pop.wav", "ding.wav"):
        source = template / "public" / name
        target = public_dir / name
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
        elif source.is_file():
            shutil.copy2(source, target)
    return workspace


def _ensure_deps(rev: Path) -> None:
    """Разовая установка node_modules (в setup обычно уже сделана)."""
    if not (rev / "node_modules").exists():
        subprocess.run("npm install", cwd=str(rev), shell=True, check=True)


def _normalize_loudness(mp4: Path) -> None:
    """Привести аудио mp4 к LUFS_TARGET (однопроходный loudnorm), видео без
    перекодирования (Revideo не нормализует звук сам)."""
    mp4 = Path(mp4)
    tmp = mp4.with_name(mp4.stem + ".loudnorm.tmp.mp4")
    subprocess.run(
        [FFMPEG, "-y", "-i", str(mp4),
         "-af", f"loudnorm=I={LUFS_TARGET}:TP=-1.5:LRA=11",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
         "-movflags", "+faststart", str(tmp)],
        check=True,
    )
    tmp.replace(mp4)


def _resolve_hyperframes_segment(seg: dict, public_dir: Path, *, hf_render=None) -> None:
    """Сегмент с effect.hyperframes -> отрендерить блок в public_dir и заменить
    эффект на fullscreen-биролл (src=клип, caption hidden). На ошибке сегмент
    не трогаем — встроенный эффект (chart_bars) остаётся как фолбэк."""
    eff = seg.get("effect") or {}
    hf = eff.get("hyperframes")
    if not hf:
        return
    render = hf_render or _hf.render_block
    window = float(seg.get("end", 0)) - float(seg.get("start", 0))
    clip = Path(public_dir) / f"hf_{seg.get('id')}.mp4"
    try:
        render(hf["block"], hf.get("variables") or {}, window, clip)
        seg["effect"] = {"type": "broll", "style": "fullscreen", "src": clip.name, "offset": 0.0}
        seg["caption"] = "hidden"
        print(f"[hyperframes] seg#{seg.get('id')}: блок {hf['block']} → {clip.name}")
    except Exception as e:
        print(f"[hyperframes] seg#{seg.get('id')}: рендер блока не удался "
              f"({str(e)[:120]}) — фолбэк на {eff.get('type')}")


def _normalize_words(words: list) -> list:
    """Привести к форме, которую читает project.tsx: [{start,end,text}]."""
    out = []
    for w in words:
        out.append({
            "start": float(w.get("start", 0.0)),
            "end": float(w.get("end", 0.0)),
            "text": w.get("text") or w.get("word") or "",
        })
    return out


def _concat_master_visuals(
    rdir: Path, avatar_mp4s: list, block_durations: list[float], height: int = OUT_H
) -> Path:
    """Собрать беззвучный base ровно по immutable master timeline.

    HeyGen иногда добавляет/съедает несколько кадров относительно входного WAV.
    Каждый visual fragment поэтому trim/pad-ится до alignment-derived block
    duration. Аудио HeyGen полностью отбрасывается.
    """
    if len(avatar_mp4s) != len(block_durations):
        raise ValueError("avatar fragments и master block durations не совпадают")
    if not avatar_mp4s:
        raise ValueError("нет avatar fragments для master visual timeline")

    base = Path(rdir) / "top.master.mp4"
    cmd = [FFMPEG, "-y"]
    for source in avatar_mp4s:
        cmd += ["-i", str(source)]

    parts, labels = [], []
    for index, duration in enumerate(block_durations):
        duration = float(duration)
        if duration <= 0:
            raise ValueError(f"master block {index} имеет duration <= 0")
        parts.append(
            f"[{index}:v]"
            f"scale={OUT_W}:{height}:force_original_aspect_ratio=increase,"
            f"crop={OUT_W}:{height},fps={FPS},setsar=1,"
            f"tpad=stop_mode=clone:stop_duration={duration:.6f},"
            f"trim=duration={duration:.6f},setpts=PTS-STARTPTS[v{index}]"
        )
        labels.append(f"[v{index}]")
    parts.append(
        "".join(labels) + f"concat=n={len(labels)}:v=1:a=0[v]"
    )
    cmd += [
        "-filter_complex", ";".join(parts),
        "-map", "[v]", *VENC, "-an", str(base),
    ]
    subprocess.run(cmd, check=True)
    return base


def assemble_revideo(rdir, scenario: dict, broll_mp4, broll_offset_s: float, out_mp4, *,
                     format: str = "avatar", avatar_mp4s: list | None = None,
                     voice_wavs: list | None = None, transcribe_fn=None,
                     broll_segments: list | None = None, punch_windows: list | None = None,
                     whoosh_at: list | None = None, caption_fixes: dict | None = None,
                     grade: bool = False, grain: bool = False,
                     zoom: bool = False, flash: bool = False,
                     config: dict | None = None, face: dict | None = None,
                     hf_render=None, master_audio: Path | None = None,
                     alignment_words: list | None = None,
                     master_timed_scenario: dict | None = None,
                     edit_plan: dict | None = None) -> dict:
    rdir = Path(rdir)
    rdir.mkdir(parents=True, exist_ok=True)
    out_mp4 = Path(out_mp4)
    transcribe_fn = transcribe_fn or _default_transcribe
    config = config or {}
    render_workspace = _prepare_render_workspace(rdir)
    render_public = render_workspace / "public"

    blocks = scenario["blocks"]
    if format in ("split", "avatar"):
        if not avatar_mp4s:
            raise RuntimeError(f"format={format} требует avatar_mp4s")
        frag_srcs = avatar_mp4s
    elif format == "fullscreen":
        if not voice_wavs:
            raise RuntimeError("format=fullscreen требует voice_wavs")
        frag_srcs = voice_wavs
    else:
        raise RuntimeError(f"неизвестный format: {format!r}")
    if len(frag_srcs) != len(blocks):
        raise RuntimeError(f"фрагментов {len(frag_srcs)} != блоков {len(blocks)}")

    if master_audio is not None:
        master_audio = Path(master_audio)
        if not master_audio.exists():
            raise RuntimeError(f"master audio не найден: {master_audio}")
        if not master_timed_scenario or alignment_words is None:
            raise RuntimeError(
                "master audio требует master_timed_scenario и alignment_words"
            )
        timed = master_timed_scenario
        if len(timed.get("blocks") or []) != len(blocks):
            raise RuntimeError("master timed scenario не совпадает со scenario")
        block_durations = [
            float(block["end"]) - float(block["start"])
            for block in timed["blocks"]
        ]
        if format not in ("split", "avatar"):
            raise RuntimeError("Master Revideo-путь пока поддерживает format=split|avatar")
        base = _concat_master_visuals(rdir, avatar_mp4s, block_durations, height=OUT_H)
        words = list(alignment_words)
    else:
        # Legacy rollback: ретайминг по фактическим HeyGen fragments и Whisper.
        frag_durs = [media_dur(str(a)) for a in frag_srcs]
        timed = retime_scenario(scenario, frag_durs)
        holds = [_pause_after(b) for b in timed["blocks"]]
        if format in ("split", "avatar"):
            base = _concat_avatars(rdir, avatar_mp4s, holds, height=OUT_H)
        else:
            raise RuntimeError("Revideo-путь пока поддерживает format=split|avatar")
        words = transcribe_fn(base, rdir)

    # 3) words.json: ElevenLabs alignment primary, Whisper только legacy/fallback.
    if caption_fixes:
        words = apply_caption_fixes(words, caption_fixes)
    words = _normalize_words(words)

    # 4) Один edit_plan получает exact timing и только затем проецируется в tz.
    # Compatibility-вход broll_segments сначала нормализуется тем же canonical
    # planner; Revideo больше не принимает творческих решений самостоятельно.
    if edit_plan is None:
        edit_plan = build_edit_plan(
            scenario,
            config,
            index={},
            legacy_broll_plan={"segments": list(broll_segments or [])},
            require_asset_files=False,
        )
    if edit_plan.get("status") != "final":
        edit_plan = finalize_edit_plan(edit_plan, timed, words)
    save_edit_plan(edit_plan, rdir)
    tz = edit_plan_to_tz(
        edit_plan,
        config,
        base_video="base.mp4",
        face=face,
    )
    if master_audio is not None:
        tz.setdefault("meta", {})["master_audio"] = "voice_master.wav"
        tz["meta"]["voice_layers"] = 1

    # Assets уже выбраны draft-планом. Здесь только собираем frozen paths для
    # копирования; semantic retrieval после оплаты запрещён.
    planned_clips = {}
    for window in edit_plan.get("windows") or []:
        asset = window.get("asset") or {}
        if asset.get("source") != "library" or not asset.get("src"):
            continue
        planned_clips[asset["src"]] = Path(
            asset.get("path") or (_broll_lib.LIBRARY_DIR / asset["src"])
        )

    # 4b') HyperFrames-блоки: сегмент с effect.hyperframes рендерится в клип
    # (моушн-графика на HTML/GSAP) и подставляется как fullscreen-биролл. На
    # ошибке рендера сегмент остаётся встроенным эффектом (мягкий фолбэк).
    for seg in tz.get("segments", []):
        _resolve_hyperframes_segment(seg, render_public, hf_render=hf_render)

    # 4c) Валидатор-линтер: дублирует монтажные правила движка на уровне плана,
    # чинит безопасное (длинное тире) и логирует риски перед рендером.
    # covered_ranges — блоки, для которых canonical plan разрешил HeyGen skip.
    covered_indexes = {
        int(block["index"])
        for block in edit_plan.get("blocks") or []
        if not block.get("avatar_required", True)
    }
    covered_ranges = [
        (float(block["start"]), float(block["end"]))
        for index, block in enumerate(timed["blocks"])
        if index in covered_indexes
    ]
    report = validate_tz(tz, index=_broll_lib.load_index(_broll_lib.LIBRARY_DIR),
                         covered_ranges=covered_ranges)
    for line in report.lines():
        print(f"[lint] {line}")
    if not report.ok:
        print(f"[lint] tz с {len(report.errors)} ошибк(ами) — рендер может быть некорректным")
    # covered-ошибки = гарантированный чёрный экран в ролике — падаем, а не рендерим
    fatal = [i for i in report.errors if i.rule.startswith("covered-")]
    if fatal:
        raise RuntimeError("precut-покрытие сломано: " +
                           "; ".join(i.message for i in fatal[:3]))

    # 5) разложить вход в изолированный workspace job и отрендерить общим
    # read-only кодом/зависимостями Revideo.
    rev = REVIDEO_DIR
    _ensure_deps(rev)
    (render_workspace / "src" / "tz.json").write_text(
        json.dumps(tz, ensure_ascii=False, indent=2), encoding="utf-8")
    (render_workspace / "src" / "words.json").write_text(
        json.dumps({"words": words}, ensure_ascii=False), encoding="utf-8")
    shutil.copy(str(base), str(render_public / "base.mp4"))
    if master_audio is not None:
        shutil.copy(str(master_audio), str(render_public / "voice_master.wav"))
    # frozen библиотечные клипы → public/ (движок читает src как /<file>)
    for name, src_clip in planned_clips.items():
        if src_clip.exists():
            shutil.copy(str(src_clip), str(render_public / name))
    # дефолтный broll.mp4 — фолбэк для сегментов со слабым матчем
    if broll_mp4 is not None and Path(broll_mp4).exists():
        shutil.copy(str(broll_mp4), str(render_public / "broll.mp4"))

    env = {
        **os.environ,
        "RF_OUTFILE": str(out_mp4.resolve()),
        "RF_PROJECT_FILE": str((render_workspace / "src" / "project.tsx").resolve()),
        "RF_RENDER_DIR": str((render_workspace / "output").resolve()),
    }
    subprocess.run("node render.mjs", cwd=str(rev), shell=True, check=True, env=env)

    # Revideo не нормализует звук сам — приводим к LUFS_TARGET после рендера
    _normalize_loudness(out_mp4)

    (rdir / "scenario.timed.json").write_text(
        json.dumps(timed, ensure_ascii=False, indent=2), encoding="utf-8")
    (rdir / "words.fixed.json").write_text(
        json.dumps(words, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"mp4": str(out_mp4), "dur": media_dur(str(out_mp4)),
            "timed_scenario": timed, "words_fixed": words}
