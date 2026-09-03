"""Наш каталог блоков, отданный агенту их способом — через поле registry."""
import json

import pytest

from reels_factory.hf_catalog import (
    CATALOG_DIR, REGISTRY_SUBDIR, block_names, component_names, overlay_names,
    serve_catalog, texture_overlays, write_project_config,
)

#: 12 блоков работы B1 (10 вертикальных сцен + 2 накладки-перехода) — те, что
#: физически лежат в `catalog/registry/blocks`, но реестра их клона в нашем
#: репозитории нет, поэтому имена перечислены явно.
_B1_BLOCKS = ["ai-chat-reveal", "chatgpt-exchange", "claude-exchange",
              "flowchart-vertical", "heygen-avatar-promo-card",
              "message-thread-reveal", "notes-reveal", "notification-cascade",
              "share-sheet-carousel", "slack-notification-ad",
              "hw-scribble-transition", "mk-clone-wall-transition"]

REGISTRY = {"$schema": "https://hyperframes.heygen.com/schema/registry.json",
            "name": "golden", "items": [{"name": "g01", "type": "hyperframes:block"}]}


def _catalog(tmp_path):
    root = tmp_path / "registry"
    root.mkdir(parents=True)
    (root / "registry.json").write_text(json.dumps(REGISTRY), encoding="utf-8")
    return tmp_path


def _block(root, name, *, tags, files=()):
    folder = root / "registry" / "blocks" / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.html").write_text("<div></div>", encoding="utf-8")
    listed = [{"path": f"{name}.html"}] + [{"path": p} for p in files]
    (folder / "registry-item.json").write_text(
        json.dumps({"name": name, "tags": list(tags), "files": listed}),
        encoding="utf-8")
    return folder


def _with_blocks(tmp_path, names):
    root = tmp_path / "registry"
    root.mkdir(parents=True, exist_ok=True)
    (root / "registry.json").write_text(json.dumps(
        {"name": "golden",
         "items": [{"name": n, "type": "hyperframes:block"} for n in names]}),
        encoding="utf-8")
    return tmp_path


def test_накладка_с_недостающим_файлом_агенту_не_предлагается(tmp_path, capsys):
    """`hyperframes add` тянет каждый файл из карточки блока и на 404 роняет
    всю попытку сборки. Прогон 28 потерял так попытку на `instagram-follow`:
    в каталог не переехал его `assets/avatar.jpg`. Исправить это агент не
    может — дефект каталога, а не плана."""
    _with_blocks(tmp_path, ["ок-блок", "битый-блок"])
    _block(tmp_path, "ок-блок", tags=["overlay"])
    _block(tmp_path, "битый-блок", tags=["overlay"], files=["assets/avatar.jpg"])
    assert overlay_names(tmp_path) == ["ок-блок"]
    assert "битый-блок" in capsys.readouterr().out


def test_накладка_со_смешанным_заголовком_не_предлагается():
    """`news-ticker`: заголовок — свой текст `h1` плюс акцентный `<span>`, а их
    `setOwnText` при единственном потомке пишет значение внутрь него
    (`packages/sdk/src/engine/model.ts:338-345` на v0.7.84). Текст агента
    уезжает в акцент и снимается вместе с ним как незаполненный слот, демо-
    строки `h1` остаются в кадре — D22 валит сборку при любом заполнении, и
    починить это агенту нечем."""
    from reels_factory.hf_catalog import skipped_blocks

    assert "news-ticker" in skipped_blocks()
    assert "news-ticker" not in overlay_names()


def test_фактуры_отличаются_меткой_их_реестра(tmp_path):
    """Канвас у фактуры и плашки один — 1920x1080; кроет кадр целиком только
    фактура, и различает их метка, которую блоки принесли из их реестра."""
    _with_blocks(tmp_path, ["протечка", "плашка"])
    _block(tmp_path, "протечка", tags=["overlay", "media-treatment-overlay"])
    _block(tmp_path, "плашка", tags=["overlay", "lower-third"])
    assert texture_overlays(tmp_path) == {"протечка"}


def test_конфиг_ложится_в_обе_папки(tmp_path):
    paths = write_project_config(tmp_path, "http://127.0.0.1:9999")
    assert [p.parent.name for p in paths] == [tmp_path.name, "public"]
    for path in paths:
        assert json.loads(path.read_text(encoding="utf-8"))["registry"] == \
            "http://127.0.0.1:9999"


