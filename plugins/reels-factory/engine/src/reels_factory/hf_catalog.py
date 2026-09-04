"""Наш отобранный каталог блоков как реестр HyperFrames.

Каталог мы держим свой — это единственное исключение из правила «канон
фреймворка первичен». Но отдавать его агенту надо их способом: через поле
`registry` в `hyperframes.json`, чтобы работали `hyperframes catalog` и
`hyperframes add`.

Реестр их CLI тянет по HTTP: `fetch(baseUrl + "/registry.json")` в
`packages/cli/src/registry/remote.ts:96`. Файловый путь туда положить нельзя —
`fetch` в Node 22 схему `file:` не поддерживает (проверено: `fetch failed`).
Поэтому каталог отдаётся статикой на localhost, а в `hyperframes.json`
попадает её адрес.
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path

#: Где лежит наш каталог. Он в репозитории: сборка без него не работает вовсе,
#: а разметка форм в карточках — наша, и восстановить её неоткуда. Раньше он
#: жил отдельной папкой на одной машине и под гитом не был.
#: Переменная окружения перекрывает — на сервере и в WSL путь другой.
CATALOG_DIR = Path(os.environ.get("REELS_CATALOG_DIR")
                   or Path(__file__).resolve().parents[5] / "catalog")

#: Подпапка каталога, разложенная по их схеме реестра:
#: registry.json + blocks/<имя>/{registry-item.json,<имя>.html}.
REGISTRY_SUBDIR = "registry"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _config(registry_url: str, prefix: str) -> str:
    return json.dumps({
        "$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
        "registry": registry_url,
        "paths": {"blocks": f"{prefix}compositions",
                  "components": f"{prefix}compositions/components",
                  "assets": f"{prefix}assets"},
    }, ensure_ascii=False, indent=2) + "\n"


def write_project_config(rdir, registry_url: str) -> list[Path]:
    """`hyperframes.json`: куда смотреть за блоками и куда их класть.

    Раскладка полей — из `hyperframes-registry/references/install-locations.md`.
    Без этого файла папка не размечена как проект фреймворка, и `add` молча
    создаёт конфиг с их общим реестром (`install-locations.md:19-31`), то есть
    с чужими блоками.

    Кладём в обе папки — в корень прогона и в `public/`: `add` ищет конфиг от
    текущего каталога, а из какой папки агент позовёт команду, мы не знаем и
    диктовать не хотим. Блоки в обоих случаях приземляются внутрь `public/`,
    иначе композиция сослалась бы на файл за пределами своей папки.
    """
    rdir = Path(rdir)
    public = rdir / "public"
    public.mkdir(parents=True, exist_ok=True)
    written = []
    for target, prefix in ((rdir, "public/"), (public, "")):
        path = target / "hyperframes.json"
        path.write_text(_config(registry_url, prefix), encoding="utf-8")
        written.append(path)
    return written


@contextmanager
def serve_catalog(catalog_dir=None, *, timeout_s: float = 10.0):
    """Поднять реестр статикой на localhost. Отдаёт базовый адрес."""
    root = Path(catalog_dir or CATALOG_DIR) / REGISTRY_SUBDIR
    manifest = root / "registry.json"
    if not manifest.exists():
        raise RuntimeError(
            f"каталог не разложен реестром: нет {manifest}. "
            "Реестр собирается из blocks/ каталога.")
    port = _free_port()
    process = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1",
         "--directory", str(root)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                with urllib.request.urlopen(f"{base}/registry.json", timeout=1):
                    break
            except (urllib.error.URLError, OSError):
                if time.monotonic() > deadline:
                    raise RuntimeError(f"каталог не поднялся на {base}")
                time.sleep(0.2)
        yield base
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def block_names(catalog_dir=None) -> list[str]:
    """Имена блоков реестра — для сообщений и проверок.

    Только `hyperframes:block`: реестр с работы B1 несёт ещё и
    `hyperframes:component` записи (карточка лежит в `components/<имя>`, не в
    `blocks/<имя>`), и всё остальное в этом модуле открывает файл по пути
    `blocks/<имя>/registry-item.json` — компонент по этому пути не найдётся.
    """
    root = Path(catalog_dir or CATALOG_DIR) / REGISTRY_SUBDIR
    manifest = json.loads((root / "registry.json").read_text(encoding="utf-8"))
    return [item["name"] for item in manifest.get("items") or []
            if item.get("type", "hyperframes:block") == "hyperframes:block"]


def component_names(catalog_dir=None) -> list[str]:
    """Имена компонентов реестра — `hyperframes:snippet`/`hyperframes:component`.

    Карточка компонента лежит в `components/<имя>/registry-item.json`, не в
    `blocks/<имя>` — путь другой, поэтому функция отдельная от `block_names`.
    """
    root = Path(catalog_dir or CATALOG_DIR) / REGISTRY_SUBDIR
    manifest = json.loads((root / "registry.json").read_text(encoding="utf-8"))
    return [item["name"] for item in manifest.get("items") or []
            if item.get("type") == "hyperframes:component"]


def block_durations(catalog_dir=None) -> dict[str, float]:
    """Родная длительность каждого блока — за неё его сцена собирается.

    Читаем карточку реестра, а не сам блок: то же число, но без открытия
    стокилобайтного HTML на каждый вопрос. Нужна до сборки — по ней код считает,
    какой минимум отвести карточке (`hf_slots.min_card_seconds`).
    """
    root = Path(catalog_dir or CATALOG_DIR) / REGISTRY_SUBDIR
    durations = {}
    for name in block_names(catalog_dir):
        item = json.loads((root / "blocks" / name / "registry-item.json")
                          .read_text(encoding="utf-8"))
        if item.get("duration"):
            durations[name] = float(item["duration"])
    return durations


#: Наши 25 полноэкранных блоков: имена вида g07-…. Агенту не выдаются — это
#: решение, а не пауза (см. задание, «Возврат наших блоков»).
_OUR_BLOCK = re.compile(r"^g\d\d-")

#: Чем позиция каталога становится в кадре. Поле `reels.kind` карточки:
#: `scene` — во весь кадр вместо картинки, `overlay` — на стык сцен поверх
#: всего, `effect` — в свободной зоне кадра рядом с ведущей и титром.
KINDS = ("scene", "overlay", "effect")


def _offered_in(subdir, names, catalog_dir=None):
    """Отсев одной подпапки реестра (`blocks` или `components`) по имени.

    Правила общие — записанная причина отказа и недостающие файлы, — а
    подпапка и список имён у каждого читателя свои: `_offered` берёт `blocks`,
    `_offered_components` берёт `components`.

    Причина отказа записана в карточке: например у `lower-third-bild` текст
    приходит из переменных композиции, наши слоты его не видят, и в кадр уехал
    бы немецкий дефолт «BILD EXKLUSIV».
    """
    root = Path(catalog_dir or CATALOG_DIR) / REGISTRY_SUBDIR
    for name in names:
        folder = root / subdir / name
        card = folder / "registry-item.json"
        if not card.exists():
            continue
        item = json.loads(card.read_text(encoding="utf-8"))
        skip = (item.get("reels") or {}).get("skip")
        if skip:
            print(f"позиция {name} не предложена: {skip}")
            continue
        # Карточка перечисляет свои файлы, и `hyperframes add` тянет каждый:
        # недостающий он считает провалом установки (HTTP 404) и роняет всю
        # попытку сборки. Прогон 28 потерял так попытку на `instagram-follow`,
        # у которого не переехал `assets/avatar.jpg`. Агент такое исправить не
        # может — это дефект каталога, а не плана, поэтому битая позиция ему
        # просто не предлагается.
        missing = [str(f.get("path")) for f in (item.get("files") or [])
                   if not (folder / str(f.get("path"))).exists()]
        if missing:
            print(f"позиция {name} не предложена: в каталоге нет "
                  + ", ".join(missing))
            continue
        yield name, item


def _offered(catalog_dir=None):
    """Блоки, которые каталог действительно может поставить.

    Один проход на всех читателей блоков: индекс для агента и список плашек
    старого поля `overlay`. Отсев здесь троякий и весь про дефекты каталога, а
    не плана: наши полноэкранные блоки (прогон 20 получил в паспорта наш g21,
    поставил его, и сборку завернули D22 и их `content_overlap`), позиции с
    записанной причиной отказа и позиции, чьи файлы до каталога не доехали.
    """
    names = [name for name in block_names(catalog_dir)
             if not _OUR_BLOCK.match(name)]
    yield from _offered_in("blocks", names, catalog_dir)


def _offered_components(catalog_dir=None):
    """Компоненты, которые каталог действительно может поставить.

    Тот же троякий отсев, что у `_offered`, но по компонентам — они лежат в
    своей подпапке `components/<имя>`, не в `blocks/<имя>`.
    """
    yield from _offered_in("components", component_names(catalog_dir),
                           catalog_dir)


def _offered_all(catalog_dir=None):
    """Всё, что каталог может предложить агенту — блоки и компоненты вместе.

    Только для индекса (`catalog_cards`): агент выбирает позицию любого вида
    по смыслу, не по тому, в какой подпапке она физически лежит. Остальные
    читатели (`overlay_names`, `decor_texts`) держат старое поле плана
    `overlay` — оно про блоки, компонент туда не встаёт.
    """
    yield from _offered(catalog_dir)
    yield from _offered_components(catalog_dir)


def overlay_names(catalog_dir=None) -> list[str]:
    """Имена накладок каталога — их блоков с тегом `overlay`.

    Старое поле плана `overlay`: план прошлого прогона мог назвать блок так, и
    собираться он обязан по-прежнему. Новые позиции агент называет в
    `elements`, и их вид берётся из `reels.kind` (`catalog_cards`). Смотрим
    только блоки: у части компонентов тег `overlay` тоже стоит (например,
    `camcorder-hud`), но это не то же самое поле плана.
    """
    return [name for name, item in _offered(catalog_dir)
            if "overlay" in (item.get("tags") or [])]


def catalog_cards(catalog_dir=None) -> dict[str, dict]:
    """Позиции каталога для агента и для проверок — по имени.

    Карточка отдаётся полями их же `hyperframes catalog --json` (`name`,
    `type`, `title`, `description`, `tags`, `dimensions`, `duration`) плюс
    нашими тремя: `kind` — чем позиция становится в кадре, `text_slots` — имена
    слотов позиции по порядку (их выводит `hf_slots.find_slots`), `variables` —
    зеркало `data-composition-variables` из HTML.

    Карточка без `reels.kind` — сегодняшняя плашка: вид у неё не объявлен, и в
    кадр она едет тем же путём, что и по старому полю `overlay`. Выводить вид
    из тегов нельзя: тег `overlay` носят и полосы с текстом, и фактуры, и
    полнокадровые сцены, а решает это карточка, а не наша догадка.

    Проходит блоки и компоненты вместе (`_offered_all`) — агент выбирает
    позицию любого вида по смыслу, не по подпапке, где она физически лежит.
    """
    found = {}
    for name, item in _offered_all(catalog_dir):
        reels = item.get("reels") or {}
        kind = reels.get("kind")
        # Позиция без объявленного вида предлагается только там, где её
        # предлагали и раньше, — среди накладок с тегом `overlay`.
        if kind is None and "overlay" not in (item.get("tags") or []):
            continue
        if kind is not None and kind not in KINDS:
            print(f"позиция {name} не предложена: вид {kind!r} неизвестен, "
                  f"есть {', '.join(KINDS)}")
            continue
        card = {"name": name,
                "type": str(item.get("type", "")).replace("hyperframes:", ""),
                "title": item.get("title", ""),
                "description": item.get("description", ""),
                "tags": list(item.get("tags") or [])}
        if item.get("dimensions"):
            card["dimensions"] = item["dimensions"]
        if item.get("duration"):
            card["duration"] = float(item["duration"])
        if kind is not None:
            card["kind"] = str(kind)
        if reels.get("text_slots"):
            card["text_slots"] = [str(slot) for slot in reels["text_slots"]]
        if reels.get("variables"):
            card["variables"] = dict(reels["variables"])
        if reels.get("decor_texts"):
            card["decor_texts"] = [str(text) for text in reels["decor_texts"]]
        found[name] = card
    return found


def decor_texts(catalog_dir=None) -> dict[str, set[str]]:
    """Надписи, которые в позиции нарисованы, а не подставлены.

    Читается из карточки (`reels.decor_texts`), а не из списка в коде: у
    камкордерного HUD «REC» — сама суть блока, и знает об этом тот, кто заводил
    карточку. Гейт заглушек (`D22_placeholders`) судит по совпадению текста
    копии с исходником, и такая надпись выглядит как незаполненный слот.
    """
    found = {}
    for name, item in _offered(catalog_dir):
        texts = (item.get("reels") or {}).get("decor_texts")
        if texts:
            found[name] = {str(text) for text in texts}
    return found


#: Файлы фреймворка, которые уезжают агенту как есть: полка примитивов с
#: разбором «что / когда брать / чего избегать» у каждого
#: (`registry/components/CATALOG.md` их клона) и карта «тип содержимого →
#: категория → блок» (`skills/motion-graphics/catalog-map.md`). Копии живут в
#: репозитории по той же причине, что и каталог: на проде клона нет, а без них
#: агент выбирает позицию по одному имени.
REFERENCE_SUBDIR = "reference"
REFERENCE_FILES = ("CATALOG.md", "catalog-map.md")

_INDEX_HEAD = """# Каталог этого прогона

