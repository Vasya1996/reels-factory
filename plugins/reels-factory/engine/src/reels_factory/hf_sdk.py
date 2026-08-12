"""Их редактор композиций из питона: тонкая обёртка над `@hyperframes/sdk`.

Разбор HTML, правку элементов и запись обратно движок держит готовыми. Своего
разборщика у нас нет: элементы, их атрибуты, собственный текст и даже список
твинов, целящихся в элемент, отдаёт `comp.getElements()`
(`packages/sdk/src/types.ts:25-50`), а правки идут их же операциями
(`packages/sdk/src/types.ts:104-163`).

Процесс node поднимается один на сборку и живёт, пока открыт `sdk_session()`.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

BRIDGE = Path(__file__).resolve().parents[2] / "scripts" / "hf_sdk.mjs"

#: Чем звать node. На Windows это `node.exe` в PATH, в WSL — обычный `node`.
NODE = os.environ.get("REELS_NODE") or shutil.which("node") or "node"


@dataclass
class Node:
    """Элемент композиции в разборе их SDK."""

    hfid: str
    tag: str
    classes: list[str]
    attrs: dict[str, str]
    text: str | None
    start: float | None
    duration: float | None
    track_index: int | None
    anims: list[str]
    parent: int | None
    index: int
    children: list[int] = field(default_factory=list)

    def has_class(self, name: str) -> bool:
        return name in self.classes


def _to_node(raw: dict) -> Node:
    return Node(hfid=raw["hfid"], tag=raw["tag"], classes=raw["classes"],
                attrs=raw["attrs"], text=raw["text"], start=raw["start"],
                duration=raw["duration"], track_index=raw["trackIndex"],
                anims=raw["anims"], parent=raw["parent"], index=raw["index"],
                children=raw["children"])


class SdkError(RuntimeError):
    pass


class Sdk:
    """Открытые композиции и очередь правок к ним."""

    def __init__(self, process: subprocess.Popen):
        self._process = process
        self._id = 0

    def _call(self, **message) -> dict:
        self._id += 1
        message["id"] = self._id
        self._process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        self._process.stdin.flush()
        line = self._process.stdout.readline()
        if not line:
            tail = (self._process.stderr.read() or "")[-1000:]
            raise SdkError(f"мост к их SDK оборвался: {tail}")
        answer = json.loads(line)
        if not answer.get("ok"):
            raise SdkError(answer.get("error") or "мост к их SDK вернул отказ")
        return answer

    def open(self, name: str, path) -> None:
        self._call(cmd="open", name=name, path=str(path))

    def elements(self, name: str) -> list[Node]:
        return [_to_node(raw) for raw in self._call(cmd="elements", name=name)["elements"]]

    def dispatch(self, name: str, ops: list[dict]) -> None:
        if ops:
            self._call(cmd="dispatch", name=name, ops=ops)

    def save(self, name: str, path) -> None:
        self._call(cmd="save", name=name, path=str(path))

    def close(self, name: str) -> None:
        self._call(cmd="close", name=name)

    def extract(self, path, selector: str, *, all: bool = False) -> list[dict]:
        """Куски чужого файла разметкой: `{"outer": …, "text": …}` на каждый."""
        return self._call(cmd="extract", path=str(path), selector=selector,
                          all=all)["found"]


@contextmanager
def sdk_session():
    """Поднять мост на время сборки."""
    if not BRIDGE.exists():
        raise SdkError(f"нет моста {BRIDGE}")
    process = subprocess.Popen(
        [NODE, str(BRIDGE)], cwd=str(BRIDGE.parent),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace")
    try:
        yield Sdk(process)
    finally:
        try:
            process.stdin.close()
        except OSError:
            pass
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


# ------------------------------------------------------------------ операции

def set_text(target: str, value: str) -> dict:
    return {"type": "setText", "target": target, "value": value}


def set_attribute(target: str, name: str, value: str | None) -> dict:
    return {"type": "setAttribute", "target": target, "name": name, "value": value}


def set_timing(target: str, *, start: float | None = None,
               duration: float | None = None,
               track_index: int | None = None) -> dict:
    op = {"type": "setTiming", "target": target}
    if start is not None:
        op["start"] = start
    if duration is not None:
        op["duration"] = duration
    if track_index is not None:
        op["trackIndex"] = track_index
    return op


def remove_element(target: str) -> dict:
    return {"type": "removeElement", "target": target}


def add_element(parent: str | None, index: int, html: str) -> dict:
    return {"type": "addElement", "parent": parent, "index": index, "html": html}


def remove_tween(animation_id: str) -> dict:
    return {"type": "removeGsapTween", "animationId": animation_id}