def test_блоки_приземляются_внутрь_public(tmp_path):
    """Композиция не должна ссылаться на файл за пределами своей папки."""
    root, public = write_project_config(tmp_path, "http://127.0.0.1:9999")
    assert json.loads(root.read_text(encoding="utf-8"))["paths"]["blocks"] == \
        "public/compositions"
    assert json.loads(public.read_text(encoding="utf-8"))["paths"]["blocks"] == \
        "compositions"


def test_каталог_отдаётся_по_http(tmp_path):
    """Их CLI тянет реестр через fetch — файловый путь туда положить нельзя."""
    import urllib.request

    with serve_catalog(_catalog(tmp_path)) as url:
        with urllib.request.urlopen(f"{url}/registry.json", timeout=5) as response:
            assert json.loads(response.read())["items"][0]["name"] == "g01"


def test_без_разложенного_реестра_сборка_не_начинается(tmp_path):
    import pytest

    with pytest.raises(RuntimeError, match="реестр"):
        with serve_catalog(tmp_path):
            pass


def _card(kind_dir: str, name: str) -> dict:
    root = CATALOG_DIR / REGISTRY_SUBDIR
    return json.loads((root / kind_dir / name / "registry-item.json")
                      .read_text(encoding="utf-8"))


def test_блоки_работы_b1_несут_reels_kind():
    """Каждая карточка, добавленная импортом 13 вертикальных блоков и 3
    накладок (работа B1), несёт `reels.kind` — без него B2 нечем судить, на
    весь кадр её ставить, на стык или в зону."""
    for name in _B1_BLOCKS:
        kind = _card("blocks", name).get("reels", {}).get("kind")
        assert kind in ("scene", "overlay", "effect"), name


def test_каждый_компонент_несёт_reels_effect_и_контракт_монтажа():
    names = component_names()
    assert len(names) > 100, "компоненты не разложены реестром"
    for name in names:
        reels = _card("components", name).get("reels", {})
        assert reels.get("kind") == "effect", name
        assert reels.get("mount") in ("composition", "paste"), name


def test_block_names_не_включает_компоненты():
    """`block_names` открывает файл по пути `blocks/<имя>` — отдай он имя
    компонента, следующий читатель (`block_backing`, `skipped_blocks`, …)
    получил бы `FileNotFoundError` на `blocks/count-up`."""
    blocks = set(block_names())
    comps = set(component_names())
    assert not (blocks & comps)
    assert "count-up" in comps and "count-up" not in blocks


def test_overlay_names_не_отдаёт_компоненты_и_новые_сцены_как_плашки():
    """Компонент не тегирован их полем `tags` вовсе (он лежит в другой папке
    и `overlay_names` его не видит), а наши новые вертикальные сцены не несут
    тег `overlay` — обе причины проверяем прямо на живом каталоге."""
    names = overlay_names()
    comps = set(component_names())
    assert not (set(names) & comps)
    for name in ("ai-chat-reveal", "chatgpt-exchange", "heygen-avatar-promo-card",
                 "notification-cascade"):
        assert name not in names


@pytest.mark.slow
def test_add_реально_ставит_сцену_накладку_и_компонент(tmp_path):
    """`hyperframes add` — единственный способ их CLI забрать карточку из
    реестра, и он смотрит по путям `hyperframes.json#paths`, не по нашей
    раскладке диска. Живой вызов на одной сцене, одной накладке и одном
    компоненте — доказательство, что наш HTTP-реестр отдаёт их ровно там, где
    `add` их ищет (что для сцены/накладки, что для компонента —
    `compositions/` и `compositions/components/`)."""
    from reels_factory.hf_render import _cli

    with serve_catalog() as url:
        write_project_config(tmp_path, url)
        for name in ("heygen-avatar-promo-card", "hw-scribble-transition", "count-up"):
            _cli("add", name, "--no-clipboard", cwd=tmp_path)

    assert (tmp_path / "public" / "compositions"
            / "heygen-avatar-promo-card.html").exists()
    assert (tmp_path / "public" / "compositions"
            / "hw-scribble-transition.html").exists()
    assert (tmp_path / "public" / "compositions" / "components"
            / "count-up.html").exists()
