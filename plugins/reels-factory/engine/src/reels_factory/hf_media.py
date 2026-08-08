"""Подбор вставок: их поиск, наш отсев, их заморозка.

Что показать под фразу, решает агент — он присылает намерение словами. Дальше
всё механика, и делается она их же средствами:

1. кандидатов ищет их CLI — `heygen asset search`, ранжирование семантическое,
   их (`media-use/scripts/lib/heygen-search.mjs`);
2. выбранный файл замораживает их `resolve --from <url>`: файл ложится в
   `.media`, запись — в их реестр `manifest.jsonl` (resolve.mjs, ветка ingest);
3. наш здесь только отсев. Сам скил не отсеивает ничего: его провайдер берёт
   первый ответ поиска вслепую (`image-provider.mjs:7`), и на прогоне 15 так в
   кадр доехали водяной знак dreamstime, мыло 500x281 и один снимок на две
   сцены. А «спросить ещё раз» через их `resolve` нельзя: одинаковое намерение
   детерминированно возвращает тот же файл из манифеста (resolve.md, «How it
   works», шаги 1 и 3). Их же философия отдаёт выбор нам: «media-use does not
   semantically match for you — you are the judge» (references/resolve.md:76).

Порядок кандидатов внутри запроса — их ранжирование; мы только вычёркиваем
негодных, первый уцелевший и берётся.

Видео вместо фото взять неоткуда: их каталог отдаёт `image` и `icon` и ничего
больше (`heygen asset search --type` v0.5.0), а `--type video` у их skill — это
генерация (платный HeyGen-аватар либо локальный LTX на GPU, которого у нас
нет). Живость неподвижной вставки — забота слоя движения, не подбора.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from reels_factory.config import FFMPEG, FFPROBE

SKILL_DIR = Path.home() / ".claude" / "skills" / "media-use"
RESOLVE = SKILL_DIR / "scripts" / "resolve.mjs"

#: Сколько запросов держим в воздухе. Реестр media-use пишется атомарно
#: (`withReservedFile`, resolve.mjs:487-501), поэтому параллель безопасна;
#: ограничение здесь — вежливость к их поставщику, а не наша сохранность.
MAX_PARALLEL = 4

TIMEOUT_S = 180

#: Сколько кандидатов просить у поиска на одно намерение. Их провайдер просит
#: пять и берёт первого; нам нужен запас под отсев.
SEARCH_LIMIT = 20

#: Короткая сторона вставки в пикселях — жёсткий пол для любого файла. Ниже —
#: это значок, а не фотография.
MIN_INSERT_SIDE = 240

#: Во сколько раз файл можно растянуть до прямоугольника вставки (cover — по
#: большей из двух осей). Выше — мыло: ровно так на прогоне 15 кадр 1080x1920
#: закрывался файлом 500x281, растянутым в 6,8 раза.
MAX_UPSCALE = 3.0

#: Следы стоков на превью. Такой водяной знак — брак вставки независимо от
#: размера надписи.
WATERMARK_TOKENS = ("dreamstime", "shutterstock", "istock", "getty", "alamy",
                    "depositphotos", "123rf", "bigstock", "vecteezy", "freepik",
                    "adobe stock", "stock photo")

#: Порог OCR-уверенности и высоты, с которых слово на фотографии считается
#: читаемым текстом. Высота — доля высоты кадра: вывеска на заднем плане ниже
#: порога, надпись поверх снимка — выше.
_OCR_CONF = 60.0
_OCR_MARK_CONF = 40.0
_OCR_MIN_LETTERS = 3
_OCR_MIN_HEIGHT_SHARE = 0.03
_OCR_MIN_WORDS = 2

_LETTERS = re.compile(r"[^\W\d_]+", re.UNICODE)


def _node_env() -> dict:
    return {**os.environ}


# ------------------------------------------------------------------ их поиск

def search_assets(intent: str, *, kind: str = "image",
                  limit: int = SEARCH_LIMIT) -> list[dict]:
    """Кандидаты их каталога, в их порядке убывания похожести.

    Поля ответа: `id` (содержательный хеш — по нему дешевле всего ловить один
    снимок под разными намерениями), `url`, иногда `width`/`height`,
    `is_transparent`, `orientation`.
    """
    result = subprocess.run(
        ["heygen", "asset", "search", "--query", intent, "--type", kind,
         "--limit", str(limit)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=TIMEOUT_S, env=_node_env())
    if result.returncode != 0:
        return []
    try:
        parsed = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return []
    data = parsed.get("data")
    return data if isinstance(data, list) else []


def ingest(public, url: str, *, kind: str = "image") -> dict:
    """Заморозить выбранный URL их же `resolve --from`: файл в `.media`,
    запись в их реестр."""
    result = subprocess.run(
        ["node", str(RESOLVE), "--type", kind, "--from", url,
         "--project", str(public), "--json"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=TIMEOUT_S, env=_node_env())
    text = (result.stdout or "").strip()
    if result.returncode != 0 or not text.startswith("{"):
        return {"ok": False,
                "error": (result.stderr or text or "нет ответа")[:300]}
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        return {"ok": False, "error": f"ответ не разбирается: {error}"}


# ------------------------------------------------------------------- отсев

def _upscale(width: float, height: float, rect: dict | None) -> float:
    if not rect or not width or not height:
        return 1.0
    return max(float(rect["width"]) / width, float(rect["height"]) / height)


def candidate_problem(candidate: dict, rect: dict | None) -> str | None:
    """Чем кандидат негоден по метаданным поиска. `None` — пока годен.

    Размеры каталог отдаёт не всегда; без них судьба решается уже по файлу.
    """
    if candidate.get("is_transparent"):
        return "прозрачный — сквозь него виден чёрный фон"
    width = candidate.get("width") or 0
    height = candidate.get("height") or 0
    if not width or not height:
        return None
    if min(width, height) < MIN_INSERT_SIDE:
        return f"мелкий: {width}x{height}"
    scale = _upscale(width, height, rect)
    if scale > MAX_UPSCALE:
        return (f"{width}x{height} в прямоугольник вставки растянется в "
                f"{scale:.1f} раза — будет мыло")
    return None


#: Форматы пикселей с альфа-каналом: прозрачная вставка показывает чёрный фон
#: сцены. На прогоне 14 так вышли шесть вставок из четырнадцати.
_ALPHA_PIX_FMTS = ("rgba", "bgra", "argb", "abgr", "ya8", "ya16", "pal8",
                   "yuva420p", "yuva422p", "yuva444p", "gbrap")

#: Ниже этого значения альфа-канал считается настоящей прозрачностью: PNG-
#: фотография несёт rgba со сплошной единицей.
_OPAQUE_ALPHA = 250


def _probe_dimensions(path) -> tuple[int, int, str] | None:
    result = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=pix_fmt,width,height", "-of", "csv=p=0",
         str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    parts = (result.stdout or "").strip().split(",")
    if len(parts) < 3:
        return None
    try:
        return int(parts[0]), int(parts[1]), parts[2].strip().lower()
    except ValueError:
        return None


def _transparent(path) -> bool:
    """Есть ли в файле реально прозрачные пиксели, а не просто альфа-канал."""
    result = subprocess.run(
        [FFMPEG, "-v", "error", "-i", str(path), "-vf",
         "alphaextract,signalstats,metadata=print:file=-", "-an", "-f", "null",
         "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    found = re.search(r"YMIN=(\d+)", result.stdout or "")
    return bool(found) and int(found.group(1)) < _OPAQUE_ALPHA


def insert_problem(path, rect: dict | None = None) -> str | None:
    """Чем скачанный файл не годится во вставку. `None` — годится.

    Быстрая часть суда: размер и прозрачность одним ffprobe/ffmpeg. Текст на
    фотографии — отдельно (`text_problem`): OCR дороже, и звать его дважды
    незачем.
    """
    probed = _probe_dimensions(path)
    if probed is None:
        return "файл не читается"
    width, height, pix_fmt = probed
    if min(width, height) < MIN_INSERT_SIDE:
        return (f"файл {width}x{height} — мельче {MIN_INSERT_SIDE} px по "
                "короткой стороне, в кадре останется мыло")
    scale = _upscale(width, height, rect)
    if scale > MAX_UPSCALE:
        return (f"файл {width}x{height} в прямоугольник вставки растянется в "
                f"{scale:.1f} раза — будет мыло")
    if pix_fmt in _ALPHA_PIX_FMTS and _transparent(path):
        return "файл прозрачный — сквозь него виден чёрный фон"
    return None


_warned_no_ocr = False


def text_problem(path) -> str | None:
    """Водяной знак или читаемый текст на фотографии. `None` — чисто.

    Ни их линтер, ни media-use этого не ловят: `check` судит текст DOM, а не
    пиксели файла, у resolve фильтров нет вовсе — поэтому здесь наш OCR.
    tesseract с `--psm 11` (россыпь слов без структуры страницы) отдаёт TSV со
    словом, уверенностью и рамкой; водяной знак ловится по словарю стоков, а
    «читаемый текст» — по крупным уверенным словам. Рукописный текст OCR берёт
    нетвёрдо — это известная слепая зона, не притворяемся, что её нет.
    """
    global _warned_no_ocr
    if shutil.which("tesseract") is None:
        if not _warned_no_ocr:
            print("tesseract не установлен — вставки идут в кадр без проверки "
                  "на водяные знаки и текст")
            _warned_no_ocr = True
        return None
    probed = _probe_dimensions(path)
    frame_height = probed[1] if probed else 0
    result = subprocess.run(
        ["tesseract", str(path), "stdout", "-l", "eng+rus", "--psm", "11",
         "tsv"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        return None
    return scan_ocr_rows(result.stdout or "", frame_height)


def scan_ocr_rows(tsv: str, frame_height: int) -> str | None:
    """Суд по строкам TSV tesseract. Вынесен отдельно ради тестов без бинаря."""
    lines = tsv.splitlines()
    if not lines:
        return None
    header = lines[0].split("\t")
    try:
        conf_at = header.index("conf")
        text_at = header.index("text")
        height_at = header.index("height")
    except ValueError:
        return None

    big_words = []
    for line in lines[1:]:
        parts = line.split("\t")
        if len(parts) <= max(conf_at, text_at, height_at):
            continue
        word = parts[text_at].strip()
        if not word:
            continue
        try:
            conf = float(parts[conf_at])
            height = float(parts[height_at])
        except ValueError:
            continue
        lowered = word.lower()
        if conf >= _OCR_MARK_CONF and any(
                token in lowered for token in WATERMARK_TOKENS):
            return f"водяной знак: «{word}»"
        letters = "".join(_LETTERS.findall(word))
        if (conf >= _OCR_CONF and len(letters) >= _OCR_MIN_LETTERS
                and frame_height
                and height >= _OCR_MIN_HEIGHT_SHARE * frame_height):
            big_words.append(word)
    if len(big_words) >= _OCR_MIN_WORDS:
        return "читаемый текст на фотографии: " + " ".join(big_words[:5])
    return None


# ------------------------------------------------------------------- подбор

def _resolve_one(project: Path, kind: str, intent: str) -> dict:
    """Слепой подбор их `resolve` — для типов без поиска кандидатов (логотип
    идёт каскадом svgl → simple-icons → …, там выбирать не из чего)."""
    result = subprocess.run(
        ["node", str(RESOLVE), "--type", kind, "--intent", intent,
         "--project", str(project), "--json"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=TIMEOUT_S, env=_node_env())
    text = (result.stdout or "").strip()
    if result.returncode != 0 or not text.startswith("{"):
        return {"ok": False,
                "error": (result.stderr or text or "нет ответа")[:300]}
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        return {"ok": False, "error": f"ответ не разбирается: {error}"}


def _claim(request: dict, candidates: list[dict], taken: set[str],
           *, relaxed: bool = False) -> dict | None:
    """Первый годный и никем не занятый кандидат, в их порядке ранжирования.

    `relaxed` — запасной круг для сцен, где вставка обязательна: там мыло всё
    ещё лучше чёрного кадра, и вето растяжения снимается. Жёсткий пол размера
    и прозрачность остаются.
    """
    rect = None if relaxed else request.get("rect")
    for candidate in candidates:
        if candidate.get("id") in taken:
            continue
        if candidate_problem(candidate, rect):
            continue
        return candidate
    return None


def resolve_all(public, requests: list[dict]) -> dict[str, dict]:
    """Подобрать все вставки: поиск и заморозка параллельно, выбор по порядку.

    `requests` — список `{"key", "type", "intent", "rect", "required"}`; `rect`
    — прямоугольник, который файл закроет в кадре, `required` — сцена без
    ведущей, где вставка обязательна. Возвращает
    `{key: {"file": путь относительно public} | {"error": …}}`.

    Выбор кандидатов идёт строго в порядке запросов, а не наперегонки: иначе
    два близких намерения разыгрывали бы один снимок жребием потоков, и
    пересборка того же плана давала бы другой кадр.
    """
    public = Path(public)
    if not RESOLVE.exists():
        raise RuntimeError(
            f"нет скрипта подбора {RESOLVE}; скил media-use не установлен")
    if not requests:
        return {}

    searchable = [r for r in requests if r.get("type", "image") == "image"]
    blind = [r for r in requests if r.get("type", "image") != "image"]

    resolved: dict[str, dict] = {}

    with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as pool:
        found = dict(zip(
            [r["key"] for r in searchable],
            pool.map(lambda r: search_assets(r["intent"]), searchable)))
        for request, answer in zip(
                blind,
                pool.map(lambda r: _resolve_one(public, r["type"],
                                                r["intent"]), blind)):
            if not answer.get("ok") or not answer.get("path"):
                resolved[request["key"]] = {
                    "error": answer.get("error") or "подбор не дал файла"}
            else:
                resolved[request["key"]] = {"file": answer["path"],
                                            "intent": request["intent"]}

        # Один снимок не ставится дважды: `id` каталога — содержательный хеш,
        # прогон 15 получил один файл под двумя именами именно потому, что
        # никто не сверял кандидатов между сценами.
        taken: set[str] = set()
        chosen: dict[str, dict] = {}
        spare: dict[str, list[dict]] = {}
        for request in searchable:
            candidates = found.get(request["key"]) or []
            pick = _claim(request, candidates, taken)
            if pick is None and request.get("required"):
                pick = _claim(request, candidates, taken, relaxed=True)
            if pick is None:
                resolved[request["key"]] = {
                    "error": "каталог не дал годного кандидата: "
                             f"«{request['intent']}»"}
                continue
            taken.add(pick["id"])
            chosen[request["key"]] = pick
            spare[request["key"]] = candidates

        keys = list(chosen)
        frozen = dict(zip(keys, pool.map(
            lambda key: ingest(public, chosen[key]["url"]), keys)))

    # Суд по самому файлу — размеры каталог отдаёт не всегда, а водяной знак
    # по метаданным не виден вовсе. Негодный файл заменяется следующим
    # кандидатом того же запроса; это редкий хвост, параллелить нечего.
    by_key = {r["key"]: r for r in searchable}
    for key in keys:
        request = by_key[key]
        answer = frozen[key]
        while True:
            problem = (None if not answer.get("ok") or not answer.get("path")
                       else insert_problem(public / answer["path"],
                                           request.get("rect"))
                       or text_problem(public / answer["path"]))
            if answer.get("ok") and answer.get("path") and not problem:
                resolved[key] = {"file": answer["path"],
                                 "intent": request["intent"]}
                break
            if problem:
                print(f"вставка «{request['intent']}» отклонена: {problem}")
            pick = _claim(request, spare.get(key) or [], taken)
            if pick is None:
                resolved[key] = {"error": answer.get("error") or problem
                                 or "подбор не дал файла"}
                break
            taken.add(pick["id"])
            answer = ingest(public, pick["url"])
    return resolved
