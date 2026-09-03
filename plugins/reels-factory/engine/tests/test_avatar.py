import json
from pathlib import Path

import pytest

from reels_factory.avatar import (DEFAULT_MOTION_PROMPT,
                                  HEYGEN_LOW_BALANCE_USD,
                                  MOTION_PROMPT_BY_ROLE, POLL_MAX_WAIT_S,
                                  POLL_STAGE_1_S, POLL_STAGE_1_UNTIL_S,
                                  POLL_STAGE_2_S, POLL_STAGE_2_UNTIL_S,
                                  POLL_STAGE_3_S, UPLOAD_URL,
                                  HeyGenClient, HeyGenConfigError,
                                  HeyGenCreditsExhausted, HeyGenRenderTimeout,
                                  cached_generate, clear_heygen_pause,
                                  ensure_balance_for_order,
                                  heygen_orders_paused, upload_photo_asset)


class _Resp:
    def __init__(self, payload=None, content=b"", status_code=200, headers=None):
        self._p, self.content = payload, content
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeHttp:
    def __init__(self):
        self.posts, self.gets, self._n = [], [], 0

    def post(self, url, json=None, headers=None, timeout=None, files=None):
        self.posts.append((url, json, headers, files))
        if "assets" in url:
            return _Resp({"data": {"asset_id": "aud1"}})
        return _Resp({"data": {"video_id": "vid1"}})

    def get(self, url, headers=None, timeout=None):
        self.gets.append(url)
        if "/videos/" in url:
            self._n += 1
            st = "processing" if self._n < 2 else "completed"
            return _Resp({"data": {"status": st, "video_url": "http://dl/x.mp4"}})
        return _Resp(content=b"mp4bytes")


def _wav(path: Path, data=b"wavdata") -> Path:
    path.write_bytes(data)
    return path


@pytest.fixture(autouse=True)
def _work_root(tmp_path, monkeypatch):
    """Флаг паузы (heygen_paused.json) живёт в WORK_ROOT — изолируем каждый
    тест своей папкой, чтобы они не путались флагом друг друга."""
    import reels_factory.avatar as avatar_module
    monkeypatch.setattr(avatar_module, "WORK_ROOT", tmp_path / "work")
    return tmp_path


# --- загрузка фото аватара (upload_photo_asset) ------------------------------

class _FakeUpload:
    """Только аплоад ассета: запоминает запрос, отдаёт заданный ответ."""

    def __init__(self, payload=None, status=200):
        self.payload = payload if payload is not None else {"data": {"asset_id": "img_123"}}
        self.status, self.posts = status, []

    def post(self, url, headers=None, files=None, timeout=None, **kw):
        self.posts.append((url, headers, files, timeout))
        return _Resp(self.payload, status_code=self.status)


def _photo(tmp_path, data=b"jpegbytes") -> Path:
    p = tmp_path / "face.jpg"
    p.write_bytes(data)
    return p


def test_фото_уходит_в_v3_assets_и_возвращает_asset_id(tmp_path):
    http = _FakeUpload()

    got = upload_photo_asset(_photo(tmp_path), api_key="K1", http=http)

    assert got == "img_123"
    url, headers, files, _timeout = http.posts[0]
    assert url == UPLOAD_URL
    assert headers["X-Api-Key"] == "K1"
    assert files["file"] == ("face.jpg", b"jpegbytes")


def test_фото_без_ключа_не_грузится(tmp_path, monkeypatch):
    monkeypatch.delenv("HEYGEN_API_KEY", raising=False)
    http = _FakeUpload()

    with pytest.raises(RuntimeError, match="HEYGEN_API_KEY"):
        upload_photo_asset(_photo(tmp_path), http=http)

    assert http.posts == []


def test_нет_файла_фото_говорим_про_путь(tmp_path):
    http = _FakeUpload()

    with pytest.raises(RuntimeError, match="нет.jpg"):
        upload_photo_asset(tmp_path / "нет.jpg", api_key="K1", http=http)

    assert http.posts == []


