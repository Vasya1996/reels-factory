import json
from pathlib import Path

import pytest

from reels_factory.master_audio import (
    MasterAudioArtifacts,
    _tts_cache_key,
    alignment_to_words,
    approve_master_audio,
    build_canonical_script,
    build_master_audio,
    build_user_master_audio,
    load_approved_master_audio,
    load_master_audio,
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
            "model_id": "eleven_multilingual_v2",
            "speed": 1.1,
            "stability": 0.2,
            "similarity_boost": 0.55,
            "style": 0.5,
            "use_speaker_boost": False,
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
    assert calls[0][1]["model_id"] == "eleven_multilingual_v2"
    assert calls[0][1]["speed"] == 1.1
    assert calls[0][1]["stability"] == 0.2
    assert calls[0][1]["similarity_boost"] == 0.55
    assert calls[0][1]["style"] == 0.5
    assert calls[0][1]["use_speaker_boost"] is False
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
    assert manifest["model_id"] == "eleven_multilingual_v2"
    assert len(manifest["cache_key"]) == 64
    assert manifest["provider_request"]["request_id"] == "req_fixture_master"
    assert manifest["settings"]["speed"] == 1.1
    assert manifest["settings"]["stability"] == 0.2
    assert manifest["settings"]["similarity_boost"] == 0.55
    assert manifest["settings"]["style"] == 0.5
    assert manifest["settings"]["use_speaker_boost"] is False
    assert "private-voice-id" not in manifest_text
    assert "api_key" not in manifest_text.lower()


def test_tts_cache_key_учитывает_модель_голос_текст_и_все_settings():
    options = {
        "model_id": "eleven_multilingual_v2",
        "speed": 1.1,
        "stability": 0.2,
        "similarity_boost": 0.55,
        "style": 0.5,
        "use_speaker_boost": False,
        "seed": None,
        "language_code": "ru",
        "apply_text_normalization": "auto",
        "pronunciation_dictionary_locators": [],
        "output_format": "mp3_44100_128",
    }
    baseline = _tts_cache_key(
        voice_id="private-voice-id",
        input_sha256="text-hash",
        options=options,
    )
    assert baseline == _tts_cache_key(
        voice_id="private-voice-id",
        input_sha256="text-hash",
        options=dict(options),
    )
    for changed_options in (
        {**options, "model_id": "eleven_v3"},
        {**options, "speed": 1.0},
        {**options, "stability": 0.3},
        {**options, "similarity_boost": 0.6},
        {**options, "style": 0.4},
        {**options, "use_speaker_boost": True},
    ):
        assert baseline != _tts_cache_key(
            voice_id="private-voice-id",
            input_sha256="text-hash",
            options=changed_options,
        )
    assert baseline != _tts_cache_key(
        voice_id="another-voice",
        input_sha256="text-hash",
        options=options,
    )
    assert baseline != _tts_cache_key(
        voice_id="private-voice-id",
        input_sha256="another-text",
        options=options,
    )


def test_build_master_audio_meter_считает_canonical_text_один_раз(tmp_path):
    fixture = _fixture()
    response = fixture["response"]

    class Provider:
        def convert_with_timestamps(self, text, **kwargs):
            return TimestampedSpeech(
                audio=b"fake-mp3",
                alignment=response["alignment"],
                normalized_alignment=response["normalized_alignment"],
                request_id=response["request_id"],
            )

    def fake_run(cmd):
        Path(cmd[-1]).write_bytes(b"generated")

    meter_calls = []
    result = build_master_audio(
        _scenario(), {"language": "ru", "voice_id": "v1"}, tmp_path,
        provider=Provider(), run_cmd=fake_run, duration_fn=lambda _: 1.3,
        meter=meter_calls.append,
    )

    assert meter_calls == [len(result.canonical["text"])]


def test_build_master_audio_без_meter_работает_как_раньше(tmp_path):
    fixture = _fixture()
    response = fixture["response"]

    class Provider:
        def convert_with_timestamps(self, text, **kwargs):
            return TimestampedSpeech(
                audio=b"fake-mp3",
                alignment=response["alignment"],
                normalized_alignment=response["normalized_alignment"],
                request_id=response["request_id"],
            )

    def fake_run(cmd):
        Path(cmd[-1]).write_bytes(b"generated")

    result = build_master_audio(
        _scenario(), {"language": "ru", "voice_id": "v1"}, tmp_path,
        provider=Provider(), run_cmd=fake_run, duration_fn=lambda _: 1.3,
    )

    assert isinstance(result, MasterAudioArtifacts)


def test_build_master_audio_упавший_request_не_тарифицируется(tmp_path):
    class FailingProvider:
        def convert_with_timestamps(self, text, **kwargs):
            raise RuntimeError("elevenlabs упал")

    meter_calls = []
    with pytest.raises(RuntimeError, match="elevenlabs упал"):
        build_master_audio(
            _scenario(), {"language": "ru", "voice_id": "v1"}, tmp_path,
            provider=FailingProvider(), meter=meter_calls.append,
        )

    assert meter_calls == []


def test_build_master_audio_упавший_meter_не_роняет_уже_оплаченный_request(
    tmp_path, capsys
):
    """ElevenLabs-запрос уже оплачен и результат уже получен к моменту вызова
    meter(); сбой самого метра (contention с ботом за sqlite-ledger и т.п.)
    не должен ронять всю сборку — он честно логируется в stderr, но
    build_master_audio возвращает нормальный результат."""
    fixture = _fixture()
    response = fixture["response"]

    class Provider:
        def convert_with_timestamps(self, text, **kwargs):
            return TimestampedSpeech(
                audio=b"fake-mp3",
                alignment=response["alignment"],
                normalized_alignment=response["normalized_alignment"],
                request_id=response["request_id"],
            )

    def fake_run(cmd):
        Path(cmd[-1]).write_bytes(b"generated")

    def broken_meter(chars):
        raise RuntimeError("database is locked")

    result = build_master_audio(
        _scenario(), {"language": "ru", "voice_id": "v1"}, tmp_path,
        provider=Provider(), run_cmd=fake_run, duration_fn=lambda _: 1.3,
        meter=broken_meter,
    )

    assert isinstance(result, MasterAudioArtifacts)
    err = capsys.readouterr().err
    assert "database is locked" in err
    assert "не тарифицирован" in err


def test_master_audio_feature_flag_safe_default(monkeypatch):
    monkeypatch.delenv("RF_MASTER_AUDIO_ENABLED", raising=False)
    assert master_audio_enabled({}) is False
    assert master_audio_enabled({"master_audio": {"enabled": True}}) is True
    monkeypatch.setenv("RF_MASTER_AUDIO_ENABLED", "0")
    assert master_audio_enabled({"master_audio": {"enabled": True}}) is False
    monkeypatch.setenv("RF_MASTER_AUDIO_ENABLED", "true")
    assert master_audio_enabled({}) is True


def test_tts_audio_approval_фиксирует_hash_и_загружается_без_provider_request(
        tmp_path):
    fixture = _fixture()["response"]

    class Provider:
        def convert_with_timestamps(self, text, **kwargs):
            return TimestampedSpeech(
                audio=b"approved-preview",
                alignment=fixture["alignment"],
                normalized_alignment=fixture["normalized_alignment"],
                request_id="preview-request",
            )

    def fake_run(cmd):
        Path(cmd[-1]).write_bytes(b"generated-" + Path(cmd[-1]).name.encode())

    config = {"language": "ru", "voice_id": "v1"}
    artifact_dir = tmp_path / "audio" / "tts"
    original = build_master_audio(
        _scenario(), config, artifact_dir,
        provider=Provider(), run_cmd=fake_run, duration_fn=lambda _: 1.3,
    )
    approval = approve_master_audio(
        tmp_path, artifact_dir, source="elevenlabs_approved"
    )

    loaded = load_approved_master_audio(_scenario(), config, tmp_path)

    assert approval["artifact_dir"] == "audio/tts"
    assert loaded.wav.read_bytes() == original.wav.read_bytes()
    assert loaded.mp3.read_bytes() == b"approved-preview"
    assert loaded.manifest["provider"] == "elevenlabs"


def test_approved_audio_hash_не_даёт_подменить_дорожку_перед_рендером(tmp_path):
    fixture = _fixture()["response"]

    class Provider:
        def convert_with_timestamps(self, text, **kwargs):
            return TimestampedSpeech(
                audio=b"preview",
                alignment=fixture["alignment"],
                normalized_alignment=None,
                request_id="req",
            )

    def fake_run(cmd):
        Path(cmd[-1]).write_bytes(b"generated")

    config = {"language": "ru", "voice_id": "v1"}
    artifact_dir = tmp_path / "audio" / "tts"
    build_master_audio(
        _scenario(), config, artifact_dir,
        provider=Provider(), run_cmd=fake_run, duration_fn=lambda _: 1.3,
    )
    approve_master_audio(tmp_path, artifact_dir, source="elevenlabs_approved")
    (artifact_dir / "voice_master.wav").write_bytes(b"changed")

    with pytest.raises(ValueError, match="изменился"):
        load_approved_master_audio(_scenario(), config, tmp_path)


def test_telegram_voice_становится_master_без_генеративной_обработки(tmp_path):
    source = tmp_path / "input.ogg"
    source.write_bytes(b"telegram-opus")
    scenario = _scenario()
    config = {"language": "ru", "voice_id": "unused-for-user-audio"}

    def fake_run(cmd):
        Path(cmd[-1]).write_bytes(b"pcm-" + Path(cmd[-1]).name.encode())

    def fake_transcribe(src, workdir, language):
        out = Path(workdir) / "words.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"words": [
            {"id": 0, "start": 0.1, "end": 0.4, "text": "Кофе", "prob": 0.9},
            {"id": 1, "start": 0.4, "end": 0.8, "text": "вкусный.", "prob": 0.9},
            {"id": 2, "start": 1.0, "end": 1.3, "text": "Кофе", "prob": 0.9},
            {"id": 3, "start": 1.3, "end": 1.8, "text": "бодрит!", "prob": 0.9},
        ]}, ensure_ascii=False), encoding="utf-8")
        return {"out": str(out)}

    artifact_dir = tmp_path / "audio" / "user"
    built = build_user_master_audio(
        scenario,
        config,
        artifact_dir,
        source,
        transcribe_fn=fake_transcribe,
        run_cmd=fake_run,
        duration_fn=lambda _: 2.0,
    )
    approve_master_audio(
        tmp_path, artifact_dir, source="telegram_user_audio"
    )
    loaded = load_approved_master_audio(scenario, config, tmp_path)

    assert built.manifest["provider"] == "telegram_user_audio"
    assert built.manifest["processing"]["content_edits"] is False
    assert built.manifest["processing"]["denoise"] is False
    assert built.mp3.read_bytes() == b"telegram-opus"
    assert len(loaded.block_wavs) == 2
    assert [word["block_index"] for word in loaded.words] == [0, 0, 1, 1]


def test_telegram_voice_с_большим_пропуском_сценария_отклоняется(tmp_path):
    source = tmp_path / "input.ogg"
    source.write_bytes(b"short")

    def fake_run(cmd):
        Path(cmd[-1]).write_bytes(b"pcm")

    def fake_transcribe(src, workdir, language):
        out = Path(workdir) / "words.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"words": [
            {"id": 0, "start": 0.1, "end": 0.4, "text": "Совсем другое"},
        ]}, ensure_ascii=False), encoding="utf-8")
        return {"out": str(out)}

    with pytest.raises(ValueError, match="отличается|не целиком"):
        build_user_master_audio(
            _scenario(),
            {"language": "ru"},
            tmp_path / "audio" / "user",
            source,
            transcribe_fn=fake_transcribe,
            run_cmd=fake_run,
            duration_fn=lambda _: 1.0,
        )
