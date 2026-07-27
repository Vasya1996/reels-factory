import os
from pathlib import Path

import pytest

from reels_factory.tts import (
    MODEL_ID,
    V3_MAX_CHARACTERS,
    ElevenLabsClient,
    create_voice_clone,
    delete_voice,
    synth_voice,
)


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
    assert body["model_id"] == MODEL_ID == "eleven_v3"
    assert body["voice_settings"] == {"stability": 0.5}
    assert headers["xi-api-key"] == "k"


def test_модель_переопределяется_через_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    monkeypatch.setenv("ELEVENLABS_MODEL", "eleven_v3")
    http = _FakeHttp()

    synth_voice("x", tmp_path / "g.wav", voice_id="v1", http=http,
                run_cmd=lambda cmd: Path(cmd[-1]).write_bytes(b"wav"))

    assert http.posts[0][1]["model_id"] == "eleven_v3"


def test_timestamped_v3_передаёт_только_поддерживаемые_quality_settings(monkeypatch):
    captured = {}

    class Resp:
        headers = {"request-id": "req-1"}
        def raise_for_status(self): pass
        def json(self):
            import base64
            return {
                "audio_base64": base64.b64encode(b"mp3").decode(),
                "alignment": {
                    "characters": ["П"],
                    "character_start_times_seconds": [0.0],
                    "character_end_times_seconds": [0.1],
                },
                "normalized_alignment": None,
            }

    class Http:
        def post(self, url, **kwargs):
            captured["url"] = url
            captured.update(kwargs)
            return Resp()

    client = ElevenLabsClient(api_key="secret", http=Http())
    result = client.convert_with_timestamps(
        "П",
        voice_id="voice-1",
        stability=0.5,
        seed=42,
        language_code="ru",
        apply_text_normalization="on",
        pronunciation_dictionary_locators=[
            {"id": "dict-1", "version_id": "v1"}
        ],
    )

    assert captured["url"].endswith("/voice-1/with-timestamps")
    assert captured["params"] == {"output_format": "mp3_44100_128"}
    body = captured["json"]
    assert body["model_id"] == "eleven_v3"
    assert body["voice_settings"] == {"stability": 0.5}
    assert body["seed"] == 42
    assert body["language_code"] == "ru"
    assert body["apply_text_normalization"] == "on"
    assert body["pronunciation_dictionary_locators"] == [{
        "pronunciation_dictionary_id": "dict-1",
        "version_id": "v1",
    }]
    assert "speed" not in body["voice_settings"]
    assert "similarity_boost" not in body["voice_settings"]
    assert "style" not in body["voice_settings"]
    assert "use_speaker_boost" not in body["voice_settings"]
    assert captured["headers"]["xi-api-key"] == "secret"
    assert result.audio == b"mp3" and result.request_id == "req-1"


def test_v3_граница_5000_символов_проверяется_до_http():
    class NoHttp:
        def post(self, *args, **kwargs):
            raise AssertionError("HTTP не должен вызываться")

    client = ElevenLabsClient(api_key="k", http=NoHttp())
    with pytest.raises(ValueError, match="5000"):
        client.convert_with_timestamps(
            "я" * (V3_MAX_CHARACTERS + 1), voice_id="v1"
        )


def test_timestamped_response_без_alignment_падает():
    class Resp:
        headers = {}
        def raise_for_status(self): pass
        def json(self): return {"audio_base64": "ZmFrZQ=="}

    class Http:
        def post(self, *args, **kwargs): return Resp()

    with pytest.raises(RuntimeError, match="alignment"):
        ElevenLabsClient(api_key="k", http=Http()).convert_with_timestamps(
            "текст", voice_id="v1"
        )


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


def test_delete_voice_шлёт_delete_на_voice_id(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    captured = {}

    class Resp:
        def raise_for_status(self): pass

    class Http:
        def delete(self, url, **kw):
            captured["url"] = url
            captured["headers"] = kw.get("headers")
            return Resp()

    delete_voice("v123", http=Http())
    assert captured["url"].endswith("/v1/voices/v123")
    assert captured["headers"]["xi-api-key"] == "k"


def test_delete_voice_без_ключа_ошибка(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "")
    with pytest.raises(RuntimeError):
        delete_voice("v123", http=object())


def test_synth_voice_сообщает_число_символов(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    seen = []
    text = "Привет, это тестовая фраза для озвучки."

    synth_voice(text, tmp_path / "g.wav", voice_id="v1", http=_FakeHttp(),
                run_cmd=lambda *a, **kw: None, meter=seen.append)

    assert seen == [len(text)]


def test_synth_voice_без_meter_работает_как_раньше(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    # meter необязателен: движок зовут и вручную, там учёта нет.
    out = synth_voice("текст", tmp_path / "g.wav", voice_id="v1",
                      http=_FakeHttp(), run_cmd=lambda *a, **kw: None)
    assert out == tmp_path / "g.wav"
