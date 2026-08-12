"""Живая сборка на готовом материале. Платных вызовов к HeyGen нет."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from reels_factory.config import FFPROBE

WORK = Path(r"C:\Users\123\Videos\Reels\work\bot-583558720-1784873847")


@pytest.mark.slow
def test_живая_сборка_ролика(tmp_path):
    if not WORK.exists():
        pytest.skip("нет рабочей папки с материалом")

    from reels_factory.hf_render import assemble_hyperframes

    shutil.copyfile(WORK / "top.mp4", tmp_path / "top.mp4")
    shutil.copyfile(WORK / "reel-audio.wav", tmp_path / "voice.wav")
    words = json.loads((WORK / "words.fixed.json").read_text(encoding="utf-8"))
    # один готовый клип на весь ролик, значит и блок в сценарии один:
    # склейка базы ждёт по клипу на блок
    timed = {"total": 41.5, "blocks": [{"role": "hook", "start": 0.0, "end": 41.5,
                                        "speech": " ".join(w["text"] for w in words)}]}

    plan = {"timeline": {"final_duration_seconds": 41.5},
            "phrases": [{"id": "p1", "text": " ".join(w["text"] for w in words[:12])}],
            "windows": [{"id": "window-000", "coverage": "avatar",
                         "zone": "video-overlay", "phrase_ids": ["p1"],
                         "final_timing": {"start": 0.0, "end": 6.0},
                         "effect": {"type": "none"}}],
            "log": []}

    res = assemble_hyperframes(
        tmp_path, timed, edit_plan=plan, avatar_mp4s=[tmp_path / "top.mp4"],
        master_audio=tmp_path / "voice.wav", alignment_words=words)

    probe = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,nb_frames",
         "-of", "default=nw=1", res["mp4"]],
        capture_output=True, text=True, check=True).stdout
    assert "width=1080" in probe and "height=1920" in probe
    frames = int(probe.split("nb_frames=")[1].split()[0])
    assert abs(frames - 1245) <= 1, f"кадров {frames}, ожидали 1245±1"
    assert all(v == "PASS" for v in res["gates"].values())
