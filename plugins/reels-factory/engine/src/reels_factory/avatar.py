"""Клиент HeyGen для аватара-ведущего (v3 Avatar IV: image+audio asset,
motion_prompt/expressiveness; фолбэк на старый v2 video/generate).

generate() гонит НАШЕ аудио (ElevenLabs) в HeyGen: (1) загружает wav как
audio-ассет и (2) создаёт видео — весь v3-путь (upload + create + poll)
обёрнут в один try/except; если v3 недоступен по ключу (403/404) на ЛЮБОМ
из этих шагов — единая (без повторов) попытка фолбэка на старый v2-путь;
(3) поллит статус, скачивает готовый mp4.

cached_generate() переиспользует уже сгенерированный фрагмент (например CTA)
между рилсами по sha1-ключу от (sha1 файла аудио + avatar_id + motion_prompt +
expressiveness).

render_covered_block() — не HeyGen: для блоков формата avatar, полностью
закрытых вставкой видеоряда (see pipeline.run_make), рендерит голос поверх
чёрного кадра локально через ffmpeg — платить HeyGen за невидимый кадр незачем.

api_key/avatar_id/motion_prompt/expressiveness — из аргументов или env
(HEYGEN_API_KEY, HEYGEN_AVATAR_ID, HEYGEN_MOTION_PROMPT, HEYGEN_EXPRESSIVENESS,
дефолт expressiveness "low" — как и дефолт самого HeyGen; официальный
troubleshooting-гайд HeyGen советует именно понижать expressiveness при
галлюцинациях/лишних деталях в кадре). http/sleep — DI для тестов.

v3-запрос дополнительно закрепляет сцену вместо того, чтобы отдавать её на
волю генерации: `background` = то же фото аватара (мотив держится в кадре,
модель не "дорисовывает" случайный фон/людей) и `aspect_ratio: "9:16"` (поле
dimension в v3 игнорируется сервером — размер раньше действительно задавало
исходное фото, но актуальная схема API даёт явный контроль через
aspect_ratio, и раз плагин целиком про вертикальные рилсы — фиксируем 9:16).
"""
import hashlib
import os
from pathlib import Path

UPLOAD_URL = "https://api.heygen.com/v3/assets"
CREATE_V3_URL = "https://api.heygen.com/v3/videos"
STATUS_V3_URL = "https://api.heygen.com/v3/videos"

# Фолбэк для ключей без доступа к v3 (низкая уверенность — см. отчёт исходника).
UPLOAD_V2_URL = "https://upload.heygen.com/v1/asset"
CREATE_V2_URL = "https://api.heygen.com/v2/video/generate"
STATUS_V2_URL = "https://api.heygen.com/v1/video_status.get"

_AUDIO_MIME_BY_SUFFIX = {".wav": "audio/wav", ".mp3": "audio/mpeg"}

# Дефолт для аватара-ведущего: говорит прямо в камеру, живо, без переигрывания.
DEFAULT_MOTION_PROMPT = (
    "talking directly to the camera as a friendly presenter, natural warm "
    "expression, subtle head movements and light hand gestures while speaking, "
    "steady eye contact with the camera, calm and confident"
)

DEFAULT_EXPRESSIVENESS = "low"

POLL_INTERVAL_S = 10
POLL_MAX_ITERATIONS = 60  # 60 * 10с = 600с (10 мин)

_FALLBACK_STATUSES = (403, 404)


class _Unavailable(Exception):
    pass


