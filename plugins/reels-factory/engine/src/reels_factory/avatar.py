"""Клиент HeyGen для аватара-ведущего.

Два пути, выбор автоматический:

1. **Digital Twin + Avatar V** (предпочтительный, включается, когда задан
   look_id) — аватар обучен на видео человека, поэтому модель не выдумывает
   зубы, мимику и пластику, а воспроизводит настоящие. Тело запроса:
   `type: "avatar"` + `avatar_id` (look id двойника) + `engine.type: "avatar_v"`.
   `expressiveness` и `motion_prompt` в этом API-пути НЕ шлются: актуальная
   request schema ограничивает оба поля Photo Avatar / Avatar IV.
2. **Photo Avatar (Avatar IV)** — старый путь по одному фото (`type: "image"`),
   остаётся фолбэком, когда двойника ещё нет. Слабое место: рот на фото закрыт,
   зубы модель домысливает.

Плюс фолбэк на старый v2 video/generate для ключей без доступа к v3.

generate() гонит НАШЕ аудио (ElevenLabs) в HeyGen: (1) загружает wav как
audio-ассет и (2) создаёт видео — весь v3-путь (upload + create + poll)
обёрнут в один try/except; если v3 недоступен по ключу (403/404) на ЛЮБОМ
из этих шагов — единая (без повторов) попытка фолбэка на старый v2-путь;
(3) поллит статус, скачивает готовый mp4.

cached_generate() переиспользует уже сгенерированный фрагмент (например CTA)
между рилсами по sha1-ключу от (sha1 файла аудио + avatar_id + look_id +
engine + resolution + motion_prompt + expressiveness).

render_covered_block() — не HeyGen: для блоков формата avatar, полностью
закрытых вставкой видеоряда (see pipeline.run_make), рендерит голос поверх
чёрного кадра локально через ffmpeg — платить HeyGen за невидимый кадр незачем.

api_key/avatar_id/look_id/motion_prompt/expressiveness/engine/resolution — из
аргументов или env (HEYGEN_API_KEY, HEYGEN_AVATAR_ID, HEYGEN_LOOK_ID,
HEYGEN_MOTION_PROMPT, HEYGEN_EXPRESSIVENESS, HEYGEN_ENGINE, HEYGEN_RESOLUTION;
дефолт expressiveness "low" — как и дефолт самого HeyGen; официальный
troubleshooting-гайд HeyGen советует именно понижать expressiveness при
галлюцинациях/лишних деталях в кадре). http/sleep — DI для тестов.

Двойник создаётся один раз на человека — см. модуль twin.py.

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
    "Looks at the camera and gestures lightly with one hand, calm and confident."
)

# Один motion_prompt на весь ролик даёт ровную, «дикторскую» подачу: хук просит
# энергии, а CTA — прямого обращения, и это разная пластика. Ключ — role блока
# сценария (hook/context/development/payoff/cta), остальное берёт дефолт.
MOTION_PROMPT_BY_ROLE = {
    "hook": (
        "Looks at the camera and leans in slightly, confident and engaged."
    ),
    "context": (
        "Looks at the camera with a calm expression and subtle natural gestures."
    ),
    "development": (
        "Looks at the camera and gestures lightly with one hand, confident and clear."
    ),
    "payoff": (
        "Looks at the camera and nods gently, sincere and confident."
    ),
    "cta": (
        "Looks at the camera and makes one inviting open-hand gesture, warm and direct."
    ),
}

DEFAULT_EXPRESSIVENESS = "low"

# Движок рендера. avatar_v — высшая точность идентичности, но существует только
# для двойника; фото-аватар рендерит avatar_iv. Дефолт выбирается по тому, есть
# ли look_id, — вместо того чтобы молча полагаться на серверный дефолт HeyGen.
DEFAULT_ENGINE_TWIN = "avatar_v"
DEFAULT_ENGINE_PHOTO = "avatar_iv"
DEFAULT_RESOLUTION = "1080p"

# API request schema ограничивает оба performance controls Avatar IV.
_ENGINES_WITH_PERFORMANCE_CONTROLS = ("avatar_iv",)

POLL_INTERVAL_S = 10
POLL_MAX_ITERATIONS = 60  # 60 * 10с = 600с (10 мин)

_FALLBACK_STATUSES = (403, 404)


class _Unavailable(Exception):
    pass


def upload_photo_asset(image_path, api_key=None, http=None) -> str:
    """Залить фото аватара в HeyGen /v3/assets, вернуть asset_id.

    Загрузка ассета бесплатна — платит только генерация видео. Нужна там, где
    фото приходит из кода (телеграм-бот), а не руками через мастер setup.
    """
    image_path = Path(image_path)
    if not image_path.exists():
        raise RuntimeError(f"файл фото не найден: {image_path}")
    api_key = api_key or os.environ.get("HEYGEN_API_KEY")
    if not api_key:
        raise RuntimeError(
            "HeyGen API key не задан: передайте api_key или "
            "установите env HEYGEN_API_KEY"
        )
    if http is None:
        import requests
        http = requests

    resp = http.post(
        UPLOAD_URL, headers={"X-Api-Key": api_key},
        files={"file": (image_path.name, image_path.read_bytes())},
        timeout=120,
    )
    resp.raise_for_status()
    asset_id = ((resp.json() or {}).get("data") or {}).get("asset_id")
    if not asset_id:
        raise RuntimeError(f"HeyGen не вернул asset_id: {str(resp.json())[:200]}")
    return asset_id


class HeyGenClient:
    def __init__(self, api_key=None, avatar_id=None, motion_prompt=None,
                 http=None, sleep=None, expressiveness=None, look_id=None,
                 engine=None, resolution=None):
        self.api_key = api_key or os.environ.get("HEYGEN_API_KEY")
        self.avatar_id = avatar_id or os.environ.get("HEYGEN_AVATAR_ID")
        # look_id задан → идём путём Digital Twin (Avatar V), иначе — по фото
        self.look_id = look_id or os.environ.get("HEYGEN_LOOK_ID")
        explicit = motion_prompt or os.environ.get("HEYGEN_MOTION_PROMPT")
        self._motion_prompt_explicit = bool(explicit)
        self.motion_prompt = explicit or DEFAULT_MOTION_PROMPT
        self.expressiveness = expressiveness or os.environ.get(
            "HEYGEN_EXPRESSIVENESS", DEFAULT_EXPRESSIVENESS)
        self.engine = engine or os.environ.get("HEYGEN_ENGINE") or (
            DEFAULT_ENGINE_TWIN if self.look_id else DEFAULT_ENGINE_PHOTO)
        self.resolution = resolution or os.environ.get(
            "HEYGEN_RESOLUTION", DEFAULT_RESOLUTION)

        if http is None:
            import requests
            http = requests
        self.http = http

        if sleep is None:
            import time
            sleep = time.sleep
        self.sleep = sleep

    def motion_prompt_for(self, role=None) -> str:
        """Промпт движения под роль блока. Явно заданный клиенту motion_prompt
        (config/env) главнее ролевого: если человек прописал свою пластику,
        мы её не перебиваем."""
        if self._motion_prompt_explicit or not role:
            return self.motion_prompt
        return MOTION_PROMPT_BY_ROLE.get(role, self.motion_prompt)

    def generate(self, audio_wav: Path, out_mp4: Path, width: int = 1080,
                 height: int = 672, role=None) -> Path:
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
            video_url = self._generate_v3(audio_asset_id, headers, width, height, role)
        except _Unavailable:
            if self.look_id:
                # v2 умеет только talking_photo — двойника там не существует,
                # молча деградировать до фото-аватара нельзя: это ровно то
                # качество, ради ухода от которого двойник и заводился
                raise RuntimeError(
                    "Digital Twin требует HeyGen v3, но ключ его не отдаёт "
                    "(403/404). Проверь доступ к v3 или убери look_id, чтобы "
                    "осознанно вернуться на фото-аватар."
                )
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

    def _generate_v3(self, audio_asset_id: str, headers: dict, width: int,
                     height: int, role=None) -> str:
        motion_prompt = self.motion_prompt_for(role)
        body = (self._body_twin(audio_asset_id, motion_prompt) if self.look_id
                else self._body_photo(audio_asset_id, motion_prompt))
        resp = self.http.post(CREATE_V3_URL, json=body, headers=headers, timeout=30)
        status_code = getattr(resp, "status_code", 200)
        if status_code in _FALLBACK_STATUSES:
            raise _Unavailable(f"v3 недоступен: {status_code}")
        resp.raise_for_status()
        video_id = resp.json()["data"]["video_id"]
        return self._poll(headers, video_id, self._fetch_status_v3)

    def _body_twin(self, audio_asset_id: str, motion_prompt: str) -> dict:
        """Digital Twin: идентичность держит сам аватар, сцену закреплять нечем
        и незачем (background от фото тут не нужен — фон уже снят на видео)."""
        body = {
            "type": "avatar",
            "avatar_id": self.look_id,
            "audio_asset_id": audio_asset_id,
            "engine": {"type": self.engine},
            "aspect_ratio": "9:16",
            "resolution": self.resolution,
        }
        # Оба поля IV-only по API schema; Avatar V отклоняет extra inputs.
        if self.engine in _ENGINES_WITH_PERFORMANCE_CONTROLS:
            body["motion_prompt"] = motion_prompt
            body["expressiveness"] = self.expressiveness
        return body

    def _body_photo(self, audio_asset_id: str, motion_prompt: str) -> dict:
        body = {
            "type": "image",
            "image": {"type": "asset_id", "asset_id": self.avatar_id},
            "audio_asset_id": audio_asset_id,
            # для type:image движок НЕ шлём: HeyGen v3 отвечает 400 "Extra inputs
            # are not permitted" (param: engine). Avatar IV — серверный дефолт
            # для image, отдельного поля engine схема тут не принимает.
            "resolution": self.resolution,
            "motion_prompt": motion_prompt,
            # закрепляем сцену тем же фото — иначе модель вольна дорисовать
            # случайный фон (вплоть до посторонних людей в кадре)
            "background": {"type": "image", "asset_id": self.avatar_id},
            # dimension сервер не принимает; размер раньше задавало исходное
            # фото — теперь фиксируем явно, плагин целиком про 9:16-рилсы
            "aspect_ratio": "9:16",
        }
        if self.engine in _ENGINES_WITH_PERFORMANCE_CONTROLS:
            body["expressiveness"] = self.expressiveness
        return body

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


def cached_generate(client: HeyGenClient, audio_wav: Path, cache_dir: Path,
                    role=None) -> Path:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    audio_wav = Path(audio_wav)
    audio_sha1 = hashlib.sha1(audio_wav.read_bytes()).hexdigest()
    # getattr — чтобы ключ считался и для облегчённых дублей клиента в тестах
    motion_prompt = (client.motion_prompt_for(role)
                     if hasattr(client, "motion_prompt_for") else client.motion_prompt)
    supports_performance = (
        getattr(client, "engine", None) in _ENGINES_WITH_PERFORMANCE_CONTROLS
    )
    performance_key = (
        f"{motion_prompt}|{client.expressiveness}"
        if supports_performance else "provider-default-performance"
    )
    key = hashlib.sha1(
        f"{audio_sha1}|{client.avatar_id}|{getattr(client, 'look_id', None)}"
        f"|{getattr(client, 'engine', None)}|{getattr(client, 'resolution', None)}"
        f"|{performance_key}"
        .encode("utf-8")
    ).hexdigest()[:16]
    out_mp4 = cache_dir / f"{key}.mp4"
    if out_mp4.exists():
        return out_mp4
    return client.generate(audio_wav, out_mp4, role=role)
