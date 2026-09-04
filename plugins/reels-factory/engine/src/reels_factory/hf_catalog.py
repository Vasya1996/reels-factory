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
import logging
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

#: Отсев позиций — в лог уровня debug, а не в stdout: последнюю строку stdout
#: у `make` бот читает как JSON-ответ пользователю (`bot.run_build`), и сотни
#: строк «позиция X не предложена» на каждый вызов каталога (а зовут его и
#: индекс, и оба гейта элементов, и задание) заваливали этот канал целыми
#: экранами. Разбирается такой отсев не по ходу прогона, а когда каталог
#: правят, — этому и служит debug.
log = logging.getLogger(__name__)

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
            log.debug("позиция %s не предложена: %s", name, skip)
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
            log.debug("позиция %s не предложена: в каталоге нет %s",
                      name, ", ".join(missing))
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
    нашими: `use_when` — что этой позицией показывают, `avoid_when` — когда её
    берут зря, `kind` — чем позиция становится в кадре, `text_slots` — имена
    слотов позиции по порядку (их выводит `hf_slots.find_slots`), `variables` —
    зеркало `data-composition-variables` из HTML.

    `use_when` идёт сразу за `description` и потому попадает в ту же строку
    индекса, что имя и теги (`catalog_index`). Причина измерена шестью живыми
    ранними шагами: `description` реестра описывает анимацию — «Animated world
    choropleth with country-by-country reveal … D3 Natural Earth projection», —
    и чтобы решить, годится ли позиция сцене, агент должен был перевести
    геометрию в монтажное суждение. В четырёх прогонах из шести он находил
    позицию грепом по тегу и не ставил её. `use_when` отвечает на тот же вопрос
    прямо, теми же словами, какими сцена описана в `intent`, поэтому греп по
    слову из реплики находит позицию и по нему, а не только по тегам.

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
            log.debug("позиция %s не предложена: вид %r неизвестен, есть %s",
                      name, kind, ", ".join(KINDS))
            continue
        card = {"name": name,
                "type": str(item.get("type", "")).replace("hyperframes:", ""),
                "title": item.get("title", ""),
                "description": item.get("description", "")}
        if reels.get("use_when"):
            card["use_when"] = str(reels["use_when"])
        if reels.get("avoid_when"):
            card["avoid_when"] = str(reels["avoid_when"])
        card["tags"] = list(item.get("tags") or [])
        if item.get("dimensions"):
            card["dimensions"] = item["dimensions"]
        if item.get("duration"):
            card["duration"] = float(item["duration"])
        if kind is not None:
            card["kind"] = str(kind)
        if reels.get("mount"):
            # `composition` (по умолчанию, сабкомпозицией через
            # `data-composition-src`) или `paste` (литералом в хост, как уже
            # вставляется `caption-highlight`) — решает код размещения
            # (`hf_compose.paste_effect` против `_stage_overlay`), а не
            # догадка по подпапке реестра.
            card["mount"] = str(reels["mount"])
        if reels.get("text_slots"):
            card["text_slots"] = [str(slot) for slot in reels["text_slots"]]
        if reels.get("variables"):
            card["variables"] = dict(reels["variables"])
        if reels.get("decor_texts"):
            card["decor_texts"] = [str(text) for text in reels["decor_texts"]]
        found[name] = card
    return found


#: Слова, которые в поиске не различают ничего: они есть почти у каждой
#: позиции и у каждой реплики. Английская половина взята у них дословно
#: (`packages/cli/src/registry/localSearch.ts:22-28` на пине), русская — той же
#: породы: служебные части речи и общие глаголы речи.
_STOP_WORDS = frozenset((
    "the a an and or of to in on at is are be it its for with that this as by "
    "from into one two must not no all over under across while when where "
    "which who whom whose they them their we our you your he she his her but "
    "if then than so such can may might will would should each other another "
    "same both few more most some any every "
    "как что это эта эти этот этих того этом этой чтобы чтоб если или либо "
    "тоже также ещё еще уже там тут вот его её ему ими них нам вам они "
    "оно она мы вы ты он есть был была было были быть будет будут просто "
    "очень даже когда потому поэтому значит вообще весь вся всё все всех всем "
    "сам сама себя свой своя свои для про над под без при между через после "
    "перед может можно нужно надо такой такая такие только "
    "тот та те того тому один одна одно два две три "
    "который которая которое которые которых кого чего").split())

