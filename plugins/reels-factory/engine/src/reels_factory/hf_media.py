"""Подбор вставок: поиск, суд моделью, заморозка их средствами.

Что показать под фразу, решает агент — он присылает намерение словами. Дальше
всё механика:

1. **Видео-бироллы** ищутся в Pexels — единственный сток с серверным фильтром
   вертикали (`orientation=portrait`; Pixabay и Coverr фильтруют только
   клиентом, замерено 08.08.2026). Своего стока у HyperFrames нет вовсе —
   проверено по клону, скилам и сайту вплоть до 0.7.101: тип `video` в
   media-use умеет только генерацию (аватар за деньги либо LTX на Apple
   Silicon). Их канонический путь — «принеси файл сам»: «`<video>` — Video
   clips, B-roll, A-roll» (docs/concepts/compositions.mdx:25).
2. **Кандидатов судит модель глазами** по превью-кадрам: их же философия —
   «media-use does not semantically match for you — you are the judge»
   (references/resolve.md:76). Метаданные отсеивают мелкое и короткое, смысл
   судит одна дешёвая сессия на весь ролик.
3. **Заморозка** — их `resolve --from`: файл ложится в `.media`, запись — в их
   реестр `manifest.jsonl` (resolve.mjs, ветка ingest). Скачиваем сами (Pexels
   отдаёт 403 без User-Agent — оплаченная грабля), замораживаем локальный файл.

Картинки (`image`) остаются запасным путём — их каталог, их ранжирование, наш
отсев; подробности у соответствующих функций ниже.
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


# ------------------------------------------------------------ видео-бироллы

#: Ключ Pexels: переменная окружения либо файл в связке рядом с ключом HeyGen.
_PEXELS_KEY_FILE = Path.home() / ".reels-factory" / "pexels.key"

#: Сколько кандидатов просить у стока на одно намерение.
PEXELS_LIMIT = 10

#: Без User-Agent Pexels отдаёт 403 — оплаченная грабля (замер Юли, README
#: broll-zoom-toolkit, грабля 5).
_UA = {"User-Agent": "reels-factory/0.2 (b-roll fetch)"}

#: Сколько кандидатов на сцену показываем судье. Больше — дольше сессия,
#: а решает он обычно между первыми тремя.
JUDGE_CANDIDATES = 4


def _pexels_key() -> str | None:
    key = os.environ.get("PEXELS_API_KEY")
    if key:
        return key.strip()
    if _PEXELS_KEY_FILE.exists():
        return _PEXELS_KEY_FILE.read_text(encoding="utf-8").strip()
    return None


#: Ролики одной съёмочной серии Pexels идут соседними номерами (один автор
#: заливает дубли одной сцены пачкой). Ближе этого расстояния — считается
#: той же серией: прогон 17 поставил один и тот же блокнот в три сцены
#: тремя «разными» роликами 36633828/36633851.
SERIES_DISTANCE = 100


def _best_file(video: dict, *, portrait_only: bool = True) -> dict | None:
    """Лучший файл ролика: mp4, по высоте ближе к нашим 1920.

    Pexels отдаёт один ролик несколькими перекодировками; берём не самую
    большую, а достаточную — 4K-файл тянется дольше, а кадр у нас 1080x1920.
    Для вставки в половине кадра годится и горизонтальный HD: прямоугольник
    1080x1076 он закрывает без растяжения.
    """
    files = []
    for f in video.get("video_files") or []:
        if f.get("file_type") != "video/mp4":
            continue
        width, height = f.get("width") or 0, f.get("height") or 0
        if portrait_only and height <= width:
            continue
        small = (height < 1280) if portrait_only else (min(width, height) < 1080)
        if small:
            continue
        files.append(f)
    if not files:
        return None
    return min(files, key=lambda f: abs((f.get("height") or 0) - 1920))


def search_pexels(intent: str, *, seconds: float = 0.0,
                  portrait_only: bool = True,
                  limit: int = PEXELS_LIMIT) -> list[dict]:
    """Кандидаты Pexels, в их порядке релевантности.

    `intent` — прямой английский поисковый запрос из плана агента, уходит в
    сток без изменений. Возвращает нормализованные словари: `id`, `duration`,
    `preview` (кадр), `url` (mp4), `width`/`height` файла. Отсев по
    метаданным здесь же: короче сцены и мельче кадра не показываем даже судье.
    """
    import urllib.parse
    import urllib.request

    key = _pexels_key()
    if not key:
        print("нет ключа Pexels (PEXELS_API_KEY или ~/.reels-factory/"
              "pexels.key) — видео-бироллы не ищутся")
        return []
    fields = {"query": intent, "size": "medium", "per_page": str(limit)}
    # Вертикаль сервером — только для полноэкранной вставки; в половину кадра
    # ложится и горизонтальный HD, там фильтр ориентации лишь сузил бы выдачу.
    if portrait_only:
        fields["orientation"] = "portrait"
    query = urllib.parse.urlencode(fields)
    request = urllib.request.Request(
        f"https://api.pexels.com/videos/search?{query}",
        headers={**_UA, "Authorization": key})
    try:
        with urllib.request.urlopen(request, timeout=30) as answer:
            payload = json.loads(answer.read().decode("utf-8"))
    except Exception as error:  # сеть и лимиты — не повод ронять сборку
        print(f"поиск Pexels не ответил: {error}")
        return []

    found = []
    for video in payload.get("videos") or []:
        best = _best_file(video, portrait_only=portrait_only)
        if best is None:
            continue
        if seconds and float(video.get("duration") or 0) < seconds:
            # короче сцены: движок заморозит последний кадр, это брак
            continue
        found.append({"id": f"pexels-{video['id']}",
                      "series": int(video["id"]),
                      "duration": float(video.get("duration") or 0),
                      "preview": video.get("image"),
                      "url": best["link"],
                      "width": best.get("width"), "height": best.get("height"),
                      "is_transparent": False})
    return found


def _same_series(candidate: dict, taken_series: set[int]) -> bool:
    number = candidate.get("series")
    if number is None:
        return False
    return any(abs(number - other) < SERIES_DISTANCE for other in taken_series)


def _download(url: str, target: Path) -> Path | None:
    import urllib.request

    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers=_UA)
    try:
        with urllib.request.urlopen(request, timeout=180) as answer:
            target.write_bytes(answer.read())
    except Exception as error:
        print(f"не скачалось {url}: {error}")
        return None
    return target if target.stat().st_size > 0 else None


_JUDGE_PROMPT = """Ты отбираешь видео-бироллы для вертикального рилса.

