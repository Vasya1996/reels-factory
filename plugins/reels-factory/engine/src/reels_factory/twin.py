"""Создание Digital Twin в HeyGen — один раз на человека, потом только съём.

Зачем: фото-аватар не видел рта говорящего, поэтому зубы, артикуляцию и
пластику он домысливает — именно это и читается как «дешёвый ИИ». Двойник
обучается на видео, где человек реально говорит, и Avatar V воспроизводит
снятое, а не предсказанное.

Порядок (HeyGen v3):
1. `upload_asset()`   — заливаем обучающее видео → asset_id;
2. `create_twin()`    — POST /v3/avatars {type: "digital_twin"} → look_id +
                        group_id + supported_api_engines;
3. согласие (POST /v3/avatars/{group_id}/consent) — без него двойник не
                        отрендерит ни одного видео. Два уровня:
                        `submit_consent()` — уровень 2, заранее записанное видео,
                        только для enterprise (на self-serve → 403);
                        `request_webcam_consent()` — уровень 1, self-serve: даёт
                        ссылку, где человек записывает согласие на камеру;
4. `wait_ready()`     — поллим GET /v3/avatars/looks/{look_id}, пока обучение
                        не закончится, и заодно проверяем, что в
                        supported_api_engines есть "avatar_v".

`create_from_video()` прогоняет все четыре шага и возвращает look_id — его
кладём в factory/config.yaml как avatar.heygen_look_id (или в env
HEYGEN_LOOK_ID), дальше его читает HeyGenClient.

http/sleep — DI для тестов, как и в avatar.py.
"""
import os
from pathlib import Path

UPLOAD_URL = "https://api.heygen.com/v3/assets"
AVATARS_URL = "https://api.heygen.com/v3/avatars"
LOOKS_URL = "https://api.heygen.com/v3/avatars/looks"

# Дословная формулировка HeyGen: без неё согласие не принимается.
CONSENT_STATEMENT = (
    "I, [Full Name], hereby allow HeyGen to use the footage of me to build a "
    "HeyGen avatar."
)

# Требования HeyGen к обучающему видео (сверять при подготовке брифа клиенту).
TRAINING_MIN_SECONDS = 120
TRAINING_MIN_HEIGHT = 720

AVATAR_V = "avatar_v"

POLL_INTERVAL_S = 30
POLL_MAX_ITERATIONS = 40  # 40 * 30с = 20 мин

_READY_STATUSES = ("ready", "completed", "success")
_FAILED_STATUSES = ("failed", "error")


class TwinError(RuntimeError):
    pass


