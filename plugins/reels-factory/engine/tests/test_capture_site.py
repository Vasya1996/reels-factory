"""Снимок сайта: берётся движком, кэшируется по адресу, стареет."""
import os
import time

from reels_factory.capture_site import cache_key, cached_capture


def _fake_shot(root, url):
    target = root / cache_key(url) / "screenshots"
    target.mkdir(parents=True, exist_ok=True)
    (target / "scroll-000.png").write_bytes(b"x")
    return target / "scroll-000.png"


def test_ключ_кэша_по_адресу():
    assert cache_key("https://elevenlabs.io/") == cache_key("https://elevenlabs.io")
    assert cache_key("https://a.io") != cache_key("https://b.io")


def test_свежий_снимок_не_пересобирается(tmp_path, monkeypatch):
    from reels_factory import capture_site

    calls = []
    monkeypatch.setattr(capture_site, "capture",
                        lambda url, out_dir: calls.append(url) or {"dir": str(out_dir)})
    _fake_shot(tmp_path, "https://a.io")
    cached_capture("https://a.io", tmp_path)
    assert calls == []


def test_протухший_снимок_пересобирается(tmp_path, monkeypatch):
    from reels_factory import capture_site

    calls = []
    monkeypatch.setattr(capture_site, "capture",
                        lambda url, out_dir: calls.append(url) or {"dir": str(out_dir)})
    shot = _fake_shot(tmp_path, "https://a.io")
    old = time.time() - 8 * 24 * 3600
    os.utime(shot, (old, old))
    cached_capture("https://a.io", tmp_path, max_age_days=7)
    assert calls == ["https://a.io"]


def test_отсутствующий_снимок_собирается(tmp_path, monkeypatch):
    from reels_factory import capture_site

    calls = []
    monkeypatch.setattr(capture_site, "capture",
                        lambda url, out_dir: calls.append(url) or {"dir": str(out_dir)})
    cached_capture("https://b.io", tmp_path)
    assert calls == ["https://b.io"]
