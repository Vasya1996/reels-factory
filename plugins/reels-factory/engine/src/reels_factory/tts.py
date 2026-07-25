"""Provider-клиент ElevenLabs и legacy-обёртка синтеза.

Новый master-audio путь вызывает ``ElevenLabsClient.convert_with_timestamps``:
один утверждённый сценарий -> один MP3 и character alignment. Оркестрация,
нормализация alignment и job-артефакты находятся в ``master_audio.py``.

Модель по умолчанию — ``eleven_v3``. Для неё намеренно передаётся только
поддерживаемый voice setting ``stability``. Speed, similarity и speaker boost
в Eleven v3 недоступны; темп и эмоция управляются текстом, пунктуацией и
audio tags.

``synth_voice`` сохранён для feature-flag rollback старого block-by-block пути.
Ключ берётся только из ``ELEVENLABS_API_KEY`` и никогда не пишется в manifest.
"""
from __future__ import annotations

import base64
import binascii
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reels_factory.config import FFMPEG

TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
TTS_TIMESTAMPS_URL = TTS_URL + "/with-timestamps"
VOICES_ADD_URL = "https://api.elevenlabs.io/v1/voices/add"
VOICES_URL = "https://api.elevenlabs.io/v1/voices/{voice_id}"
MODEL_ID = "eleven_v3"
V3_MAX_CHARACTERS = 5000
DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"


@dataclass(frozen=True)
class TimestampedSpeech:
    audio: bytes
    alignment: dict
    normalized_alignment: dict | None
    request_id: str | None


def _api_key() -> str:
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ElevenLabs API key не задан: установите env ELEVENLABS_API_KEY"
        )
    return api_key


def _validate_request(text: str, model_id: str, stability: float | None,
                      seed: int | None, normalization: str,
                      dictionaries: list[dict]) -> None:
    if not str(text or "").strip():
        raise ValueError("ElevenLabs: text не может быть пустым")
    if model_id == "eleven_v3" and len(text) > V3_MAX_CHARACTERS:
        raise ValueError(
            f"Eleven v3 принимает не более {V3_MAX_CHARACTERS} символов за запрос; "
            f"получено {len(text)}. Master audio не разбит: request stitching "
            "для eleven_v3 не поддерживается."
        )
    if stability is not None and not 0.0 <= float(stability) <= 1.0:
        raise ValueError("ElevenLabs stability должна быть в диапазоне 0..1")
    if seed is not None and not 0 <= int(seed) <= 4_294_967_295:
        raise ValueError("ElevenLabs seed должна быть в диапазоне 0..4294967295")
    if normalization not in {"auto", "on", "off"}:
        raise ValueError("apply_text_normalization: допустимы auto, on или off")
    if len(dictionaries) > 3:
        raise ValueError("ElevenLabs принимает не более 3 pronunciation dictionaries")
    for locator in dictionaries:
        if not isinstance(locator, dict):
            raise ValueError("pronunciation dictionary locator должен быть объектом")
        dictionary_id = locator.get("pronunciation_dictionary_id") or locator.get("id")
        if not dictionary_id or not locator.get("version_id"):
            raise ValueError(
                "pronunciation dictionary требует pronunciation_dictionary_id "
                "(или id) и version_id"
            )


