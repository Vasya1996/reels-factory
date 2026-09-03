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


def test_build_master_audio_без_seed_в_конфиге_берёт_дефолт(tmp_path):
    """Задача 16: ElevenLabs без seed на одном тексте разъезжается до 0.65с, а
    ключ кэша HeyGen — sha1 звука. Дефолт нужен, чтобы правка титров (тот же
    текст) не перезаказывала ведущую. Конфиг здесь вовсе не задаёт `tts.seed`
    — запрос провайдеру всё равно обязан нести DEFAULT_SEED из tts.py."""
    from reels_factory.tts import DEFAULT_SEED

    fixture = _fixture()
    response = fixture["response"]
    calls = []

    class Provider:
        def convert_with_timestamps(self, text, **kwargs):
            calls.append(kwargs)
            return TimestampedSpeech(
                audio=b"fake-mp3", alignment=response["alignment"],
                normalized_alignment=response["normalized_alignment"],
                request_id=response["request_id"],
            )

    def fake_run(cmd):
        Path(cmd[-1]).write_bytes(b"generated")

    config = {"language": "ru", "voice_id": "v1", "tts": {}}  # seed не задан
    build_master_audio(
        _scenario(), config, tmp_path, provider=Provider(),
        run_cmd=fake_run, duration_fn=lambda _: 1.3,
    )

    assert calls[0]["seed"] == DEFAULT_SEED


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
    assert master_audio_enabled({}) is True
    assert master_audio_enabled({"master_audio": {"enabled": True}}) is True
    monkeypatch.setenv("RF_MASTER_AUDIO_ENABLED", "0")
    assert master_audio_enabled({"master_audio": {"enabled": True}}) is False
    monkeypatch.setenv("RF_MASTER_AUDIO_ENABLED", "true")
    assert master_audio_enabled({}) is True


def test_мастер_звук_включён_по_умолчанию(monkeypatch):
    from reels_factory.master_audio import master_audio_enabled

    monkeypatch.delenv("RF_MASTER_AUDIO_ENABLED", raising=False)
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


def test_старое_approved_elevenlabs_аудио_без_точки_проходит_проверку_сегодняшним_кодом(
        tmp_path, monkeypatch):
    """Дефект B1: до 73870a9 build_canonical_script (без prefer_tts) никогда
    не добавляла точку в конец блока — approved elevenlabs-задачи,
    утверждённые тогда, хранят script.canonical.json/audio_manifest.json с
    этим текстом. load_approved_master_audio для source=elevenlabs_approved
    пересчитывает canonical с prefer_tts=True, а эта ветка теперь безусловно
    ставит точку — старый approval не должен из-за этого падать ValueError
    и требовать нового платного вызова ElevenLabs.

    `_ensure_sentence_end` патчим тождественной функцией только на время
    build_master_audio — так approval на диске получается ровно таким, каким
    его писал код ДО 73870a9, а не подделан руками мимо реального кода."""
    import reels_factory.master_audio as master_audio_module

    monkeypatch.setattr(master_audio_module, "_ensure_sentence_end", lambda t: t)

    scenario = {"blocks": [
        {"role": "hook", "speech": "Мы это сделали"},
        {"role": "cta", "speech": "Подпишись"},
    ]}
    config = {"language": "ru", "voice_id": "v1"}

    class Provider:
        def convert_with_timestamps(self, text, **kwargs):
            return TimestampedSpeech(
                audio=b"old-preview", alignment=_alignment(text),
                normalized_alignment=None, request_id="req",
            )

    def fake_run(cmd):
        Path(cmd[-1]).write_bytes(b"generated")

    artifact_dir = tmp_path / "audio" / "tts"
    build_master_audio(
        scenario, config, artifact_dir,
        provider=Provider(), run_cmd=fake_run, duration_fn=lambda _: 1.3,
    )
    approve_master_audio(tmp_path, artifact_dir, source="elevenlabs_approved")
    saved = json.loads(
        (artifact_dir / "script.canonical.json").read_text(encoding="utf-8")
    )
    assert saved["text"] == "Мы это сделали\nПодпишись"  # без точки — старый код

    # Возвращаем настоящий _ensure_sentence_end: дальше читаем сегодняшним
    # кодом, как при рендере после git pull на проде поверх старого approval.
    monkeypatch.undo()

    # load_approved_master_audio/load_master_audio не принимают provider —
    # структурно не могут заказать новую озвучку, только прочитать диск.
    loaded = load_approved_master_audio(scenario, config, tmp_path)
    assert loaded.mp3.read_bytes() == b"old-preview"
    assert loaded.manifest["provider"] == "elevenlabs"
    assert [w["text"] for w in loaded.words] == ["Мы", "это", "сделали", "Подпишись"]
    assert len(loaded.block_wavs) == 2


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


# ---------------------------------------------------------------------------
# Задача 14: слова титра — из утверждённого сценария, тайминг — из ASR/TTS.

from reels_factory.master_audio import _align_script_words, _assign_user_words_to_blocks


