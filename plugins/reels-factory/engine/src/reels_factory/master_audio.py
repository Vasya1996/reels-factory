"""Одна master narration, alignment и детерминированная audio timeline job.

Модуль не знает о HeyGen/Revideo. Он:

1. строит canonical text и character ranges из утверждённого scenario;
2. делает ровно один ElevenLabs ``with-timestamps`` request;
3. валидирует original-text alignment и получает word timings;
4. конвертирует provider MP3 в канонический PCM WAV;
5. режет WAV на block inputs для переходного HeyGen-by-block пути;
6. сохраняет versioned job artifacts без секретов.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import unicodedata
from difflib import SequenceMatcher
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from reels_factory.config import FFMPEG
from reels_factory.render import media_dur
from reels_factory.tts import (
    DEFAULT_OUTPUT_FORMAT,
    DEFAULT_SEED,
    DEFAULT_SIMILARITY_BOOST,
    DEFAULT_SPEED,
    DEFAULT_STABILITY,
    DEFAULT_STABILITY_V3,
    DEFAULT_STYLE,
    DEFAULT_USE_SPEAKER_BOOST,
    MODEL_ID,
    V3_MODEL_ID,
    ElevenLabsClient,
)

FORMAT_VERSION = 1
_TAG_RE = re.compile(r"\[[^\]\n]*\]")
_TRUE = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class MasterAudioArtifacts:
    wav: Path
    mp3: Path
    block_wavs: tuple[Path, ...]
    words: tuple[dict, ...]
    timed_scenario: dict
    canonical: dict
    manifest: dict


def master_audio_enabled(config: dict) -> bool:
    """Feature flag: default=true — единая озвучка стала основным путём."""
    raw = os.environ.get("RF_MASTER_AUDIO_ENABLED")
    if raw is not None:
        return raw.strip().lower() in _TRUE
    return bool(((config or {}).get("master_audio") or {}).get("enabled", True))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _write_json(path: Path, value) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )


_SENTENCE_END = ".!?…"


def _ensure_sentence_end(text: str) -> str:
    """Гарантирует конец предложения перед отправкой блока в TTS.

    Без точки на конце блока ElevenLabs 31.08 обрывал интонацию блока
    посередине фразы вместо естественного спада — с точкой модель слышит
    конец мысли и доигрывает интонацию до конца. Каждый блок озвучивается
    как отдельная фраза (см. `build_canonical_script`), поэтому знак нужен
    на границе каждого, а не только в конце всего текста.
    """
    text = text.rstrip()
    if not text or text[-1] in _SENTENCE_END:
        return text
    return text + "."


def build_canonical_script(scenario: dict, config: dict, *,
                           prefer_tts: bool = False) -> dict:
    """Канонический текст блоков сценария — сумма плюс character ranges.

    `prefer_tts=True` — канонический текст ОЗВУЧКИ: для блока берётся
    `speech_tts` (фонетическая запись брендов/чисел для ElevenLabs), если он
    задан, иначе `speech`; конец каждого блока получает точку
    (`_ensure_sentence_end`). По умолчанию (`prefer_tts=False`) — канонический
    текст ПОКАЗА: всегда `speech`, тот же текст, что видит человек на экране
    утверждения и что попадает в титр. Два канонических текста для одного
    сценария — задача 15 (два текста у блока, ADR у Васи 2026-09):
    произношение бренда не должно менять то, что читает и утверждает
    человек.
    """
    blocks = scenario.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise ValueError("scenario.blocks должен быть непустым списком")

    pieces: list[str] = []
    canonical_blocks: list[dict] = []
    cursor = 0
    for index, block in enumerate(blocks):
        if prefer_tts:
            speech = str(block.get("speech_tts") or block.get("speech") or "").strip()
            speech = _ensure_sentence_end(speech)
        else:
            speech = str(block.get("speech") or "").strip()
        if not speech:
            raise ValueError(
                f"блок {index} ({block.get('role')}): пустой speech"
            )
        if pieces:
            pieces.append("\n")
            cursor += 1
        start = cursor
        pieces.append(speech)
        cursor += len(speech)
        canonical_blocks.append({
            "id": str(block.get("id") or f"block-{index}"),
            "index": index,
            "role": block.get("role"),
            "speech": speech,
            "character_start": start,
            "character_end": cursor,
        })

    text = "".join(pieces)
    tts_cfg = (config or {}).get("tts") or {}
    return {
        "format_version": FORMAT_VERSION,
        "language": str((config or {}).get("language") or "ru").lower(),
        "text": text,
        "text_sha256": _sha256_text(text),
        "pronunciation_hints": list(scenario.get("pronunciation_hints") or []),
        "pronunciation_dictionary_locators":
            list(tts_cfg.get("pronunciation_dictionary_locators") or []),
        "blocks": canonical_blocks,
    }


def validate_character_alignment(text: str, alignment: dict) -> tuple[list, list]:
    chars = alignment.get("characters")
    starts = alignment.get("character_start_times_seconds")
    ends = alignment.get("character_end_times_seconds")
    if not all(isinstance(v, list) for v in (chars, starts, ends)):
        raise ValueError("alignment должен содержать три списка character timings")
    if not (len(chars) == len(starts) == len(ends) == len(text)):
        raise ValueError(
            "alignment lengths не совпадают с длиной canonical text: "
            f"text={len(text)}, chars={len(chars)}, starts={len(starts)}, ends={len(ends)}"
        )
    if "".join(str(c) for c in chars) != text:
        raise ValueError(
            "ElevenLabs original alignment не совпадает с canonical text; "
            "normalized alignment нельзя тихо подставлять вместо утверждённого текста"
        )

    clean_starts, clean_ends = [], []
    previous_end = 0.0
    for index, (start, end) in enumerate(zip(starts, ends)):
        try:
            start, end = float(start), float(end)
        except (TypeError, ValueError) as e:
            raise ValueError(f"alignment[{index}] содержит нечисловой timing") from e
        if start < 0 or end < 0 or end < start:
            raise ValueError(f"alignment[{index}] содержит отрицательный/обратный timing")
        if start + 1e-6 < previous_end:
            raise ValueError(f"alignment[{index}] пересекается с предыдущим символом")
        clean_starts.append(start)
        clean_ends.append(end)
        previous_end = end
    return clean_starts, clean_ends


def _is_word_char(char: str) -> bool:
    return unicodedata.category(char)[0] in {"L", "N", "M"}


def _tag_mask(text: str) -> list[bool]:
    masked = [False] * len(text)
    for match in _TAG_RE.finditer(text):
        for index in range(match.start(), match.end()):
            masked[index] = True
    return masked


def _word_spans(text: str) -> list[tuple[int, int, int]]:
    """(core_start, core_end, display_end), Unicode + combining accents."""
    tags = _tag_mask(text)
    spans = []
    index = 0
    while index < len(text):
        if tags[index] or not _is_word_char(text[index]):
            index += 1
            continue
        start = index
        index += 1
        while index < len(text):
            if tags[index]:
                break
            if _is_word_char(text[index]):
                index += 1
                continue
            if (
                text[index] in {"'", "’", "-", "‑"}
                and index + 1 < len(text)
                and not tags[index + 1]
                and _is_word_char(text[index + 1])
            ):
                index += 1
                continue
            break
        core_end = index
        display_end = core_end
        while (
            display_end < len(text)
            and not tags[display_end]
            and text[display_end] in ".,!?…:;»”"
        ):
            display_end += 1
        spans.append((start, core_end, display_end))
        index = display_end
    return spans


def alignment_to_words(text: str, alignment: dict, canonical_blocks: list[dict]) -> list[dict]:
    starts, ends = validate_character_alignment(text, alignment)
    words = []
    for word_id, (start, core_end, display_end) in enumerate(_word_spans(text)):
        block = next(
            (
                b for b in canonical_blocks
                if b["character_start"] <= start < b["character_end"]
            ),
            None,
        )
        if block is None:
            raise ValueError(f"слово на character offset {start} не принадлежит блоку")
        words.append({
            "id": word_id,
            "block_id": block["id"],
            "block_index": block["index"],
            "role": block.get("role"),
            "character_start": start,
            "character_end": display_end,
            "start": starts[start],
            "end": ends[max(start, display_end - 1)],
            "text": text[start:display_end],
        })
    if not words:
        raise ValueError("alignment не содержит ни одного произносимого слова")
    return words


def _block_audio_ranges(
    canonical_blocks: list[dict], words: list[dict], duration: float
) -> list[dict]:
    spoken = []
    for block in canonical_blocks:
        own = [w for w in words if w["block_id"] == block["id"]]
        if not own:
            raise ValueError(f"alignment не содержит слов блока {block['id']}")
        spoken.append((float(own[0]["start"]), float(own[-1]["end"])))
    if duration + 0.02 < spoken[-1][1]:
        raise ValueError(
            "длительность voice_master.wav короче последнего alignment timing"
        )

    cuts = [0.0]
    for index in range(len(spoken) - 1):
        left_end, right_start = spoken[index][1], spoken[index + 1][0]
        if right_start + 1e-6 < left_end:
            raise ValueError("speech timings соседних блоков пересекаются")
        cuts.append((left_end + right_start) / 2.0)
    cuts.append(float(duration))

    ranges = []
    for index, block in enumerate(canonical_blocks):
        start, end = cuts[index], cuts[index + 1]
        if end <= start:
            raise ValueError(f"неположительная audio duration блока {block['id']}")
        ranges.append({
            "id": block["id"],
            "index": index,
            "role": block.get("role"),
            "start": start,
            "end": end,
            "duration": end - start,
            "speech_start": spoken[index][0],
            "speech_end": spoken[index][1],
        })
    return ranges


def _tts_options(config: dict) -> dict:
    tts = (config or {}).get("tts") or {}
    model_id = str(
        tts.get("model_id") or os.environ.get("ELEVENLABS_MODEL") or MODEL_ID
    )
    # Задача 16: без seed ElevenLabs на одном тексте разъезжается до 0.65с, и
    # ключ кэша HeyGen (sha1 звука) меняется от правки, которая ведущую не
    # трогает. Дефолт — только когда ключ вовсе отсутствует в конфиге; явный
    # `seed: null` по-прежнему выключает его для того, кто это сделал сознательно.
    seed = tts.get("seed", DEFAULT_SEED)
    # v3 принимает stability только дискретными значениями (0.0/0.5/1.0):
    # production-дефолт v2 (0.2) провайдер для v3 отклонит, поэтому берём
    # v3-безопасный дефолт, если явное значение в конфиге не задано.
    default_stability = (
        DEFAULT_STABILITY_V3 if model_id == V3_MODEL_ID else DEFAULT_STABILITY
    )
    return {
        "model_id": model_id,
        "speed": float(tts.get("speed", DEFAULT_SPEED)),
        "stability": float(tts.get("stability", default_stability)),
        "similarity_boost": float(
            tts.get("similarity_boost", DEFAULT_SIMILARITY_BOOST)
        ),
        "style": float(tts.get("style", DEFAULT_STYLE)),
        "use_speaker_boost": bool(
            tts.get("use_speaker_boost", DEFAULT_USE_SPEAKER_BOOST)
        ),
        "seed": None if seed in (None, "") else int(seed),
        "language_code": str(
            tts.get("language_code") or (config or {}).get("language") or "ru"
        ).lower(),
        "apply_text_normalization": str(
            tts.get("apply_text_normalization") or "auto"
        ).lower(),
        "pronunciation_dictionary_locators":
            list(tts.get("pronunciation_dictionary_locators") or []),
        "output_format": str(tts.get("output_format") or DEFAULT_OUTPUT_FORMAT),
    }


def _tts_cache_key(
    *,
    voice_id: str,
    input_sha256: str,
    options: dict,
) -> str:
    """Stable, secret-free identity of the paid TTS input."""
    identity = {
        "provider": "elevenlabs",
        "voice_id_sha256": _sha256_text(str(voice_id)),
        "input_sha256": input_sha256,
        "options": options,
    }
    packed = json.dumps(
        identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return _sha256_text(packed)


def build_master_audio(
    scenario: dict,
    config: dict,
    workdir,
    *,
    voice_id: str | None = None,
    provider: ElevenLabsClient | None = None,
    run_cmd: Callable | None = None,
    duration_fn: Callable[[str], float] | None = None,
    meter: Callable[[int], None] | None = None,
) -> MasterAudioArtifacts:
    wd = Path(workdir)
    wd.mkdir(parents=True, exist_ok=True)
    voice_id = voice_id or (config or {}).get("voice_id")
    if not voice_id:
        raise ValueError("voice_id не задан для master audio")
    provider = provider or ElevenLabsClient()
    if run_cmd is None:
        from reels_factory import render
        run_cmd = render.run
    duration_fn = duration_fn or media_dur

    # canonical — то, что реально уходит в ElevenLabs (speech_tts или speech,
    # с точкой на конце блока) и потому единственный источник identity/денег
    # (text_sha256, cache_key, script.canonical.json). caption_canonical —
    # то, что видел и утвердил человек (всегда speech); слова для титра
    # получают текст отсюда, тайминги — из ответа ElevenLabs на canonical.
    canonical = build_canonical_script(scenario, config, prefer_tts=True)
    caption_canonical = build_canonical_script(scenario, config)
    _write_json(wd / "script.canonical.json", canonical)
    options = _tts_options(config)
    result = provider.convert_with_timestamps(
        canonical["text"], voice_id=voice_id, **options
    )
    # Считаем ровно то, за что берёт деньги ElevenLabs — символы единственного
    # запроса. После convert_with_timestamps (внутри уже raise_for_status):
    # за упавший запрос платить не за что.
    if meter is not None:
        try:
            meter(len(canonical["text"]))
        except Exception as exc:
            # Запрос ElevenLabs уже оплачен и результат уже получен — сбой
            # самого метра (contention с ботом за sqlite-ledger и т.п.) не
            # должен восприниматься как повод считать этот шаг неудачным.
            print(
                f"[billing] master_audio: meter упал, ElevenLabs-запрос "
                f"оплачен, но не тарифицирован: {exc}",
                file=sys.stderr,
            )

    mp3 = wd / "voice_master.mp3"
    wav = wd / "voice_master.wav"
    mp3.write_bytes(result.audio)
    run_cmd([
        str(FFMPEG), "-y", "-i", str(mp3),
        "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(wav),
    ])
    duration = float(duration_fn(str(wav)))
    if duration <= 0:
        raise ValueError("voice_master.wav имеет неположительную длительность")

    tts_words = alignment_to_words(
        canonical["text"], result.alignment, canonical["blocks"]
    )
    # Слова для титра/утверждения — из caption_canonical (speech), тайминги —
    # от ElevenLabs (tts_words, char-perfect). Без гварда: расхождение между
    # speech и speech_tts — намеренная фонетическая правка, не шум.
    words, _match_ratio = _align_script_words(caption_canonical, tts_words)
    ranges = _block_audio_ranges(caption_canonical["blocks"], words, duration)
    timed_scenario = json.loads(json.dumps(scenario, ensure_ascii=False))
    for block, timing in zip(timed_scenario["blocks"], ranges):
        block["start"] = timing["start"]
        block["end"] = timing["end"]
        block["audio_start"] = timing["start"]
        block["audio_end"] = timing["end"]
        block["speech_start"] = timing["speech_start"]
        block["speech_end"] = timing["speech_end"]
    timed_scenario["total"] = duration

    block_wavs = []
    for timing in ranges:
        out = wd / f"voice_{timing['index']}.wav"
        run_cmd([
            str(FFMPEG), "-y",
            "-ss", f"{timing['start']:.6f}",
            "-t", f"{timing['duration']:.6f}",
            "-i", str(wav),
            "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(out),
        ])
        block_wavs.append(out)

    characters_doc = {
        "format_version": FORMAT_VERSION,
        "text_sha256": canonical["text_sha256"],
        "alignment": result.alignment,
        "normalized_alignment": result.normalized_alignment,
    }
    words_doc = {
        "format_version": FORMAT_VERSION,
        "text_sha256": canonical["text_sha256"],
        "words": words,
        "blocks": ranges,
    }
    _write_json(wd / "alignment.characters.json", characters_doc)
    _write_json(wd / "alignment.words.json", words_doc)

    manifest = {
        "format_version": FORMAT_VERSION,
        "provider": "elevenlabs",
        "model_id": options["model_id"],
        "cache_key": _tts_cache_key(
            voice_id=str(voice_id),
            input_sha256=canonical["text_sha256"],
            options=options,
        ),
        "voice_id_sha256": _sha256_text(str(voice_id)),
        "input_sha256": canonical["text_sha256"],
        "input_characters": len(canonical["text"]),
        "duration_seconds": duration,
        "settings": {
            "speed": options["speed"],
            "stability": options["stability"],
            "similarity_boost": options["similarity_boost"],
            "style": options["style"],
            "use_speaker_boost": options["use_speaker_boost"],
            "seed": options["seed"],
            "language_code": options["language_code"],
            "apply_text_normalization": options["apply_text_normalization"],
            "pronunciation_dictionary_locators":
                options["pronunciation_dictionary_locators"],
            "output_format": options["output_format"],
        },
        "provider_request": {
            "request_id": result.request_id,
            "endpoint": "/v1/text-to-speech/{voice_id}/with-timestamps",
        },
        "files": {
            "provider_audio": {
                "path": mp3.name,
                "sha256": _sha256_bytes(result.audio),
            },
            "canonical_audio": {"path": wav.name},
            "characters_alignment": {"path": "alignment.characters.json"},
            "words_alignment": {"path": "alignment.words.json"},
            "block_audio": [
                {"path": path.name, "sha256": _sha256_bytes(path.read_bytes())}
                for path in block_wavs
            ],
        },
    }
    manifest["files"]["canonical_audio"]["sha256"] = _sha256_bytes(wav.read_bytes())
    _write_json(wd / "audio_manifest.json", manifest)

    return MasterAudioArtifacts(
        wav=wav,
        mp3=mp3,
        block_wavs=tuple(block_wavs),
        words=tuple(words),
        timed_scenario=timed_scenario,
        canonical=canonical,
        manifest=manifest,
    )


def _timed_scenario_from_ranges(scenario: dict, ranges: list[dict], duration: float) -> dict:
    if len(ranges) != len(scenario.get("blocks") or []):
        raise ValueError("audio ranges не совпадают с блоками scenario")
    timed = json.loads(json.dumps(scenario, ensure_ascii=False))
    for block, timing in zip(timed["blocks"], ranges):
        block["start"] = float(timing["start"])
        block["end"] = float(timing["end"])
        block["audio_start"] = float(timing["start"])
        block["audio_end"] = float(timing["end"])
        block["speech_start"] = float(timing["speech_start"])
        block["speech_end"] = float(timing["speech_end"])
    timed["total"] = float(duration)
    return timed


def _verify_file(path: Path, expected_sha256: str | None = None) -> Path:
    if not path.is_file():
        raise ValueError(f"audio artifact не найден: {path.name}")
    if expected_sha256 and _sha256_bytes(path.read_bytes()) != expected_sha256:
        raise ValueError(f"audio artifact изменился после утверждения: {path.name}")
    return path


def _canonical_compare_text(canonical: dict) -> str:
    """Текст canonical для сверки «сценарий не поменялся с утверждения» —
    устойчив к тому, что версия кода, которая писала этот canonical, могла
    ставить (или не ставить) точку на конце блока.

    Дефект B1 (задача 15 после ревью): `_ensure_sentence_end` начала
    безусловно добавлять точку в конец каждого блока TTS-текста. Аудио,
    утверждённое ДО этой правки, хранит `script.canonical.json` без точки —
    хотя произнесённый текст блока не менялся ни на символ. Сверять
    text_sha256 «в лоб» с сегодняшним canonical для такого approval значит
    сравнивать текст с точкой и без и получать ложное расхождение. Здесь обе
    стороны сравнения проходят через один и тот же (сегодняшний, идемпотентный
    — добавляет точку только если её ещё нет) `_ensure_sentence_end`, поэтому
    расхождение только в точке схлопывается, а реальная правка слов в блоке
    по-прежнему ловится."""
    blocks = canonical.get("blocks") or []
    return "\n".join(
        _ensure_sentence_end(str(block.get("speech") or "")) for block in blocks
    )


def load_master_audio(
    scenario: dict,
    config: dict,
    artifact_dir,
    *,
    prefer_tts: bool = False,
) -> MasterAudioArtifacts:
    """Загрузить готовые master artifacts и проверить их immutable contract.

    `prefer_tts` должен совпадать с тем, каким canonical эти artifacts
    записаны: `audio/tts` (ElevenLabs, `build_master_audio`) — True, `audio/
    user` (голосовое Telegram, `build_user_master_audio`) — False. Иначе
    text_sha256 никогда не совпадёт: у одного canonical — speech_tts или
    speech, у другого — всегда speech.

    Два разных сравнения текста здесь неспроста разные величины. «Сценарий не
    поменялся с утверждения» сравнивается через `_canonical_compare_text` —
    пересобранный СЕГОДНЯ canonical против сохранённого, но нормализованные
    одинаково (см. её докстринг, дефект B1). А вот manifest/words_doc должны
    совпадать именно с СОХРАНЁННЫМ `saved_canonical["text_sha256"]`: их писал
    один и тот же вызов `build_master_audio`, что и `script.canonical.json`,
    какой бы код тогда ни считал точки — это внутренняя согласованность трёх
    файлов одного approval, а не вопрос «изменился ли сценарий», и её не
    должна поколебать более поздняя правка правил канонизации."""
    wd = Path(artifact_dir)
    canonical = build_canonical_script(scenario, config, prefer_tts=prefer_tts)
    saved_canonical = json.loads(
        (wd / "script.canonical.json").read_text(encoding="utf-8")
    )
    if _canonical_compare_text(saved_canonical) != _canonical_compare_text(canonical):
        raise ValueError("утверждённое аудио создано для другого сценария")

    manifest = json.loads((wd / "audio_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("input_sha256") != saved_canonical.get("text_sha256"):
        raise ValueError("audio manifest не совпадает с утверждённым сценарием")
    files = manifest.get("files") or {}
    canonical_file = files.get("canonical_audio") or {}
    source_file = files.get("provider_audio") or files.get("source_audio") or {}
    wav = _verify_file(
        wd / str(canonical_file.get("path") or "voice_master.wav"),
        canonical_file.get("sha256"),
    )
    source = _verify_file(
        wd / str(source_file.get("path") or "voice_master.mp3"),
        source_file.get("sha256"),
    )

    words_doc = json.loads(
        (wd / str((files.get("words_alignment") or {}).get("path")
                  or "alignment.words.json")).read_text(encoding="utf-8")
    )
    if words_doc.get("text_sha256") != saved_canonical.get("text_sha256"):
        raise ValueError("word alignment не совпадает с утверждённым сценарием")
    words = list(words_doc.get("words") or [])
    ranges = list(words_doc.get("blocks") or [])
    if not words or not ranges:
        raise ValueError("утверждённое аудио не содержит word/block timings")
    duration = float(manifest.get("duration_seconds") or media_dur(str(wav)))
    timed = _timed_scenario_from_ranges(scenario, ranges, duration)
    block_docs = list(files.get("block_audio") or [])
    if block_docs and len(block_docs) != len(ranges):
        raise ValueError("audio manifest содержит неверное число block slices")
    block_wavs = tuple(
        _verify_file(
            wd / str(
                (block_docs[index] if block_docs else {}).get("path")
                or f"voice_{index}.wav"
            ),
            (block_docs[index] if block_docs else {}).get("sha256"),
        )
        for index in range(len(ranges))
    )
    return MasterAudioArtifacts(
        wav=wav,
        mp3=source,
        block_wavs=block_wavs,
        words=tuple(words),
        timed_scenario=timed,
        canonical=saved_canonical,
        manifest=manifest,
    )


def approve_master_audio(job_workdir, artifact_dir, *, source: str) -> dict:
    """Зафиксировать выбранную дорожку с hash, который проверит render stage."""
    job_wd = Path(job_workdir).resolve()
    artifacts = Path(artifact_dir).resolve()
    try:
        relative = artifacts.relative_to(job_wd)
    except ValueError as exc:
        raise ValueError("audio artifacts должны находиться внутри job workdir") from exc
    manifest_path = artifacts / "audio_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    canonical_file = (manifest.get("files") or {}).get("canonical_audio") or {}
    wav = _verify_file(
        artifacts / str(canonical_file.get("path") or "voice_master.wav"),
        canonical_file.get("sha256"),
    )
    approval = {
        "format_version": FORMAT_VERSION,
        "source": str(source),
        "artifact_dir": relative.as_posix(),
        "input_sha256": manifest.get("input_sha256"),
        "canonical_audio_sha256": _sha256_bytes(wav.read_bytes()),
    }
    _write_json(job_wd / "audio.approved.json", approval)
    return approval


def load_approved_master_audio(
    scenario: dict,
    config: dict,
    job_workdir,
) -> MasterAudioArtifacts:
    job_wd = Path(job_workdir).resolve()
    approval = json.loads(
        (job_wd / "audio.approved.json").read_text(encoding="utf-8")
    )
    artifact_dir = (job_wd / str(approval.get("artifact_dir") or "")).resolve()
    try:
        artifact_dir.relative_to(job_wd)
    except ValueError as exc:
        raise ValueError("audio approval ссылается за пределы job workdir") from exc
    # source различает canonical: только ElevenLabs-путь мог использовать
    # speech_tts (approve_master_audio(source=...) в bot.py:
    # "elevenlabs_approved" | "telegram_user_audio").
    prefer_tts = approval.get("source") == "elevenlabs_approved"
    artifacts = load_master_audio(scenario, config, artifact_dir, prefer_tts=prefer_tts)
    if approval.get("input_sha256") != artifacts.canonical["text_sha256"]:
        raise ValueError("audio approval создан для другого сценария")
    actual = _sha256_bytes(artifacts.wav.read_bytes())
    if approval.get("canonical_audio_sha256") != actual:
        raise ValueError("утверждённая аудиодорожка изменилась перед рендером")
    return artifacts


def _normalized_tokens(text: str) -> list[str]:
    return [
        text[start:end].casefold()
        for start, end, _display_end in _word_spans(str(text or ""))
    ]


def _script_words(canonical: dict) -> list[dict]:
    """Слова УТВЕРЖДЁННОГО текста canonical["text"] со своим блоком.

    Тот же `_word_spans`, что режет ElevenLabs alignment на слова
    (`alignment_to_words`) — один способ узнать, где в тексте слово, для
    любого источника таймингов."""
    text = canonical["text"]
    words = []
    for start, core_end, display_end in _word_spans(text):
        block = next(
            (
                b for b in canonical["blocks"]
                if b["character_start"] <= start < b["character_end"]
            ),
            None,
        )
        if block is None:
            raise ValueError(f"слово на character offset {start} не принадлежит блоку")
        words.append({
            "block_id": block["id"],
            "block_index": block["index"],
            "role": block.get("role"),
            "token": text[start:core_end].casefold(),
            "text": text[start:display_end],
        })
    return words


# Тайминг слова сценария, которого нет в услышанной речи (opcode "delete") —
# не ноль (соседние слова не должны схлопнуться в одну отметку времени), но
# и не заметная зрителю длительность.
_MIN_WORD_DURATION = 0.01


def _align_script_words(
    canonical: dict,
    spoken_words: list[dict],
    *,
    min_match_ratio: float | None = None,
    word_ratio_bounds: tuple[float, float] | None = None,
) -> tuple[list[dict], float]:
    """Слова УТВЕРЖДЁННОГО текста (canonical["text"]) + тайминги слов, которые
    услышали/выровняли (`spoken_words`, каждое — {"text","start","end"}).

    Титр показывает то, что утверждено, а не то, что распознала машина —
    случай Артёма: сценарий «нужен просто Клод код», ASR услышала «код -код»
    (0.52 порог ниже это ещё пропускает), и в титре должно остаться «Клод
    код» с временем ASR, а не «код -код» с экрана. Разбор по словам —
    `SequenceMatcher.get_opcodes()` на нормализованных токенах:
    - equal — слово сценария забирает тайминг ровно того же слова речи;
    - replace — слова сценария внутри разошедшегося куска делят между собой
      интервал [начало первого услышанного слова куска, конец последнего]
      поровну;
    - insert (лишнее услышанное слово) — отбрасывается, в титр не идёт;
    - delete (слово сценария, которого не услышали) — тайминга не получает
      сразу и во втором проходе прижимается к ближайшему уже расставленному
      соседу с длительностью `_MIN_WORD_DURATION`.

    `min_match_ratio`/`word_ratio_bounds` — тот же гвард, что раньше проверял
    только общее сходство (SequenceMatcher.ratio()) голосового с утверждённым
    сценарием: он остаётся для пути «голосовое пользователя», где расхождение
    — это шум записи и повод отклонить её. Для пути «синтез ElevenLabs» текст
    озвучки (`speech_tts`) — намеренная фонетическая запись поверх `speech`
    (не шум), поэтому там оба параметра остаются None и гварда нет.
    """
    script_words = _script_words(canonical)
    script_tokens = [w["token"] for w in script_words]

    clean_spoken = []
    for word in spoken_words:
        text = str(word.get("text") or "").strip()
        if not text:
            continue
        try:
            start, end = float(word["start"]), float(word["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if start < 0 or end <= start:
            continue
        clean_spoken.append({"text": text, "start": start, "end": end})

    spoken_tokens_meta = [
        {"token": token, "start": word["start"], "end": word["end"]}
        for word in clean_spoken
        for token in _normalized_tokens(word["text"])
    ]
    spoken_tokens = [meta["token"] for meta in spoken_tokens_meta]

    if not script_tokens or not spoken_tokens:
        raise ValueError("не удалось сопоставить слова сценария с озвучкой")

    matcher = SequenceMatcher(None, script_tokens, spoken_tokens, autojunk=False)
    match_ratio = matcher.ratio()
    word_ratio = len(spoken_tokens) / len(script_tokens)
    if min_match_ratio is not None and match_ratio < min_match_ratio:
        raise ValueError(
            "голосовое заметно отличается от утверждённого сценария или "
            "записано не целиком"
        )
    if word_ratio_bounds is not None and not (
        word_ratio_bounds[0] <= word_ratio <= word_ratio_bounds[1]
    ):
        raise ValueError(
            "голосовое заметно отличается от утверждённого сценария или "
            "записано не целиком"
        )

    timings: list[tuple[float, float] | None] = [None] * len(script_tokens)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                meta = spoken_tokens_meta[j1 + offset]
                timings[i1 + offset] = (meta["start"], meta["end"])
        elif tag == "replace":
            span_start = spoken_tokens_meta[j1]["start"]
            span_end = spoken_tokens_meta[j2 - 1]["end"]
            count = i2 - i1
            if span_end <= span_start:
                span_end = span_start + count * _MIN_WORD_DURATION
            step = (span_end - span_start) / count
            for offset in range(count):
                timings[i1 + offset] = (
                    span_start + offset * step,
                    span_start + (offset + 1) * step,
                )
        # insert: лишнее услышанное слово — script_tokens его не касается.
        # delete: заполняется вторым проходом ниже, от соседей.

    for index in range(len(timings)):
        if timings[index] is not None:
            continue
        before = next(
            (timings[i][1] for i in range(index - 1, -1, -1) if timings[i]),
            None,
        )
        if before is not None:
            timings[index] = (before, before + _MIN_WORD_DURATION)
            continue
        after = next(
            (timings[i][0] for i in range(index + 1, len(timings)) if timings[i]),
            None,
        )
        anchor = after if after is not None else 0.0
        timings[index] = (max(0.0, anchor - _MIN_WORD_DURATION), anchor)

    words = []
    for index, script_word in enumerate(script_words):
        start, end = timings[index]
        words.append({
            "id": index,
            "block_id": script_word["block_id"],
            "block_index": script_word["block_index"],
            "role": script_word["role"],
            "character_start": None,
            "character_end": None,
            "start": start,
            "end": end,
            "text": script_word["text"],
        })
    return words, match_ratio


def _assign_user_words_to_blocks(
    raw_words: list[dict],
    canonical: dict,
) -> tuple[list[dict], float]:
    """Голосовое пользователя -> слова УТВЕРЖДЁННОГО сценария с таймингом ASR.

    Тонкая обёртка над `_align_script_words` с прежним порогом похожести:
    расхождение здесь — шум записи (не читал, сбился, записал не то), а не
    намеренная правка текста, поэтому гвард остаётся включённым."""
    return _align_script_words(
        canonical, raw_words,
        min_match_ratio=0.52, word_ratio_bounds=(0.60, 1.55),
    )


def build_user_master_audio(
    scenario: dict,
    config: dict,
    artifact_dir,
    source_audio,
    *,
    transcribe_fn=None,
    run_cmd: Callable | None = None,
    duration_fn: Callable[[str], float] | None = None,
) -> MasterAudioArtifacts:
    """Telegram voice -> exact final master без TTS, чистки, склеек и дозаписей."""
    wd = Path(artifact_dir)
    wd.mkdir(parents=True, exist_ok=True)
    source_audio = Path(source_audio)
    if not source_audio.is_file():
        raise ValueError("голосовое не найдено")
    if run_cmd is None:
        from reels_factory import render
        run_cmd = render.run
    if transcribe_fn is None:
        from reels_factory.transcribe import transcribe_file
        transcribe_fn = transcribe_file
    duration_fn = duration_fn or media_dur

    suffix = source_audio.suffix.lower() or ".ogg"
    frozen_source = wd / f"user_voice_source{suffix}"
    shutil.copyfile(source_audio, frozen_source)
    wav = wd / "voice_master.wav"
    run_cmd([
        str(FFMPEG), "-y", "-i", str(frozen_source),
        "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(wav),
    ])
    duration = float(duration_fn(str(wav)))
    if duration <= 0:
        raise ValueError("голосовое имеет неположительную длительность")

    canonical = build_canonical_script(scenario, config)
    _write_json(wd / "script.canonical.json", canonical)
    source_sha256 = _sha256_bytes(frozen_source.read_bytes())
    # faster-whisper кеширует extracted audio16k.wav в workdir. Новый voice
    # обязан получить новый каталог, иначе повтор после неудачной записи
    # незаметно расшифрует старый файл.
    transcript_dir = wd / f"transcription-{source_sha256[:12]}"
    meta = transcribe_fn(
        str(wav),
        str(transcript_dir),
        language=canonical["language"],
    )
    raw_doc = json.loads(Path(meta["out"]).read_text(encoding="utf-8"))
    words, match_ratio = _assign_user_words_to_blocks(
        list(raw_doc.get("words") or []), canonical
    )
    ranges = _block_audio_ranges(canonical["blocks"], words, duration)
    timed = _timed_scenario_from_ranges(scenario, ranges, duration)

    block_wavs = []
    for timing in ranges:
        out = wd / f"voice_{timing['index']}.wav"
        run_cmd([
            str(FFMPEG), "-y",
            "-ss", f"{timing['start']:.6f}",
            "-t", f"{timing['duration']:.6f}",
            "-i", str(wav),
            "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(out),
        ])
        block_wavs.append(out)

    words_doc = {
        "format_version": FORMAT_VERSION,
        "text_sha256": canonical["text_sha256"],
        "words": words,
        "blocks": ranges,
        "transcript_match_ratio": round(match_ratio, 4),
    }
    _write_json(wd / "alignment.words.json", words_doc)
    manifest = {
        "format_version": FORMAT_VERSION,
        "provider": "telegram_user_audio",
        "input_sha256": canonical["text_sha256"],
        "input_characters": len(canonical["text"]),
        "duration_seconds": duration,
        "transcript_match_ratio": round(match_ratio, 4),
        "processing": {
            "content_edits": False,
            "denoise": False,
            "generated_audio": False,
            "canonical_pcm": "48000Hz stereo pcm_s16le",
        },
        "files": {
            "source_audio": {
                "path": frozen_source.name,
                "sha256": source_sha256,
            },
            "canonical_audio": {
                "path": wav.name,
                "sha256": _sha256_bytes(wav.read_bytes()),
            },
            "words_alignment": {"path": "alignment.words.json"},
            "block_audio": [
                {"path": path.name, "sha256": _sha256_bytes(path.read_bytes())}
                for path in block_wavs
            ],
        },
    }
    _write_json(wd / "audio_manifest.json", manifest)
    return MasterAudioArtifacts(
        wav=wav,
        mp3=frozen_source,
        block_wavs=tuple(block_wavs),
        words=tuple(words),
        timed_scenario=timed,
        canonical=canonical,
        manifest=manifest,
    )
