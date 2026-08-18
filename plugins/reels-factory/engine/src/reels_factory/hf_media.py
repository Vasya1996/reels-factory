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
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from reels_factory.config import FFMPEG, FFPROBE, cli_env

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
    """Окружение их скриптов подбора: то же, что у их CLI (см. `cli_env`)."""
    return cli_env()


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
PEXELS_LIMIT = 15

#: Без User-Agent Pexels отдаёт 403 — оплаченная грабля (замер Юли, README
#: broll-zoom-toolkit, грабля 5).
_UA = {"User-Agent": "reels-factory/0.2 (b-roll fetch)"}

#: Сколько кандидатов на сцену показываем судье. Нам нужны подходящие ролики,
#: а не популярные: верхушка выдачи Pexels — это популярное, и узкий пул
#: заставлял судью выбирать из него. Восемь превью на сцену — судья выбирает
#: по смыслу, а не из того, что чаще качают.
JUDGE_CANDIDATES = 8

#: Сколько кадров одного кандидата показываем судье. Один кадр — это обложка
#: ролика, и по ней не видно, что происходит дальше: игральные карты прогона 23
#: на обложке выглядели «руками с бумагами». Второй кадр берём из их же
#: `video_pictures` — Pexels отдаёт раскадровку ролика в самой выдаче, лишних
#: запросов не нужно.
PREVIEW_FRAMES = 2


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
                      "previews": _preview_frames(video),
                      "url": best["link"],
                      "width": best.get("width"), "height": best.get("height"),
                      "is_transparent": False})
    return found


