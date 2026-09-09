"""Карта документации Claude Code — из их же индекса, а не руками.

Карта, написанная руками, устаревает молча: в индексе 202 страницы, а в
предыдущей рукописной карте было 25, и среди недостающих лежала
`agent-sdk/modifying-system-prompts`, на которую прямо ссылается наш движок
(`hf_agent.py:52`). Поэтому карта — производная от индекса.

Запуск:  python .claude/doc-map/generate.py
Выход:   .claude/doc-map/claude-code.md

Сеть недоступна — прежняя карта остаётся на месте, код выхода 0: карта нужна
библиотекарю в любом состоянии сети, а её возраст он видит по строке в шапке.
"""
from __future__ import annotations

import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

INDEX = "https://code.claude.com/docs/llms.txt"
PREFIX = "https://code.claude.com/docs/"
OUT = Path(__file__).with_name("claude-code.md")

#: Переводные индексы `_llms/<язык>.md` — те же страницы на других языках.
_SKIP = re.compile(r"^_llms/")
#: Недельные страницы «что нового». Их два десятка и они копятся; свежая
#: says что изменилось с прошлого раза, старые — история, за которой идут
#: в сам индекс.
_WEEKLY = re.compile(r"^en/whats-new/")
_ENTRY = re.compile(r"\[([^\]]+)\]\((https://code\.claude\.com/docs/[^)]+)\)")


def rows(text: str) -> list[tuple[str, str, str]]:
    """(раздел, страница, slug) в порядке индекса, без переводов и старых недель."""
    out: list[tuple[str, str, str]] = []
    section = ""
    weekly_seen = 0
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            section = stripped.lstrip("#").strip()
            continue
        found = _ENTRY.search(stripped)
        if not found:
            continue
        slug = found.group(2)[len(PREFIX):]
        if _SKIP.match(slug):
            continue
        if _WEEKLY.match(slug):
            weekly_seen += 1
            if weekly_seen > 1:
                continue
        out.append((section, found.group(1), slug))
    return out


def render(entries: list[tuple[str, str, str]], stamp: str) -> str:
    head = (
        "# Карта документации Claude Code\n\n"
        f"Сгенерирована {stamp} UTC из {INDEX}. **Руками не править** — следующий\n"
        "прогон `python .claude/doc-map/generate.py` затрёт правку.\n\n"
        f"Полный адрес страницы: `{PREFIX}<slug>`. Страницы нет в карте — значит\n"
        "её нет и в индексе на момент генерации: перегенерировать и сказать об этом.\n\n"
        "| Раздел | Страница | slug |\n| --- | --- | --- |\n"
    )
    body = "\n".join(f"| {s} | {t} | {slug} |" for s, t, slug in entries)
    return head + body + "\n"


def main() -> int:
    # Без User-Agent сайт отвечает 403: urllib по умолчанию представляется
    # `Python-urllib/3.x`, и такой запрос отбивается. Проверено на этой машине.
    request = urllib.request.Request(INDEX, headers={"User-Agent": "reels-factory-doc-map"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            text = response.read().decode("utf-8")
    except Exception as error:  # сеть, прокси, таймаут — всё одно
        old = "прежняя карта на месте" if OUT.exists() else "карты нет вовсе"
        print(f"индекс не скачался ({error}); {old}")
        return 0
    entries = rows(text)
    if not entries:
        print("индекс скачался, но записей в нём не нашлось — карта не тронута")
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    OUT.write_text(render(entries, stamp), encoding="utf-8")
    print(f"карта обновлена: {len(entries)} страниц, {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
