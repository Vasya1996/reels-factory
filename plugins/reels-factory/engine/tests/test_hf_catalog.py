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
#:
#: `mk-clone-wall-transition` снова несёт skip (ветка catalog-tails,
#: 0.8.27): их правило `content_overlap` (packages/cli/src/commands/
#: layout-audit.browser.js:648-673) не читает `data-layout-allow-occlusion`,
#: которым автор явно разметил кирпичную стену тайлов
#: (mk-clone-wall-transition.html:157-158) — дыра в их линте, не брак
#: позиции, но и не повод молчать: находка настоящая.
#:
#: `message-thread-reveal`, `gesture-tap`, `pull-back-reveal` тоже снова
#: несут skip (прогон scratchpad/catalog-sweep, 05.09.2026 — настоящая
#: сборка с реальными словами фразы вместо пустого элемента, впервые
#: проверена подстановка). Каждая находка настоящая и своя:
#: `message-thread-reveal` — `console_error` `TypeError: Cannot set
#: properties of null (setting 'textContent')`: 123 текстовых слота
#: (максимум по каталогу) при 102 реальных словах тестовой фразы рвут
#: рантайм — агент почти никогда не наберёт ровно 123 слова под одну сцену.
#: `gesture-tap` — `contrast_aa_failure` 4.48:1 (нужно 4.5:1) на подписи
#: "Product designer sharing practical interaction notes", найдено check
#: на середине сцены (time=4) — обычный слишком светлый серый, не связано
#: с угасанием таймлайна. `pull-back-reveal` — `content_overlap` на
#: `div.pbr-detail-context`: два текстовых блока накладываются.
_B15_UNSKIPPED = [
    "aurora-drift",
    "beat-accent", "beat-timeline", "caption-texture", "chromatic-aberration-wipe",
    "decline-chart", "directional-wipe", "drift-hold", "gloss-sweep",
    "grain-field", "kinetic-type-swap", "light-sweep-pass", "line-swap",
    "multiplayer-cursors", "overwhelm-surround", "physical-exit",
    "push-in", "scramble-reveal", "scroll-feed", "spotlight-card", "spring-pop",
    "stagger-cascade", "star-rating-fill", "store-badge-lockup", "svg-mask-reveal",
    "tilt-card", "variable-font-flex",
]


#: Позиции, у которых `skip` сняла перепроверка 06.09.2026: их причина
#: (`composition_file_too_large`) была НАШЕЙ — копия позиции теряла маркер
#: реестра по дороге, — и на 0.8.27 настоящая сборка даёт по каждой PASS, а
#: кадр (work/skips-recheck/<имя>/ours) показывает каркас интерфейса нашей
#: палитрой без единой чужой надписи.
_ВЕРНУТЫ_ПЕРЕПРОВЕРКОЙ = [
    "scroll-camera-story", "spring-stack-shuffle", "ui-focus-zoom",
    "whip-pan-cut",
]


def test_позиции_вернутые_перепроверкой_предложены_и_валидны():
    """Тот же вид проверки, что у `_B15_UNSKIPPED`: карточка без `reels.skip`,
    с известным видом и контрактом монтажа, и со строкой о том, чем позицию
    показывают."""
    offered = catalog_cards()
    for name in _ВЕРНУТЫ_ПЕРЕПРОВЕРКОЙ:
        assert name in offered, f"{name}: не предложена — reels.skip не снят?"
        card = offered[name]
        assert card.get("kind") == "effect", name
        reels = _card("components", name).get("reels", {})
        assert reels.get("mount") in ("composition", "paste"), name
        assert "skip" not in reels, name
        assert (card.get("use_when") or "").strip(), name
        assert (card.get("avoid_when") or "").strip(), name


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
        for name in ("notification-cascade", "hw-scribble-transition", "count-up"):
            _cli("add", name, "--no-clipboard", cwd=tmp_path)

    assert (tmp_path / "public" / "compositions"
            / "notification-cascade.html").exists()
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
        "demo-paste": "effect", "demo-media": "scene", "demo-host": "scene",
        # Карточка без `reels.kind` — сегодняшняя плашка: вид у неё не объявлен.
        "demo-plain": None}
    поля = set(cards["demo-scene"])
    assert {"name", "type", "title", "description", "tags", "dimensions",
            "duration"} <= поля, "формат разошёлся с `catalog --json`"
    assert cards["demo-scene"]["text_slots"] == ["line"]
    assert cards["count-up"]["variables"]["end"] == {
        "type": "number", "default": 100, "role": "content"}
    # У упругой позиции размеров нет вовсе — она меряет себя коробкой хоста.
    assert "dimensions" not in cards["count-up"]


