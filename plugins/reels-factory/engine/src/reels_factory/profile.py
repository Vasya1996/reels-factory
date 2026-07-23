"""Профиль ведущего: фото -> HeyGen asset, запись голоса -> ElevenLabs voice.

Оба шага делаются один раз на человека и переиспользуются во всех его роликах.
Фото можно накопить несколько (разная одежда/фон) — голос обычно один.

Ключи — из env (HEYGEN_API_KEY, ELEVENLABS_API_KEY), как и везде в движке.
http — DI для тестов.
"""
import os
from pathlib import Path

from reels_factory.avatar import UPLOAD_URL


class ProfileError(RuntimeError):
    pass


def upload_photo(path, api_key=None, http=None) -> str:
    """Залить фото ведущего в HeyGen и вернуть asset_id (бесплатно, платит
    только рендер)."""
    path = Path(path)
    if not path.exists():
        raise ProfileError(f"нет файла фото: {path}")
    api_key = api_key or os.environ.get("HEYGEN_API_KEY")
    if not api_key:
        raise ProfileError("HeyGen API key не задан: env HEYGEN_API_KEY")
    if http is None:
        import requests
        http = requests

    resp = http.post(UPLOAD_URL, headers={"X-Api-Key": api_key},
                     files={"file": (path.name, path.read_bytes())}, timeout=120)
    resp.raise_for_status()
    asset_id = (resp.json().get("data") or {}).get("asset_id")
    if not asset_id:
        raise ProfileError(f"HeyGen не вернул asset_id: {str(resp.json())[:200]}")
    return asset_id
