"""Нормализация громкости в Revideo-пути (_normalize_loudness). Без реального ffmpeg."""
from pathlib import Path
from unittest.mock import patch

from reels_factory.config import FFMPEG, LUFS_TARGET
from reels_factory.revideo_render import (
    _concat_avatar_island_visuals,
    _concat_master_visuals,
    _normalize_loudness,
    _prepare_render_workspace,
)


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
    # faststart: moov в начало файла, иначе телеграм-плеер не знает размеров
    # видео до полной загрузки и показывает вертикальный ролик квадратом
    assert "-movflags" in cmd and cmd[cmd.index("-movflags") + 1] == "+faststart"
    assert kwargs.get("check") is True
    # out_mp4 заменён нормализованным результатом (tmp -> out через Path.replace)
    assert mp4.read_bytes() == b"normalized"


def test_revideo_workspace_изолирован_для_каждой_job(tmp_path):
    template = tmp_path / "template"
    (template / "src").mkdir(parents=True)
    (template / "public" / "emoji").mkdir(parents=True)
    (template / "src" / "project.tsx").write_text("// project", encoding="utf-8")
    (template / "src" / "global.css").write_text("/* css */", encoding="utf-8")
    (template / "public" / "emoji" / "icon.png").write_bytes(b"png")
    (template / "public" / "whoosh.wav").write_bytes(b"sfx")
    # Остаток старого shared runtime не должен попасть новому клиенту.
    (template / "public" / "base.mp4").write_bytes(b"old-client")

    first = _prepare_render_workspace(tmp_path / "jobs" / "job-a", template)
    second = _prepare_render_workspace(tmp_path / "jobs" / "job-b", template)
    assert not (first / "public" / "base.mp4").exists()
    assert not (second / "public" / "base.mp4").exists()
    (first / "src" / "tz.json").write_text('{"job":"a"}', encoding="utf-8")
    (second / "src" / "tz.json").write_text('{"job":"b"}', encoding="utf-8")
    (first / "public" / "base.mp4").write_bytes(b"client-a")
    (second / "public" / "base.mp4").write_bytes(b"client-b")

    assert first != second
    assert (first / "src" / "tz.json").read_text(encoding="utf-8") == '{"job":"a"}'
    assert (second / "src" / "tz.json").read_text(encoding="utf-8") == '{"job":"b"}'
    assert (first / "public" / "base.mp4").read_bytes() == b"client-a"
    assert (second / "public" / "base.mp4").read_bytes() == b"client-b"
    assert (first / "public" / "emoji" / "icon.png").exists()
    assert (second / "public" / "emoji" / "icon.png").exists()
    assert (first / "public" / "whoosh.wav").read_bytes() == b"sfx"
    assert (second / "public" / "whoosh.wav").read_bytes() == b"sfx"


def test_master_visual_concat_точно_подгоняет_timeline_и_удаляет_audio(tmp_path):
    clips = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
    for clip in clips:
        clip.write_bytes(b"video")

    def fake_run(cmd, **kwargs):
        Path(cmd[-1]).write_bytes(b"silent-base")

    with patch(
        "reels_factory.revideo_render.subprocess.run", side_effect=fake_run
    ) as run:
        out = _concat_master_visuals(tmp_path, clips, [1.25, 2.5])

    assert out.read_bytes() == b"silent-base"
    cmd = run.call_args.args[0]
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "trim=duration=1.250000" in graph
    assert "trim=duration=2.500000" in graph
    assert "concat=n=2:v=1:a=0" in graph
    assert "-an" in cmd
    assert run.call_args.kwargs["check"] is True


def test_avatar_island_concat_ставит_shots_и_чёрные_overlay_gaps_точно(tmp_path):
    clips = [tmp_path / "shot-a.mp4", tmp_path / "shot-b.mp4"]
    for clip in clips:
        clip.write_bytes(b"video")
    plan = {
        "timeline": {"duration_seconds": 12.0},
        "shots": [
            {
                "id": "shot-a",
                "visible_timing": {"start": 0.0, "end": 3.0},
                "trim": {"start_seconds": 0.2},
            },
            {
                "id": "shot-b",
                "visible_timing": {"start": 7.0, "end": 10.0},
                "trim": {"start_seconds": 0.2},
            },
        ],
    }

    def fake_run(cmd, **kwargs):
        Path(cmd[-1]).write_bytes(b"island-base")

    with patch(
        "reels_factory.revideo_render.subprocess.run", side_effect=fake_run
    ) as run:
        out = _concat_avatar_island_visuals(tmp_path, clips, plan)

    assert out.read_bytes() == b"island-base"
    cmd = run.call_args.args[0]
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "trim=start=0.200000:duration=3.000000" in graph
    assert "d=4.000000" in graph  # B-roll/HyperFrames gap 3..7
    assert "d=2.000000" in graph  # tail gap 10..12
    assert "concat=n=4:v=1:a=0" in graph
    assert "-an" in cmd