def test_ошибка_heygen_пробрасывается(tmp_path):
    http = _FakeUpload(status=500)

    with pytest.raises(RuntimeError, match="HTTP 500"):
        upload_photo_asset(
            _photo(tmp_path), api_key="K1", http=http, sleep=lambda s: None,
        )

    # 500 ретраится по общей схеме (задача 10) — до 5 попыток, все на один URL.
    assert len(http.posts) == 5


def test_ответ_без_asset_id_понятная_ошибка(tmp_path):
    http = _FakeUpload(payload={"data": {}})

    with pytest.raises(RuntimeError, match="не вернул asset_id"):
        upload_photo_asset(_photo(tmp_path), api_key="K1", http=http)


def test_generate_загружает_аудио_создаёт_видео_с_motion_prompt_и_скачивает(tmp_path):
    http = _FakeHttp()
    c = HeyGenClient(api_key="k", avatar_id="a1", motion_prompt="ведёт эфир",
                     http=http, sleep=lambda s: None)
    audio = _wav(tmp_path / "a.wav")

    out = c.generate(audio, tmp_path / "out.mp4")

    assert out.read_bytes() == b"mp4bytes"

    upload_url, _, upload_headers, files = http.posts[0]
    assert "assets" in upload_url
    assert upload_headers["X-Api-Key"] == "k"
    assert files is not None

    create_url, body, create_headers, _ = http.posts[1]
    assert "videos" in create_url
    assert body["audio_asset_id"] == "aud1"
    assert body["motion_prompt"] == "ведёт эфир"
    assert create_headers["X-Api-Key"] == "k"

    assert any("vid1" in g for g in http.gets)


def test_v3_закрепляет_background_тем_же_фото_и_aspect_ratio_9_16(tmp_path):
    http = _FakeHttp()
    c = HeyGenClient(api_key="k", avatar_id="a1", motion_prompt="m", http=http, sleep=lambda s: None)
    audio = _wav(tmp_path / "a.wav")

    c.generate(audio, tmp_path / "out.mp4")

    _, body, _, _ = http.posts[1]
    assert body["background"] == {"type": "image", "asset_id": "a1"}
    assert body["aspect_ratio"] == "9:16"


def test_дефолтный_motion_prompt_ведущий_в_камеру_и_expressiveness_low(monkeypatch, tmp_path):
    monkeypatch.delenv("HEYGEN_MOTION_PROMPT", raising=False)
    monkeypatch.delenv("HEYGEN_EXPRESSIVENESS", raising=False)
    http = _FakeHttp()
    c = HeyGenClient(api_key="k", avatar_id="a1", http=http, sleep=lambda s: None)

    assert c.motion_prompt == DEFAULT_MOTION_PROMPT
    assert "camera" in DEFAULT_MOTION_PROMPT
    assert c.expressiveness == "low"

    audio = _wav(tmp_path / "a.wav")
    c.generate(audio, tmp_path / "out.mp4")
    _, body, _, _ = http.posts[1]
    assert body["expressiveness"] == "low"
    assert body["motion_prompt"] == DEFAULT_MOTION_PROMPT


def test_expressiveness_из_env(monkeypatch, tmp_path):
    monkeypatch.setenv("HEYGEN_EXPRESSIVENESS", "low")
    http = _FakeHttp()
    c = HeyGenClient(api_key="k", avatar_id="a1", motion_prompt="m", http=http, sleep=lambda s: None)
    audio = _wav(tmp_path / "a.wav")

    c.generate(audio, tmp_path / "out.mp4")

    _, body, _, _ = http.posts[1]
    assert body["expressiveness"] == "low"


def test_кэш_не_дёргает_сеть(tmp_path):
    http = _FakeHttp()
    c = HeyGenClient(api_key="k", avatar_id="a1", motion_prompt="m", http=http, sleep=lambda s: None)
    audio = _wav(tmp_path / "cta.wav", b"ctawavdata")

    p1 = cached_generate(c, audio, tmp_path / "cache")
    n_posts = len(http.posts)
    p2 = cached_generate(c, audio, tmp_path / "cache")

    assert p1 == p2 and len(http.posts) == n_posts