class TwinClient:
    def __init__(self, api_key=None, http=None, sleep=None):
        self.api_key = api_key or os.environ.get("HEYGEN_API_KEY")
        if not self.api_key:
            raise TwinError(
                "HeyGen API key не задан: передайте api_key в TwinClient "
                "или установите env HEYGEN_API_KEY"
            )

        if http is None:
            import requests
            http = requests
        self.http = http

        if sleep is None:
            import time
            sleep = time.sleep
        self.sleep = sleep

    @property
    def _headers(self) -> dict:
        return {"X-Api-Key": self.api_key}

    def upload_asset(self, path: Path) -> str:
        """Залить видео (обучающее или consent) и вернуть asset_id."""
        path = Path(path)
        resp = self.http.post(
            UPLOAD_URL, headers=self._headers,
            files={"file": (path.name, path.read_bytes())},
            timeout=600,
        )
        resp.raise_for_status()
        return resp.json()["data"]["asset_id"]

    def create_twin(self, name: str, asset_id: str) -> dict:
        """POST /v3/avatars — создать двойника из залитого видео.

        Возвращает {"look_id", "group_id", "supported_api_engines"}.
        """
        body = {
            "type": "digital_twin",
            "name": name,
            "file": {"type": "asset_id", "asset_id": asset_id},
        }
        resp = self.http.post(AVATARS_URL, json=body, headers=self._headers, timeout=120)
        resp.raise_for_status()
        data = resp.json().get("data", resp.json())
        item = data["avatar_item"]
        return {
            "look_id": item["id"],
            "group_id": item.get("group_id") or (data.get("avatar_group") or {}).get("id"),
            "supported_api_engines": item.get("supported_api_engines") or [],
        }

    def submit_consent(self, group_id: str, consent_asset_id: str) -> None:
        """Согласие уровня 2 — заранее записанное видео. Доступно ТОЛЬКО
        enterprise-аккаунтам: на обычном (self-serve) ключе HeyGen отвечает 403.
        В этом случае используй request_webcam_consent() (уровень 1)."""
        resp = self.http.post(
            f"{AVATARS_URL}/{group_id}/consent",
            json={"consent_video": {"type": "asset_id", "asset_id": consent_asset_id}},
            headers=self._headers, timeout=120,
        )
        if getattr(resp, "status_code", 200) == 403:
            raise TwinError(
                "Загрузка заранее записанного consent-видео доступна только "
                "enterprise-аккаунтам (HeyGen вернул 403). На self-serve ключе "
                "вызови request_webcam_consent(group_id): вернётся ссылка, по "
                "которой человек записывает согласие на камеру, затем wait_ready()."
            )
        resp.raise_for_status()

    def request_webcam_consent(self, group_id: str, reroute_url: str | None = None) -> str:
        """Согласие уровня 1 (self-serve): POST с пустым телом возвращает URL
        хостед-страницы HeyGen, где человек записывает согласие на камеру
        (произносит код + держит мимику). reroute_url — куда вернуть его после
        записи, для бесшовного онбординга в свой продукт. Возвращает этот URL —
        его отправляют человеку; после записи двойник становится verified."""
        body: dict = {}
        if reroute_url:
            body["reroute_url"] = reroute_url
        resp = self.http.post(
            f"{AVATARS_URL}/{group_id}/consent",
            json=body, headers=self._headers, timeout=60,
        )
        resp.raise_for_status()
        return (resp.json().get("data") or {}).get("url")

    def fetch_look(self, look_id: str) -> dict:
        resp = self.http.get(f"{LOOKS_URL}/{look_id}", headers=self._headers, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        return payload.get("data", payload)

    def wait_ready(self, look_id: str) -> dict:
        """Ждать окончания обучения. Возвращает данные лука."""
        for _ in range(POLL_MAX_ITERATIONS):
            look = self.fetch_look(look_id)
            status = str(look.get("status") or "").lower()
            if status in _FAILED_STATUSES:
                raise TwinError(f"HeyGen не смог обучить двойника (look_id={look_id})")
            if status in _READY_STATUSES or not status:
                return look
            self.sleep(POLL_INTERVAL_S)
        raise TwinError(
            f"Обучение двойника не закончилось за "
            f"{POLL_MAX_ITERATIONS * POLL_INTERVAL_S} с (look_id={look_id})"
        )

    def create_from_video(self, name: str, training_video: Path,
                          consent_video: Path) -> str:
        """Полный путь: видео → обученный двойник. Возвращает look_id.

        Падает с понятной ошибкой, если лук не поддерживает avatar_v — тогда
        рендерить его придётся на avatar_iv, и смысл двойника частично теряется.
        """
        training_asset = self.upload_asset(training_video)
        created = self.create_twin(name, training_asset)

        consent_asset = self.upload_asset(consent_video)
        if not created["group_id"]:
            raise TwinError(
                "HeyGen не вернул group_id — без него нельзя отправить согласие."
            )
        self.submit_consent(created["group_id"], consent_asset)

        look = self.wait_ready(created["look_id"])
        engines = look.get("supported_api_engines") or created["supported_api_engines"]
        if engines and AVATAR_V not in engines:
            raise TwinError(
                f"Лук {created['look_id']} не поддерживает {AVATAR_V} "
                f"(доступно: {engines}). Обычно причина в исходном видео — "
                f"нужен ролик от {TRAINING_MIN_SECONDS} с, от {TRAINING_MIN_HEIGHT}p, "
                "одно чётко видимое лицо, человек говорит вслух."
            )
        return created["look_id"]
