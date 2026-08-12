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
    """Имена блоков реестра — для сообщений и проверок."""
    root = Path(catalog_dir or CATALOG_DIR) / REGISTRY_SUBDIR
    manifest = json.loads((root / "registry.json").read_text(encoding="utf-8"))
    return [item["name"] for item in manifest.get("items") or []]


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


def overlay_names(catalog_dir=None) -> list[str]:
    """Имена накладок каталога — их блоков с тегом `overlay`.

    Ровно те 23 их блока, что перенесены ревизией работы 5: нижние трети,
    вспышки, фактура, соц-карточки. Фильтра по одному тегу мало: наши
    полноэкранные блоки тоже несут тег `overlay` в своих карточках — прогон
    20 получил в паспорта наш g21, поставил его, и сборку завернули D22
    (заглушка) и их `content_overlap`. Поэтому наши имена исключаются явно.
    """
    root = Path(catalog_dir or CATALOG_DIR) / REGISTRY_SUBDIR
    found = []
    for name in block_names(catalog_dir):
        if _OUR_BLOCK.match(name):
            continue
        folder = root / "blocks" / name
        item = json.loads((folder / "registry-item.json")
                          .read_text(encoding="utf-8"))
        if "overlay" not in (item.get("tags") or []):
            continue
        # Причина отказа записана в карточке: например у `lower-third-bild`
        # текст приходит из переменных композиции, наши слоты его не видят, и
        # в кадр уехал бы немецкий дефолт «BILD EXKLUSIV».
        skip = (item.get("reels") or {}).get("skip")
        if skip:
            print(f"накладка {name} не предложена: {skip}")
            continue
        # Карточка блока перечисляет свои файлы, и `hyperframes add` тянет
        # каждый: недостающий он считает провалом установки (HTTP 404) и роняет
        # всю попытку сборки. Прогон 28 потерял так попытку на
        # `instagram-follow`, у которого не переехал `assets/avatar.jpg`.
        # Агент такое исправить не может — это дефект каталога, а не плана,
        # поэтому битый блок ему просто не предлагается.
        missing = [str(f.get("path")) for f in (item.get("files") or [])
                   if not (folder / str(f.get("path"))).exists()]
        if missing:
            print(f"накладка {name} не предложена: в каталоге нет "
                  + ", ".join(missing))
            continue
        found.append(name)
    return found


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