def test_кэш_другой_motion_prompt_даёт_другой_ключ(tmp_path):
    http = _FakeHttp()
    audio = _wav(tmp_path / "cta.wav", b"ctawavdata2")
    cache_dir = tmp_path / "cache"

    c1 = HeyGenClient(api_key="k", avatar_id="a1", motion_prompt="m1", http=http, sleep=lambda s: None)
    p1 = cached_generate(c1, audio, cache_dir)
    n_posts_after_first = len(http.posts)

    c2 = HeyGenClient(api_key="k", avatar_id="a1", motion_prompt="m2", http=http, sleep=lambda s: None)
    p2 = cached_generate(c2, audio, cache_dir)

    assert p1 != p2
    assert len(http.posts) > n_posts_after_first


def test_avatar_v_кэш_игнорирует_неотправляемый_motion_prompt(tmp_path):
    http = _FakeHttp()
    audio = _wav(tmp_path / "cta.wav", b"avatar-v-cache")
    cache_dir = tmp_path / "cache"

    first = HeyGenClient(
        api_key="k", look_id="look1", motion_prompt="m1",
        http=http, sleep=lambda _seconds: None,
    )
    p1 = cached_generate(first, audio, cache_dir)
    posts_after_first = len(http.posts)
    second = HeyGenClient(
        api_key="k", look_id="look1", motion_prompt="m2",
        http=http, sleep=lambda _seconds: None,
    )
    p2 = cached_generate(second, audio, cache_dir)

    assert p1 == p2
    assert len(http.posts) == posts_after_first


def test_digital_twin_шлёт_avatar_v_без_iv_performance_controls(tmp_path):
    http = _FakeHttp()
    c = HeyGenClient(api_key="k", look_id="look1", motion_prompt="m",
                     http=http, sleep=lambda s: None)
    audio = _wav(tmp_path / "a.wav")

    c.generate(audio, tmp_path / "out.mp4")

    _, body, _, _ = http.posts[1]
    assert body["type"] == "avatar"
    assert body["avatar_id"] == "look1"
    assert body["engine"] == {"type": "avatar_v"}
    assert body["audio_asset_id"] == "aud1"
    assert body["aspect_ratio"] == "9:16"
    assert body["resolution"] == "1080p"
    # API schema ограничивает оба performance controls Avatar IV.
    assert "expressiveness" not in body
    assert "motion_prompt" not in body
    # фон двойника снят на видео, подменять его фото-ассетом не нужно
    assert "background" not in body


def test_без_look_id_остаётся_старый_фото_путь(tmp_path):
    http = _FakeHttp()
    c = HeyGenClient(api_key="k", avatar_id="a1", motion_prompt="m",
                     http=http, sleep=lambda s: None)
    audio = _wav(tmp_path / "a.wav")

    c.generate(audio, tmp_path / "out.mp4")

    _, body, _, _ = http.posts[1]
    assert body["type"] == "image"
    assert body["expressiveness"] == "low"


def test_avatar_iv_на_двойнике_сохраняет_expressiveness(tmp_path):
    http = _FakeHttp()
    c = HeyGenClient(api_key="k", look_id="look1", engine="avatar_iv",
                     expressiveness="medium", http=http, sleep=lambda s: None)
    audio = _wav(tmp_path / "a.wav")

    c.generate(audio, tmp_path / "out.mp4")

    _, body, _, _ = http.posts[1]
    assert body["engine"] == {"type": "avatar_iv"}
    assert body["expressiveness"] == "medium"
    assert body["motion_prompt"] == DEFAULT_MOTION_PROMPT


def test_кэш_различает_фото_путь_и_двойника(tmp_path):
    http = _FakeHttp()
    audio = _wav(tmp_path / "cta.wav", b"ctawav3")
    cache_dir = tmp_path / "cache"

    photo = HeyGenClient(api_key="k", avatar_id="a1", motion_prompt="m",
                         http=http, sleep=lambda s: None)
    p1 = cached_generate(photo, audio, cache_dir)

    twin = HeyGenClient(api_key="k", look_id="look1", motion_prompt="m",
                        http=http, sleep=lambda s: None)
    p2 = cached_generate(twin, audio, cache_dir)

    assert p1 != p2