class ElevenLabsClient:
    """Минимальный HTTP provider client с DI для полностью сетевых-free тестов."""

    def __init__(self, *, api_key: str | None = None, http=None):
        self.api_key = api_key or _api_key()
        if http is None:
            import requests
            http = requests
        self.http = http

    def convert_with_timestamps(
        self,
        text: str,
        *,
        voice_id: str,
        model_id: str = MODEL_ID,
        stability: float | None = 0.5,
        seed: int | None = None,
        language_code: str | None = None,
        apply_text_normalization: str = "auto",
        pronunciation_dictionary_locators: list[dict] | None = None,
        output_format: str = DEFAULT_OUTPUT_FORMAT,
    ) -> TimestampedSpeech:
        dictionaries = list(pronunciation_dictionary_locators or [])
        _validate_request(
            text, model_id, stability, seed, apply_text_normalization, dictionaries
        )
        if not voice_id:
            raise ValueError("ElevenLabs voice_id не задан")
        if not output_format.startswith("mp3_"):
            raise ValueError(
                "Master audio сохраняет provider output как MP3; "
                "output_format должен начинаться с mp3_"
            )

        body: dict[str, Any] = {
            "text": text,
            "model_id": model_id,
            "apply_text_normalization": apply_text_normalization,
        }
        if language_code:
            body["language_code"] = language_code
        if stability is not None:
            # Для v3 speed/similarity/style/speaker boost не добавляем:
            # эти настройки либо недоступны, либо ухудшают стабильность.
            body["voice_settings"] = {"stability": float(stability)}
        if seed is not None:
            body["seed"] = int(seed)
        if dictionaries:
            body["pronunciation_dictionary_locators"] = [
                {
                    "pronunciation_dictionary_id":
                        d.get("pronunciation_dictionary_id") or d.get("id"),
                    "version_id": d["version_id"],
                }
                for d in dictionaries
            ]

        resp = self.http.post(
            TTS_TIMESTAMPS_URL.format(voice_id=voice_id),
            params={"output_format": output_format},
            json=body,
            headers={"xi-api-key": self.api_key, "Content-Type": "application/json"},
            timeout=120,
        )
        resp.raise_for_status()
        payload = resp.json()
        try:
            audio = base64.b64decode(payload["audio_base64"], validate=True)
        except (KeyError, TypeError, ValueError, binascii.Error) as e:
            raise RuntimeError("ElevenLabs не вернул корректный audio_base64") from e
        alignment = payload.get("alignment")
        if not isinstance(alignment, dict):
            raise RuntimeError("ElevenLabs не вернул character alignment")
        headers = getattr(resp, "headers", {}) or {}
        request_id = (
            headers.get("request-id")
            or headers.get("request_id")
            or payload.get("request_id")
        )
        return TimestampedSpeech(
            audio=audio,
            alignment=alignment,
            normalized_alignment=payload.get("normalized_alignment"),
            request_id=request_id,
        )


def synth_voice(text: str, out_wav: Path, voice_id: str | None = None,
                model_id: str | None = None, stability: float | None = None,
                http=None, run_cmd=None) -> Path:
    voice_id = voice_id or os.environ.get("ELEVENLABS_VOICE_ID")
    if not voice_id:
        raise RuntimeError(
            "voice_id не задан: передайте voice_id или установите env ELEVENLABS_VOICE_ID"
        )
    api_key = _api_key()

    model_id = model_id or os.environ.get("ELEVENLABS_MODEL") or MODEL_ID
    if stability is None and model_id == "eleven_v3":
        stability = float(os.environ.get("ELEVENLABS_STABILITY") or 0.5)
    if stability is not None and not 0.0 <= float(stability) <= 1.0:
        raise ValueError("ElevenLabs stability должна быть в диапазоне 0..1")

    if http is None:
        import requests
        http = requests
    if run_cmd is None:
        from reels_factory import render
        run_cmd = render.run

    out_wav = Path(out_wav)
    mp3_tmp = out_wav.with_suffix(".mp3")

    body: dict[str, Any] = {"text": text, "model_id": model_id}
    if stability is not None:
        body["voice_settings"] = {"stability": float(stability)}

    resp = http.post(
        TTS_URL.format(voice_id=voice_id),
        json=body,
        headers={"xi-api-key": api_key, "Content-Type": "application/json"},
        timeout=60,
    )
    resp.raise_for_status()
    mp3_tmp.write_bytes(resp.content)

    run_cmd([str(FFMPEG), "-y", "-i", str(mp3_tmp), "-ar", "48000", "-ac", "2", str(out_wav)])

    mp3_tmp.unlink(missing_ok=True)
    return out_wav


def create_voice_clone(audio_path, name: str, http=None) -> str:
    """Мгновенный клон голоса (IVC): запись 1–2 мин чистой речи -> voice_id.

    Требует тариф ElevenLabs с клонированием (Starter+). Ключ — env
    ELEVENLABS_API_KEY.
    """
    api_key = _api_key()
    if http is None:
        import requests
        http = requests
    audio_path = Path(audio_path)
    with open(audio_path, "rb") as f:
        resp = http.post(
            VOICES_ADD_URL,
            data={"name": name},
            files={"files": (audio_path.name, f)},
            headers={"xi-api-key": api_key},
            timeout=120,
        )
    resp.raise_for_status()
    voice_id = resp.json().get("voice_id")
    if not voice_id:
        raise RuntimeError(f"ElevenLabs не вернул voice_id: {resp.json()!r}")
    return voice_id


def delete_voice(voice_id: str, http=None) -> None:
    """Удаляет клон голоса в ElevenLabs — на тарифе лимит числа голосов,
    старый клон надо освободить перед тем, как записать новый.
    """
    api_key = _api_key()
    if http is None:
        import requests
        http = requests
    resp = http.delete(VOICES_URL.format(voice_id=voice_id),
                       headers={"xi-api-key": api_key}, timeout=30)
    resp.raise_for_status()
