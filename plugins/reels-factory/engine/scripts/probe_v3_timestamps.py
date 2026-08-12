"""Разовый платный проб: поддерживает ли eleven_v3 /with-timestamps + alignment
для казахского. НИЧЕГО секретного не печатает (ключ только читается из env).

Запуск (там, где задан ELEVENLABS_API_KEY):
    python plugins/reels-factory/engine/scripts/probe_v3_timestamps.py [voice_id]

Если voice_id не передан — берётся первый доступный голос аккаунта.
Стоимость: один запрос на ~90 символов казахского текста.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from reels_factory.tts import ElevenLabsClient  # noqa: E402

# Короткий казахский фрагмент — минимальная стоимость запроса.
KK_TEXT = "Сәлеметсіз бе! Бұл дауыс сынағы. Зейін — тағдырдың сыйы емес, жай ғана дағды."


def _first_voice_id(http, api_key: str) -> str:
    resp = http.get(
        "https://api.elevenlabs.io/v2/voices",
        headers={"xi-api-key": api_key},
        params={"page_size": 1},
        timeout=30,
    )
    resp.raise_for_status()
    voices = resp.json().get("voices") or []
    if not voices:
        raise SystemExit("У аккаунта нет ни одного голоса — передай voice_id аргументом.")
    return voices[0]["voice_id"]


def _try(client: ElevenLabsClient, voice_id: str, language_code: str | None):
    """Один запрос v3 with-timestamps. Возвращает (ok, инфо-строка)."""
    try:
        speech = client.convert_with_timestamps(
            KK_TEXT,
            voice_id=voice_id,
            model_id="eleven_v3",
            stability=0.5,
            speed=None,
            similarity_boost=None,
            style=None,
            use_speaker_boost=None,
            language_code=language_code,
            apply_text_normalization="auto",
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"ОШИБКА ({language_code=}): {type(exc).__name__}: {str(exc)[:300]}"

    align = speech.alignment or {}
    chars = align.get("characters") or []
    starts = align.get("character_start_times_seconds") or []
    ends = align.get("character_end_times_seconds") or []
    aligned_text = "".join(str(c) for c in chars)
    dur = float(ends[-1]) if ends else 0.0
    ok_len = len(chars) == len(KK_TEXT) == len(starts) == len(ends)
    ok_text = aligned_text == KK_TEXT
    return True, (
        f"OK ({language_code=}): audio={len(speech.audio)} байт | "
        f"alignment.chars={len(chars)} (text={len(KK_TEXT)}) | "
        f"lengths_match={ok_len} | text_match={ok_text} | "
        f"~duration={dur:.2f}s | request_id={speech.request_id}"
    )


def main() -> None:
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise SystemExit(
            "ELEVENLABS_API_KEY не задан в окружении — запусти там, где он есть."
        )
    import requests

    voice_id = sys.argv[1] if len(sys.argv) > 1 else _first_voice_id(requests, api_key)
    print(f"[probe] voice_id={voice_id[:6]}… model=eleven_v3 chars={len(KK_TEXT)}")

    client = ElevenLabsClient(api_key=api_key, http=requests)

    # 1) сначала как отправит текущий код: language_code="kk"
    ok, info = _try(client, voice_id, "kk")
    print("[kk ]", info)
    if ok:
        print("\nВЫВОД: eleven_v3 вернул alignment -> монтаж для казахского возможен.")
        return

    # 2) фолбэк на ISO-639-3 'kaz'
    ok, info = _try(client, voice_id, "kaz")
    print("[kaz]", info)
    if ok:
        print("\nВЫВОД: v3 требует код 'kaz', не 'kk' — нужен маппинг языка для v3.")
        return

    # 3) без language_code — вдруг проблема только в коде языка
    ok, info = _try(client, voice_id, None)
    print("[none]", info)
    if ok:
        print("\nВЫВОД: v3 отдаёт alignment без language_code; kk/kaz провайдер не принял.")
        return

    print(
        "\nВЫВОД: eleven_v3 не отдал alignment ни в одном варианте -> "
        "для казахского монтаж через master_audio недоступен; "
        "нужен путь без монтажа (или whisper-alignment)."
    )


if __name__ == "__main__":
    main()