def test_варианты_выбора_берутся_из_разметки_позиции():
    """Живой ранний шаг отказался от позиции этой дырой: «`icon-morph-beat`
    близко, но допустимые значения `pair` каталог не называет»
    (presearch-report, донор A). Варианты автор позиции пишет в
    `data-composition-variables` разметки полем `options`; карточка реестра
    держит только тип и умолчание, и без разбора разметки заполнить поле в
    плане было нечем.
    """
    accent = catalog_cards(FIXTURE)["count-up"]["variables"]["accent"]
    assert accent == {"type": "enum", "default": "green", "role": "style",
                      "options": ["green", "blue", "violet"]}
    # Тип без выбора вариантов не заводит.
    assert "options" not in catalog_cards(FIXTURE)["count-up"]["variables"]["end"]


def test_у_живого_каталога_выбор_назван_у_каждой_переменной_enum():
    """Тот самый случай отказа — на боевом каталоге, а не на фикстуре: без
    вариантов `enum` в плане не заполнить вовсе."""
    cards = catalog_cards()
    pair = cards["icon-morph-beat"]["variables"]["pair"]
    assert pair["options"] == ["mic-check", "play-check", "lock-unlock"]
    немые = [f'{card["name"]}.{key}'
             for card in cards.values()
             for key, rule in (card.get("variables") or {}).items()
             if rule.get("type") == "enum" and not rule.get("options")]
    assert not немые, "выбор без вариантов: " + ", ".join(немые[:5])


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
        ["count-up", "demo-host", "demo-media", "demo-paste", "demo-plain",
         "demo-scene", "demo-stitch"])
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
    """Белый список гейта заглушек живёт в карточке, а не литералом в коде.

    Словарь читает ВСЕ карточки реестра: и компоненты, и снятые `skip`.
    Отбор предложений к нарисованной надписи отношения не имеет — оба
    читателя (`hf_slots.fill_ops` и гейт D22) спрашивают по имени того, что
    уже собирается. Прежний проход шёл через `_offered`, и ревью 05.09.2026
    поймало обе дыры сразу: `camcorder-hud` получил `skip` по кадру — и D22
    тут же объявил его нарисованное «REC» незаполненной заглушкой; decor
    компонентов не читался вовсе.
    """
    assert decor_texts(FIXTURE) == {"demo-stitch": {"Заголовок"},
                                    "demo-skip": {"REC"},
                                    "count-up": {"%"}}


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


def test_видимый_текст_предлагаемой_позиции_нечем_не_остаётся():
    """Одно определение слота на весь путь — у КАЖДОЙ предлагаемой позиции.

    Правило проекта: позицию выбирает агент по содержанию, а слова
    подставляет код. Значит у позиции без `skip` всякая видимая надпись
    обязана быть либо слотом в `text_slots` (имена — из `hf_slots.find_slots`,
    тем же разбором, каким подставляет сборка), либо помечена
    `decor_texts` как оформление, которое никто не заполняет. Иначе позиция
    приводит в оплаченный ролик чужой демо-текст, а `check --strict` этого не
    видит: прогон scratchpad/catalog-sweep 05.09.2026 отдал такие позиции как
    «чисто», а на кадре стояли «Dr. Maya Chen · Host · Neuroscientist»,
    «u/placeholder_user» и «Prompt to change this title to whatever you want».

    Раньше сверка бралась только за карточки вида `scene`, и семнадцать
    позиций без `kind` (нижние плашки, соц-карточки, приборные накладки)
    обещали агенту ноль слотов при живой разметке — гейт D36
    (`hf_gates._element_problems`) слова к ним не пропускал, сборка копировала
    блок как есть, и демо-текст доезжал до кадра.

    Отчёт B4 (причина, по которой сверка появилась вообще): карточка
    `v-code-diff` держала видимые демо-строки вместо имён слотов, сборка
    зипала слова агента по строкам карточки, `fill_ops` их не узнавал и
    снимал элемент целиком.

    Разбор — настоящим мостом их SDK, как у `passport`: свой разборщик HTML у
    нас не тот, каким блок читает движок.

    До 06.09.2026 сверка была тавтологичной у каждой позиции, чья разметка
    лежит внутри `<template>` (73 из 147 предлагаемых): наш мост читал текст
    голым `querySelectorAll` линкдома, а он внутрь шаблона не заходит, и обе
    стороны сравнения выходили пустым списком. Прежний докстринг называл
    причиной «их разбор» — по факту их `comp.getElements()` внутрь шаблона
    смотрит, терял узлы НАШ мост (`scripts/hf_sdk.mjs`, чинится обходом
    `walkCompositionDescendants`).

    Чего эта сверка НЕ видит и после починки: позицию, чья разметка пуста, а
    текст пишет её собственный `<script>` из умолчаний
    `data-composition-variables` (`cta-lockup` — «Get HyperFrames»,
    `testimonial-card` — выдуманный отзыв). Это отдельный канал, и судить его
    надо по `variables`/`portrays` карточки, а не по узлам разбора.
    """
    from reels_factory.hf_sdk import sdk_session
    from reels_factory.hf_slots import slot_contract, text_slot_names

    root = CATALOG_DIR / REGISTRY_SUBDIR
    cards = catalog_cards()
    assert cards, "каталог не предлагает ни одной позиции"
    with sdk_session() as sdk:
        for name, card in cards.items():
            folder = next(root / sub / name for sub in ("blocks", "components")
                          if (root / sub / name / f"{name}.html").exists())
            item = json.loads((folder / "registry-item.json")
                              .read_text(encoding="utf-8"))
            decor = set((item.get("reels") or {}).get("decor_texts") or [])
            html = (folder / f"{name}.html").read_text(encoding="utf-8")
            sdk.open(name, folder / f"{name}.html")
            nodes = sdk.elements(name)
            sdk.close(name)
            # Тем же контрактом, каким считает сборка (`_stage_overlay`):
            # содержимое слота под файл — не надпись сцены.
            names = text_slot_names(nodes, decor, slot_contract(html))
            assert (card.get("text_slots") or []) == names, (
                f"{name}: карточка обещает {card.get('text_slots')}, "
                f"а разметка даёт {names} — агент считает слоты по одному "
                "списку, а код по другому")


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


