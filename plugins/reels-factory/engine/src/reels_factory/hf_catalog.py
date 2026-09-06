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

import functools
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


def component_install_target(name: str, catalog_dir=None) -> str | None:
    """Путь под `public/`, куда `hyperframes add` кладёт html компонента.

    `hf_compose._installed_path` раньше угадывал этот путь формулой (плоско —
    `compositions/components/<имя>.html`), а формула верна для почти всех
    компонентов, но не для `texture-mask-text`: его собственный
    `registry-item.json` (байт-в-байт совпадает с `hyperframes-ref/registry/
    components/texture-mask-text/registry-item.json` — сверено) несёт
    вложенный `target: "compositions/components/texture-mask-text/
    texture-mask-text.html"`, потому что рядом с html лежат 66 текстур и
    авторы блока держат его в одноимённой подпапке. `add` кладёт файл ровно
    туда, куда велит этот `target` (их `remapTarget`, `add.ts:40-59`, меняет
    только префикс `compositions/components/`, саму вложенность не трогает) —
    значит и наш код должен спросить манифест, а не считать по формуле.

    `None`, если у карточки нет своего `target` (обычный случай, и тестовые
    фикстуры `_block()`/`_with_blocks()` его тоже не пишут) — тогда
    `_installed_path` считает по прежней формуле.
    """
    root = Path(catalog_dir or CATALOG_DIR) / REGISTRY_SUBDIR
    card = root / "components" / name / "registry-item.json"
    if not card.exists():
        return None
    item = json.loads(card.read_text(encoding="utf-8"))
    for f in item.get("files") or []:
        if str(f.get("path")) == f"{name}.html":
            target = f.get("target")
            return str(target) if target else None
    return None


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


def _registry_cards(catalog_dir=None):
    """Каждая карточка реестра, обеих подпапок — один проход для всех
    читателей, которым нужна ЛЮБАЯ позиция, а не только та, что каталог
    предлагает агенту.

    До этой функции каждый читатель обходил реестр своим циклом и сам выбирал
    подпапку: `_offered_in` брал обе, но по отдельному списку имён на каждую,
    `decor_texts` — обе своим циклом, а `skipped_blocks` — только `blocks`,
    потому что была написана 11.08.2026 (a68f242), до того как в каталоге
    появились компоненты (04.09.2026, 6df1bba). Один новый вид позиций так и
    не доехал до старого читателя: ревью PR #90 07.09.2026 нашло 123
    компонента со `skip`, которых `skipped_blocks` не видел вовсе, и гейт
    `D36_elements` вместо их настоящей причины отказа отвечал агенту «такой
    позиции в каталоге нет». Один генератор на всех читателей избавляет от
    выбора подпапки, который можно забыть повторить.

    Отдаёт подпапку (`blocks`/`components`), имя, папку позиции и разобранный
    JSON карточки — БЕЗ отбора: `skip`, недостающие файлы и что угодно ещё
    решает вызывающий. Карточка без файла и файл с битым JSON пропускаются
    здесь же — как раньше делал только `decor_texts`, — разбирать нечего, а
    не отбор по смыслу.
    """
    root = Path(catalog_dir or CATALOG_DIR) / REGISTRY_SUBDIR
    for subdir, names in (("blocks", block_names(catalog_dir)),
                          ("components", component_names(catalog_dir))):
        for name in names:
            folder = root / subdir / name
            card = folder / "registry-item.json"
            if not card.exists():
                continue
            try:
                item = json.loads(card.read_text(encoding="utf-8"))
            except ValueError:
                continue
            yield subdir, name, folder, item


def _offered_in(subdir, names, catalog_dir=None):
    """Отсев одной подпапки реестра (`blocks` или `components`) по имени.

    Правила общие — записанная причина отказа и недостающие файлы, — а
    подпапка и список имён у каждого читателя свои: `_offered` берёт `blocks`,
    `_offered_components` берёт `components`. Карточки идут из общего
    генератора (`_registry_cards`); отбор — свой, здесь.

    Причина отказа записана в карточке: например у `lower-third-bild` текст
    приходит из переменных композиции, наши слоты его не видят, и в кадр уехал
    бы немецкий дефолт «BILD EXKLUSIV».
    """
    wanted = set(names)
    for card_subdir, name, folder, item in _registry_cards(catalog_dir):
        if card_subdir != subdir or name not in wanted:
            continue
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