def test_случай_артёма_delete_и_equal_текст_сценария_время_asr():
    # Сценарий: «Нужен просто Клод код.» ASR услышала «код -код» вместо
    # «Клод код» — «-код» токенизируется в «код» (ведущий дефис не буква).
    canonical = build_canonical_script(
        {"blocks": [{"role": "hook",
                     "speech": "Нужен просто Клод код."}]},
        {"language": "ru"},
    )
    raw_words = [
        {"text": "Нужен", "start": 0.0, "end": 0.3},
        {"text": "просто", "start": 0.3, "end": 0.6},
        {"text": "код", "start": 0.6, "end": 0.8},
        {"text": "-код", "start": 0.85, "end": 1.1},
    ]
    words, match_ratio = _assign_user_words_to_blocks(raw_words, canonical)

    assert [w["text"] for w in words] == ["Нужен", "просто", "Клод", "код."]
    # equal: первые два слова получают тайминг ровно тех же слов ASR
    assert (words[0]["start"], words[0]["end"]) == (0.0, 0.3)
    assert (words[1]["start"], words[1]["end"]) == (0.3, 0.6)
    # delete: «Клод» не услышан — прижат к концу «просто», минимальная длительность
    assert words[2]["start"] == pytest.approx(0.6)
    assert 0.0 < words[2]["end"] - words[2]["start"] <= 0.02
    # equal: «код» сценария сопоставлен с ПЕРВЫМ услышанным «код» (0.6-0.8) —
    # SequenceMatcher матчит по самой ранней позиции; второе услышанное «код»
    # (0.85-1.1, из «-код») — insert, лишнее слово ASR, отброшено
    assert (words[3]["start"], words[3]["end"]) == (0.6, 0.8)
    assert all(w["block_id"] == canonical["blocks"][0]["id"] for w in words)
    assert 0.0 < match_ratio < 1.0


def test_align_script_words_replace_делит_интервал_поровну():
    canonical = build_canonical_script(
        {"blocks": [{"role": "hook", "speech": "Привет друзья"}]},
        {"language": "ru"},
    )
    spoken = [
        {"text": "хай", "start": 1.0, "end": 1.4},
        {"text": "чуваки", "start": 1.4, "end": 2.0},
    ]
    words, _ = _align_script_words(canonical, spoken)
    assert [w["text"] for w in words] == ["Привет", "друзья"]
    # replace: два слова сценария делят интервал [1.0, 2.0] поровну
    assert (words[0]["start"], words[0]["end"]) == pytest.approx((1.0, 1.5))
    assert (words[1]["start"], words[1]["end"]) == pytest.approx((1.5, 2.0))


def test_align_script_words_insert_лишнее_слово_asr_отброшено():
    canonical = build_canonical_script(
        {"blocks": [{"role": "hook", "speech": "Кофе бодрит"}]},
        {"language": "ru"},
    )
    spoken = [
        {"text": "ну", "start": 0.0, "end": 0.1},   # лишнее (insert), в текст не входит
        {"text": "кофе", "start": 0.1, "end": 0.4},
        {"text": "бодрит", "start": 0.4, "end": 0.9},
    ]
    words, _ = _align_script_words(canonical, spoken)
    assert [w["text"] for w in words] == ["Кофе", "бодрит"]
    assert (words[0]["start"], words[0]["end"]) == (0.1, 0.4)
    assert (words[1]["start"], words[1]["end"]) == (0.4, 0.9)


def test_align_script_words_без_гварда_расходится_и_не_падает():
    # speech_tts — намеренная фонетика поверх speech, не шум: без порогов
    # функция не должна падать даже на сильном расхождении.
    canonical = build_canonical_script(
        {"blocks": [{"role": "hook", "speech": "Мы внедрили Qaz AI Research"}]},
        {"language": "ru"},
    )
    spoken = [
        {"text": "мы", "start": 0.0, "end": 0.1},
        {"text": "внедрили", "start": 0.1, "end": 0.4},
        {"text": "казак", "start": 0.4, "end": 0.7},
        {"text": "эй", "start": 0.7, "end": 0.8},
        {"text": "ай", "start": 0.8, "end": 0.9},
        {"text": "рисёрч", "start": 0.9, "end": 1.2},
    ]
    words, match_ratio = _align_script_words(canonical, spoken)
    assert [w["text"] for w in words] == ["Мы", "внедрили", "Qaz", "AI", "Research"]
    assert match_ratio < 0.6  # сильно разошлось — и это ожидаемо, не повод падать


