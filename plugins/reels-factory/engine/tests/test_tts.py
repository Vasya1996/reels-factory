import os
from pathlib import Path

import pytest

from reels_factory.tts import synth_voice, MODEL_ID


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


def test_synth_voice_шлёт_текст_дефолтную_модель_и_голос_в_url(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    monkeypatch.delenv("ELEVENLABS_MODEL", raising=False)
    http = _FakeHttp()

    out = synth_voice("Привет", tmp_path / "g.wav", voice_id="v1", http=http,
                      run_cmd=lambda cmd: Path(cmd[-1]).write_bytes(b"wav"))

    assert out.exists()
    url, body, headers = http.posts[0]
    assert "v1" in url
    assert body["text"] == "Привет"
    # дефолт — рабочая для клон-голосов модель
    assert body["model_id"] == MODEL_ID == "eleven_multilingual_v2"
    assert headers["xi-api-key"] == "k"


def test_модель_переопределяется_через_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    monkeypatch.setenv("ELEVENLABS_MODEL", "eleven_v3")
    http = _FakeHttp()

    synth_voice("x", tmp_path / "g.wav", voice_id="v1", http=http,
                run_cmd=lambda cmd: Path(cmd[-1]).write_bytes(b"wav"))

    assert http.posts[0][1]["model_id"] == "eleven_v3"


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