class HeyGenClient:
    def __init__(self, api_key=None, avatar_id=None, motion_prompt=None,
                 http=None, sleep=None, expressiveness=None):
        self.api_key = api_key or os.environ.get("HEYGEN_API_KEY")
        self.avatar_id = avatar_id or os.environ.get("HEYGEN_AVATAR_ID")
        self.motion_prompt = motion_prompt or os.environ.get(
            "HEYGEN_MOTION_PROMPT", DEFAULT_MOTION_PROMPT)
        self.expressiveness = expressiveness or os.environ.get(
            "HEYGEN_EXPRESSIVENESS", DEFAULT_EXPRESSIVENESS)

        if http is None:
            import requests
            http = requests
        self.http = http

        if sleep is None:
            import time
            sleep = time.sleep
        self.sleep = sleep

    def generate(self, audio_wav: Path, out_mp4: Path, width: int = 1080, height: int = 672) -> Path:
        if not self.api_key:
            raise RuntimeError(
                "HeyGen API key не задан: передайте api_key в HeyGenClient "
                "или установите env HEYGEN_API_KEY"
            )

        audio_wav = Path(audio_wav)
        out_mp4 = Path(out_mp4)
        headers = {"X-Api-Key": self.api_key}

        try:
            audio_asset_id = self._upload_audio_v3(audio_wav, headers)
            video_url = self._generate_v3(audio_asset_id, headers, width, height)
        except _Unavailable:
            audio_asset_id = self._upload_audio_v2(audio_wav, headers)
            video_url = self._generate_v2_legacy(audio_asset_id, headers, width, height)

        dl_resp = self.http.get(video_url, timeout=30)
        dl_resp.raise_for_status()
        out_mp4.parent.mkdir(parents=True, exist_ok=True)
        out_mp4.write_bytes(dl_resp.content)
        return out_mp4

    def _upload_audio_v3(self, audio_wav: Path, headers: dict) -> str:
        resp = self.http.post(
            UPLOAD_URL, headers=headers,
            files={"file": (audio_wav.name, audio_wav.read_bytes())},
            timeout=60,
        )
        status_code = getattr(resp, "status_code", 200)
        if status_code in _FALLBACK_STATUSES:
            raise _Unavailable(f"v3 upload недоступен: {status_code}")
        resp.raise_for_status()
        return resp.json()["data"]["asset_id"]

    def _upload_audio_v2(self, audio_wav: Path, headers: dict) -> str:
        content_type = _AUDIO_MIME_BY_SUFFIX.get(audio_wav.suffix.lower(), "audio/wav")
        v2_headers = {**headers, "Content-Type": content_type}
        resp = self.http.post(
            UPLOAD_V2_URL, headers=v2_headers, data=audio_wav.read_bytes(), timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["data"]["asset_id"]

    def _generate_v3(self, audio_asset_id: str, headers: dict, width: int, height: int) -> str:
        body = {
            "type": "image",
            "image": {"type": "asset_id", "asset_id": self.avatar_id},
            "audio_asset_id": audio_asset_id,
            "motion_prompt": self.motion_prompt,
            "expressiveness": self.expressiveness,
            # закрепляем сцену тем же фото — иначе модель вольна дорисовать
            # случайный фон (вплоть до посторонних людей в кадре)
            "background": {"type": "image", "asset_id": self.avatar_id},
            # dimension сервер не принимает; размер раньше задавало исходное
            # фото — теперь фиксируем явно, плагин целиком про 9:16-рилсы
            "aspect_ratio": "9:16",
        }
        resp = self.http.post(CREATE_V3_URL, json=body, headers=headers, timeout=30)
        status_code = getattr(resp, "status_code", 200)
        if status_code in _FALLBACK_STATUSES:
            raise _Unavailable(f"v3 недоступен: {status_code}")
        resp.raise_for_status()
        video_id = resp.json()["data"]["video_id"]
        return self._poll(headers, video_id, self._fetch_status_v3)

    def _generate_v2_legacy(self, audio_asset_id: str, headers: dict, width: int, height: int) -> str:
        body = {
            "video_inputs": [
                {
                    "character": {"type": "talking_photo", "talking_photo_id": self.avatar_id},
                    "voice": {"type": "audio", "audio_asset_id": audio_asset_id},
                }
            ],
            "dimension": {"width": width, "height": height},
        }
        resp = self.http.post(CREATE_V2_URL, json=body, headers=headers, timeout=30)
        resp.raise_for_status()
        video_id = resp.json()["data"]["video_id"]
        return self._poll(headers, video_id, self._fetch_status_v2)

    def _fetch_status_v3(self, video_id: str, headers: dict) -> tuple:
        resp = self.http.get(f"{STATUS_V3_URL}/{video_id}", headers=headers, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        data = payload.get("data", payload)
        return data["status"], data.get("video_url")

    def _fetch_status_v2(self, video_id: str, headers: dict) -> tuple:
        resp = self.http.get(f"{STATUS_V2_URL}?video_id={video_id}", headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()["data"]
        return data["status"], data.get("video_url")

    def _poll(self, headers: dict, video_id: str, fetch_status) -> str:
        for _ in range(POLL_MAX_ITERATIONS):
            status, video_url = fetch_status(video_id, headers)
            if status == "completed":
                return video_url
            if status == "failed":
                raise RuntimeError(f"HeyGen video generation failed (video_id={video_id})")
            self.sleep(POLL_INTERVAL_S)
        raise RuntimeError(
            f"HeyGen video generation timed out after {POLL_MAX_ITERATIONS} poll attempts "
            f"(video_id={video_id})"
        )


def render_covered_block(audio_wav: Path, out_mp4: Path, width: int = 1080, height: int = 1920) -> Path:
    """Замена HeyGen-рендера для блока формата avatar, который на 100% закрыт
    вставкой видеоряда (plan_avatar_inserts берёт вставку строго на весь
    [start,end] блока — под ней в принципе ничего не видно). Голос из
    audio_wav вшивается в чёрный кадр той же длительности одним локальным
    ffmpeg-проходом — без HeyGen, без сети, без затрат.
    """
    from reels_factory.config import FFMPEG
    from reels_factory.render import run, media_dur

    audio_wav = Path(audio_wav)
    out_mp4 = Path(out_mp4)
    dur = media_dur(str(audio_wav))
    cmd = [
        FFMPEG, "-y",
        "-f", "lavfi", "-i", f"color=c=black:s={width}x{height}:d={dur}",
        "-i", str(audio_wav),
        "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-pix_fmt", "yuv420p",
        "-video_track_timescale", "30000",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
        "-shortest", str(out_mp4),
    ]
    run(cmd)
    return out_mp4


def cached_generate(client: HeyGenClient, audio_wav: Path, cache_dir: Path) -> Path:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    audio_wav = Path(audio_wav)
    audio_sha1 = hashlib.sha1(audio_wav.read_bytes()).hexdigest()
    key = hashlib.sha1(
        f"{audio_sha1}|{client.avatar_id}|{client.motion_prompt}|{client.expressiveness}"
        .encode("utf-8")
    ).hexdigest()[:16]
    out_mp4 = cache_dir / f"{key}.mp4"
    if out_mp4.exists():
        return out_mp4
    return client.generate(audio_wav, out_mp4)