#: Окончания кириллицы, отсекаемые от слова, чтобы «карта», «карты» и «карте»
#: считались одним словом. Список отсортирован по длине: отрезается самое
#: длинное совпавшее. Библиотеки под это не заводим — задача поиска здесь та
#: же, что у них: разделить общий словарь, а не разобрать морфологию.
_ENDINGS = tuple(sorted((
    "ившись", "ывшись", "авшись", "ующий", "ающий", "ющий", "ящий", "ается",
    "аются", "ость", "ести", "ями", "ами", "ого", "его", "ому", "ему", "ыми",
    "ими", "ешь", "ишь", "ете", "ите", "ать", "ять", "еть", "ить", "ыть",
    "уть", "ам", "ям", "ах", "ях", "ов", "ев", "ей", "ий", "ый", "ой", "ая",
    "яя", "ое",
    "ее", "ые", "ие", "ым", "им", "ом", "ем", "ую", "юю", "ут", "ют", "ат",
    "ят", "ит", "ет", "ла", "ло", "ли", "ся", "сь", "ья", "ье", "ью",
    "а", "я", "о", "е", "ы", "и", "у", "ю", "ь", "й", "л"),
    key=len, reverse=True))

#: Короче трёх букв основа не бывает: «имя» без окончания стало бы «им», и по
#: нему совпало бы всё подряд.
_MIN_STEM = 3

_VOWELS = "аеёиоуыэюя"

_WORD_RE = re.compile(r"[a-zа-яё]+")


def _stem(word: str) -> str:
    """Основа слова кириллицы простым отсечением окончания.

    Латиницу не трогаем вовсе: по ней ищут их же словом, без склонений, и их
    поиск основ не берёт.
    """
    if not any("а" <= letter <= "я" or letter == "ё" for letter in word):
        return word
    for ending in _ENDINGS:
        if word.endswith(ending) and len(word) - len(ending) >= _MIN_STEM:
            word = word[:-len(ending)]
            break
    # Хвостовая гласная снимается отдельно: у одного корня окончания разной
    # длины («сравнение» → «сравнен», «сравнения» → «сравнени»), и без этого
    # два падежа одного слова разошлись бы по разным основам.
    while len(word) > _MIN_STEM and word[-1] in _VOWELS:
        word = word[:-1]
    return word


def search_tokens(text: str) -> list[str]:
    """Слова текста, по которым идёт поиск: их правило плюс основы кириллицы.

    Их правило дословно (`localSearch.ts:29-32`): нижний регистр, только буквы,
    короче трёх букв — прочь, стоп-слова — прочь. Кириллица к нему добавлена
    двумя вещами, без которых поиск по русской реплике не работал бы вовсе: их
    выражение `[a-z]+` русского слова не видит, а падеж и число развели бы
    «карта» в `use_when` и «карте» в реплике по разным словам.
    """
    words = _WORD_RE.findall(text.lower())
    return [_stem(word) for word in words
            if len(word) > 2 and word not in _STOP_WORDS]


def _card_text(card: dict) -> str:
    """Текст карточки, по которому она ищется.

    Поля их: `name`, `title`, `description`, `tags`
    (`packages/cli/src/commands/catalog.ts:534`). Наше одно — `use_when`: оно и
    написано теми же словами, какими сцену описывает агент, а `description`
    описывает анимацию.
    """
    return " ".join((card.get("name", ""), card.get("title", ""),
                     card.get("description", ""),
                     " ".join(card.get("tags") or []),
                     card.get("use_when", "")))


