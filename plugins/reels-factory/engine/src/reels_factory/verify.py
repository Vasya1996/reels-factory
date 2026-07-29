"""QA-гейты готового рилса (стиль "D<N>_<name>" -> "PASS(...)"/"FAIL(...)").

D1 duration   — длительность mp4 в пределах ±2с от total РЕТАЙМЛЕННОГО сценария.
D2 resolution — 1080x1920 @ 30fps.
D3 loudness   — LUFS -14 ± 1.5.
D4 captions   — caps.ass лежит рядом с mp4. SKIP, если файла нет (Revideo
                вшивает субтитры в картинку и caps.ass не создаёт — проверка
                вшитых сабов — D7).
D5 voice      — голос ведущего слышен: mean_volume в окне первой реплики
                [hook_start+0.3, hook_speech_end-0.3] >= -35 dB.
D6 broll_bed  — SKIP: отдельной фоновой аудиодорожки в HyperFrames-пути нет.
D7 captions   — автогейт по words (транскрипт после caption-фиксов). FAIL — если
                слово точно совпадает с известным вариантом бренд-словаря, но не
                с display (регресс проводки apply_caption_fixes). Левенштейн-
                подозрения не фейлят — собираются в warn-список внутри PASS.

dur_fn/wh_fn/lufs_fn/fps_fn/volume_fn — DI для тестов (дефолты — реальные замеры).
"""
import re
import subprocess
from pathlib import Path

from reels_factory.config import FFMPEG, FFPROBE, OUT_W, OUT_H, FPS, LUFS_TARGET
from reels_factory.compose import build_caption_fixes, _split_edges, _pause_after
from reels_factory.render import load_words_file, media_dur, probe_wh, measure_lufs


def _levenshtein(a: str, b: str) -> int:
    """Расстояние Левенштейна между строками (простая DP, без зависимостей)."""
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if la == 0:
        return lb
    if lb == 0:
        return la
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        ca = a[i - 1]
        for j in range(1, lb + 1):
            cost = 0 if ca == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[lb]


def _word_core(text) -> str:
    return _split_edges(text)[1].lower()


def _d7_captions(words, caption_fixes: dict) -> str:
    if not words:
        return "PASS(нет слов)"
    displays_low = {str(d).lower() for d in caption_fixes}
    variants_low = {str(v).lower() for variants in caption_fixes.values() for v in variants
                    if " " not in str(v)}
    lev_variants = [v for v in variants_low if len(v) >= 4]

    bad, warn = [], []
    for w in words:
        core = _word_core(w.get("text", ""))
        if not core or core in displays_low:
            continue
        if core in variants_low:
            bad.append(w.get("text"))
            continue
        if any(_levenshtein(core, v) <= 2 for v in lev_variants):
            warn.append(w.get("text"))

    if bad:
        return f"FAIL({bad})"
    return f"PASS(warn: {', '.join(warn)})" if warn else "PASS()"


def _probe_fps(src) -> float:
    out = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0",
                          "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0", str(src)],
                         capture_output=True, text=True).stdout.strip()
    num, den = out.split("/")
    return float(num) / float(den)


def _mean_volume(src, start: float, end: float):
    """mean_volume (dB) окна [start,end] через ffmpeg volumedetect. None, если
    не распарсилось."""
    out = subprocess.run(
        [FFMPEG, "-ss", f"{start}", "-to", f"{end}", "-i", str(src),
         "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    m = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", out)
    return float(m.group(1)) if m else None


def _first_speech_window(scenario: dict):
    """Окно первой реплики [start, end-pause] (речь хука до паузы-заморозки)."""
    b = scenario["blocks"][0]
    start = float(b["start"])
    end = float(b["end"]) - _pause_after(b)
    return start, max(start, end)


def verify_reel(mp4: Path, scenario: dict, dur_fn=None, wh_fn=None, lufs_fn=None,
                fps_fn=None, volume_fn=None, words=None, hypothesis: dict | None = None,
                format: str = "split") -> dict:
    mp4 = Path(mp4)
    dur_fn = dur_fn or media_dur
    wh_fn = wh_fn or probe_wh
    lufs_fn = lufs_fn or measure_lufs
    fps_fn = fps_fn or _probe_fps
    volume_fn = volume_fn or _mean_volume

    gates = {}

    total = scenario.get("total", scenario["blocks"][-1]["end"])
    dur = dur_fn(str(mp4))
    d1_ok = abs(dur - total) <= 2.0
    gates["D1_duration"] = (
        f"PASS({dur:.2f}/{total:.2f})" if d1_ok
        else f"FAIL(длительность mp4 ({dur:.2f} с) расходится с сценарием "
             f"({total:.2f} с) больше чем на 2 с)")

    w, h = wh_fn(str(mp4))
    fps = fps_fn(str(mp4))
    d2_ok = (w, h) == (OUT_W, OUT_H) and abs(fps - FPS) <= 0.5
    gates["D2_resolution"] = (f"PASS({w}x{h}@{fps:.2f})" if d2_ok
                              else f"FAIL({w}x{h}@{fps:.2f})")

    lufs = lufs_fn(str(mp4))
    d3_ok = lufs is not None and abs(lufs - LUFS_TARGET) <= 1.5
    gates["D3_loudness"] = f"PASS({lufs})" if d3_ok else f"FAIL({lufs})"

    caps_path = mp4.parent / "caps.ass"
    gates["D4_captions"] = (
        "PASS" if caps_path.exists()
        else "SKIP(субтитры вшиты рендером; проверка — D7)")

    # D5: слышен ли голос ведущего в окне первой реплики
    fs, fe = _first_speech_window(scenario)
    mv = volume_fn(str(mp4), fs + 0.3, max(fs + 0.3, fe - 0.3))
    d5_ok = mv is not None and mv >= -35.0
    gates["D5_voice"] = f"PASS({mv} dB)" if d5_ok else f"FAIL({mv} dB)"

    gates["D6_broll_bed"] = "SKIP(фоновой дорожки в HyperFrames-пути нет)"

    # D7: автогейт по субтитрам — не осталось ли непочиненных коверканий бренда/темы
    words_list = words if (words is None or isinstance(words, list)) else load_words_file(str(words))
    fixes = build_caption_fixes(hypothesis or {"theme": scenario.get("theme")})
    gates["D7_captions"] = _d7_captions(words_list, fixes)

    # SKIP (например D6 для avatar без вставок) не считается провалом
    all_pass = all(not v.startswith("FAIL") for v in gates.values())
    return {"all_pass": all_pass, "gates": gates}
