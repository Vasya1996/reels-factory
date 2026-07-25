import json
from pathlib import Path

import pytest

from reels_factory.master_audio import (
    MasterAudioArtifacts,
    alignment_to_words,
    build_canonical_script,
    build_master_audio,
    master_audio_enabled,
    validate_character_alignment,
)
from reels_factory.tts import TimestampedSpeech


FIXTURE = Path(__file__).parent / "fixtures" / "elevenlabs_timestamped_ru.json"


def _fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _scenario():
    return {"blocks": [
        {"role": "hook", "speech": "Кофе вкусный."},
        {"role": "cta", "speech": "Кофе бодрит!"},
    ]}


def _alignment(text):
    return {
        "characters": list(text),
        "character_start_times_seconds": [i * 0.05 for i in range(len(text))],
        "character_end_times_seconds": [(i + 1) * 0.05 for i in range(len(text))],
    }


def test_canonical_script_сохраняет_character_ranges_и_повторы():
    canonical = build_canonical_script(_scenario(), {"language": "ru"})
    assert canonical["text"] == "Кофе вкусный.\nКофе бодрит!"
    first, second = canonical["blocks"]
    assert canonical["text"][first["character_start"]:first["character_end"]] == first["speech"]
    assert canonical["text"][second["character_start"]:second["character_end"]] == second["speech"]
    assert first["character_start"] == 0
    assert second["character_start"] == first["character_end"] + 1


def test_alignment_words_unicode_tags_пунктуация_и_повторные_слова():
    text = "[excited] Ко́фе, кофе!"
    blocks = [{
        "id": "block-0", "index": 0, "role": "hook",
        "character_start": 0, "character_end": len(text),
    }]
    words = alignment_to_words(text, _alignment(text), blocks)
    assert [w["text"] for w in words] == ["Ко́фе,", "кофе!"]
    assert all(w["block_id"] == "block-0" for w in words)
    assert words[0]["character_start"] > text.index("]")
    assert words[0]["end"] <= words[1]["start"]


def test_alignment_rejects_normalized_text_substitution_and_overlap():
    text = "тест"
    wrong = _alignment("тост")
    with pytest.raises(ValueError, match="canonical text"):
        validate_character_alignment(text, wrong)

    overlap = _alignment(text)
    overlap["character_start_times_seconds"][1] = 0.01
    with pytest.raises(ValueError, match="пересекается"):
        validate_character_alignment(text, overlap)


def test_master_audio_rejects_wav_shorter_than_alignment(tmp_path):
    fixture = _fixture()["response"]

    class Provider:
        def convert_with_timestamps(self, text, **kwargs):
            return TimestampedSpeech(
                audio=b"mp3",
                alignment=fixture["alignment"],
                normalized_alignment=None,
                request_id="req",
            )

    def fake_run(cmd):
        Path(cmd[-1]).write_bytes(b"generated")

    with pytest.raises(ValueError, match="короче"):
        build_master_audio(
            _scenario(), {"language": "ru", "voice_id": "v1"}, tmp_path,
            provider=Provider(), run_cmd=fake_run, duration_fn=lambda _: 1.0,
        )


def test_build_master_audio_один_provider_request_и_полный_contract(tmp_path):
    fixture = _fixture()
    response = fixture["response"]
    calls = []

    class Provider:
        def convert_with_timestamps(self, text, **kwargs):
            calls.append((text, kwargs))
            return TimestampedSpeech(
                audio=b"fake-mp3",
                alignment=response["alignment"],
                normalized_alignment=response["normalized_alignment"],
                request_id=response["request_id"],
            )

    ffmpeg_calls = []
    def fake_run(cmd):
        ffmpeg_calls.append(cmd)
        Path(cmd[-1]).write_bytes(b"generated")

    config = {
        "language": "ru",
        "voice_id": "private-voice-id",
        "tts": {
            "model_id": "eleven_v3",
            "stability": 0.5,
            "seed": 7,
            "apply_text_normalization": "auto",
        },
    }
    result = build_master_audio(
        _scenario(), config, tmp_path, provider=Provider(),
        run_cmd=fake_run, duration_fn=lambda _: 1.3,
    )

    assert isinstance(result, MasterAudioArtifacts)
    assert len(calls) == 1
    assert calls[0][0] == fixture["text"]
    assert calls[0][1]["model_id"] == "eleven_v3"
    assert calls[0][1]["stability"] == 0.5
    assert calls[0][1]["seed"] == 7
    assert result.mp3.read_bytes() == b"fake-mp3"
    assert result.wav.exists()
    assert len(result.block_wavs) == 2
    assert len(ffmpeg_calls) == 3  # MP3->master WAV + две alignment-based нарезки
    assert all(path.exists() for path in result.block_wavs)

    expected = {
        "script.canonical.json",
        "voice_master.mp3",
        "voice_master.wav",
        "alignment.characters.json",
        "alignment.words.json",
        "audio_manifest.json",
    }
    assert expected <= {p.name for p in tmp_path.iterdir()}
    words_doc = json.loads(
        (tmp_path / "alignment.words.json").read_text(encoding="utf-8")
    )
    assert [w["text"] for w in words_doc["words"]] == [
        "Кофе", "вкусный.", "Кофе", "бодрит!",
    ]
    assert len(words_doc["blocks"]) == 2
    assert words_doc["blocks"][0]["end"] == pytest.approx(
        words_doc["blocks"][1]["start"]
    )
    assert result.timed_scenario["total"] == 1.3

    manifest_text = (tmp_path / "audio_manifest.json").read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    assert manifest["model_id"] == "eleven_v3"
    assert manifest["provider_request"]["request_id"] == "req_fixture_master"
    assert manifest["settings"]["stability"] == 0.5
    assert "private-voice-id" not in manifest_text
    assert "api_key" not in manifest_text.lower()


def test_master_audio_feature_flag_safe_default(monkeypatch):
    monkeypatch.delenv("RF_MASTER_AUDIO_ENABLED", raising=False)
    assert master_audio_enabled({}) is False
    assert master_audio_enabled({"master_audio": {"enabled": True}}) is True
    monkeypatch.setenv("RF_MASTER_AUDIO_ENABLED", "0")
    assert master_audio_enabled({"master_audio": {"enabled": True}}) is False
    monkeypatch.setenv("RF_MASTER_AUDIO_ENABLED", "true")
    assert master_audio_enabled({}) is True
