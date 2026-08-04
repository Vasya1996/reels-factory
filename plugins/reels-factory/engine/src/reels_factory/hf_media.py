"""Подбор вставок скилом media-use — параллельно и кодом.

Что показать под фразу, решает агент: он присылает намерение словами. Сам
вызов — работа механическая, и делать её по одному в агентской сессии дорого
вдвойне: каждый запрос идёт в сеть, а агент ждёт ответа, ничего не решая.
Восемь вставок последовательно — это минута-полторы его времени.

Команда и её флаги — их же (`media-use/SKILL.md:15`), меняется только то, кто
её зовёт и сколько запросов идёт разом.
"""
from __future__ import annotations

import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SKILL_DIR = Path.home() / ".claude" / "skills" / "media-use"
RESOLVE = SKILL_DIR / "scripts" / "resolve.mjs"

#: Сколько запросов держим в воздухе. Реестр media-use пишется атомарно
#: (`withReservedFile`, resolve.mjs:487-501), поэтому параллель безопасна;
#: ограничение здесь — вежливость к их поставщику, а не наша сохранность.
MAX_PARALLEL = 4

TIMEOUT_S = 180


def _resolve_one(project: Path, kind: str, intent: str) -> dict:
    result = subprocess.run(
        ["node", str(RESOLVE), "--type", kind, "--intent", intent,
         "--project", str(project), "--json"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=TIMEOUT_S, env={**os.environ})
    text = (result.stdout or "").strip()
    if result.returncode != 0 or not text.startswith("{"):
        return {"ok": False,
                "error": (result.stderr or text or "нет ответа")[:300]}
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        return {"ok": False, "error": f"ответ не разбирается: {error}"}


def resolve_all(public, requests: list[dict]) -> dict[str, dict]:
    """Подобрать все вставки разом.

    `requests` — список `{"key": …, "type": "image"|"icon"|…, "intent": …}`.
    Возвращает `{key: {"file": путь относительно public} | {"error": …}}`.
    """
    public = Path(public)
    if not RESOLVE.exists():
        raise RuntimeError(
            f"нет скрипта подбора {RESOLVE}; скил media-use не установлен")
    if not requests:
        return {}

    with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as pool:
        answers = list(pool.map(
            lambda request: _resolve_one(public, request.get("type", "image"),
                                         request["intent"]),
            requests))

    resolved: dict[str, dict] = {}
    for request, answer in zip(requests, answers):
        if not answer.get("ok") or not answer.get("path"):
            resolved[request["key"]] = {
                "error": answer.get("error") or "подбор не дал файла"}
            continue
        resolved[request["key"]] = {"file": answer["path"],
                                    "intent": request["intent"]}
    return resolved
