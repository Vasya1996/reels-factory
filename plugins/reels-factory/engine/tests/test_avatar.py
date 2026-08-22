from pathlib import Path

import pytest

from reels_factory.avatar import (DEFAULT_MOTION_PROMPT, MOTION_PROMPT_BY_ROLE,
                                  POLL_MAX_ITERATIONS, UPLOAD_URL,
                                  HeyGenClient, HeyGenRenderTimeout,
                                  cached_generate, upload_photo_asset)


class _Resp:
    def __init__(self, payload=None, content=b""):
        self._p, self.content = payload, content

    def json(self):
        return self._p

    def raise_for_status(self):
        pass


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


# --- загрузка фото аватара (upload_photo_asset) ------------------------------

class _FakeUpload:
    """Только аплоад ассета: запоминает запрос, отдаёт заданный ответ."""

    def __init__(self, payload=None, status=200):
        self.payload = payload if payload is not None else {"data": {"asset_id": "img_123"}}
        self.status, self.posts = status, []

    def post(self, url, headers=None, files=None, timeout=None, **kw):
        self.posts.append((url, headers, files, timeout))
        return _RespWithStatus(self.payload, status_code=self.status)


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
        upload_photo_asset(_photo(tmp_path), api_key="K1", http=http)


def test_ответ_без_asset_id_понятная_ошибка(tmp_path):
    http = _FakeUpload(payload={"data": {}})

    with pytest.raises(RuntimeError, match="не вернул asset_id"):
        upload_photo_asset(_photo(tmp_path), api_key="K1", http=http)


class _RespWithStatus(_Resp):
    def __init__(self, payload=None, content=b"", status_code=200):
        super().__init__(payload, content)
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeHttpV3Forbidden:
    """Все v3-запросы (включая аплоад) отвечают 403 → должен сработать фолбэк на v2."""

    def __init__(self):
        self.posts, self.gets, self._n = [], [], 0

    def post(self, url, json=None, headers=None, timeout=None, files=None, data=None):
        self.posts.append((url, json, headers, files, data))
        if "v3" in url:
            return _RespWithStatus(status_code=403)
        if "upload.heygen.com" in url:
            return _RespWithStatus({"data": {"asset_id": "aud2"}})
        return _RespWithStatus({"data": {"video_id": "vid2"}})

    def get(self, url, headers=None, timeout=None):
        self.gets.append(url)
        if "video_status" in url:
            self._n += 1
            st = "processing" if self._n < 2 else "completed"
            return _RespWithStatus({"data": {"status": st, "video_url": "http://dl/y.mp4"}})
        return _RespWithStatus(content=b"mp4bytes2")


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


def test_v3_403_на_аплоаде_переключает_на_v2_без_повторного_захода_в_v3(tmp_path):
    http = _FakeHttpV3Forbidden()
    c = HeyGenClient(api_key="k", avatar_id="a1", motion_prompt="m", http=http, sleep=lambda s: None)
    audio = _wav(tmp_path / "a.wav")

    out = c.generate(audio, tmp_path / "out.mp4")

    assert out.read_bytes() == b"mp4bytes2"

    v3_calls = [p for p in http.posts if "v3" in p[0]]
    assert len(v3_calls) == 1  # только неудавшийся аплоад, повторного захода в v3 нет

    v2_upload_calls = [p for p in http.posts if "upload.heygen.com" in p[0]]
    assert len(v2_upload_calls) == 1

    v2_create_calls = [p for p in http.posts if "v2/video/generate" in p[0]]
    assert len(v2_create_calls) == 1
    assert v2_create_calls[0][1]["video_inputs"][0]["voice"]["audio_asset_id"] == "aud2"

    assert any("video_status" in g for g in http.gets)


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


def test_двойник_не_деградирует_молча_до_v2_при_403(tmp_path):
    import pytest

    http = _FakeHttpV3Forbidden()
    c = HeyGenClient(api_key="k", look_id="look1", http=http, sleep=lambda s: None)
    audio = _wav(tmp_path / "a.wav")

    with pytest.raises(RuntimeError, match="Digital Twin"):
        c.generate(audio, tmp_path / "out.mp4")

    assert not [p for p in http.posts if "upload.heygen.com" in p[0]]


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


def test_ожидание_heygen_полчаса_и_таймаут_отличим_от_отказа(tmp_path):
    """P6-09: потолок ожидания был 10 минут, а таймаут приходил тем же
    `RuntimeError`, что и отказ рендера. Заказ на их стороне жив и оплачен —
    отличить его от несостоявшегося было нечем, и обе ветки вели к повторному
    заказу за те же деньги."""
    http = _ВечноРендерит()
    спал = []
    c = HeyGenClient(api_key="k", avatar_id="a1", motion_prompt="m",
                     http=http, sleep=спал.append)

    with pytest.raises(HeyGenRenderTimeout) as отказ:
        c.generate(_wav(tmp_path / "a.wav"), tmp_path / "out.mp4")

    assert отказ.value.video_id == "vid-долгий"
    assert sum(спал) >= 1800, "ждём заказ не меньше получаса"
    assert http.опросов == POLL_MAX_ITERATIONS
