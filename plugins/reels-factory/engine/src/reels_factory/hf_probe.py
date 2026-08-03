"""Гейты по живой композиции, а не по раскадровке.

Раскадровка — мнение агента: он волен написать в ней любые координаты, а в
index.html сверстать другое. Здесь композиция открывается в headless-браузере,
перематывается их же каскадом (`scripts/probe_composition.cjs`) и судится по
тому, что реально оказалось в DOM в этот момент.

Проверка, которая не состоялась, обязана падать: молчаливый PASS на
неоткрывшемся браузере опаснее отсутствия гейта.
"""
from __future__ import annotations

import functools
import json
import shutil
import subprocess
from pathlib import Path

from reels_factory.config import OUT_H, OUT_W
from reels_factory.hf_layout import moved_face, violations

#: Скрипт пробы лежит рядом с движком; при editable-установке путь живой.
PROBE_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "probe_composition.cjs"

#: Частота выборки по умолчанию. Карточка живёт секунды, вставка — доли;
#: четверть секунды ловит и то и другое, не раздувая прогон.
DEFAULT_INTERVAL = 0.25

#: Порог «заметно другого» положения окна ведущей — 5% стороны кадра
#: (54 px по горизонтали, 96 px по вертикали при 1080x1920). Ниже этого сдвиг
#: читается как дрожание, а не как перестановка: самая мелкая раскладка в
#: hf_layout.VIDEO_RECTS — `pip` 360x203, и любая настоящая смена раскладки
#: даёт разницу в сотни пикселей, то есть порог с запасом ниже полезного
#: сигнала и с запасом выше округлений getBoundingClientRect.
MOVE_FRACTION = 0.05


def _node() -> str:
    node = shutil.which("node")
    if not node:
        raise RuntimeError(
            "нет node в PATH — проба живой композиции не запускается; "
            "без неё гейты D8/D14/D15 не проверены")
    return node


@functools.lru_cache(maxsize=4)
def chrome_path(hf_version: str) -> str | None:
    """Браузер, которым рендерит движок. Спрашиваем у них же.

    Свой список путей проба держит на случай системного Chrome, но у нас его
    нет: `browser ensure` кладёт закреплённую сборку в ~/.cache/hyperframes, и
    единственный поддерживаемый способ узнать её путь — их команда
    (`hyperframes-cli/references/doctor-browser.md:51-52`). Судить композицию
    другим браузером нельзя: они и закрепили версию потому, что кадр между
    сборками Chrome плывёт (там же:55).
    """
    result = subprocess.run(
        f'npx --yes hyperframes@{hf_version} browser path',
        shell=True, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    for line in reversed((result.stdout or "").splitlines()):
        candidate = line.strip()
        if candidate and Path(candidate).exists():
            return candidate
    return None


def run_probe(rdir, *, interval: float = DEFAULT_INTERVAL,
              hf_version: str | None = None) -> dict:
    """Снять выборки с композиции `rdir/public` и вернуть отчёт пробы."""
    rdir = Path(rdir)
    public = rdir / "public"
    index = public / "index.html"
    if not index.exists():
        raise RuntimeError(f"нет композиции {index} — судить нечего")
    if not PROBE_SCRIPT.exists():
        raise RuntimeError(
            f"нет скрипта пробы {PROBE_SCRIPT}; движок установлен не из клона")

    if hf_version is None:
        from reels_factory.hyperframes_blocks import _HF_VERSION
        hf_version = _HF_VERSION

    out = rdir / "probe.json"
    command = [_node(), str(PROBE_SCRIPT), "--project", str(public),
               "--out", str(out), "--interval", str(interval),
               "--hf-version", hf_version]
    chrome = chrome_path(hf_version)
    if chrome:
        command += ["--chrome", chrome]
    result = subprocess.run(command, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(
            "проба живой композиции не состоялась: "
            f"{(result.stderr or result.stdout or '').strip()[:800]}")
    if not out.exists():
        raise RuntimeError(f"проба отработала, но не оставила {out}")
    return json.loads(out.read_text(encoding="utf-8"))


def _noticeably_different(a: dict, b: dict) -> bool:
    dx = MOVE_FRACTION * OUT_W
    dy = MOVE_FRACTION * OUT_H
    return (abs(a["left"] - b["left"]) >= dx or abs(a["width"] - b["width"]) >= dx
            or abs(a["top"] - b["top"]) >= dy or abs(a["height"] - b["height"]) >= dy)


def _distinct_positions(rects: list[dict]) -> list[dict]:
    """Заметно разные положения окна ведущей."""
    distinct: list[dict] = []
    for rect in rects:
        if all(_noticeably_different(rect, seen) for seen in distinct):
            distinct.append(rect)
    return distinct


def _gate_face(samples: list[dict], face: dict | None) -> str:
    if not face:
        return "PASS: лица нет в face.json — перекрывать нечего"
    problems = []
    for sample in samples:
        video = sample.get("videoRect")
        if not video or not video.get("visible"):
            # ведущей на экране нет: аватар на этот кусок не заказан
            continue
        here = moved_face(face, video)
        for text in sample.get("texts") or []:
            if violations(text["rect"], here):
                label = (text.get("text") or text.get("selector") or "?")[:40]
                problems.append(f'{sample["time"]}с: «{label}»')
    if not problems:
        return "PASS"
    shown = "; ".join(problems[:5])
    tail = f" и ещё {len(problems) - 5}" if len(problems) > 5 else ""
    return f"FAIL: текст на лице ведущей — {shown}{tail}"


def _gate_presenter_moves(samples: list[dict]) -> str:
    rects = [sample["videoRect"] for sample in samples
             if sample.get("videoRect") and sample["videoRect"].get("visible")]
    if not rects:
        return "FAIL: ведущей нет на экране ни на одной выборке"
    distinct = _distinct_positions(rects)
    if len(distinct) >= 2:
        return "PASS"
    only = distinct[0]
    return ("FAIL: окно ведущей за весь ролик стоит на месте — "
            f'{int(only["left"])},{int(only["top"])} '
            f'{int(only["width"])}x{int(only["height"])}')


def _gate_catalog_blocks(report: dict) -> str:
    sources = report.get("compositionSrc") or []
    if sources:
        return "PASS"
    return ("FAIL: в композиции нет ни одного data-composition-src — "
            "блоки каталога не подключены")


def gates_from_report(report: dict, face: dict | None = None) -> dict[str, str]:
    """Судить готовый отчёт пробы. Отдельно от запуска — ради тестов."""
    samples = report.get("samples") or []
    if not samples:
        raise RuntimeError("проба не сняла ни одной выборки — проверять нечего")
    if report.get("sweepStatic"):
        # Их же условие sweep_static (checkPipeline.ts:480-515): один отпечаток
        # на всех выборках значит, что перемотка ничего не двигала, и любой
        # зелёный вердикт этого прогона недостоверен.
        reason = ("FAIL: таймлайн не двигался под перемоткой — "
                  "вердикты пробы недостоверны")
        return {"D8_face": reason, "D14_presenter_moves": reason,
                "D15_catalog_blocks": reason}
    return {
        "D8_face": _gate_face(samples, face),
        "D14_presenter_moves": _gate_presenter_moves(samples),
        "D15_catalog_blocks": _gate_catalog_blocks(report),
    }


def probe_gates(rdir, *, face: dict | None = None,
                interval: float = DEFAULT_INTERVAL) -> dict[str, str]:
    """Прогнать пробу и вернуть гейты `{"имя": "PASS" | "FAIL: причина"}`."""
    return gates_from_report(run_probe(rdir, interval=interval), face)
