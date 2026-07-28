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
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from reels_factory.config import FFMPEG
from reels_factory.render import media_dur
from reels_factory.tts import (
    DEFAULT_OUTPUT_FORMAT,
    MODEL_ID,
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


def build_canonical_script(scenario: dict, config: dict) -> dict:
    blocks = scenario.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise ValueError("scenario.blocks должен быть непустым списком")

    pieces: list[str] = []
    canonical_blocks: list[dict] = []
    cursor = 0
    for index, block in enumerate(blocks):
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
    seed = tts.get("seed")
    return {
        "model_id": model_id,
        "stability": float(tts.get("stability", 0.5)),
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

    canonical = build_canonical_script(scenario, config)
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

    words = alignment_to_words(
        canonical["text"], result.alignment, canonical["blocks"]
    )
    ranges = _block_audio_ranges(canonical["blocks"], words, duration)
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
        "voice_id_sha256": _sha256_text(str(voice_id)),
        "input_sha256": canonical["text_sha256"],
        "input_characters": len(canonical["text"]),
        "duration_seconds": duration,
        "settings": {
            "stability": options["stability"],
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