def test_user_voice_caption_words_идут_из_сценария_а_не_из_asr():
    # Интеграционно через build_user_master_audio: в титре остаётся слово
    # сценария («Кофе»/«вкусный.»), даже если ASR расслышала его иначе.
    source = Path("/dev/null")

    def fake_run(cmd):
        Path(cmd[-1]).write_bytes(b"pcm")

    def fake_transcribe(src, workdir, language):
        out = Path(workdir) / "words.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"words": [
            {"id": 0, "start": 0.1, "end": 0.4, "text": "Кофэ"},
            {"id": 1, "start": 0.4, "end": 0.8, "text": "вкусный"},
            {"id": 2, "start": 1.0, "end": 1.3, "text": "Кофе"},
            {"id": 3, "start": 1.3, "end": 1.8, "text": "бодрит"},
        ]}, ensure_ascii=False), encoding="utf-8")
        return {"out": str(out)}

    import tempfile
    src_file = Path(tempfile.mkstemp()[1])
    src_file.write_bytes(b"telegram-opus")
    built = build_user_master_audio(
        _scenario(), {"language": "ru"}, Path(tempfile.mkdtemp()) / "audio" / "user",
        src_file,
        transcribe_fn=fake_transcribe,
        run_cmd=fake_run,
        duration_fn=lambda _: 2.0,
    )
    # «Кофэ» (опечатка распознавания) не попадает в титр — там «Кофе» сценария
    assert [w["text"] for w in built.words] == ["Кофе", "вкусный.", "Кофе", "бодрит!"]


# ---------------------------------------------------------------------------
# Задача 15: у блока два текста — speech (показ/утверждение/титр) и
# speech_tts (произношение для ElevenLabs).

def test_canonical_script_prefer_tts_берёт_speech_tts_и_добавляет_точку():
    scenario = {"blocks": [
        {"role": "hook", "speech": "Мы внедрили Qaz AI",
         "speech_tts": "Мы внедрили Казак Эй Ай"},   # без точки на конце
        {"role": "cta", "speech": "Сохрани себе."},   # speech_tts нет вовсе
    ]}
    tts = build_canonical_script(scenario, {"language": "ru"}, prefer_tts=True)
    display = build_canonical_script(scenario, {"language": "ru"})

    assert tts["blocks"][0]["speech"] == "Мы внедрили Казак Эй Ай."  # точка добавлена
    assert tts["blocks"][1]["speech"] == "Сохрани себе."  # нет speech_tts — фолбэк на speech
    # display (то, что видит человек) не знает о speech_tts вовсе
    assert display["blocks"][0]["speech"] == "Мы внедрили Qaz AI"
    assert display["text"] != tts["text"]


def test_build_master_audio_озвучивает_speech_tts_а_слова_титра_из_speech(tmp_path):
    scenario = {"blocks": [
        {"role": "hook", "speech": "Мы внедрили Qaz AI",
         "speech_tts": "Мы внедрили Казак Эй Ай"},
    ]}
    calls = []

    class Provider:
        def convert_with_timestamps(self, text, **kwargs):
            calls.append(text)
            return TimestampedSpeech(audio=b"mp3", alignment=_alignment(text),
                                     normalized_alignment=None, request_id="req")

    def fake_run(cmd):
        Path(cmd[-1]).write_bytes(b"generated")

    result = build_master_audio(
        scenario, {"language": "ru", "voice_id": "v1"}, tmp_path,
        provider=Provider(), run_cmd=fake_run, duration_fn=lambda _: 5.0,
    )

    # в ElevenLabs ушла фонетика с точкой на конце, не то, что видит человек
    assert calls[0] == "Мы внедрили Казак Эй Ай."
    assert calls[0].endswith(".")
    # а в титре/утверждении остаются слова speech — «Qaz AI», не «Казак Эй Ай»
    assert [w["text"] for w in result.words[:2]] == ["Мы", "внедрили"]
    assert "Qaz" in [w["text"] for w in result.words]
    assert "AI" in [w["text"] for w in result.words]
    assert not any("Казак" in w["text"] for w in result.words)
    # identity/деньги считаются по тексту озвучки (speech_tts), не по показу
    assert result.canonical["text"] == "Мы внедрили Казак Эй Ай."


def test_build_master_audio_без_speech_tts_озвучивает_speech_как_раньше(tmp_path):
    fixture = _fixture()
    response = fixture["response"]

    class Provider:
        def convert_with_timestamps(self, text, **kwargs):
            return TimestampedSpeech(
                audio=b"fake-mp3", alignment=response["alignment"],
                normalized_alignment=response["normalized_alignment"],
                request_id=response["request_id"],
            )

    def fake_run(cmd):
        Path(cmd[-1]).write_bytes(b"generated")

    result = build_master_audio(
        _scenario(), {"language": "ru", "voice_id": "v1"}, tmp_path,
        provider=Provider(), run_cmd=fake_run, duration_fn=lambda _: 1.3,
    )
    assert [w["text"] for w in result.words] == [
        "Кофе", "вкусный.", "Кофе", "бодрит!",
    ]


def test_build_master_audio_v3_дефолтная_stability_дискретна(tmp_path):
    # kk-ролик идёт на eleven_v3; без явной stability в конфиге провайдер
    # должен получить v3-безопасное значение 0.5, а не production-дефолт v2 0.2.
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

    def fake_run(cmd):
        Path(cmd[-1]).write_bytes(b"generated")

    config = {
        "language": "kk",
        "voice_id": "kk-voice-id",
        "tts": {"model_id": "eleven_v3", "language_code": "kk"},
    }
    build_master_audio(
        _scenario(), config, tmp_path, provider=Provider(),
        run_cmd=fake_run, duration_fn=lambda _: 1.3,
    )
    assert calls[0][1]["model_id"] == "eleven_v3"
    assert calls[0][1]["stability"] == 0.5