def test_поиск_не_даёт_очков_за_слова_из_avoid_when():
    """`avoid_when` отвечает на вопрос «брать ли», а не «найти ли».

    Слова у него ровно те, которых в сцене быть НЕ должно, и очки за них
    поставили бы позицию первой у той самой фразы, которой она не годится.
    Поле в текст поиска не входит (`_card_text`), и тест держит это правилом, а
    не совпадением: у брендовых позиций `avoid_when` называет отсутствующий
    контент («имени бренда в сценарии нет»), и по слову «умолчание» такая
    позиция находиться не должна.
    """
    from reels_factory.hf_catalog import _card_text, search_cards

    cards = catalog_cards()
    card = cards["logo-sting"]
    assert "умолчания" in card["avoid_when"], "мерка теста устарела"
    assert "умолчан" not in _card_text(card).lower(), (
        "`avoid_when` попал в текст поиска")
    имена = [item["name"] for item in
             search_cards("вымышленное умолчание", cards=cards)]
    assert "logo-sting" not in имена, имена


def test_позиции_с_чужим_контентом_говорят_чего_у_плана_нет():
    """Живые ранние шаги отказывали этим позициям своими словами: «в сценарии
    нет имени бренда и нет числовой оценки — эти позиции держат вымышленный
    логотип или рейтинг» (донор B), «экран-слот `browser-device-stage` требует
    контента, которого на этапе плана нет» (донор A). Условие это карточное, а
    не плановое: позиция годна, когда контент есть, — поэтому оно записано
    строкой `avoid_when`, а не `skip`.
    """
    cards = catalog_cards()
    for name in ("browser-device-stage", "logo-sting", "logo-wall",
                 "logo-brand-close", "trust-strip", "svg-mask-reveal",
                 "star-rating-fill"):
        avoid = cards[name].get("avoid_when") or ""
        assert "нет" in avoid, f"{name}: не сказано, чего у плана нет: {avoid}"
        # И позиция остаётся предложенной: контент бывает и настоящий.
        assert cards[name].get("use_when"), name


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


def test_карта_мира_находится_под_репликой_про_весь_мир_и_не_под_областью():
    """Донор C: ролик про то, как читают дети по каждой области и школе
    страны, — агент трижды находил `v-world-map` по тегу `map` и не ставил.
    Он был прав: блок рисует хороплет всего мира и названную область не
    выделяет (`top5Codes` зашиты в скрипте). Карточка теперь говорит правду:
    под «по всему миру» карта находится, под «по каждой области» — нет.
    """
    from reels_factory.hf_catalog import search_cards

    мир = [card["name"] for card in search_cards(
        "Клиенты по всему миру: страны мира на одной карте.")]
    assert "v-world-map" in мир, f"карта под репликой про весь мир не нашлась: {мир}"

    область = [card["name"] for card in search_cards(
        "По каждой области. По каждому городу. По каждой школе.")]
    assert "v-world-map" not in область, (
        f"карта мира предложена под реплику про область: {область}")