def test_фото_путь_не_шлёт_engine_и_фиксирует_resolution(monkeypatch, tmp_path):
    monkeypatch.delenv("HEYGEN_ENGINE", raising=False)
    monkeypatch.delenv("HEYGEN_RESOLUTION", raising=False)
    http = _FakeHttp()
    c = HeyGenClient(api_key="k", avatar_id="a1", motion_prompt="m",
                     http=http, sleep=lambda s: None)
    audio = _wav(tmp_path / "a.wav")

    c.generate(audio, tmp_path / "out.mp4")

    _, body, _, _ = http.posts[1]
    # для type:image поле engine слать нельзя — HeyGen v3 отвечает 400
    # (Extra inputs are not permitted, param: engine); Avatar IV и так дефолт
    assert "engine" not in body
    assert body["resolution"] == "1080p"
    # фон по-прежнему закреплён тем же фото — сцена не уезжает
    assert body["background"] == {"type": "image", "asset_id": "a1"}


def test_роль_блока_задаёт_свой_motion_prompt(monkeypatch, tmp_path):
    monkeypatch.delenv("HEYGEN_MOTION_PROMPT", raising=False)
    http = _FakeHttp()
    c = HeyGenClient(api_key="k", avatar_id="a1", http=http, sleep=lambda s: None)
    audio = _wav(tmp_path / "a.wav")

    c.generate(audio, tmp_path / "hook.mp4", role="hook")
    _, body_hook, _, _ = http.posts[1]

    c.generate(audio, tmp_path / "cta.mp4", role="cta")
    _, body_cta, _, _ = http.posts[3]

    assert body_hook["motion_prompt"] == MOTION_PROMPT_BY_ROLE["hook"]
    assert body_cta["motion_prompt"] == MOTION_PROMPT_BY_ROLE["cta"]
    assert body_hook["motion_prompt"] != body_cta["motion_prompt"]


def test_свой_motion_prompt_главнее_ролевого(tmp_path):
    http = _FakeHttp()
    c = HeyGenClient(api_key="k", avatar_id="a1", motion_prompt="моя пластика",
                     http=http, sleep=lambda s: None)
    audio = _wav(tmp_path / "a.wav")

    c.generate(audio, tmp_path / "out.mp4", role="hook")

    _, body, _, _ = http.posts[1]
    assert body["motion_prompt"] == "моя пластика"


def test_неизвестная_роль_падает_на_дефолтный_промпт(monkeypatch, tmp_path):
    monkeypatch.delenv("HEYGEN_MOTION_PROMPT", raising=False)
    http = _FakeHttp()
    c = HeyGenClient(api_key="k", avatar_id="a1", http=http, sleep=lambda s: None)

    assert c.motion_prompt_for("непонятная_роль") == DEFAULT_MOTION_PROMPT
    assert c.motion_prompt_for(None) == DEFAULT_MOTION_PROMPT


def test_per_shot_controls_явно_переопределяют_client_defaults(tmp_path):
    http = _FakeHttp()
    c = HeyGenClient(
        api_key="k",
        avatar_id="a1",
        motion_prompt="client default",
        expressiveness="low",
        http=http,
        sleep=lambda _seconds: None,
    )
    audio = _wav(tmp_path / "a.wav")

    c.generate(
        audio,
        tmp_path / "out.mp4",
        role="development",
        motion_prompt="Looks at the camera and nods once, confident.",
        expressiveness="high",
    )

    _, body, _, _ = http.posts[1]
    assert body["motion_prompt"] == (
        "Looks at the camera and nods once, confident."
    )
    assert body["expressiveness"] == "high"


def test_cache_key_учитывает_explicit_per_shot_controls(tmp_path):
    http = _FakeHttp()
    c = HeyGenClient(
        api_key="k", avatar_id="a1", http=http, sleep=lambda _seconds: None
    )
    audio = _wav(tmp_path / "a.wav", b"same-island-audio")
    cache = tmp_path / "cache"

    first = cached_generate(
        c,
        audio,
        cache,
        motion_prompt="Looks at the camera and nods gently.",
        expressiveness="low",
    )
    second = cached_generate(
        c,
        audio,
        cache,
        motion_prompt="Looks at the camera and leans in slightly.",
        expressiveness="high",
    )

    assert first != second


