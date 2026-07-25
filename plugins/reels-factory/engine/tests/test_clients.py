import pytest

from reels_factory import clients
from reels_factory.config import ConfigError


def _base(**over):
    """Минимальный валидный конфиг-шаблон (проходит load_config для формата avatar)."""
    b = {
        "theme": "ИИ-агенты",
        "format": "avatar",
        "voice_id": "V_BASE",
        "persona": {"description": "ведущий канала"},
        "product": {"name": "Prod", "cta_phrase": "подпишись"},
        "avatar": {"heygen_look_id": "LOOK_BASE"},
    }
    b.update(over)
    return b


@pytest.fixture(autouse=True)
def _isolate_registry(tmp_path, monkeypatch):
    # каждый тест — свой пустой реестр во временной папке
    monkeypatch.setattr(clients, "CLIENTS_DIR", tmp_path / "clients")


def test_register_создаёт_video_профиль_и_list_видит_его():
    path = clients.register_client("ivan", _base(), name="Иван",
                                   voice_id="V1", look_id="LOOK1")
    assert path.exists()

    got = clients.load_client("ivan")
    assert got["voice_id"] == "V1"
    assert got["avatar"]["heygen_look_id"] == "LOOK1"

    row = next(r for r in clients.list_clients() if r["id"] == "ivan")
    assert row["mode"] == "video"
    assert row["voice_id"] == "V1"
    assert row["name"] == "Иван"


def test_register_photo_режим_по_asset_id_вытесняет_look_из_базы():
    # база с двойником (look_id), но клиента заводим по фото — look_id должен уйти,
    # иначе режим ошибочно останется video
    clients.register_client("anna", _base(), voice_id="V2", asset_id="ASSET1")

    got = clients.load_client("anna")
    assert got["avatar"]["heygen_asset_id"] == "ASSET1"
    assert "heygen_look_id" not in got["avatar"]
    assert clients.avatar_mode(got) == "photo"


def test_look_id_вытесняет_asset_id_режим_явный():
    base = _base(avatar={"heygen_asset_id": "OLD_PHOTO"})
    clients.register_client("mix", base, voice_id="V", look_id="NEWLOOK")

    got = clients.load_client("mix")
    assert got["avatar"]["heygen_look_id"] == "NEWLOOK"
    assert "heygen_asset_id" not in got["avatar"]  # video главнее фото


def test_повторный_register_без_overwrite_падает_с_overwrite_заменяет():
    clients.register_client("dup", _base(), voice_id="V", look_id="L1")
    with pytest.raises(ConfigError, match="уже есть"):
        clients.register_client("dup", _base(), voice_id="V", look_id="L2")

    clients.register_client("dup", _base(), voice_id="V", look_id="L2", overwrite=True)
    assert clients.load_client("dup")["avatar"]["heygen_look_id"] == "L2"


def test_load_client_несуществующего_падает():
    with pytest.raises(ConfigError, match="не найден"):
        clients.load_client("ghost")


def test_register_без_аватара_падает():
    with pytest.raises(ConfigError, match="[Аа]ватар"):
        clients.register_client("noav", _base(avatar={}), voice_id="V")


def test_невалидный_профиль_не_остаётся_в_реестре():
    # база без обязательного voice_id и без override голоса → запись не пройдёт
    # валидацию load_config и файл не должен остаться
    bad = _base()
    bad.pop("voice_id")
    with pytest.raises(ConfigError):
        clients.register_client("broken", bad, look_id="L")
    assert not clients.client_path("broken").exists()


def test_недопустимый_client_id_отвергается():
    for bad in ["", "../evil", "a/b", ".hidden"]:
        with pytest.raises(ConfigError):
            clients.client_path(bad)


def test_list_пустого_реестра_пустой():
    assert clients.list_clients() == []


def test_clear_client_voice_убирает_voice_id_но_не_ломает_аватар():
    import yaml

    clients.register_client("ivan", _base(), name="Иван", voice_id="V1", look_id="LOOK1")

    clients.clear_client_voice("ivan")

    cfg = yaml.safe_load(clients.client_path("ivan").read_text(encoding="utf-8"))
    assert "voice_id" not in cfg
    assert cfg["avatar"]["heygen_look_id"] == "LOOK1"
    # без voice_id профиль честно неполон — падает, а не 404 в ElevenLabs
    with pytest.raises(ConfigError, match="voice_id"):
        clients.load_client("ivan")


def test_clear_client_voice_молчит_если_клиента_нет():
    clients.clear_client_voice("нет-такого")  # не должно падать


def test_clear_client_voice_убирает_только_активный_языковой_голос():
    import yaml

    clients.register_client(
        "ivan",
        _base(
            language="ru",
            voice_language="ru",
            voices={"ru": "V1", "kk": "V2"},
        ),
        voice_id="V1",
        look_id="LOOK1",
    )

    clients.clear_client_voice("ivan")

    cfg = yaml.safe_load(
        clients.client_path("ivan").read_text(encoding="utf-8")
    )
    assert "voice_id" not in cfg and "voice_language" not in cfg
    assert cfg["voices"] == {"kk": "V2"}
    assert cfg["avatar"]["heygen_look_id"] == "LOOK1"


def test_list_clients_показывает_карту_голосов_и_активный_язык():
    clients.register_client(
        "ivan",
        _base(
            language="ru",
            voice_language="ru",
            voices={"ru": "V1", "kk": "V2"},
        ),
        voice_id="V1",
        look_id="LOOK1",
    )

    row = next(r for r in clients.list_clients() if r["id"] == "ivan")

    assert row["voice_language"] == "ru"
    assert row["voices"] == {"ru": "V1", "kk": "V2"}


def test_clear_client_voice_другого_языка_не_сбрасывает_активный():
    clients.register_client(
        "ivan",
        _base(
            language="ru",
            voice_language="ru",
            voices={"ru": "V1", "kk": "V2"},
        ),
        voice_id="V1",
        look_id="LOOK1",
    )

    clients.clear_client_voice("ivan", language="kk")

    cfg = clients.load_client("ivan")
    assert cfg["voice_id"] == "V1"
    assert cfg["voice_language"] == "ru"
    assert cfg["voices"] == {"ru": "V1"}