#: Как их компоненты объявляют переменные композиции: JSON-массив в атрибуте
#: корня, в одинарных кавычках (все 175 размеченных файлов каталога — так, и
#: так же его читает их же блок `v-bar-chart-race.js:18`). Варианты значения
#: лежат внутри объявления полем `options` — списком `{"value", "label"}`
#: (`icon-morph-beat.html:32`), и в карточке реестра их нет: `reels.variables`
#: держит только тип и умолчание.
_VARIABLES_ATTR = re.compile(
    r"data-composition-variables\s*=\s*'(.*?)'", re.DOTALL)


@functools.lru_cache(maxsize=1024)
def _declared_options(path: str, stamp: tuple) -> tuple:
    """Объявление переменных одного файла позиции: `(имя, {поле: значение})`.

    Поля — `options` (варианты `enum`), `role`, `portrays`, а у `number` ещё
    `min`/`max` — допустимая граница величины (`docs/concepts/variables.mdx`
    не называет их вовсе, а сам тип живёт в `packages/parsers/src/types.ts:
    241-248` клона 0.8.27: `min?`, `max?`, `step?`, `unit?`). Нужны только
    `min`/`max` — по ним считает диапазон число, названное в реплике
    (`hf_catalog.number_variables`, гейт `D36_elements`).

    Читается из самой разметки, а не из карточки: список вариантов — это то,
    что автор позиции уже написал в `data-composition-variables`, и второе его
    издание в `registry-item.json` разошлось бы с первым при первой же правке
    компонента.

    Кэш по пути и отпечатку файла: карточек полторы сотни, а `catalog_cards`
    зовут и индекс, и оба гейта элементов, и задание.
    """
    del stamp  # часть ключа кэша, а не аргумент разбора
    try:
        html = Path(path).read_text(encoding="utf-8")
    except OSError:
        return ()
    found = _VARIABLES_ATTR.search(html)
    if not found:
        return ()
    try:
        declared = json.loads(found.group(1))
    except ValueError:
        log.debug("позиция %s: `data-composition-variables` не разбирается",
                  path)
        return ()
    out = []
    for item in declared if isinstance(declared, list) else []:
        if not isinstance(item, dict):
            continue
        rule = {}
        values = tuple(str(option.get("value"))
                       for option in item.get("options") or []
                       if isinstance(option, dict) and option.get("value")
                       is not None)
        if values:
            rule["options"] = values
        # `role` и `portrays` — их же поля объявления переменной
        # (`docs/concepts/variables.mdx:84-109`): `role` говорит, на что
        # переменная влияет (`content`, `style`, …), `portrays` — что значение
        # ЗНАЧИТ для зрителя, и «tells an editing agent which slots carry
        # identity and must not be filled with invented copy» (там же:88-90).
        # Наш `reels.variables` — урезанное зеркало, оба поля в нём не
        # заведены; читаем их оттуда же, откуда варианты, — из объявления
        # автора позиции, чтобы второе издание не разошлось с первым.
        if item.get("role"):
            rule["role"] = str(item["role"])
        portrays = item.get("portrays")
        if isinstance(portrays, list) and portrays:
            rule["portrays"] = tuple(str(one) for one in portrays)
        elif isinstance(portrays, str) and portrays:
            rule["portrays"] = (portrays,)
        if item.get("type") == "number":
            for bound in ("min", "max"):
                value = item.get(bound)
                if isinstance(value, (int, float)) and not isinstance(
                        value, bool):
                    rule[bound] = value
        if rule:
            out.append((str(item.get("id")), rule))
    return tuple(out)


def _html_files(folder: Path, item: dict):
    """Файлы разметки позиции с отпечатком — ключом кэша разборов."""
    for entry in item.get("files") or []:
        name = str(entry.get("path") or "")
        if not name.endswith(".html"):
            continue
        path = folder / name
        try:
            stat = path.stat()
        except OSError:
            continue
        yield path, (stat.st_mtime, stat.st_size)


def _variable_options(folder: Path, item: dict) -> dict[str, dict]:
    """Объявление переменных позиции по всем её файлам разметки.

    Имя переменной → `options`/`role`/`portrays` так, как их написал автор
    позиции в `data-composition-variables`.
    """
    found = {}
    for path, stamp in _html_files(folder, item):
        for key, rule in _declared_options(str(path), stamp):
            found.setdefault(key, dict(rule))
    return found


@functools.lru_cache(maxsize=1024)
def _declared_slots(path: str, stamp: tuple) -> tuple:
    """Слоты одного файла позиции: `(имя, вид)` — разбор `hf_slots`."""
    del stamp  # часть ключа кэша, а не аргумент разбора
    from reels_factory.hf_slots import slot_contract
    try:
        html = Path(path).read_text(encoding="utf-8")
    except OSError:
        return ()
    return tuple(sorted(slot_contract(html).items()))