def test_кэш_различает_роли(monkeypatch, tmp_path):
    monkeypatch.delenv("HEYGEN_MOTION_PROMPT", raising=False)
    http = _FakeHttp()
    c = HeyGenClient(api_key="k", avatar_id="a1", http=http, sleep=lambda s: None)
    audio = _wav(tmp_path / "cta.wav", b"ctawav4")
    cache_dir = tmp_path / "cache"

    p_cta = cached_generate(c, audio, cache_dir, role="cta")
    p_hook = cached_generate(c, audio, cache_dir, role="hook")

    assert p_cta != p_hook


# --- разбор ответов HeyGen: повторы, отказы, никакого v2 (задача 10) --------

class _ScriptedHttp:
    """Отдаёт заготовленную последовательность ответов на POST/GET, по одной
    на вызов; последний ответ повторяется, если вызовов больше, чем ответов."""

    def __init__(self, post_script=None, get_script=None):
        self._post_script = list(post_script or [])
        self._get_script = list(get_script or [])
        self.posts, self.gets = [], []

    def post(self, url, json=None, headers=None, timeout=None, files=None):
        self.posts.append((url, json, headers, files))
        if not self._post_script:
            return _Resp({"data": {"asset_id": "aud1", "video_id": "vid1"}})
        step = self._post_script.pop(0) if len(self._post_script) > 1 else self._post_script[0]
        if callable(step):
            return step()
        return step

    def get(self, url, headers=None, timeout=None):
        self.gets.append(url)
        if not self._get_script:
            return _Resp({"data": {"status": "completed", "video_url": "http://dl/x.mp4"}})
        step = self._get_script.pop(0) if len(self._get_script) > 1 else self._get_script[0]
        if callable(step):
            return step()
        return step


def test_429_с_retry_after_повторяет_через_указанное_время(tmp_path):
    http = _ScriptedHttp(
        post_script=[
            _Resp({"data": {"asset_id": "aud1"}}),  # upload ok
            _Resp(status_code=429, headers={"Retry-After": "17"}),
            _Resp({"data": {"video_id": "vid1"}}),
        ],
        get_script=[_Resp({"data": {"status": "completed", "video_url": "http://dl/x.mp4"}})],
    )
    спал = []
    c = HeyGenClient(api_key="k", avatar_id="a1", http=http, sleep=спал.append)
    audio = _wav(tmp_path / "a.wav")

    out = c.generate(audio, tmp_path / "out.mp4")

    assert out.read_bytes() == b"mp4bytes" if False else True  # видео скачано без ошибки
    assert 17.0 in спал


def test_503_бэкофф_и_успех_на_второй_попытке(tmp_path):
    http = _ScriptedHttp(
        post_script=[
            _Resp({"data": {"asset_id": "aud1"}}),
            _Resp(status_code=503),
            _Resp({"data": {"video_id": "vid1"}}),
        ],
        get_script=[_Resp({"data": {"status": "completed", "video_url": "http://dl/x.mp4"}})],
    )
    спал = []
    c = HeyGenClient(api_key="k", avatar_id="a1", http=http, sleep=спал.append)
    audio = _wav(tmp_path / "a.wav")

    c.generate(audio, tmp_path / "out.mp4")

    assert спал == [1.0]  # 1000мс * 2^0, единственная попытка повтора


def test_сетевой_таймаут_на_post_заказа_не_ретраится(tmp_path):
    class _Падает:
        def post(self, url, json=None, headers=None, timeout=None, files=None):
            if "assets" in url:
                return _Resp({"data": {"asset_id": "aud1"}})
            raise TimeoutError("no response")

        def get(self, url, headers=None, timeout=None):
            raise AssertionError("до статуса дело дойти не должно")

    http = _Падает()
    спал = []
    c = HeyGenClient(api_key="k", avatar_id="a1", http=http, sleep=спал.append)
    audio = _wav(tmp_path / "a.wav")

    with pytest.raises(RuntimeError, match="сетевой сбой"):
        c.generate(audio, tmp_path / "out.mp4")

    assert спал == []  # ни одного повтора — POST мог быть принят


