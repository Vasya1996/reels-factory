"""Revideo как рендер-слой: drop-in замена compose.assemble.

Готовит вход для движка `engine/revideo` (base.mp4 из склейки аватар-фрагментов,
words.json, tz.json из адаптера, видеоряд), запускает `node render.mjs` и
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

from reels_factory.config import FFMPEG, OUT_H, LUFS_TARGET
from reels_factory.render import media_dur
from reels_factory.compose import (
    _concat_avatars, retime_scenario, _pause_after,
    apply_caption_fixes, _default_transcribe,
)
from reels_factory.revideo_adapter import plan_to_tz
from reels_factory import broll_library as _broll_lib
from reels_factory import hyperframes_blocks as _hf
from reels_factory.broll_retrieval import resolve_broll
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


def assemble_revideo(rdir, scenario: dict, broll_mp4, broll_offset_s: float, out_mp4, *,
                     format: str = "avatar", avatar_mp4s: list | None = None,
                     voice_wavs: list | None = None, transcribe_fn=None,
                     broll_segments: list | None = None, punch_windows: list | None = None,
                     whoosh_at: list | None = None, caption_fixes: dict | None = None,
                     grade: bool = False, grain: bool = False,
                     zoom: bool = False, flash: bool = False,
                     config: dict | None = None, face: dict | None = None,
                     hf_render=None) -> dict:
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

    # 1) ретайминг под фактические длительности
    frag_durs = [media_dur(str(a)) for a in frag_srcs]
    timed = retime_scenario(scenario, frag_durs)
    holds = [_pause_after(b) for b in timed["blocks"]]

    # 2) base.mp4 — склейка аватар-фрагментов (голос вшит), фуллскрин
    if format in ("split", "avatar"):
        base = _concat_avatars(rdir, avatar_mp4s, holds, height=OUT_H)
    else:
        # fullscreen: нужен видеоряд-подложка; base = concat голосов поверх видеоряда
        # (упрощённо — для MVP Revideo-пути основной сценарий avatar/split)
        raise RuntimeError("Revideo-путь пока поддерживает format=split|avatar")

    # 3) words.json (транскрипт base + caption-фиксы)
    words = transcribe_fn(base, rdir)
    if caption_fixes:
        words = apply_caption_fixes(words, caption_fixes)
    words = _normalize_words(words)

    # 4) tz.json из адаптера (фразовая раскладка по словам, с broll_query)
    tz = plan_to_tz(timed, broll_segments, config, words=words, base_video="base.mp4",
                    broll_file="broll.mp4", face=face)

    # 4b) Модуль B — семантический подбор b-roll: заполнить effect.src по
    # broll_query из библиотеки. Если библиотека не проиндексирована, src
    # остаётся дефолтным broll.mp4 (обратная совместимость, деградация мягкая).
    retr = resolve_broll(tz, library_dir=_broll_lib.LIBRARY_DIR)
    for line in retr.log:
        print(f"[broll] {line}")

    # 4b') HyperFrames-блоки: сегмент с effect.hyperframes рендерится в клип
    # (моушн-графика на HTML/GSAP) и подставляется как fullscreen-биролл. На
    # ошибке рендера сегмент остаётся встроенным эффектом (мягкий фолбэк).
    for seg in tz.get("segments", []):
        _resolve_hyperframes_segment(seg, render_public, hf_render=hf_render)

    # 4c) Валидатор-линтер: дублирует монтажные правила движка на уровне плана,
    # чинит безопасное (длинное тире) и логирует риски перед рендером.
    # covered_ranges — precut-блоки (аватар не генерился, base чёрный).
    covered_roles = {s["role"] for s in (broll_segments or []) if s.get("insert")}
    covered_ranges = [(float(b["start"]), float(b["end"]))
                      for b in timed["blocks"] if b.get("role") in covered_roles]
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
    # подобранные библиотечные клипы → public/ (движок читает src как /<file>)
    for name in retr.used_clips:
        src_clip = _broll_lib.LIBRARY_DIR / name
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