def _slot_contract(folder: Path, item: dict) -> dict[str, str]:
    """Слоты позиции по всем её файлам разметки: имя → чем заполняется."""
    found: dict[str, str] = {}
    for path, stamp in _html_files(folder, item):
        for key, kind in _declared_slots(str(path), stamp):
            found.setdefault(key, kind)
    return found


#: Значение по умолчанию, в которое можно положить фразу плана: одна короткая
#: строка с буквами и без служебных знаков. Путь SVG (`M 92 328 C 178 …`,
#: длиннее 80), домен (`app.example.com`), хэндл (`@ken`), число (`100`, `3`)
#: и пустая строка фразой не считаются: слова плана там сломали бы позицию, а
#: не заполнили её. Запятая сама по себе фразу не отменяет («Less, but
#: better»), а три и больше кусков через запятую — уже список
#: (`_LIST_DEFAULT`).
#:
#: `|` фразу не отменяет: это перенос строки ВНУТРИ одной фразы, а не
#: разделитель списка, и так его называют сами позиции — «A `|` breaks
#: the line» (`notes-typing.html:21`, `ai-chat-reveal.html:13` —
#: `ecHeadline`, `social-proof-card.html:19` — `f1`/`f2`/`f3`, «First
#: feature, `|` breaks the line»). Раньше `|` лежал в общем запрете вместе
#: с `;`/`<`/`>` и т.д., и этим держал в кадре английскую рекламу
#: HyperFrames — `social-proof-card.f1/f2/f3` («Write / plain HTML» и
#: т.д.) не проходили правило вовсе, хотя канал остальных полей позиции
#: уже чинил PR #80 (ревью, пункт 6): исключение работало для домена,
#: списка через запятую, пути SVG — но не имело причины для `|`.
_PHRASE_DEFAULT = re.compile(
    r"^(?=.*[^\W\d_])[^;<>/\\@#{}]{1,80}$")
#: Домен, а не фраза: одно слово с точкой внутри.
_DOMAIN_DEFAULT = re.compile(r"^\S+\.\S+$")


def word_variables(card: dict) -> list[str]:
    """Текстовые переменные позиции, куда код кладёт слова плана, по порядку.

    Правило проекта одно на оба канала: содержание в кадр кладёт код, а не
    агент правкой файла. У позиции со слотами разметки канал — слоты
    (`hf_slots.fill_ops`); у позиции без слотов текст живёт переменной, её
    пишет собственный скрипт позиции, и слова плана туда не доезжали вовсе —
    в кадре стояла английская демо-строка карточки («HELLO», «Get
    HyperFrames», «This changed how we ship.»; перепроверка отложенных
    05.09.2026, пункт 7.1). Канал их штатный: значения едут хосту одним JSON
    в `data-variable-values` (`hf_compose`), как велит их же `add.ts:64-72`.

    Берётся не всякая переменная:

    - `type: string` и `role: content` — их собственные поля объявления
      (`docs/concepts/variables.mdx:66-109`): `role` говорит, что переменная
      влияет на содержание, а не на цвет или тайминг;
    - без `portrays` — это их прямой запрет: «tells an editing agent which
      slots carry identity and must not be filled with invented copy»
      (там же:88-90). Фирменное заполняется данными пользователя или не
      заполняется вовсе;
    - умолчание — одна фраза (`_PHRASE_DEFAULT`), а не список, путь, домен
      или число: у позиции, чья переменная держит `Docs,Tickets,Dashboards`,
      подстановка одной строки убрала бы четыре чипа из четырёх;
    - у позиции нет `text_slots`: там, где слоты есть, слова уже разложены по
      ним, и второй канал положил бы тот же текст дважды.
    """
    if card.get("text_slots"):
        return []
    found = []
    for key, rule in (card.get("variables") or {}).items():
        if rule.get("type") != "string" or rule.get("role") != "content":
            continue
        if rule.get("portrays"):
            continue
        default = str(rule.get("default") or "")
        if not _PHRASE_DEFAULT.match(default) or _DOMAIN_DEFAULT.match(default):
            continue
        # Список, а не фраза: у позиции, чья переменная держит
        # `Docs,Tickets,Dashboards,Inbox`, одна подставленная строка убрала бы
        # четыре чипа из четырёх.
        if len(default.split(",")) >= 3:
            continue
        found.append(key)
    return found


