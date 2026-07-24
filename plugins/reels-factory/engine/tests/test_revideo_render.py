"""Нормализация громкости в Revideo-пути (_normalize_loudness). Без реального ffmpeg."""
from pathlib import Path
from unittest.mock import patch

from reels_factory.config import FFMPEG, LUFS_TARGET
from reels_factory.revideo_render import _normalize_loudness


def test_normalize_loudness_вызывает_ffmpeg_с_loudnorm_и_lufs_target(tmp_path):
    mp4 = tmp_path / "out.mp4"
    mp4.write_bytes(b"original")

    def fake_run(cmd, *args, **kwargs):
        # реальный ffmpeg создал бы tmp-файл рядом — эмулируем это, чтобы
        # Path.replace() из _normalize_loudness не упал на отсутствующем файле
        Path(cmd[-1]).write_bytes(b"normalized")

    with patch("reels_factory.revideo_render.subprocess.run", side_effect=fake_run) as mock_run:
        _normalize_loudness(mp4)

    assert mock_run.call_count == 1
    args, kwargs = mock_run.call_args
    cmd = args[0]
    assert isinstance(cmd, list)  # список аргументов, не shell-строка
    assert cmd[0] == FFMPEG
    assert f"loudnorm=I={LUFS_TARGET}:TP=-1.5:LRA=11" in cmd
    assert "-c:v" in cmd and cmd[cmd.index("-c:v") + 1] == "copy"
    assert "-c:a" in cmd and cmd[cmd.index("-c:a") + 1] == "aac"
    assert kwargs.get("check") is True
    # out_mp4 заменён нормализованным результатом (tmp -> out через Path.replace)
    assert mp4.read_bytes() == b"normalized"
