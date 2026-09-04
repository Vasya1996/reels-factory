"""Наш каталог блоков, отданный агенту их способом — через поле registry."""
import json
import logging
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


def test_накладка_с_недостающим_файлом_агенту_не_предлагается(tmp_path, caplog):
    """`hyperframes add` тянет каждый файл из карточки блока и на 404 роняет
    всю попытку сборки. Прогон 28 потерял так попытку на `instagram-follow`:
    в каталог не переехал его `assets/avatar.jpg`. Исправить это агент не
    может — дефект каталога, а не плана."""
    _with_blocks(tmp_path, ["ок-блок", "битый-блок"])
    _block(tmp_path, "ок-блок", tags=["overlay"])
    _block(tmp_path, "битый-блок", tags=["overlay"], files=["assets/avatar.jpg"])
    with caplog.at_level(logging.DEBUG, logger="reels_factory.hf_catalog"):
        assert overlay_names(tmp_path) == ["ок-блок"]
    assert "битый-блок" in caplog.text


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


#: Позиции, у которых работа B1.5 сняла reels.skip — живым check --strict на
#: реальной сборке (не зондом), см. scratchpad/b15-report.md. Число не
#: пришпиливаем к общему счёту skip в каталоге — только эти конкретные имена
#: обязаны быть предложены агенту.
_B15_UNSKIPPED = [
    "message-thread-reveal", "mk-clone-wall-transition", "aurora-drift",
    "beat-accent", "beat-timeline", "caption-texture", "chromatic-aberration-wipe",
    "decline-chart", "directional-wipe", "drift-hold", "gesture-tap", "gloss-sweep",
    "grain-field", "kinetic-type-swap", "light-sweep-pass", "line-swap",
    "multiplayer-cursors", "overwhelm-surround", "physical-exit", "pull-back-reveal",
    "push-in", "scramble-reveal", "scroll-feed", "spotlight-card", "spring-pop",
    "stagger-cascade", "star-rating-fill", "store-badge-lockup", "svg-mask-reveal",
    "tilt-card", "variable-font-flex",
]


def test_позиции_снятые_в_b15_предложены_и_валидны():
    """Карточка без `reels.skip`, с известным видом и (для компонента) с
    известным контрактом монтажа — тем же самым, каким уже проверяет карточки
    B1 (`test_блоки_работы_b1_несут_reels_kind`,
    `test_каждый_компонент_несёт_reels_effect_и_контракт_монтажа`)."""
    offered = catalog_cards()
    comps = set(component_names())
    for name in _B15_UNSKIPPED:
        assert name in offered, f"{name}: не предложена — reels.skip не снят?"
        card = offered[name]
        assert card.get("kind") in ("scene", "overlay", "effect"), name
        if name in comps:
            reels = _card("components", name).get("reels", {})
            assert reels.get("mount") in ("composition", "paste"), name
            assert "skip" not in reels, name


#: Полка примитивов их клона (`catalog/reference/CATALOG.md`) — те её позиции,
#: что дошли до нашего каталога. У них `use_when`/`avoid_when` уже написаны
#: авторами блоков, и наши строки — их перевод, а не сочинение заново.
_ПОЛКА = [
    "per-word-rise", "scramble-reveal", "kinetic-type-swap", "oversized-cursor",
    "press-ripple", "browser-device-stage", "count-up", "chart-story",
    "titlecard-lockup", "svg-stroke-trace", "whiteboard-ink", "cta-close",
    "logo-brand-close", "before-after-wipe", "cut-the-curve", "scroll-feed",
    "iris-reveal", "particle-image-reveal", "telemetry-hud",
    "native-notification-pop", "vox-annotate",
]