def test_у_каждой_предложенной_позиции_все_файлы_карточки_на_диске():
    """`hyperframes add` тянет каждый файл из `files` карточки и роняет
    установку на первом недостающем (HTTP 404). `_offered_in` такую позицию
    молча не предлагает — и дефект каталога живёт незамеченным: так
    `heygen-avatar-promo-card` без пяти mp4 полгода считался «доступным».
    Позиция либо целая, либо несёт `reels.skip` с причиной."""
    from reels_factory.hf_catalog import CATALOG_DIR, REGISTRY_SUBDIR

    root = Path(CATALOG_DIR) / REGISTRY_SUBDIR
    broken = []
    for card in root.glob("*/*/registry-item.json"):
        item = json.loads(card.read_text(encoding="utf-8"))
        if (item.get("reels") or {}).get("skip"):
            continue
        for f in item.get("files") or []:
            if not (card.parent / str(f.get("path"))).exists():
                broken.append(f"{item['name']}: {f.get('path')}")
    assert broken == []


#: Позиция, объявляющая переменную их полем `portrays`: оно младше нашего
#: порта каталога (введено у них 2026-09-01, есть на пине 0.8.27) и прямо
#: перечисляет, что нельзя заполнять выдуманным текстом.
_С_ЛИЧНОСТЬЮ = """<!doctype html>
<html data-composition-id="брендовая" data-width="1080" data-height="1920"
  data-composition-variables='[
    {"id": "wordmark", "type": "string", "role": "content",
     "portrays": ["subject_name"], "label": "Wordmark", "default": "HYPERFRAMES"},
    {"id": "accent", "type": "string", "role": "style", "default": "green"}]'>
<body><div class="clip" data-start="0" data-duration="4">HYPERFRAMES</div></body>
</html>"""


def test_импорт_сохраняет_role_и_portrays_переменной(tmp_path):
    """`portrays` — их готовый признак «эта строка несёт чужую личность»:
    «tells an editing agent which slots carry identity and must not be filled
    with invented copy» (`docs/concepts/variables.mdx:88-90`). Наш
    `reels.variables` — урезанное зеркало на тип и умолчание, и оба поля в
    него не заведены; берём их из объявления автора позиции, оттуда же, откуда
    варианты `enum`, — иначе агент не отличает свободную надпись от бренда,
    и дефолт «HYPERFRAMES» доезжает до кадра русского ролика.
    """
    _with_blocks(tmp_path, ["брендовая"])
    folder = _block(tmp_path, "брендовая", tags=["overlay"])
    (folder / "брендовая.html").write_text(_С_ЛИЧНОСТЬЮ, encoding="utf-8")
    card = json.loads((folder / "registry-item.json").read_text(encoding="utf-8"))
    card["reels"] = {"kind": "scene",
                     "variables": {"wordmark": {"type": "string",
                                                "default": "HYPERFRAMES"},
                                   "accent": {"type": "string",
                                              "default": "green"}}}
    (folder / "registry-item.json").write_text(
        json.dumps(card, ensure_ascii=False), encoding="utf-8")
    variables = catalog_cards(tmp_path)["брендовая"]["variables"]
    assert variables["wordmark"] == {"type": "string", "default": "HYPERFRAMES",
                                     "role": "content",
                                     "portrays": ["subject_name"]}
    assert variables["accent"] == {"type": "string", "default": "green",
                                   "role": "style"}


def test_семья_и_работа_позиции_едут_в_индекс_их_же_словами():
    """Группировки по назначению у их реестра нет отдельным полем, но `family`
    и `jobs` в карточке — их собственные слова о том же: позиции одной работы
    закрывают одну задачу. Своей классификации не заводим — у 60 позиций из
    147 этих полей нет вовсе, и пустое честнее выдуманного."""
    cards = catalog_cards()
    сравнение = {name for name, card in cards.items()
                 if "compare" in (card.get("jobs") or [])}
    assert {"before-after-wipe", "comparison-split"} <= сравнение, сравнение
    index = catalog_index()
    assert "`family` и `jobs`" in index
    assert '"jobs": ["compare"]' in index


def test_слоты_под_файл_названы_в_карточке_каталога():
    """Позиция с рамкой под кадр биролла обязана сказать об этом индексу: без
    файла в кадре остаётся пустой макет, и решает это `D36_elements` до
    заказа ведущей, а не сборка после."""
    cards = catalog_cards()
    assert sorted(cards["before-after-wipe"]["media_slots"]) == ["after",
                                                                "before"]
    assert cards["browser-device-stage"]["host_slots"] == [
        "browser-device-stage-screen", "browser-device-stage-screen-b"]
    # Слот, который заполняет не файл, а переменная или скрипт позиции, в
    # список не попадает: `light-sweep-pass` кладёт в `scene` свою разметку,
    # `whiteboard-ink` рисует `strokes` скриптом.
    for name in ("light-sweep-pass", "whiteboard-ink", "press-ripple"):
        assert not cards[name].get("media_slots"), name
        assert not cards[name].get("host_slots"), name
