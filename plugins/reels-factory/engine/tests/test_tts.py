import os
from pathlib import Path

import pytest

from reels_factory.tts import synth_voice, MODEL_ID, create_voice_clone


class _Resp:
    def __init__(self, content=b"fake-mp3"):
        self.content = content

    def raise_for_status(self):
        pass


class _FakeHttp:
    def __init__(self):
        self.posts = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.posts.append((url, json, headers))
        return _Resp()


def test_synth_voice_шлёт_текст_модель_v3_и_голос_в_url(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    http = _FakeHttp()

    out = synth_voice("Привет [excited]", tmp_path / "g.wav", voice_id="v1", http=http,
                      run_cmd=lambda cmd: Path(cmd[-1]).write_bytes(b"wav"))

    assert out.exists()
    url, body, headers = http.posts[0]
    assert "v1" in url
    assert body["text"] == "Привет [excited]"
    assert body["model_id"] == MODEL_ID
    assert headers["xi-api-key"] == "k"


def test_synth_voice_без_ключа_ошибка(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "")
    with pytest.raises(RuntimeError):
        synth_voice("x", tmp_path / "g.wav", voice_id="v1", http=_FakeHttp())


def test_synth_voice_без_голоса_ошибка(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    monkeypatch.delenv("ELEVENLABS_VOICE_ID", raising=False)
    with pytest.raises(RuntimeError):
        synth_voice("x", tmp_path / "g.wav", http=_FakeHttp())


@pytest.mark.slow
def test_synth_voice_реальный_синтез(tmp_path):
    if not (os.environ.get("ELEVENLABS_API_KEY") and os.environ.get("ELEVENLABS_VOICE_ID")):
        pytest.skip("нет ключа/голоса ElevenLabs")
    out = synth_voice("проверка связи", tmp_path / "g.wav")
    assert out.stat().st_size > 1000


def test_create_voice_clone_posts_and_returns_id(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    audio = tmp_path / "voice.mp3"
    audio.write_bytes(b"fake")
    captured = {}

    class Resp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"voice_id": "v123"}

    class Http:
        def post(self, url, **kw):
            captured["url"] = url
            captured["data"] = kw.get("data")
            captured["files"] = kw.get("files")
            captured["headers"] = kw.get("headers")
            return Resp()

    vid = create_voice_clone(audio, "Серик", http=Http())
    assert vid == "v123"
    assert captured["url"].endswith("/v1/voices/add")
    assert captured["data"]["name"] == "Серик"
    assert captured["headers"]["xi-api-key"] == "k"
    assert captured["files"]  # запись приложена
