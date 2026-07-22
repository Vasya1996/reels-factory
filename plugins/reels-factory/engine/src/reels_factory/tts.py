"""Синтез голоса ведущего через ElevenLabs (eleven_v3).

synth_voice() шлёт текст в ElevenLabs TTS, получает mp3 и конвертирует в wav
48kHz stereo через ffmpeg (render.run). Квадратно-скобочные эмоц-теги в тексте
([excited], [laughs] и т.п.) не трогаем — их понимает сама модель.

voice_id — аргумент, иначе env ELEVENLABS_VOICE_ID. Ключ — из env
ELEVENLABS_API_KEY (в коде ключа нет). http/run_cmd — DI для тестов.
"""
import os
from pathlib import Path

from reels_factory.config import FFMPEG

TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
VOICES_ADD_URL = "https://api.elevenlabs.io/v1/voices/add"
MODEL_ID = "eleven_v3"


def synth_voice(text: str, out_wav: Path, voice_id: str | None = None,
                http=None, run_cmd=None) -> Path:
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
        json={"text": text, "model_id": MODEL_ID},
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
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ElevenLabs API key не задан: установите env ELEVENLABS_API_KEY")
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