def test_каждая_доступная_позиция_говорит_что_ею_показывают():
    """`use_when` есть у каждой позиции, которую агент может назвать.

    Судим по `catalog_cards` — это и есть «доступные»: позиция с записанным
    `reels.skip`, с недоехавшими файлами или наша собственная (`g*`) агенту не
    предлагается вовсе, и писать ей строку не для кого.

    Причина поля измерена шестью живыми ранними шагами (density-report):
    карточка несла `description` их реестра, а он описывает анимацию —
    «Animated world choropleth … D3 Natural Earth projection». Чтобы решить,
    годится ли позиция сцене, агент должен был перевести описание геометрии в
    монтажное суждение, и в четырёх прогонах из шести не переводил: находил
    `v-world-map` грепом по тегу `map` под ролик целиком про карту страны — и
    не ставил ничего.
    """
    for name, card in sorted(catalog_cards().items()):
        text = card.get("use_when") or ""
        assert text.strip(), f"{name}: не сказано, что этой позицией показывают"
        assert "\n" not in text, f"{name}: `use_when` длиннее одной строки"
        assert any("а" <= ch.lower() <= "я" for ch in text), \
            f"{name}: `use_when` написан не по-русски"


def test_у_позиций_полки_переведён_и_avoid_when():
    """Разбор полки их клона несёт две строки, и вторая — тоже суждение о
    содержании: «числу нужен контекст — бери chart-story». Перевод берёт обе,
    иначе половина уже написанной работы осталась бы в файле, куда свод правил
    поиск не отправляет."""
    cards = catalog_cards()
    for name in _ПОЛКА:
        assert name in cards, f"{name}: позиция полки не предлагается"
        assert (cards[name].get("avoid_when") or "").strip(), name


def test_use_when_попадает_в_строку_карточки_индекса():
    """Греп по слову из реплики должен находить позицию.

    Карточка занимает одну строку (`test_карточка_индекса_занимает_одну_
    строку`), поэтому проверять надо не наличие поля в JSON, а то, что оно
    стоит в той же строке, где имя: свод правил велит искать `grep`-ом, и
    строка, найденная по слову из `intent`, обязана нести имя позиции.
    """
    text = catalog_index(FIXTURE)
    fenced = text.split("```json")[1].split("```")[0].strip()
    body = json.loads(fenced)
    lines = fenced.splitlines()
    for card, line in zip(body, lines[1:-1]):
        assert card["use_when"] in line, f"{card['name']}: `use_when` не в строке"
        assert card["name"] in line
    assert "`use_when`" in text, "шапка индекса не называет, чем ещё искать"


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
        "demo-paste": "effect",
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


def test_позиция_с_причиной_отказа_в_индекс_не_попадает(caplog):
    """Причина отказа записана в карточке, и агенту такую позицию не
    предлагают: исправить её он не может — это дефект каталога, а не плана."""
    with caplog.at_level(logging.DEBUG, logger="reels_factory.hf_catalog"):
        assert "demo-skip" not in catalog_cards(FIXTURE)
    assert "demo-skip" in skipped_blocks(FIXTURE)
    assert "demo-skip" in caplog.text


def test_карточка_без_вида_остаётся_плашкой_по_старому_правилу():
    """Обратная совместимость: пока вид в карточке не объявлен, позиция живёт
    по нынешнему правилу — тег `overlay` и старое поле плана."""
    assert overlay_names(FIXTURE) == ["demo-plain"]
    assert catalog_cards(FIXTURE)["demo-plain"].get("kind") is None


def test_индекс_печатается_json_ом_с_нашими_полями():
    text = catalog_index(FIXTURE)
    body = json.loads(text.split("```json")[1].split("```")[0])
    assert [item["name"] for item in body] == sorted(
        ["count-up", "demo-paste", "demo-plain", "demo-scene", "demo-stitch"])
    assert "Search by intent" not in text, "правило поиска живёт в своде правил"
    assert "`kind`" in text and "`text_slots`" in text and "`variables`" in text


