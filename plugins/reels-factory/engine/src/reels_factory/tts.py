"""Синтез голоса ведущего через ElevenLabs.

synth_voice() шлёт текст в ElevenLabs TTS, получает mp3 и конвертирует в wav
48kHz stereo через ffmpeg (render.run).

Модель по умолчанию — eleven_multilingual_v2: стабильно работает с клон-голосами
(и Instant, и Professional) и с русским. eleven_v3 звучит выразительнее и понимает
эмоц-теги [excited]/[laughs], НО требует, чтобы голос был дообучен именно под неё —
иначе TTS падает с voice_not_fine_tuned. Модель можно переопределить аргументом
model_id или env ELEVENLABS_MODEL (например "eleven_v3" для голоса под v3).

voice_id — аргумент, иначе env ELEVENLABS_VOICE_ID. Ключ — из env
ELEVENLABS_API_KEY (в коде ключа нет). http/run_cmd — DI для тестов.
"""
import os
from pathlib import Path

from reels_factory.config import FFMPEG

TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
MODEL_ID = "eleven_multilingual_v2"


def synth_voice(text: str, out_wav: Path, voice_id: str | None = None,
                model_id: str | None = None, http=None, run_cmd=None) -> Path:
    voice_id = voice_id or os.environ.get("ELEVENLABS_VOICE_ID")
    if not voice_id:
        raise RuntimeError(
            "voice_id не задан: передайте voice_id или установите env ELEVENLABS_VOICE_ID"
        )
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ElevenLabs API key не задан: установите env ELEVENLABS_API_KEY"
        )

    model_id = model_id or os.environ.get("ELEVENLABS_MODEL") or MODEL_ID

    if http is None:
        import requests
        http = requests
    if run_cmd is None:
        from reels_factory import render
        run_cmd = render.run

    out_wav = Path(out_wav)
    mp3_tmp = out_wav.with_suffix(".mp3")

    resp = http.post(
        TTS_URL.format(voice_id=voice_id),
        json={"text": text, "model_id": model_id},
        headers={"xi-api-key": api_key, "Content-Type": "application/json"},
        timeout=60,
    )
    resp.raise_for_status()
    mp3_tmp.write_bytes(resp.content)

    run_cmd([str(FFMPEG), "-y", "-i", str(mp3_tmp), "-ar", "48000", "-ac", "2", str(out_wav)])

    mp3_tmp.unlink(missing_ok=True)
    return out_wav