#: Позиция → её числовые переменные (одна или несколько), куда ложится
#: величина, названная вслух.
#:
#: Не структурный признак (`type: "number"` + `role: "content"`), а
#: перечень, сверенный со скриптом каждой позиции — потому что структурного
#: признака «число видно зрителю» в их контракте нет вовсе (ревью PR #86,
#: пункт 0a):
#: - `role` не заведено в базовом типе переменной: `NumberVariable` несёт
#:   `type`, `default`, `min?`, `max?`, `step?`, `unit?` и ничего сверх
#:   (`packages/parsers/src/types.ts:241-248` клона 0.8.27), а в доке —
#:   вольная метка без словаря значений («role says which aspect… content,
#:   style, timing, motion, layout», `docs/concepts/variables.mdx:107-109`);
#:   рантайм по нему не ветвится ни разу — `grep -rn '"role"' packages/`
#:   находит только CLI-тесты и HTML-атрибут `role` accessibility, к
#:   переменным композиции отношения не имеющий;
#: - `unit` — про физическую единицу, не про видимость зрителю: живой скан
#:   `registry/**/registry-item.json` даёт `unit` вперемешку у
#:   `role:content` (`browser-device-stage.swap_at` — секунды до подмены
#:   экрана, `svg-mask-reveal.revealProgress` — % маски) и у `role:layout`
#:   (`ui-focus-zoom.anchor_x` — % кадра) — не дискриминатор;
#: - поля `format` в контракте нет вовсе — ни в `types.ts`, ни в доке.
#: Раз признака нет, таблица — не отказ от структурного решения ради
#: закрытого списка, а факт: 20 карточек несут `type:number`+`role:content`
#: (клон 0.8.27), а печатает спетое число зрителю на экран едва ли треть.
#: Остальные — `beatCount` (строки таблицы), `swap_at` (секунды до подмены
#: экрана), `cursorCount`/`count`/`screens`/`card_count`/`cards` (сколько
#: повторов нарисовать), `expand`/`badge_state`/`accent_word_index` (индекс
#: элемента), `revealProgress`/`anchor_x`/`anchor_y`/`zoom`/`travel`/
#: `sections` (геометрия и прогресс анимации своей же анимации) — цифра
#: плана легла бы туда числом, а не тем, что видит зритель, или разъехала бы
#: раскладку. Разбор по каждой карточке — в ревью числовых переменных
#: (06.09.2026).
#:
#: `chart-story` тоже несёт `type: "number"` + `role: "content"`
#: (`emphasize`), но это индекс акцентируемого столбца, а не величина: сами
#: числа графика лежат в `data` — строке через запятую, которую
#: `word_variables` уже отсеивает списком (`_PHRASE_DEFAULT`, ниже), и
#: собственный `avoid_when` карточки прямо отправляет одиночное число в
#: `count-up`. Числового канала он поэтому не получает — не пропуск, а то же
#: решение, что уже стоит в карточке.
#:
#: `animated-bar-chart` и `x-follow-card` из того же списка в задании не
#: несут переменных вовсе — ни у нас, ни в клоне 0.8.27 (`registry-item.json`
#: обеих пуст полем `variables`, разметка литеральна). Число из речи там
#: положить некуда, пока карточка не заведёт `data-composition-variables` и
#: не прочитает её своим скриптом — работа над самим блоком, не канал.
#:
#: `decline-chart` и `testimonial-card` довешены ревью PR #86 (пункт 0b):
#: печатают число зрителю тем же `textContent`, что и три исходные карточки,
#: и до этой правки предлагались агенту без `skip` и без числового канала.
#: `decline-chart.html:231` — `value.textContent = String(Math.round
#: (startValue + (endValue - startValue) * p))`: за кадр видны ОБЕ точки —
#: `start_value` в начале интерполяции и `end_value` в её конце, — обе
#: реально называются вслух («упало с восьмидесяти двух до тридцати
#: четырёх»), поэтому у карточки два ключа канала, не один; оставить только
#: `end_value` подставило бы вымышленное умолчание (82) под видимое зрителю
#: число начала. `testimonial-card.html:273` — `ratingValueEl.textContent =
#: ratingText + " / 5"`: `.tc-rating-value` не несёт CSS-правила, прячущего
#: его (`grep -n 'tc-rating-value\s*{'` по файлу — пусто), и `aria-hidden`
#: на видимость не влияет — элемент цел в кадре.
_NUMBER_CONTENT_CARDS = {
    "count-up": ("end",),
    "conic-progress-ring": ("progress",),
    "star-rating-fill": ("rating",),
    "decline-chart": ("start_value", "end_value"),
    "testimonial-card": ("rating",),
}