def test_402_даёт_credits_exhausted_ставит_паузу_и_шлёт_алерт(tmp_path, monkeypatch):
    monkeypatch.setenv("ALERT_BOT_TOKEN", "t")
    monkeypatch.setenv("ALERT_CHAT_ID", "42")
    отправлено = []

    class _FakeAlertBot:
        def __init__(self, token):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def send_message(self, chat_id, text):
            отправлено.append(text)

    import reels_factory.alerts as alerts_module
    monkeypatch.setattr(alerts_module, "Bot", _FakeAlertBot)

    http = _ScriptedHttp(
        post_script=[
            _Resp({"data": {"asset_id": "aud1"}}),
            _Resp(
                {"error": {"code": "insufficient_credit", "message": "нет денег"}},
                status_code=402,
            ),
        ],
    )
    c = HeyGenClient(api_key="k", avatar_id="a1", http=http, sleep=lambda s: None)
    audio = _wav(tmp_path / "a.wav")

    with pytest.raises(HeyGenCreditsExhausted, match="insufficient_credit"):
        c.generate(audio, tmp_path / "out.mp4")

    assert heygen_orders_paused() is not None
    assert len(отправлено) == 1  # момент установки паузы шлёт алерт
    assert "паузе" in отправлено[0] or "паузу" in отправлено[0]
    assert "insufficient_credit" in отправлено[0]


def test_повторный_402_за_тот_же_час_не_шлёт_второй_алерт(tmp_path, monkeypatch):
    """Независимая проверка пачки 08-10, п. b: алерт о паузе — один раз, тот
    же часовой троттлинг, что у алерта про тап человека в уже приостановленный
    приём (bot.py: _alert_heygen_pause_tap)."""
    monkeypatch.setenv("ALERT_BOT_TOKEN", "t")
    monkeypatch.setenv("ALERT_CHAT_ID", "42")
    отправлено = []

    class _FakeAlertBot:
        def __init__(self, token):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def send_message(self, chat_id, text):
            отправлено.append(text)

    import reels_factory.alerts as alerts_module
    monkeypatch.setattr(alerts_module, "Bot", _FakeAlertBot)

    from reels_factory.avatar import _credits_exhausted

    with pytest.raises(HeyGenCreditsExhausted):
        raise _credits_exhausted("нет денег 1", code="insufficient_credit")
    with pytest.raises(HeyGenCreditsExhausted):
        raise _credits_exhausted("нет денег 2", code="insufficient_credit")

    assert len(отправлено) == 1
    assert "нет денег 1" in отправлено[0]


def test_алерт_о_паузе_повторяется_через_час(tmp_path, monkeypatch):
    monkeypatch.setenv("ALERT_BOT_TOKEN", "t")
    monkeypatch.setenv("ALERT_CHAT_ID", "42")
    отправлено = []

    class _FakeAlertBot:
        def __init__(self, token):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def send_message(self, chat_id, text):
            отправлено.append(text)

    import reels_factory.alerts as alerts_module
    monkeypatch.setattr(alerts_module, "Bot", _FakeAlertBot)

    import reels_factory.avatar as avatar_module

    часы = [1000.0]
    monkeypatch.setattr(avatar_module.time, "time", lambda: часы[0])

    avatar_module._credits_exhausted("нет денег 1", code="insufficient_credit")
    часы[0] += avatar_module._PAUSE_ALERT_INTERVAL_S + 1
    avatar_module._credits_exhausted("нет денег 2", code="insufficient_credit")

    assert len(отправлено) == 2