#: Сколько кандидатов показывают под фразой. Пять — не порог качества, а
#: длина, которую читают: под каждой фразой задания стоит свой список, и
#: двадцатью строками он заслонил бы саму фразу.
MAX_CANDIDATES = 5


def search_cards(query: str, *, cards=None, catalog_dir=None,
                 limit: int | None = MAX_CANDIDATES) -> list[dict]:
    """Позиции каталога, отвечающие этому тексту, — лучшие первыми.

    Одна функция на всех: по ней код собирает кандидатов под фразу задания
    (`hf_brief`), по ней же меряют тесты. Правило — то же, каким отвечает их
    `hyperframes catalog --query`, когда локальной модели нет
    (`rankByWords`/`searchByWords`, `packages/cli/src/registry/localSearch.ts:45-70`
    на пине 0.7.84): общий словарь, а не подстрока. Счёт — число общих слов,
    делённое на корень из числа слов карточки; делитель обязателен, иначе
    самая многословная карточка выигрывает любой запрос. Порядок при равном
    счёте — по имени вниз, как у них.

    Зачем это код, а не агент: шесть живых ранних шагов подряд агент искал
    только по восьми строкам таблицы тегов свода и ни разу — по русскому слову
    реплики; дословно совпадающую карточку `v-world-map` он находил дважды и не
    ставил (usewhen-report, density-report). Поиск — работа механическая, и она
    уходит коду, как ушли секунды и геометрия.

    Индекс это не заменяет: `catalog.index.md` остаётся целиком, и поиск по
    словам находит не всё — у половины позиций `use_when` написан не теми
    словами, что реплика.
    """
    if cards is None:
        cards = catalog_cards(catalog_dir)
    want = set(search_tokens(query))
    if not want:
        return []
    scored = []
    for card in cards.values():
        have = set(search_tokens(_card_text(card)))
        shared = len(want & have)
        if not shared:
            continue
        scored.append((shared / ((len(have) ** 0.5) or 1.0),
                       card.get("name", ""), card))
    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    found = [card for _, _, card in scored]
    return found if limit is None else found[:limit]


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

Позиции, которые код умеет поставить в кадр. Ищи по смыслу — по `use_when`,
`description` и `tags`, — а не глазами по именам: имя придумывал автор позиции,
и оно редко совпадает с твоими словами.

Файл длиннее, чем берёт одно чтение, поэтому карточка занимает ровно одну
строку: строку, найденную поиском, видно целиком — с именем, видом, тегами,
слотами и переменными.

Поля `name`, `type`, `title`, `description`, `tags`, `dimensions`, `duration` —
формата `hyperframes catalog --json`. Наши:

- `use_when` — что этой позицией показывают: признак содержания сцены, а не то,
  как позиция выглядит. Ищи по ней теми же словами, какими написан `intent`
  сцены: `grep -i 'сравнен' catalog.index.md`.
- `avoid_when` — когда позицию берут зря; стоит там, где случай уже разобран.

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

    Карточка печатается одной строкой, а не разложенным JSON. Причина
    измерена живым прогоном: разложенный `indent=1` давал 5008 строк на 168
    позиций, и единственное чтение агента (`artyom-early-b4c`, транскрипт
    `5204d33a`) вернуло строки 1–2331 — половину каталога, молча, без пометки
    об обрезке. Читать такой файл целиком нельзя, а искать по нему нечем:
    строка с найденным тегом в разложенном JSON выглядит как `"counter",` и
    имени позиции не несёт. Одна строка на карточку делает файл искомым —
    `grep` возвращает позицию целиком, — и метод поиска назван в своде правил
    (`hf_montage_skill`, «Чем занять кадр: позиция каталога»).

    Разбирается по-прежнему как JSON: строки — элементы одного списка.
    """
    cards = sorted(catalog_cards(catalog_dir).values(), key=lambda c: c["name"])
    rows = ",\n".join(json.dumps(card, ensure_ascii=False) for card in cards)
    return _INDEX_HEAD + "```json\n[\n" + rows + "\n]\n```\n"


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