def number_variables(card: dict) -> list[str]:
    """Числовые переменные позиции, куда код кладёт величину(ы) из реплики.

    Второй канал содержания рядом со словами (`word_variables`, выше) —
    правило проекта то же: содержание в кадр кладёт код, а не агент правкой
    файла. У позиции без слотов разметки число — как и слово — живёт
    переменной, но канал у него свой: их рантайм не форматирует `number`
    вовсе (`applyVariableBindings.ts` кладёт `String(value)` и только,
    проверено по клону 0.8.27), формат — дело собственного скрипта позиции
    (`count-up.html` копит тысячи через `toLocaleString`, `star-rating-
    fill.html` округляет `toFixed(1)`), а плану нужно просто число, не фраза.

    Заполняется по счёту с `word_variables`: агент называет его сам, полем
    `variables` элемента (`{"name": "count-up", "variables": {"end": 12}}` —
    тот же путь, что элемент уже умеет для любой другой переменной,
    `hf_gates._element_problems`), а не отдельным списком слов — числа не
    склеиваются, и второй способ подать то же значение был бы новым каналом
    там, где хватает старого.

    Только позиции из `_NUMBER_CONTENT_CARDS`, и только те их ключи, что
    таблица называет, — почему список закрытый, а не структурный фильтр по
    `type`/`role`, сказано в комментарии над ним. У `decline-chart` ключей
    два (`start_value`, `end_value`): позиция может печатать зрителю больше
    одного числа разом, и обе точки нужны из речи, а не одна с воображаемым
    вторым концом.
    """
    if card.get("text_slots"):
        return []
    keys = _NUMBER_CONTENT_CARDS.get(card.get("name")) or ()
    found = []
    for key in keys:
        rule = (card.get("variables") or {}).get(key) or {}
        if rule.get("type") != "number" or rule.get("role") != "content":
            continue
        if rule.get("portrays"):
            continue
        found.append(key)
    return found


#: `conic-progress-ring` → строковая переменная, куда код зеркалит то же
#: число текстом. Их собственный скрипт держит видимый счётчик в центре
#: отдельной строковой переменной `label` (`type: "string"`, живёт своим
#: путём — `word_variables`, не этим), которая анимируется в такт с
#: числовой `progress`, но не читает её значение сама: без слова агента
#: `label` остаётся на умолчании карточки («100»), и кольцо доезжает до
#: спетого числа, а центр досчитывает до чужого
#: (`conic-progress-ring.html:181-191`: `labelText = vars.label == null ?
#: "100" : …` — умолчание разметки, не `progress`). Проверено кадром:
#: `progress: 64` без `label` — кольцо на 64%, центр «100»
#: (`scratchpad/number-vars-check`, 06.09.2026). Только эта одна позиция:
#: у `count-up` и `star-rating-fill` видимый счётчик читает свою же
#: числовую переменную напрямую (`count-up.html:181-183` — `formatValue
#: (end)`; `star-rating-fill.html:262` — `rating.toFixed(1)`), второго
#: слова для них не нужно.
_NUMBER_MIRROR = {
    "conic-progress-ring": "label",
}


def number_mirror_variable(card: dict) -> str | None:
    """Строковая переменная-зеркало числа этой позиции, если она есть.

    Код зеркалит число сам — то же правило, что и у остальных двух каналов
    содержания: содержание в кадр кладёт код, а не агент второй правкой
    того же значения. Явно названное планом слово в этой переменной
    сильнее — зеркало ставится, только если план его не занял
    (`hf_compose.build_composition`).
    """
    return _NUMBER_MIRROR.get(card.get("name"))


def image_variables(card: dict) -> list[str]:
    """Переменные-картинки позиции: куда код кладёт путь к подобранному файлу.

    Их собственный явный тип объявления, седьмой в списке рядом со `string`
    (`docs/concepts/variables.mdx:63-73`: «`image` | An image path or image
    value»). Значение показывает зрителю не наш `hf_slots.fill_ops` (там
    слот — это узел `data-slot` в разметке, и с такой переменной у него может
    не быть ничего общего вовсе), а их собственный рантайм:
    `data-var-src="<id>"` на элементе читает `data-variable-values` тем же
    способом, каким `word_variables` кладёт туда фразу
    (`packages/core/src/runtime/applyVariableBindings.ts:168-174` клона
    0.8.27 — `resolveUrl(...)`, затем `el.setAttribute("src", url)`). Живой
    пример их полки — `share-sheet-carousel.registry-item.json:65-72`,
    `slideImage1`.

    `portrays` исключает переменную тем же запретом, что и слова: лого бренда
    нельзя подменить случайным кадром биролла (тот же живой пример держит
    `brandLogo` с `portrays: ["subject_logo"]`).
    """
    found = []
    for key, rule in (card.get("variables") or {}).items():
        if rule.get("type") != "image":
            continue
        if rule.get("portrays"):
            continue
        found.append(key)
    return found