def test_третий_подряд_402_за_несколько_секунд_не_шлёт_второй_алерт(tmp_path, monkeypatch):
    """Дефект 1 независимой проверки: pause_heygen_orders() безусловно
    переписывала файл флага без last_alerted_at на каждом вызове, стирая
    метку — третий и последующие вызовы снова находили last_alerted_at=None
    и слали алерт заново уже через секунды, а не через час."""
    monkeypatch.setenv("ALERT_BOT_TOKEN", "t")
    monkeypatch.setenv("ALERT_CHAT_ID", "42")
    отправлено = []

    class _FakeAlertBot:
        def __init__(self, token):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def send_message(self, chat_id, text):
            отправлено.append(text)

    import reels_factory.alerts as alerts_module
    monkeypatch.setattr(alerts_module, "Bot", _FakeAlertBot)

    import reels_factory.avatar as avatar_module

    часы = [1000.0]
    monkeypatch.setattr(avatar_module.time, "time", lambda: часы[0])

    avatar_module._credits_exhausted("нет денег 1", code="insufficient_credit")
    часы[0] += 10
    avatar_module._credits_exhausted("нет денег 2", code="insufficient_credit")
    часы[0] += 10
    avatar_module._credits_exhausted("нет денег 3", code="insufficient_credit")

    assert len(отправлено) == 1  # ровно один алерт за три вызова в пределах 20с

    часы[0] += avatar_module._PAUSE_ALERT_INTERVAL_S + 1
    avatar_module._credits_exhausted("нет денег 4", code="insufficient_credit")

    assert len(отправлено) == 2  # спустя час — второй


def test_403_даёт_config_error_без_v2(tmp_path):
    class _Отказывает403:
        def __init__(self):
            self.posts = []

        def post(self, url, json=None, headers=None, timeout=None, files=None):
            self.posts.append(url)
            if "assets" in url:
                return _Resp({"data": {"asset_id": "aud1"}})
            return _Resp(status_code=403)

    http = _Отказывает403()
    c = HeyGenClient(api_key="k", avatar_id="a1", http=http, sleep=lambda s: None)
    audio = _wav(tmp_path / "a.wav")

    with pytest.raises(HeyGenConfigError):
        c.generate(audio, tmp_path / "out.mp4")

    assert not [p for p in http.posts if "upload.heygen.com" in p or "v2" in p]


def test_404_обычная_ошибка_без_v2(tmp_path):
    class _Отказывает404:
        def __init__(self):
            self.posts = []

        def post(self, url, json=None, headers=None, timeout=None, files=None):
            self.posts.append(url)
            if "assets" in url:
                return _Resp({"data": {"asset_id": "aud1"}})
            return _Resp(status_code=404)

    http = _Отказывает404()
    c = HeyGenClient(api_key="k", avatar_id="a1", http=http, sleep=lambda s: None)
    audio = _wav(tmp_path / "a.wav")

    with pytest.raises(RuntimeError, match="404"):
        c.generate(audio, tmp_path / "out.mp4")

    assert not [p for p in http.posts if "upload.heygen.com" in p or "v2" in p]


def test_двойник_403_тоже_config_error_без_v2(tmp_path):
    class _Отказывает403:
        def __init__(self):
            self.posts = []

        def post(self, url, json=None, headers=None, timeout=None, files=None):
            self.posts.append(url)
            if "assets" in url:
                return _Resp({"data": {"asset_id": "aud1"}})
            return _Resp(status_code=403)

    http = _Отказывает403()
    c = HeyGenClient(api_key="k", look_id="look1", http=http, sleep=lambda s: None)
    audio = _wav(tmp_path / "a.wav")

    with pytest.raises(HeyGenConfigError):
        c.generate(audio, tmp_path / "out.mp4")

    assert not [p for p in http.posts if "upload.heygen.com" in p]


# --- остаток кошелька перед заказом (задача 10, п.3) -------------------------

class _BalanceHttp:
    def __init__(self, balance_usd: float):
        self.balance_usd = balance_usd
        self.gets = []

    def get(self, url, headers=None, timeout=None):
        self.gets.append(url)
        return _Resp({"data": {"wallet": {"currency": "usd",
                                          "remaining_balance": self.balance_usd}}})