Позиции, которые код умеет поставить в кадр. Ищи по смыслу — по `description`
и `tags`, — а не глазами по именам: имя придумывал автор позиции, и оно редко
совпадает с твоими словами.

Поля `name`, `type`, `title`, `description`, `tags`, `dimensions`, `duration` —
формата `hyperframes catalog --json`. Наши три:

- `kind` — чем позиция становится в кадре: `scene` (во весь кадр), `overlay`
  (на стык сцен поверх всего), `effect` (в свободной зоне кадра). Позиция без
  `kind` — плашка над полосой титра.
- `text_slots` — надписи позиции, которые код подменит твоими словами: в поле
  `words` пиши по строке на слот, в том же порядке.
- `variables` — параметры позиции с типом и значением по умолчанию: в поле
  `variables` пиши только те, что меняешь.

"""


def catalog_index(catalog_dir=None) -> str:
    """Индекс каталога для агента: чем искать и что можно назвать.

    По имени, а не по порядку реестра: блоки и компоненты лежат в разных
    подпапках (`catalog_cards`), и их естественный порядок — сперва все блоки,
    потом все компоненты — агенту ничего не говорит.
    """
    cards = sorted(catalog_cards(catalog_dir).values(), key=lambda c: c["name"])
    return (_INDEX_HEAD + "```json\n"
            + json.dumps(cards, ensure_ascii=False, indent=1) + "\n```\n")


def write_catalog_files(rdir, catalog_dir=None) -> list[Path]:
    """Положить рядом с заданием индекс каталога и справочники фреймворка."""
    rdir = Path(rdir)
    rdir.mkdir(parents=True, exist_ok=True)
    written = [rdir / "catalog.index.md"]
    written[0].write_text(catalog_index(catalog_dir), encoding="utf-8")
    source = Path(catalog_dir or CATALOG_DIR) / REFERENCE_SUBDIR
    for name in REFERENCE_FILES:
        origin = source / name
        if origin.exists():
            target = rdir / name
            target.write_text(origin.read_text(encoding="utf-8"),
                              encoding="utf-8")
            written.append(target)
    return written


#: Метка их реестра, которой помечены накладки-фактуры: световая протечка,
#: рамка видоискателя, оформление стоп-кадра. Метка их, не наша — она стоит в
#: карточках блоков, перенесённых из их реестра.
TEXTURE_TAG = "media-treatment-overlay"


def skipped_blocks(catalog_dir=None) -> dict[str, str]:
    """Блоки, которые нельзя ставить, и причина у каждого.

    Причина записана в карточке нашего каталога: например их же проверка под
    `--strict` валит блок, чей CSS адресуется по собственному
    `data-composition-id`, — исправить это может только автор блока.
    """
    root = Path(catalog_dir or CATALOG_DIR) / REGISTRY_SUBDIR
    found = {}
    for name in block_names(catalog_dir):
        card = root / "blocks" / name / "registry-item.json"
        if not card.exists():
            continue
        item = json.loads(card.read_text(encoding="utf-8"))
        reason = (item.get("reels") or {}).get("skip")
        if reason:
            found[name] = str(reason)
    return found


def block_backing(catalog_dir=None) -> dict[str, str]:
    """Есть ли у накладки своя подложка под текстом: `own`, `none`, `textless`.

    Их проверка контраста меряет реальные пиксели под буквами и `text-shadow`
    не засчитывает (`packages/cli/src/commands/contrast-audit.browser.js`),
    поэтому накладка без подложки на светлом биролле валит сборку. Признак
    размечен в карточках нашего каталога — по нему код решает, подкладывать ли
    скрим, а не выбрасывает накладку.
    """
    root = Path(catalog_dir or CATALOG_DIR) / REGISTRY_SUBDIR
    found = {}
    for name in block_names(catalog_dir):
        card = root / "blocks" / name / "registry-item.json"
        if not card.exists():
            continue
        item = json.loads(card.read_text(encoding="utf-8"))
        backing = (item.get("reels") or {}).get("backing")
        if backing:
            found[name] = str(backing)
    return found


def texture_overlays(catalog_dir=None) -> set[str]:
    """Накладки-фактуры: те, что кроют кадр целиком, а не плашкой.

    Фактура — это обработка изображения, натянутая на весь кадр (протечка света
    заливает его, рамка видоискателя обводит его края). Остальные накладки
    каталога — плашки с текстом: у них есть верх и низ, и им место над полосой
    титра. Разница видна только по метке, канвас у тех и других одинаковый
    1920x1080.
    """
    root = Path(catalog_dir or CATALOG_DIR) / REGISTRY_SUBDIR
    found = set()
    for name in block_names(catalog_dir):
        item = json.loads((root / "blocks" / name / "registry-item.json")
                          .read_text(encoding="utf-8"))
        if TEXTURE_TAG in (item.get("tags") or []):
            found.add(name)
    return found


def overlay_passports(catalog_dir=None) -> str:
    """Паспорта накладок для задания агенту: имя, длительность, слоты."""
    from reels_factory.hf_sdk import sdk_session
    from reels_factory.hf_slots import passport

    root = Path(catalog_dir or CATALOG_DIR) / REGISTRY_SUBDIR
    pages = []
    with sdk_session() as sdk:
        for name in overlay_names(catalog_dir):
            folder = root / "blocks" / name
            item = json.loads(
                (folder / "registry-item.json").read_text(encoding="utf-8"))
            sdk.open(name, folder / f"{name}.html")
            pages.append(passport(
                sdk.elements(name), name=name, title=item.get("title", ""),
                description=item.get("description", ""),
                duration=item.get("duration")))
            sdk.close(name)
    return "\n\n".join(pages)


def block_passports(catalog_dir=None) -> str:
    """Паспорта всех блоков: что за сцена и какие в ней слоты.

    Раньше агент открывал файл блока сам — по сотне килобайт на блок, из них
    почти всё base64 шрифтов. Паспорт даёт то же знание в двадцать строк:
    описание сцены и имена слотов с тем, что в них лежит сейчас.
    """
    from reels_factory.hf_sdk import sdk_session
    from reels_factory.hf_slots import passport

    root = Path(catalog_dir or CATALOG_DIR) / REGISTRY_SUBDIR
    pages = []
    with sdk_session() as sdk:
        for name in block_names(catalog_dir):
            folder = root / "blocks" / name
            item = json.loads(
                (folder / "registry-item.json").read_text(encoding="utf-8"))
            sdk.open(name, folder / f"{name}.html")
            pages.append(passport(
                sdk.elements(name), name=name, title=item.get("title", ""),
                description=item.get("description", ""),
                duration=item.get("duration")))
            sdk.close(name)
    return "\n\n".join(pages)
