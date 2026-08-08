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

#: Где лежит наш каталог. Переопределяется переменной окружения — на сервере и
#: в WSL путь другой, а зашивать в код чужую машину нельзя.
CATALOG_DIR = Path(os.environ.get("REELS_CATALOG_DIR")
                   or Path.home() / "projects" / "golden-catalog")

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
        item = json.loads((root / "blocks" / name / "registry-item.json")
                          .read_text(encoding="utf-8"))
        if "overlay" in (item.get("tags") or []):
            found.append(name)
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