def test_карточка_индекса_занимает_одну_строку():
    """Индекс ищут `grep`-ом, а не читают целиком.

    Живой ранний шаг `artyom-early-b4c` (транскрипт `5204d33a`): единственное
    чтение `catalog.index.md` вернуло строки 1–2331 из 5008 — половину
    каталога, молча. Разложенный JSON и искать не давал: строка с найденным
    тегом выглядела как `"counter",` и имени позиции не несла. Одна строка на
    карточку чинит оба конца сразу — файл остаётся разбираемым JSON-ом, а
    найденная строка несёт позицию целиком.
    """
    text = catalog_index(FIXTURE)
    fenced = text.split("```json")[1].split("```")[0].strip()
    body = json.loads(fenced)
    lines = fenced.splitlines()
    assert len(lines) == len(body) + 2, "карточка занимает не одну строку"
    for card, line in zip(body, lines[1:-1]):
        assert card["name"] in line, "имени позиции в её строке нет"
        for tag in card.get("tags") or []:
            assert f'"{tag}"' in line, "тег позиции ищется не в её строке"


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


def test_text_slots_карточки_равны_слотам_разметки():
    """Одно определение слота на весь путь.

    Отчёт B4: карточка `v-code-diff` держала видимые демо-строки
    («greet.js», «Code Diff», два куска кода), а `hf_slots.find_slots` выводит
    из разметки имена (`accent`, `filename`) — сборка зипала слова агента по
    строкам карточки, `fill_ops` их не узнавал и снимал элемент целиком. Слова
    агента раскладывает теперь сама разметка, а карточка отвечает индексу — и
    равна ей, иначе агент считает слоты по одному списку, а код по другому.

    Разбор — настоящим мостом их SDK, как у `passport`: свой разборщик HTML у
    нас не тот, каким блок читает движок.
    """
    from reels_factory.hf_sdk import sdk_session
    from reels_factory.hf_slots import text_slot_names

    root = CATALOG_DIR / REGISTRY_SUBDIR
    scenes = {name: card for name, card in catalog_cards().items()
              if card.get("kind") == "scene"}
    assert scenes, "в каталоге нет ни одной позиции вида `scene`"
    with sdk_session() as sdk:
        for name, card in scenes.items():
            folder = next(root / sub / name for sub in ("blocks", "components")
                          if (root / sub / name / f"{name}.html").exists())
            item = json.loads((folder / "registry-item.json")
                              .read_text(encoding="utf-8"))
            decor = set((item.get("reels") or {}).get("decor_texts") or [])
            sdk.open(name, folder / f"{name}.html")
            names = text_slot_names(sdk.elements(name), decor)
            sdk.close(name)
            assert card.get("text_slots") == names, (
                f"{name}: карточка обещает {card.get('text_slots')}, "
                f"а разметка даёт {names}")


#: Пять образцов B3 и то, чем их разметка обязана дать заполнить кадр: у
#: терминала и диффа видимый текст жил в скрипте, и слотами он не был вовсе
#: (отчёт B4). Имена — от классов разметки, порядок — документа.
СЛОТЫ_ОБРАЗЦОВ = {
    "v-code-diff": ["file", "title", "before", "after"],
    "v-code-snippet-apple-terminal-basic": ["window-title", "command"],
    "v-world-map": ["headline", "subtitle", "source"],
    "v-bar-chart-race": ["headline", "subtitle", "source"],
    "v-macos-notification": ["app-name", "notification-title",
                             "notification-body"],
}


def test_у_вертикальных_образцов_заполняются_заголовок_подпись_и_код():
    """Заголовок и подпись — у всех пяти; строки кода — у тех двух, где код и
    есть содержание позиции."""
    cards = catalog_cards()
    for name, slots in СЛОТЫ_ОБРАЗЦОВ.items():
        assert cards[name]["text_slots"] == slots, name


def test_отсев_позиций_не_печатается_в_stdout(capsys):
    """Последнюю строку stdout у `make` бот читает как JSON-ответ
    пользователю (`bot.run_build`), а каталог зовут и индекс, и оба гейта
    элементов, и задание — сотнями строк «позиция X не предложена» этот канал
    заваливало на каждом шаге (побочная находка отчёта B4). Диагностика живёт
    в логе уровня debug.
    """
    catalog_cards(FIXTURE)
    catalog_index(FIXTURE)
    printed = capsys.readouterr()
    assert "не предложена" not in printed.out
    assert "не предложена" not in printed.err