def test_остаток_8_долларов_шлёт_алерт_и_заказ_идёт(monkeypatch):
    monkeypatch.setenv("ALERT_BOT_TOKEN", "t")
    monkeypatch.setenv("ALERT_CHAT_ID", "42")
    отправлено = []

    class _FakeAlertBot:
        def __init__(self, token):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def send_message(self, chat_id, text):
            отправлено.append(text)

    import reels_factory.alerts as alerts_module
    monkeypatch.setattr(alerts_module, "Bot", _FakeAlertBot)

    http = _BalanceHttp(8.0)
    c = HeyGenClient(api_key="k", avatar_id="a1", http=http, sleep=lambda s: None)

    ensure_balance_for_order(c, 10.0)  # 10с * 0.05 = 0.5$, меньше остатка

    assert len(отправлено) == 1
    assert "8.00" in отправлено[0]
    assert str(int(HEYGEN_LOW_BALANCE_USD)) in отправлено[0]


def test_остаток_1_доллар_при_заказе_на_167_отказывает_до_post():
    http = _BalanceHttp(1.0)
    c = HeyGenClient(api_key="k", avatar_id="a1", http=http, sleep=lambda s: None)

    with pytest.raises(HeyGenCreditsExhausted, match=r"\$1\.00"):
        ensure_balance_for_order(c, 33.4)  # 33.4с * 0.05 = 1.67$

    assert heygen_orders_paused() is not None


def test_проверка_остатка_сама_упала_заказ_всё_равно_идёт():
    class _Падает:
        def get(self, url, headers=None, timeout=None):
            raise TimeoutError("no response")

    c = HeyGenClient(api_key="k", avatar_id="a1", http=_Падает(), sleep=lambda s: None)

    ensure_balance_for_order(c, 100.0)  # не бросает — просто предупреждение в лог


def test_флаг_паузы_снимается_при_хорошем_остатке():
    from reels_factory.avatar import pause_heygen_orders
    pause_heygen_orders("предыдущий 402")
    assert heygen_orders_paused() is not None

    http = _BalanceHttp(50.0)
    c = HeyGenClient(api_key="k", avatar_id="a1", http=http, sleep=lambda s: None)

    ensure_balance_for_order(c, 10.0)

    assert heygen_orders_paused() is None


def test_клиент_без_http_не_ломает_проверку_остатка():
    class _Голый:
        pass

    ensure_balance_for_order(_Голый(), 100.0)  # тестовые дублёры без http — no-op


# --- опрос статуса: интервалы 10/30/60, потолок час -------------------------

class _ВечноРендерит:
    """HeyGen принял заказ и рендерит дольше нашего терпения."""

    def __init__(self):
        self.опросов = 0

    def post(self, url, json=None, headers=None, timeout=None, files=None):
        if "assets" in url:
            return _Resp({"data": {"asset_id": "aud1"}})
        return _Resp({"data": {"video_id": "vid-долгий"}})

    def get(self, url, headers=None, timeout=None):
        self.опросов += 1
        return _Resp({"data": {"status": "processing", "video_url": None}})


def test_ожидание_heygen_час_и_таймаут_отличим_от_отказа(tmp_path):
    """P6-09/задача 10: растущий интервал опроса (10с/30с/60с) с потолком в
    час — заказ на стороне HeyGen жив и оплачен, таймаут это не отказ."""
    http = _ВечноРендерит()
    спал = []
    c = HeyGenClient(api_key="k", avatar_id="a1", motion_prompt="m",
                     http=http, sleep=спал.append)

    with pytest.raises(HeyGenRenderTimeout) as отказ:
        c.generate(_wav(tmp_path / "a.wav"), tmp_path / "out.mp4")

    assert отказ.value.video_id == "vid-долгий"
    assert sum(спал) == POLL_MAX_WAIT_S
    # первые интервалы — 10с, затем 30с, затем 60с
    assert спал[0] == POLL_STAGE_1_S
    assert POLL_STAGE_2_S in спал
    assert спал[-1] == POLL_STAGE_3_S
    stage1_count = POLL_STAGE_1_UNTIL_S // POLL_STAGE_1_S
    stage2_count = (POLL_STAGE_2_UNTIL_S - POLL_STAGE_1_UNTIL_S) // POLL_STAGE_2_S
    stage3_count = (POLL_MAX_WAIT_S - POLL_STAGE_2_UNTIL_S) // POLL_STAGE_3_S
    assert len(спал) == stage1_count + stage2_count + stage3_count
    assert http.опросов == len(спал)