#: Каналы, которыми код кладёт содержание плана в карточку каталога, по
#: имени, каким их называет `content_channels`. Список закрытый и общий на
#: всех: заводить пятый канал вместо расширения этого списка значило бы
#: разойтись с тем, что уже проверяет `content_channels`.
CONTENT_CHANNELS = ("text_slots", "word_variables", "number_variables",
                    "media_slots")


def content_channels(card: dict) -> list[str]:
    """Каналы содержания у этой карточки, по каким доехали слова, число или
    файл плана. Пусто — позиция ничем из этого не наполняется: в кадре встанет
    голый каркас позиции, а не содержание сцены.

    Один вопрос закрывает места, которые прежде смотрели на карточку порознь
    и не сходились: `hf_montage.filling_element` считал держателем кадра
    любую позицию вида `scene`/`effect` по одному лишь `kind`, не спрашивая,
    есть ли ей чем наполниться, — и `keyframe-scrub-stack` со `scroll-feed`
    (обе без единого слота или переменной) встали держателями кадра на живом
    прогоне `exp-beat-direction` (ролики A и B в `work/exp-beat-direction/`)
    пустыми стопками карточек и пустой лентой постов. `hf_gates._element_
    problems` про канал не спрашивал вовсе, а у большинства предлагаемых
    позиций канала нет вовсе (`skeletons-report.md`).

    Четыре канала, каждый — то место в карточке, куда `hf_compose` кладёт
    слова, число или файл плана, а не готовую демо-строку позиции:

    - `text_slots` — надписи в разметке позиции, которые заполняет
      `hf_slots.fill_ops`;
    - `word_variables(card)` — тот же текст вторым каналом, собственной
      строковой переменной позиции без слотов;
    - `number_variables(card)` — величина из речи, собственной числовой
      переменной позиции (PR #86): у `count-up` это `end`, у `decline-chart`
      — обе точки интерполяции, `start_value` и `end_value`. Список ключей
      закрытый (`_NUMBER_CONTENT_CARDS`), не по одному лишь `type`/`role` —
      причина стоит рядом с таблицей;
    - `media_slots` — слот под файл (кадр биролла, снимок); их явный
      `type: "image"` у переменной уже слит в это же поле выше
      (`image_variables`, `media_variable_slots`) — агенту всё равно, куда
      именно код положит файл, лишь бы слот был.
    """
    channels = []
    if card.get("text_slots"):
        channels.append("text_slots")
    if word_variables(card):
        channels.append("word_variables")
    if number_variables(card):
        channels.append("number_variables")
    if card.get("media_slots"):
        channels.append("media_slots")
    return channels


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
        # Семья и работа позиции — их собственные поля реестра, не наша
        # выдуманная классификация: `family` («ui-props», «transitions») и
        # `jobs` («compare», «prove», «ask») стоят у 87 из 147 предлагаемых
        # позиций, и по ним видно, что три-четыре карточки закрывают одну и ту
        # же задачу. Своего поля вместо них не заводим: пустое у остальных 60
        # честнее выдуманного.
        if item.get("family"):
            card["family"] = str(item["family"])
        if item.get("jobs"):
            card["jobs"] = [str(job) for job in item["jobs"]]
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
        if reels.get("targets"):
            # На что позицию вешают: приём их полки живёт не своей разметкой,
            # а чужим элементом кадра («Wrap target text with class=…»,
            # `inline-highlight.html:4`). Список мишеней — из шапки самого
            # файла, не из нашей догадки, а закрытый перечень имён —
            # `hf_compose.PASTE_TARGETS`.
            card["targets"] = [str(one) for one in reels["targets"]]
        if reels.get("text_slots"):
            card["text_slots"] = [str(slot) for slot in reels["text_slots"]]
        subdir = ("components"
                  if str(item.get("type", "")).endswith("component")
                  else "blocks")
        folder = (Path(catalog_dir or CATALOG_DIR) / REGISTRY_SUBDIR / subdir
                  / name)
        if reels.get("variables"):
            # Варианты значения `enum` в карточке реестра не записаны, а без
            # них поле в плане не заполнить: на живом раннем шаге агент так и
            # сказал — «`icon-morph-beat` близко, но допустимые значения `pair`
            # каталог не называет» — и позицию не взял. Берём их оттуда, где их
            # написал автор позиции: из `data-composition-variables` разметки.
            # Оттуда же — `role` и `portrays`: `portrays` прямо называет
            # переменные, которые нельзя заполнять выдуманным текстом
            # («must not be filled with invented copy»,
            # `docs/concepts/variables.mdx:88-90`), и без него агент не
            # отличает свободную надпись от чужого бренда.
            declared = _variable_options(folder, item)
            variables = {}
            for key, rule in reels["variables"].items():
                rule = dict(rule)
                said = declared.get(key) or {}
                if said.get("options") and not rule.get("options"):
                    rule["options"] = list(said["options"])
                if said.get("role") and not rule.get("role"):
                    rule["role"] = said["role"]
                if said.get("portrays") and not rule.get("portrays"):
                    rule["portrays"] = list(said["portrays"])
                # `min`/`max` — та же граница, которой их код клэмпит число
                # уже в кадре (`conic-progress-ring.html:170-180`: «Both
                # numeric controls clamp to their declared ranges before they
                # reach layout or animation»); называем её плану ДО заказа,
                # чтобы отказ пришёл гейтом, а не тихим клэмпом после оплаты.
                for bound in ("min", "max"):
                    if said.get(bound) is not None and rule.get(bound) is None:
                        rule[bound] = said[bound]
                variables[key] = rule
            card["variables"] = variables
        if reels.get("decor_texts"):
            card["decor_texts"] = [str(text) for text in reels["decor_texts"]]
        # Слоты под файл — по контракту самой позиции, а не по списку имён
        # (`hf_slots.slot_contract`). `media_slots` заполняет код подобранным
        # файлом; `host_slots` их контракт ждёт `<template>`-ом в хостовой
        # странице, и нашей сборкой они недостижимы — оба списка судит
        # `D36_elements` ДО заказа ведущей.
        from reels_factory.hf_slots import HOST_SLOT, MEDIA_KINDS
        contract = _slot_contract(folder, item)
        media = [key for key, kind in contract.items() if kind in MEDIA_KINDS]
        host = [key for key, kind in contract.items() if kind == HOST_SLOT]
        # Их явный `type: "image"` — второй, отдельный канал того же самого
        # требования «сцене нужен файл»: слот у него не в разметке (`data-
        # slot`), а в объявлении переменной (`image_variables`). Гейт
        # `D36_elements` спрашивает `media_slots` не заботясь об источнике, а
        # где именно подавать файл — в узел или в `data-variable-values` —
        # решает `media_variable_slots` уже в сборке (`hf_compose`).
        image_vars = image_variables(card) if card.get("variables") else []
        if image_vars:
            media = sorted(set(media) | set(image_vars))
            card["media_variable_slots"] = sorted(image_vars)
        if media:
            card["media_slots"] = media
        if host:
            card["host_slots"] = host
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

    Читаем ВСЕ карточки реестра — и блоки, и компоненты, и снятые `skip`, —
    а не только предлагаемые. Это словарь «у позиции такая-то надпись
    нарисована», и отбор предложений к нему отношения не имеет: оба
    читателя (`hf_slots.fill_ops` через `_stage_overlay` и гейт D22) спрашивают
    по имени того, что уже собирается. Прежний проход шёл через `_offered` и
    ронял две вещи: decor компонентов не видел вовсе, а `skip` на позиции
    забирал у гейта знание о её надписи — ревью 05.09.2026: стоило снять
    `camcorder-hud`, и D22 объявил его «REC» заглушкой.

    Карточки идут из общего генератора обеих подпапок (`_registry_cards`) —
    он уже пропускает карточку без файла и битый JSON тем же способом, каким
    это раньше делал только этот читатель.
    """
    found = {}
    for subdir, name, folder, item in _registry_cards(catalog_dir):
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

_INDEX_HEAD = r"""# Каталог этого прогона

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

