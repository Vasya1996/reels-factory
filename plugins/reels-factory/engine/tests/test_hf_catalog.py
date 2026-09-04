"""Наш каталог блоков, отданный агенту их способом — через поле registry."""
import json
import re
from pathlib import Path

import pytest

from reels_factory.hf_catalog import (
    CATALOG_DIR, REGISTRY_SUBDIR, block_names, catalog_cards, catalog_index,
    component_names, decor_texts, overlay_names, serve_catalog, skipped_blocks,
    texture_overlays, write_catalog_files, write_project_config,
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


# ---------- индекс каталога для агента ----------

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "catalog"


def test_индекс_отдаёт_карточки_всех_трёх_видов():
    """Формат — их же `catalog --json` плюс наши поля: агент ищет по описанию и
    тегам, а вид позиции говорит коду, чем она станет в кадре."""
    cards = catalog_cards(FIXTURE)
    assert {name: card.get("kind") for name, card in cards.items()} == {
        "count-up": "effect", "demo-scene": "scene", "demo-stitch": "overlay",
        # Карточка без `reels.kind` — сегодняшняя плашка: вид у неё не объявлен.
        "demo-plain": None}
    поля = set(cards["demo-scene"])
    assert {"name", "type", "title", "description", "tags", "dimensions",
            "duration"} <= поля, "формат разошёлся с `catalog --json`"
    assert cards["demo-scene"]["text_slots"] == ["line"]
    assert cards["count-up"]["variables"]["end"] == {"type": "number",
                                                     "default": 100}
    # У упругой позиции размеров нет вовсе — она меряет себя коробкой хоста.
    assert "dimensions" not in cards["count-up"]


def test_позиция_с_причиной_отказа_в_индекс_не_попадает(capsys):
    """Причина отказа записана в карточке, и агенту такую позицию не
    предлагают: исправить её он не может — это дефект каталога, а не плана."""
    assert "demo-skip" not in catalog_cards(FIXTURE)
    assert "demo-skip" in skipped_blocks(FIXTURE)
    assert "demo-skip" in capsys.readouterr().out


def test_карточка_без_вида_остаётся_плашкой_по_старому_правилу():
    """Обратная совместимость: пока вид в карточке не объявлен, позиция живёт
    по нынешнему правилу — тег `overlay` и старое поле плана."""
    assert overlay_names(FIXTURE) == ["demo-plain"]
    assert catalog_cards(FIXTURE)["demo-plain"].get("kind") is None


def test_индекс_печатается_json_ом_с_нашими_полями():
    text = catalog_index(FIXTURE)
    body = json.loads(text.split("```json")[1].split("```")[0])
    assert [item["name"] for item in body] == sorted(
        ["count-up", "demo-plain", "demo-scene", "demo-stitch"])
    assert "Search by intent" not in text, "правило поиска живёт в своде правил"
    assert "`kind`" in text and "`text_slots`" in text and "`variables`" in text


def test_рисованный_текст_читается_из_карточки():
    """Белый список гейта заглушек живёт в карточке, а не литералом в коде."""
    assert decor_texts(FIXTURE) == {"demo-stitch": {"Заголовок"}}


def test_индекс_и_справочники_кладутся_рядом_с_заданием(tmp_path):
    written = write_catalog_files(tmp_path, FIXTURE)
    assert (tmp_path / "catalog.index.md").exists()
    assert [path.name for path in written][0] == "catalog.index.md"


def test_справочники_фреймворка_лежат_в_репозитории():
    """Клона фреймворка на проде нет, поэтому полка и карта категорий едут
    копиями в каталоге — как и сам каталог блоков."""
    from reels_factory.hf_catalog import (
        CATALOG_DIR, REFERENCE_FILES, REFERENCE_SUBDIR,
    )
    for name in REFERENCE_FILES:
        assert (CATALOG_DIR / REFERENCE_SUBDIR / name).exists(), name


#: Простой относительный src/href/CSS-url — без ведущего "/" (корень
#: проекта), без "data:" (инлайн) и без "../" (тот их линтер переписывает
#: сам, `rewriteAssetPath` в исходнике их CLI на нашем пине 0.7.84,
#: `dist/cli.js` — не путать с более новым клоном `hyperframes-ref`, где та
#: же функция уже умеет искать соседа на диске).
_PLAIN_RELATIVE_ASSET_REF = re.compile(
    r'(?:src|href)=["\'](?!https?:|/|data:)([^"\']+)["\']'
    r'|url\((?!["\']?(?:https?:|/|data:))["\']?([^)"\']+)["\']?\)')


def test_ассет_лежит_ровно_там_куда_его_шлёт_простая_ссылка():
    """Наш движок монтирует ЛЮБУЮ позицию каталога как саб-композицию через
    `data-composition-src` (`hf_compose._stage_overlay`) — своей страницей она
    не открывается никогда. На пине 0.7.84 их `rewriteAssetPath` простой
    относительный путь (без `../`) не трогает вовсе — он остаётся тем же
    словом, а после монтажа резолвится браузером от корня проекта. Значит
    `<img src="assets/x.svg">` обязан находить файл ровно по `target`
    `"assets/x.svg"` — не глубже (не `"compositions/assets/x.svg"`), иначе
    рендер молча теряет картинку, видео, аудио или шрифт
    (`missing_local_asset`/`audio_src_not_found`, проверено живым
    `check --strict` на `ai-chat-reveal` до правки — находка была, после
    правки `target` на `assets/…` находка исчезла).

    Ловит именно то, что случилось при импорте B1: часть позиций получила
    `target` на уровень глубже, чем ссылается их же html, потому что решение
    сверялось с рабочей копией клона `hyperframes-ref` — та несёт более
    новую версию `rewriteAssetPath` с эвристикой «есть сосед на диске», а на
    закреплённом пине 0.7.84 эвристики ещё нет.
    """
    from reels_factory.hf_catalog import CATALOG_DIR, REGISTRY_SUBDIR

    # Семья `composition_self_attribute_selector` — правит параллельная ветка
    # (см. задание B1.5: «эти позиции НЕ трогай»). У троих из них тот же
    # дефект таргета, но чинить его здесь означало бы редактировать карточки,
    # которые сейчас держит другая рука — правка того же класса ждёт их PR.
    IN_FLIGHT_ELSEWHERE = {"instagram-follow", "tiktok-follow", "yt-lower-third",
                          "reddit-post", "spotify-card", "x-post",
                          "macos-notification", "v-macos-notification"}

    root = CATALOG_DIR / REGISTRY_SUBDIR
    broken = []
    for subdir in ("blocks", "components"):
        for item_dir in sorted((root / subdir).iterdir()):
            card = item_dir / "registry-item.json"
            if not card.exists():
                continue
            item = json.loads(card.read_text(encoding="utf-8"))
            if item["name"] in IN_FLIGHT_ELSEWHERE:
                continue
            files = item.get("files") or []
            comp_files = [f for f in files if f.get("type") == "hyperframes:composition"]
            asset_files = [f for f in files if f.get("type") == "hyperframes:asset"]
            if not comp_files or not asset_files:
                continue
            targets_by_name: dict[str, str] = {}
            for f in asset_files:
                target = f["target"].replace("\\", "/")
                targets_by_name.setdefault(Path(target).name, target)
            htmls = [
                source.read_text(encoding="utf-8", errors="ignore")
                for f in comp_files
                for source in [item_dir / f["path"]] if source.exists()]
            seen = set()
            for html in htmls:
                for a, b in _PLAIN_RELATIVE_ASSET_REF.findall(html):
                    ref = (a or b).split("?", 1)[0].split("#", 1)[0]
                    target = targets_by_name.get(Path(ref).name)
                    # Не одна из наших асетных записей вовсе (внешний URL уже
                    # отсеян регэкспом выше, но имя может ни с чем не
                    # совпасть) — тогда сверять не с чем.
                    if target is None or ref == target or ref in seen:
                        continue
                    seen.add(ref)
                    broken.append(f'{item["name"]}: ссылка "{ref}", '
                                  f'а target — "{target}"')
    assert not broken, (
        "target ассета не совпадает с тем словом, по которому на него "
        "ссылается простой относительный путь в html (на пине 0.7.84 "
        "резолвится от корня проекта буквально, не от файла): "
        + "; ".join(broken))