def test_поиск_по_каталогу_считает_тем_же_правилом_что_их_каталог():
    """`search_cards` повторяет их `hyperframes catalog --query` без модели:
    общий словарь, а не подстрока (`rankByWords`/`searchByWords`,
    `packages/cli/src/registry/localSearch.ts:45-70` на пине 0.7.84).

    Меряем три их правила разом: стоп-слова и слова короче трёх букв в счёт не
    идут (запрос из одних служебных слов не находит ничего); совпадение по
    подстроке ничего не значит без общего слова; лучшая позиция идёт первой.
    """
    from reels_factory.hf_catalog import search_cards

    cards = catalog_cards(FIXTURE)
    assert search_cards("the and of to it is", cards=cards) == [], (
        "запрос из одних стоп-слов что-то нашёл")
    assert search_cards("", cards=cards) == [], "пустой запрос что-то нашёл"
    found = search_cards("counter number", cards=cards)
    assert found and found[0]["name"] == "count-up", (
        f"по своим же тегам позиция не первая: {[c['name'] for c in found]}")


def test_поиск_по_каталогу_находит_русское_слово_в_любом_падеже():
    """Их выражение `[a-z]+` русского слова не видит вовсе, а `use_when`
    написан по-русски и падежами реплики: «карта» в карточке против «карте» в
    речи. Без основ поиск по реплике не отвечал бы никогда.
    """
    from reels_factory.hf_catalog import search_cards, search_tokens

    cards = catalog_cards(FIXTURE)
    основы = {слово: search_tokens(слово)[0]
              for слово in ("карта", "карты", "карте", "картой", "картам")}
    assert len(set(основы.values())) == 1, f"падежи разошлись: {основы}"
    for реплика in ("Вот карта страны.", "Всё это видно на карте страны.",
                    "По карте видно каждый город."):
        имена = [card["name"] for card in search_cards(реплика, cards=cards)]
        assert "demo-scene" in имена, (
            f"«{реплика}» не нашла полнокадровую карту: {имена}")


def test_поиск_по_каталогу_идёт_и_по_use_when():
    """Поле наше, и добавлено к их четырём именно потому, что `description`
    описывает анимацию, а `use_when` — содержание сцены теми же словами,
    какими её описывает агент. Мерка: слово, которого нет нигде, кроме
    `use_when`, позицию находит.
    """
    from reels_factory.hf_catalog import search_cards

    cards = catalog_cards(FIXTURE)
    card = cards["demo-plain"]
    их = " ".join((card["name"], card["title"], card["description"],
                   " ".join(card["tags"]))).lower()
    assert "подпись" not in их and "лицом" not in их, (
        "слово запроса встречается и в их полях — мерка не про `use_when`")
    имена = [item["name"] for item in
             search_cards("Подпись под лицом говорящего", cards=cards)]
    assert "demo-plain" in имена, f"по `use_when` позиция не нашлась: {имена}"


def test_поиск_по_каталогу_отдаёт_не_больше_горсти():
    """Кандидаты печатаются под каждой фразой задания, и длинный список
    заслонил бы саму фразу. Число — не порог качества, а длина, которую
    читают.
    """
    from reels_factory.hf_catalog import MAX_CANDIDATES, search_cards

    живые = catalog_cards()
    найдено = search_cards("Названа сцена: число, карта, сравнение, интерфейс",
                           cards=живые, limit=None)
    assert len(найдено) > MAX_CANDIDATES, "запрос слишком узкий для мерки"
    assert len(search_cards("Названа сцена: число, карта, сравнение, "
                            "интерфейс", cards=живые)) == MAX_CANDIDATES


def test_поиск_находит_карту_под_репликой_про_области_страны():
    """Решающий случай трёх живых прогонов на доноре C: ролик про то, как
    читают дети по каждой области и школе страны, агент дважды находил
    `v-world-map` грепом по тегу `map` и не ставил ни разу, а по русскому
    слову не искал вовсе. Теперь этот поиск делает код, и мерка — та же
    реплика.
    """
    from reels_factory.hf_catalog import search_cards

    имена = [card["name"] for card in search_cards(
        "По каждой области. По каждому городу. По каждой школе.")]
    assert "v-world-map" in имена, f"карта под репликой не нашлась: {имена}"