- `family` и `jobs` — семья позиции и работа, которую она делает, словами их
  же реестра (`family`, `jobs` в `registry-item.json`). Позиции одной семьи и
  одной работы делают одно и то же — бери ОДНУ: `grep '"jobs": \["compare"\]'
  catalog.index.md` покажет всех соперниц разом. У 60 позиций из 147 этих полей
  нет вовсе — там ищи по `use_when`, как раньше.
- `media_slots` — слоты, куда встаёт файл (кадр биролла, снимок): позиция с
  ними берётся ТОЛЬКО в сцену со вставкой (`insert`), иначе в кадре останется
  пустой макет и план вернётся с `D36_elements`. Источник у имени в списке
  может быть разным — узел `data-slot` в разметке или их явный `type:
  "image"` у переменной (`media_variable_slots` называет, какие из
  `media_slots` — второго рода): агенту это безразлично, сцене нужен файл в
  обоих случаях, а куда его положить — в узел или в `data-variable-values` —
  решает сборка.
- `host_slots` — слоты, содержимое которых их контракт ждёт из хостовой
  страницы; наша сборка их не заполняет, и такую позицию ставить нельзя.
- `kind` — чем позиция становится в кадре: `scene` (во весь кадр подложкой под
  окном ведущей), `overlay` (на стык сцен поверх всего), `effect` (в свободной
  зоне кадра). Позиция без `kind` — плашка над полосой титра. Держателем
  кадра встаёт только позиция с каналом содержимого — `text_slots`, рабочей
  переменной или `media_slots`: без канала это декор (`aurora-drift`,
  `grain-overlay`), и `avoid_when` у неё так и говорит — она держится только
  ПОВЕРХ другого держателя (ведущая целиком, вставка, схема), а одна в сцене
  кадр не закрывает (`D36_elements`).
