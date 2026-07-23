import pytest

from reels_factory.twin import AVATAR_V, TwinClient, TwinError


class _Resp:
    def __init__(self, payload=None):
        self._p = payload

    def json(self):
        return self._p

    def raise_for_status(self):
        pass


class _FakeHttp:
    """Обучение занимает два опроса, потом лук готов и умеет avatar_v."""

    def __init__(self, engines=(AVATAR_V, "avatar_iv"), statuses=None):
        self.posts, self.gets = [], []
        self.engines = list(engines)
        self.statuses = list(statuses or ["training", "ready"])

    def post(self, url, json=None, headers=None, timeout=None, files=None):
        self.posts.append((url, json, files))
        if url.endswith("/assets"):
            n = len([p for p in self.posts if p[0].endswith("/assets")])
            return _Resp({"data": {"asset_id": f"asset{n}"}})
        if url.endswith("/consent"):
            return _Resp({"data": {"ok": True}})
        return _Resp({"data": {
            "avatar_item": {
                "id": "look1",
                "group_id": "group1",
                "supported_api_engines": self.engines,
            },
            "avatar_group": {"id": "group1"},
        }})

    def get(self, url, headers=None, timeout=None):
        self.gets.append(url)
        status = self.statuses.pop(0) if self.statuses else "ready"
        return _Resp({"data": {
            "status": status,
            "supported_api_engines": self.engines,
        }})


def _videos(tmp_path):
    train = tmp_path / "train.mp4"
    train.write_bytes(b"trainingfootage")
    consent = tmp_path / "consent.mp4"
    consent.write_bytes(b"consentfootage")
    return train, consent


def test_создание_двойника_проходит_все_шаги_и_возвращает_look_id(tmp_path):
    http = _FakeHttp()
    c = TwinClient(api_key="k", http=http, sleep=lambda s: None)
    train, consent = _videos(tmp_path)

    look_id = c.create_from_video("Жанна", train, consent)

    assert look_id == "look1"

    urls = [p[0] for p in http.posts]
    assert urls[0].endswith("/assets")          # обучающее видео
    assert urls[1].endswith("/v3/avatars")      # создание двойника
    assert urls[2].endswith("/assets")          # consent-видео
    assert urls[3].endswith("/group1/consent")  # согласие

    body_create = http.posts[1][1]
    assert body_create["type"] == "digital_twin"
    assert body_create["name"] == "Жанна"
    assert body_create["file"] == {"type": "asset_id", "asset_id": "asset1"}

    body_consent = http.posts[3][1]
    assert body_consent["consent_video"] == {"type": "asset_id", "asset_id": "asset2"}

    assert any("look1" in g for g in http.gets)


def test_лук_без_avatar_v_отвергается_с_подсказкой_про_видео(tmp_path):
    http = _FakeHttp(engines=("avatar_iv",))
    c = TwinClient(api_key="k", http=http, sleep=lambda s: None)
    train, consent = _videos(tmp_path)

    with pytest.raises(TwinError, match="avatar_v"):
        c.create_from_video("Серик", train, consent)


def test_проваленное_обучение_падает_понятной_ошибкой(tmp_path):
    http = _FakeHttp(statuses=["training", "failed"])
    c = TwinClient(api_key="k", http=http, sleep=lambda s: None)
    train, consent = _videos(tmp_path)

    with pytest.raises(TwinError, match="обучить"):
        c.create_from_video("Серик", train, consent)


def test_без_ключа_не_создаётся(monkeypatch):
    # на машине разработчика ключ может стоять в env — тест про его отсутствие
    monkeypatch.delenv("HEYGEN_API_KEY", raising=False)
    with pytest.raises(TwinError, match="API key"):
        TwinClient(api_key="", http=object())


class _RespConsent:
    def __init__(self, payload=None, status_code=200):
        self._p, self.status_code = payload, status_code

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_webcam_consent_уровня_1_возвращает_ссылку_на_запись():
    seen = {}

    class _H:
        def post(self, url, json=None, headers=None, timeout=None, files=None):
            seen["url"], seen["body"] = url, json
            return _RespConsent({"data": {"url": "https://app.heygen.com/record?token=xyz"}})

    c = TwinClient(api_key="k", http=_H(), sleep=lambda s: None)
    link = c.request_webcam_consent("g1")

    assert link == "https://app.heygen.com/record?token=xyz"
    assert seen["url"].endswith("/g1/consent")
    assert seen["body"] == {}  # уровень 1 — пустое тело


def test_webcam_consent_прокидывает_reroute_url():
    seen = {}

    class _H:
        def post(self, url, json=None, headers=None, timeout=None, files=None):
            seen.update(json or {})
            return _RespConsent({"data": {"url": "u"}})

    c = TwinClient(api_key="k", http=_H(), sleep=lambda s: None)
    c.request_webcam_consent("g1", reroute_url="https://me/back")

    assert seen["reroute_url"] == "https://me/back"


def test_pre_recorded_consent_на_self_serve_даёт_понятную_ошибку():
    class _H:
        def post(self, url, json=None, headers=None, timeout=None, files=None):
            return _RespConsent({"error": {"code": "resource_access_denied"}}, status_code=403)

    c = TwinClient(api_key="k", http=_H(), sleep=lambda s: None)
    with pytest.raises(TwinError, match="enterprise"):
        c.submit_consent("g1", "asset1")
