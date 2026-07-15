"""Низкоуровневые ffmpeg-хелперы, общие для сборки и QA-гейтов.

run — запуск ffmpeg с внятной ошибкой; probe_wh/media_dur — размеры/длительность
через ffprobe; measure_lufs — интегральная громкость; parse_loudnorm_json —
разбор замера двухпроходного loudnorm; load_words_file — чтение words.json.
"""
import re
import json
import subprocess

from reels_factory.config import FFMPEG, FFPROBE, LUFS_TARGET

VENC = ["-c:v", "libx264", "-crf", "20", "-preset", "medium", "-pix_fmt", "yuv420p",
        "-video_track_timescale", "30000"]
AENC = ["-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2"]


def run(cmd, cwd=None):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg fail ({p.returncode})\nCMD: {' '.join(map(str,cmd))}\n{p.stderr[-1500:]}")
    return p.stderr


def probe_wh(src):
    out = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0",
                          "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(src)],
                         capture_output=True, text=True).stdout.strip()
    w, h = out.split("x")[:2]
    return int(w), int(h)


def media_dur(src):
    out = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(src)], capture_output=True, text=True).stdout.strip()
    return float(out)


def measure_lufs(src):
    """Интегральная громкость (LUFS) готового файла через loudnorm-замер | None."""
    p = subprocess.run([FFMPEG, "-i", str(src),
                        "-af", f"loudnorm=I={LUFS_TARGET}:TP=-1.5:LRA=11:print_format=json",
                        "-f", "null", "-"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", p.stderr, re.S)
    if m:
        try:
            return float(json.loads(m.group(0)).get("input_i"))
        except Exception:
            pass
    return None


# --- двухпроходный loudnorm: замер (print_format=json) -> применение с
# measured_*-параметрами и linear=true (стандартный фикс из документации фильтра,
# однопроходный недотягивал тихие разговорные сегменты до цели). ---
_LOUDNORM_KEYS = ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")


def parse_loudnorm_json(stderr_text):
    """Последний {...}-блок замера loudnorm из stderr ffmpeg -> dict float-значений
    (input_i/input_tp/input_lra/input_thresh/target_offset) | None, если не распарсился."""
    blocks = re.findall(r"\{[^{}]*\}", stderr_text, re.S)
    if not blocks:
        return None
    try:
        d = json.loads(blocks[-1])
        return {k: float(d[k]) for k in _LOUDNORM_KEYS}
    except (ValueError, KeyError, TypeError):
        return None


def load_words_file(path):
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    return d["words"] if isinstance(d, dict) else d