- `targets` — на ЧТО эту позицию вешают. Такая позиция своей картинки в кадр
  не приносит вовсе: это приём поверх уже стоящего элемента — окна ведущей
  (`presenter`), вставки сцены (`insert`), ОДНОГО слова титра этой сцены
  (`caption`), схемы (`schema`) или собственной разметки позиции (`self`).
  Мишень пиши в поле `target` элемента; если в списке одно значение, код
  возьмёт его сам. Мишень `caption` держит текст, а не строку целиком, и
  ждёт вдобавок поле `word` — само слово, буквально как оно звучит в
  реплике; без него или со словом, которого в этой сцене нет, план не
  примет (`D36_elements`). Кадр такая позиция НЕ закрывает — сцене всё
  равно нужны вставка, схема или ведущая, а мишени, которой в сцене нет,
  план не примет тем же гейтом.
- `text_slots` — надписи позиции, которые код подменит твоими словами: в поле
  `words` пиши по строке на слот, в том же порядке.
- `variables` — параметры позиции с типом и значением по умолчанию: в поле
  `variables` пиши только те, что меняешь. У переменной-выбора (`enum`) рядом
  стоит `options` — список допустимых значений, и другое значение план не
  примет (`D36_elements`).
- У позиции без `text_slots`, чья `variables` несёт величину из реплики
  (`end` у `count-up`, `progress` у `conic-progress-ring`, `rating` у
  `star-rating-fill`), это поле — обязательное: без него в кадре останется
  умолчание карточки, а не число из речи. Диапазон — `min`/`max` той же
  переменной; вне него план вернётся с `D36_elements`.

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


def skipped_positions(catalog_dir=None) -> dict[str, str]:
    """Позиции каталога — блоки и компоненты обеих подпапок реестра, —
    которые нельзя ставить, и причина у каждой.

    Причина записана в карточке нашего каталога: например их же проверка под
    `--strict` валит блок, чей CSS адресуется по собственному
    `data-composition-id`, — исправить это может только автор блока.

    Названа «позиции», не «блоки», и обходит обе подпапки одним генератором
    (`_registry_cards`) не просто ради слова: до этой правки функция открывала
    только `blocks/` — так и было написано 11.08.2026 (a68f242), когда
    компонентов в каталоге ещё не было. Когда они появились 04.09.2026
    (6df1bba), обход за ними не пошёл, и ревью PR #90 07.09.2026 нашло 123
    компонента со `skip`, для которых `hf_gates._element_problems` и
    `hf_compose.element_problem` отвечали агенту «такой позиции в каталоге
    нет» вместо настоящей причины отказа из карточки.
    """
    found = {}
    for subdir, name, folder, item in _registry_cards(catalog_dir):
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
                duration=item.get("duration"),
                contract=_slot_contract(folder, item)))
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
                duration=item.get("duration"),
                contract=_slot_contract(folder, item)))
            sdk.close(name)
    return "\n\n".join(pages)
