import json
from pathlib import Path

import pytest

from reels_factory.ingest import ingest


def test_локальный_файл(tmp_path):
    v = tmp_path / "vod.mp4"
    v.write_bytes(b"fake")
    wd = tmp_path / "wd"
    meta = ingest(str(v), wd)
    assert meta["kind"] == "local"
    assert meta["video_path"] == str(v.resolve())
    saved = json.loads((wd / "meta.json").read_text(encoding="utf-8"))
    assert saved == meta


def test_несуществующий_локальный_путь(tmp_path):
    with pytest.raises(FileNotFoundError):
        ingest(str(tmp_path / "нет.mp4"), tmp_path / "wd")


@pytest.mark.slow
def test_скачивание_url(tmp_path):
    meta = ingest("https://www.youtube.com/watch?v=jNQXAC9IVRw", tmp_path / "wd")
    assert meta["kind"] == "url"
    assert meta["duration_s"] > 0
    assert Path(meta["video_path"]).stat().st_size > 0