def _preview_frames(video: dict) -> list[str]:
    """Кадры кандидата для судьи: обложка плюс кадр из середины ролика.

    `video_pictures` — их же раскадровка в ответе поиска (десяток кадров с
    порядковым `nr`). Берём кадр примерно с середины: начало ролика часто
    пустое, а конец уходит из плана.
    """
    frames = [video.get("image")]
    shots = [s.get("picture") for s in (video.get("video_pictures") or [])
             if s.get("picture")]
    if shots:
        frames.append(shots[len(shots) // 2])
    seen, unique = set(), []
    for url in frames:
        if url and url not in seen:
            seen.add(url)
            unique.append(url)
    return unique[:PREVIEW_FRAMES]


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
кадры кандидатов (файлы; у кандидата их до двух — обложка и кадр из
середины ролика, смотри оба). Посмотри кадры инструментом Read и для
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


#: Сколько раз зовём судью. Первая попытка падает от сети и таймаута чаще,
#: чем от плохого запроса, — вторая обычно проходит. Третьей нет: она стоит
#: ещё пять минут прогона, а после двух отказов дело не в удаче.
JUDGE_ATTEMPTS = 2

#: Судье дают до восьми кандидатов по два кадра на каждый — картинок много,
#: и дешёвой сессии нужно время. Прежние пять минут прогон 23 не уложил и
#: молча деградировал в «берём первых». Сессий теперь несколько и идут они
#: параллельно, поэтому таймаут — на серию, а не на весь ролик.
JUDGE_TIMEOUT_S = 600


def judge_previews(requests: list[dict], *, domain: str = "", anti: str = "",
                   runner=None, spend=None) -> dict[str, int | None]:
    """Один суд на весь ролик: дешёвая сессия смотрит кадры и выбирает.

    `requests` — `[{"key", "intent", "speech", "previews": [[кадры кандидата]]}]`.
    Возвращает `{key: индекс выбранного | None}`.

    `spend` — кошелёк сборки (`AgentSpend`): судья платный, на прогоне 462a1c62
    пять его сессий стоили $0,79 против $0,45 у планировщика. Своя обёртка ему
    нужна ради дешёвой модели, поэтому в счёт ролика он попадает кошельком.

    Отказ судьи — это пересдача, а не повод собирать вслепую. Прогон 23 показал
    цену тихой деградации: судья молча не уложился в таймаут, сборка взяла
    первых кандидатов Pexels, и в ролик про продажи приехали игральные карты.
    Кончились попытки — поднимаем RuntimeError: пусть встанет сборка, а не
    качество.
    """
    from reels_factory.hf_agent import HeyGenAgentRunner

    blocks = []
    for request in requests:
        lines = [f'Сцена `{request["key"]}`: диктор говорит «{request.get("speech") or request["intent"]}»,'
                 f' показать: {request["intent"]}']
        for index, frames in enumerate(request["previews"]):
            shots = [frames] if isinstance(frames, str) else list(frames)
            lines.append(f"- кандидат {index}: " + ", ".join(shots))
        blocks.append("\n".join(lines))
    prompt = _JUDGE_PROMPT.format(domain=domain or "не указана",
                                  anti=anti or "не указано",
                                  scenes="\n\n".join(blocks))

    trouble = ""
    for attempt in range(JUDGE_ATTEMPTS):
        session = runner
        if session is None:
            session = HeyGenAgentRunner(timeout_s=JUDGE_TIMEOUT_S,
                                        model="claude-haiku-4-5", spend=spend)
            # Дешёвой модели глубина рассуждения не передаётся вовсе:
            # конструктор подхватил бы REELS_AGENT_EFFORT из окружения раннера,
            # а флаг там про модель плана, не про судью.
            session.effort = None
        try:
            answer = session.run(prompt)
        except Exception as error:
            trouble = f"сессия упала: {error}"
        else:
            match = re.search(r"\{.*\}", answer, re.S)
            if not match:
                trouble = "в ответе нет JSON"
            else:
                try:
                    verdicts = json.loads(match.group(0))
                except json.JSONDecodeError as error:
                    trouble = f"JSON не разбирается: {error}"
                else:
                    return {str(key): (int(value) if value is not None else None)
                            for key, value in verdicts.items()}
        left = JUDGE_ATTEMPTS - attempt - 1
        print(f"судья бироллов не отработал ({trouble})"
              + (f" — пересдача, попыток осталось {left}" if left else ""))
    raise RuntimeError(
        f"судья бироллов не отработал за {JUDGE_ATTEMPTS} попытки "
        f"({trouble}). Собирать вслепую нельзя: без суда в кадр попадает "
        "первое, что отдал сток")


# ------------------------------------------------------------------- подбор

def _resolve_one(project: Path, kind: str, intent: str,
                 entity: str | None = None) -> dict:
    """Слепой подбор их `resolve` — для типов без поиска кандидатов (логотип
    идёт каскадом svgl → simple-icons → …, там выбирать не из чего).

    `entity` — имя бренда отдельным полем. Каскад логотипа заводится именно им:
    их же образец вызова — `--type logo --entity linkedin --intent "LinkedIn
    logo"` (`media-use/references/resolve.md:42`), и по нему же ищется
    сохранённый ранее знак (`resolve.mjs:327-330`).
    """
    result = subprocess.run(
        ["node", str(RESOLVE), "--type", kind, "--intent", intent,
         *(["--entity", entity] if entity else []),
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


#: Их же источник фирменных знаков — первая ступень каскада логотипа
#: (`media-use/scripts/lib/logo-provider.mjs:28`).
SVGL_API = "https://api.svgl.app"


def svgl_route(entity: str, *, dark: bool) -> str | None:
    """Ссылка на нужное начертание знака бренда у их первого поставщика.

    Их подбор всегда берёт светлое начертание — `hit.route?.light`
    (`logo-provider.mjs:130`), то есть тёмный знак под светлый фон, и выбора
    флагом нет. На тёмной палитре такой знак тонет, поэтому спрашиваем сам
    источник: у части брендов лежит пара `{light, dark}`, у полноцветных —
    одна ссылка строкой, и она годится на любом фоне.

    Возвращает `None`, когда бренда там нет или парного начертания у него нет:
    тогда работает их обычный каскад svgl → simple-icons → GitHub → фавикон.
    """
    query = str(entity or "").strip().lower()
    if not query:
        return None
    # Без заголовка агента источник отвечает 403: их скрипты ходят туда через
    # `fetch` браузерного профиля, у python-запроса такого заголовка нет.
    request = urllib.request.Request(
        f"{SVGL_API}?search={urllib.parse.quote(query)}",
        headers={"User-Agent": "reels-factory/1.0", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            items = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(items, list):
        return None
    for item in items:
        title = str(item.get("title") or "").strip().lower()
        if title != query and query not in title:
            continue
        route = item.get("route")
        if isinstance(route, str):
            return route          # полноцветный знак, начертание одно
        if isinstance(route, dict):
            return route.get("dark" if dark else "light") or route.get("light")
    return None


#: Сколько раз добирать следующего кандидата, если файл не годится. Два круга
#: покрывают обычные отказы (не скачался, растянут, водяной знак), а дальше
#: выдача Pexels уже не про эту реплику — там место запасной схеме.
REPICK_ROUNDS = 3


def _next_candidate(order: list[dict], taken: set[str],
                    taken_series: set[int]) -> dict | None:
    """Первый кандидат из списка, который ещё никем не занят.

    Занятость считается на весь ролик: один и тот же ролик не ставится дважды,
    и ролики одной съёмочной серии Pexels тоже — они снимались подряд и в кадре
    неотличимы.
    """
    for candidate in order:
        if candidate["id"] in taken or candidate.get("vetoed"):
            continue
        if _same_series(candidate, taken_series):
            continue
        return candidate
    return None


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
                    judge_runner=None, agent_spend=None,
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
            frames = cand.get("previews") or (
                [cand["preview"]] if cand.get("preview") else [])
            for shot, url in enumerate(frames[:PREVIEW_FRAMES]):
                jobs.append((request["key"], index, shot, url))
    # Имя файла собирается из ключа сцены, а он бывает составным («s-07::shot0»).
    # Двоеточие Windows в имени файла не принимает: локально каждое превью
    # падало с «Invalid argument», судья оставался без кадров, и ролик выходил
    # вовсе без вставок. На сервере это не всплывало — там двоеточие законно.
    safe = lambda value: re.sub(r'[:<>"/\|?*]', "-", str(value))  # noqa: E731
    paths = dict(zip(
        [(key, index, shot) for key, index, shot, _ in jobs],
        pool.map(lambda job: _download(
            job[3],
            previews_dir / f"{safe(job[0])}-{job[1]}-{job[2]}.jpg"), jobs)))

    # Страховка от текста в кадре ДО судьи: OCR по превью снимает кандидата
    # с крупной надписью («NEW YEAR NEW ME» прогона 17 судья пропустил).
    # Надпись хотя бы на одном кадре снимает весь ролик: в середине она
    # держится столько же, сколько на обложке.
    for (key, index, shot), path in list(paths.items()):
        if path is None:
            continue
        problem = text_problem(path)
        if problem:
            print(f"кандидат {key}/{index} снят по кадру {shot}: {problem}")
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
            if candidates[index].get("vetoed"):
                continue
            frames = [str(paths[(request["key"], index, shot)])
                      for shot in range(PREVIEW_FRAMES)
                      if paths.get((request["key"], index, shot))]
            if frames:
                shown.append(frames)
                mapping.append(index)
        if shown:
            shown_maps[request["key"]] = mapping
            with_previews.append({**request, "previews": shown})
    if with_previews:
        # Судим посерийно и параллельно, а не одной сессией на весь ролик.
        # Одна сессия читает кадры по одному, и на пяти сериях по два плана
        # это больше сотни картинок подряд — прогон 24 упёрся в неё временем.
        # Внутри серии оба плана по-прежнему судит один судья: два одинаковых
        # кадра подряд — как раз то, что он обязан развести. Повтор между
        # РАЗНЫМИ сериями держит код: один ролик дважды не ставится, и ролики
        # одной съёмочной серии Pexels тоже (`taken`, `_same_series`).
        batches: dict[str, list[dict]] = {}
        for request in with_previews:
            batches.setdefault(str(request["key"]).split("::")[0],
                               []).append(request)
        for verdicts in pool.map(
                lambda batch: judge_previews(batch, domain=domain, anti=anti,
                                             runner=judge_runner,
                                             spend=agent_spend),
                list(batches.values())):
            judged.update(verdicts)

    taken: set[str] = set()
    taken_series: set[int] = set()
    chosen: dict[str, dict] = {}
    orders: dict[str, list[dict]] = {}
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
        if raw == "unjudged":
            # Ни одного кадра судье не досталось (кадры не скачались) либо он
            # пропустил сцену в ответе. Брать первого из выдачи Pexels нельзя:
            # это и есть та слепая сборка, из-за которой в прогон 23 приехали
            # игральные карты. Сцену закроет ведущая (settle_inserts).
            resolved[request["key"]] = {
                "error": f"сцену не судили: «{request['intent']}»"}
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

        orders[request["key"]] = order
        pick = _next_candidate(order, taken, taken_series)
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

    def settle(batch: dict[str, dict]) -> list[str]:
        """Заморозить выбранных и вернуть ключи, у которых файл не годится."""
        failed = []
        for key, answer in pool.map(freeze, list(batch.items())):
            answer["intent"] = next(r["intent"] for r in requests
                                    if r["key"] == key)
            resolved[key] = answer
            if "file" not in answer:
                failed.append(key)
                continue
            problem = insert_problem(public / answer["file"],
                                     next(r.get("rect") for r in requests
                                          if r["key"] == key))
            if problem:
                print(f"биролл «{answer['intent']}» отклонён: {problem}")
                resolved[key] = {"error": problem}
                failed.append(key)
        return failed

    # Добор: негодный файл заменяется СЛЕДУЮЩИМ кандидатом того же запроса —
    # у сцены их скачано и отсужено с запасом. Прежде такую сцену закрывала
    # копия вставки соседней (`settle_inserts`), то есть кадр не про эту
    # реплику. Кругов немного: каждый стоит скачивания, а хвост выдачи Pexels
    # тем временем дешевеет по смыслу.
    batch = dict(chosen)
    for _ in range(REPICK_ROUNDS):
        failed = settle(batch)
        if not failed:
            break
        batch = {}
        for key in failed:
            pick = _next_candidate(orders.get(key) or [], taken, taken_series)
            if pick is None:
                continue
            taken.add(pick["id"])
            if pick.get("series") is not None:
                taken_series.add(pick["series"])
            batch[key] = pick
            print(f"добор кандидата для {key}: {pick.get('url', '')[:60]}")
        if not batch:
            break
    return resolved


def resolve_all(public, requests: list[dict], *, context: dict | None = None,
                judge_runner=None, agent_spend=None) -> dict[str, dict]:
    """Подобрать все вставки: поиск и заморозка параллельно, выбор по порядку.

    `requests` — список `{"key", "type", "intent", "rect", "required",
    "seconds", "speech"}`; `rect` — прямоугольник, который файл закроет в
    кадре, `required` — сцена без ведущей, где вставка обязательна, `speech` —
    реплика диктора для судьи. `context` — `{"domain": …, "anti": …}` из плана
    агента. `agent_spend` — кошелёк сборки, куда судья кладёт свой расход.
    Возвращает
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
                judge_runner=judge_runner, agent_spend=agent_spend,
                pool=pool))

        found = dict(zip(
            [r["key"] for r in searchable],
            pool.map(lambda r: search_assets(r["intent"]), searchable)))
        def blind_one(request: dict) -> dict:
            """Знак бренда — начертанием под палитру ролика, остальное их
            каскадом как есть."""
            if request["type"] == "logo" and request.get("entity"):
                route = svgl_route(request["entity"],
                                   dark=bool(request.get("dark_frame")))
                if route:
                    frozen = ingest(public, route, kind="logo")
                    if frozen.get("ok") and frozen.get("path"):
                        return frozen
            return _resolve_one(public, request["type"], request["intent"],
                                request.get("entity"))

        for request, answer in zip(blind, pool.map(blind_one, blind)):
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