Тема ролика: {domain}
Чего в ролике быть не должно: {anti}

Ниже сцены. У каждой — реплика диктора, которую биролл иллюстрирует, и
превью-кадры кандидатов (файлы). Посмотри кадры инструментом Read и для
каждой сцены выбери ОДИН кандидат, который буквально показывает то, о чём
реплика, живой и снятый камерой. Отклоняй: не про то, постановочные стоковые
клише (рукопожатия, «бизнесмен вообще»), кадры с крупным читаемым текстом,
мультяшное и нарисованное. Если не годится ни один — null.

Не выбирай кандидата, чей кадр почти совпадает с уже выбранным для другой
сцены — та же обстановка, тот же предмет, тот же ракурс: повтор картинки
хуже отказа. Ролик смотрят подряд, и два одинаковых кадра зритель видит
как один.

{scenes}

Ответь ТОЛЬКО JSON без пояснений: {{"<id сцены>": <номер кандидата или null>, …}}
"""


def judge_previews(requests: list[dict], *, domain: str = "", anti: str = "",
                   runner=None) -> dict[str, int | None]:
    """Один суд на весь ролик: дешёвая сессия смотрит превью и выбирает.

    `requests` — `[{"key", "intent", "speech", "previews": [пути]}]`.
    Возвращает `{key: индекс выбранного | None}`. Без судьи (нет previews или
    сессия упала) — берётся первый кандидат, как раньше: суд улучшает выбор,
    но его отказ не должен останавливать фабрику.
    """
    from reels_factory.hf_agent import HeyGenAgentRunner

    blocks = []
    for request in requests:
        lines = [f'Сцена `{request["key"]}`: диктор говорит «{request.get("speech") or request["intent"]}»,'
                 f' показать: {request["intent"]}']
        for index, preview in enumerate(request["previews"]):
            lines.append(f"- кандидат {index}: {preview}")
        blocks.append("\n".join(lines))
    prompt = _JUDGE_PROMPT.format(domain=domain or "не указана",
                                  anti=anti or "не указано",
                                  scenes="\n\n".join(blocks))

    if runner is None:
        runner = HeyGenAgentRunner(timeout_s=300, model="claude-haiku-4-5")
        # Дешёвой модели глубина рассуждения не передаётся вовсе: конструктор
        # подхватил бы REELS_AGENT_EFFORT из окружения раннера, а флаг там про
        # модель плана, не про судью.
        runner.effort = None
    try:
        answer = runner.run(prompt)
    except Exception as error:
        print(f"судья бироллов не ответил ({error}) — берём первых кандидатов")
        return {}
    match = re.search(r"\{.*\}", answer, re.S)
    if not match:
        print("судья бироллов не вернул JSON — берём первых кандидатов")
        return {}
    try:
        verdicts = json.loads(match.group(0))
    except json.JSONDecodeError:
        print("JSON судьи не разбирается — берём первых кандидатов")
        return {}
    return {str(key): (int(value) if value is not None else None)
            for key, value in verdicts.items()}


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


def _resolve_videos(public: Path, requests: list[dict], *,
                    domain: str = "", anti: str = "",
                    judge_runner=None,
                    pool: ThreadPoolExecutor) -> dict[str, dict]:
    """Видео-бироллы: поиск в Pexels, суд моделью, заморозка их `resolve`.

    Выбор строго в порядке запросов; один ролик не ставится дважды.
    Вердикт `null` судьи уважается: сцена остаётся без вставки, и её
    закрывает ведущая (settle_inserts) — кринж хуже отсутствия.
    """
    resolved: dict[str, dict] = {}

    def hunt(request: dict) -> list[dict]:
        # Вертикаль обязательна только там, где вставка закрывает кадр
        # целиком; в половину кадра (сплит с ведущей) ложится и
        # горизонтальный HD без растяжения.
        rect = request.get("rect") or {}
        portrait = float(rect.get("height") or 1920) > 1500
        found = search_pexels(request["intent"],
                              seconds=float(request.get("seconds") or 0),
                              portrait_only=portrait)
        if not found and domain:
            # запасной запрос — тема ролика: хуже точного, лучше пустоты
            found = search_pexels(domain,
                                  seconds=float(request.get("seconds") or 0),
                                  portrait_only=portrait)
        return found

    found = dict(zip([r["key"] for r in requests], pool.map(hunt, requests)))

    previews_dir = public / ".broll-previews"
    jobs = []
    for request in requests:
        for index, cand in enumerate(
                (found.get(request["key"]) or [])[:JUDGE_CANDIDATES]):
            if cand.get("preview"):
                jobs.append((request["key"], index, cand["preview"]))
    paths = dict(zip(
        [(key, index) for key, index, _ in jobs],
        pool.map(lambda job: _download(
            job[2], previews_dir / f"{job[0]}-{job[1]}.jpg"), jobs)))

    # Страховка от текста в кадре ДО судьи: OCR по превью снимает кандидата
    # с крупной надписью («NEW YEAR NEW ME» прогона 17 судья пропустил).
    for (key, index), path in list(paths.items()):
        if path is None:
            continue
        problem = text_problem(path)
        if problem:
            print(f"кандидат {key}/{index} снят по превью: {problem}")
            paths[(key, index)] = None
            candidates = found.get(key) or []
            if index < len(candidates):
                candidates[index] = {**candidates[index], "vetoed": True}

    judged: dict[str, int | None] = {}
    shown_maps: dict[str, list[int]] = {}
    with_previews = []
    for request in requests:
        candidates = found.get(request["key"]) or []
        shown, mapping = [], []
        for index in range(min(JUDGE_CANDIDATES, len(candidates))):
            path = paths.get((request["key"], index))
            if path:
                shown.append(str(path))
                mapping.append(index)
        if shown:
            shown_maps[request["key"]] = mapping
            with_previews.append({**request, "previews": shown})
    if with_previews:
        judged = judge_previews(with_previews, domain=domain, anti=anti,
                                runner=judge_runner)

    taken: set[str] = set()
    taken_series: set[int] = set()
    chosen: dict[str, dict] = {}
    for request in requests:
        candidates = found.get(request["key"]) or []
        if not candidates:
            resolved[request["key"]] = {
                "error": f"Pexels не дал кандидатов: «{request['intent']}»"}
            continue
        raw = judged.get(request["key"], "unjudged")
        if raw is None:
            resolved[request["key"]] = {
                "error": "судья забраковал всех кандидатов: "
                         f"«{request['intent']}»"}
            continue
        order = candidates
        # Номер судьи — это номер в списке ПОКАЗАННЫХ превью; в номера
        # кандидатов его переводит карта (превью могло не скачаться или
        # слететь по OCR, и списки расходятся).
        mapping = shown_maps.get(request["key"]) or []
        if isinstance(raw, int) and 0 <= raw < len(mapping):
            best = mapping[raw]
            order = [candidates[best]] + [c for i, c in enumerate(candidates)
                                          if i != best]

        def eligible(candidate: dict) -> bool:
            return (candidate["id"] not in taken
                    and not candidate.get("vetoed")
                    and not _same_series(candidate, taken_series))

        pick = next((c for c in order if eligible(c)), None)
        if pick is None:
            resolved[request["key"]] = {
                "error": "все кандидаты заняты, из одной серии с занятыми "
                         "или сняты по превью"}
            continue
        taken.add(pick["id"])
        if pick.get("series") is not None:
            taken_series.add(pick["series"])
        chosen[request["key"]] = pick

    def freeze(item: tuple[str, dict]) -> tuple[str, dict]:
        key, cand = item
        raw = _download(cand["url"], public / ".broll-tmp" / f"{cand['id']}.mp4")
        if raw is None:
            return key, {"error": f"биролл не скачался: {cand['url']}"}
        answer = ingest(public, str(raw), kind="video")
        raw.unlink(missing_ok=True)
        if not answer.get("ok") or not answer.get("path"):
            return key, {"error": answer.get("error") or "заморозка не удалась"}
        return key, {"file": answer["path"], "intent": ""}

    for key, answer in pool.map(freeze, list(chosen.items())):
        answer["intent"] = next(r["intent"] for r in requests
                                if r["key"] == key)
        resolved[key] = answer
        if "file" in answer:
            problem = insert_problem(public / answer["file"],
                                     next(r.get("rect") for r in requests
                                          if r["key"] == key))
            if problem:
                print(f"биролл «{answer['intent']}» отклонён: {problem}")
                resolved[key] = {"error": problem}
    return resolved


def resolve_all(public, requests: list[dict], *, context: dict | None = None,
                judge_runner=None) -> dict[str, dict]:
    """Подобрать все вставки: поиск и заморозка параллельно, выбор по порядку.

    `requests` — список `{"key", "type", "intent", "rect", "required",
    "seconds", "speech"}`; `rect` — прямоугольник, который файл закроет в
    кадре, `required` — сцена без ведущей, где вставка обязательна, `speech` —
    реплика диктора для судьи. `context` — `{"domain": …, "anti": …}` из плана
    агента. Возвращает
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

    videos = [r for r in requests if r.get("type") == "video"]
    searchable = [r for r in requests if r.get("type", "image") == "image"]
    blind = [r for r in requests
             if r.get("type", "image") not in ("image", "video")]

    resolved: dict[str, dict] = {}

    with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as pool:
        if videos:
            resolved.update(_resolve_videos(
                public, videos,
                domain=str((context or {}).get("domain") or ""),
                anti=str((context or {}).get("anti") or ""),
                judge_runner=judge_runner, pool=pool))

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
