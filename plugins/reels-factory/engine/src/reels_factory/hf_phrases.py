"""Фразы озвучки и раскладка сцен по ним.

Секунды сцен считает код, а не агент. Прогоны 9 и 10 показали цену обратного:
модель тратила по 30–45 тысяч токенов на ход, перебирая в уме зазоры, минимальные
длительности блоков и покрытие кусков без ведущей, а десятый прогон всё равно
развалился на трёх сотых секунды и потребовал второй сессии.

У HyperFrames такого расчёта нет, и это не упущение: там длительность сцены
назначает синтез — озвучка генерится покадрово, и её реальная длина
перезаписывает прикидку агента («Real voice duration overrides estimates»,
general-video/SKILL.md:107; механика — faceless-explainer/scripts/audio.mjs:271).
Мы приносим один готовый мастер-звук, перезаписывать нечем, поэтому этот кусок
наш.

Нарезку речи на фразы и правило «граница соседних фраз — середина паузы между
ними» берём готовыми из `editplan`: `_phrase_spans` и `finalize_edit_plan:2257`.
Своей второй нарезки не заводим — разойдутся.
"""
from __future__ import annotations

from reels_factory.config import FPS
from reels_factory.editplan import _phrase_spans
from reels_factory.hf_layout import quantize
from reels_factory.hf_rhythm import MAX_STATIC_SPAN

#: Сколько слов уходит на фразу при пропорциональном дележе, когда пословный
#: список разошёлся со сценарием. Порядок слов при этом сохраняется.
_MIN_WORDS = 1


def _block_words(words: list[dict], block: dict, index: int) -> list[dict]:
    """Слова блока: по явному `block_index`, а где его нет — по времени."""
    explicit = [w for w in words if w.get("block_index") == index]
    if explicit:
        return explicit
    start, end = float(block["start"]), float(block["end"])
    return [w for w in words if start <= float(w["start"]) < end]


def _split_by_counts(block_words: list[dict], counts: list[int]) -> list[list[dict]]:
    """Разложить слова блока по фразам.

    Слова приходят из самого синтеза и совпадают со сценарием по построению
    (`master_audio.alignment_to_words`), поэтому обычно достаточно счётчика слов
    каждой фразы. Если списки всё же разошлись — режем пропорционально, тем же
    приёмом, что `editplan._words_for_phrase:2163`, но не бросаем сборку: план
    агента от этого не становится неверным.
    """
    if sum(counts) == len(block_words):
        pieces, cursor = [], 0
        for count in counts:
            pieces.append(block_words[cursor:cursor + count])
            cursor += count
        return pieces

    total = sum(counts)
    bounds, consumed = [0], 0
    for count in counts[:-1]:
        consumed += count
        raw = round(len(block_words) * consumed / total)
        lowest = bounds[-1] + _MIN_WORDS
        highest = len(block_words) - (len(counts) - len(bounds))
        bounds.append(max(lowest, min(raw, highest)))
    bounds.append(len(block_words))
    return [block_words[bounds[i]:bounds[i + 1]] for i in range(len(counts))]


def phrase_timeline(scenario: dict, words: list[dict], *,
                    language: str = "ru") -> list[dict]:
    """Пронумерованные фразы озвучки с точными временами.

    `start`/`end` — граница показа: она проходит посередине паузы между
    соседними фразами, чтобы карточка не обрывала слово. `said` — когда фраза
    действительно звучит.
    """
    phrases: list[dict] = []
    for index, block in enumerate(scenario.get("blocks") or []):
        speech = str(block.get("speech") or "")
        spans = _phrase_spans(speech, language=language)
        if not spans:
            continue
        texts = [speech[a:b] for a, b in spans]
        block_words = _block_words(words, block, index)
        if not block_words:
            continue
        pieces = _split_by_counts(block_words, [len(t.split()) for t in texts])

        spoken = [(float(p[0]["start"]), float(p[-1]["end"]))
                  for p in pieces if p]
        if len(spoken) != len(texts):
            continue
        cuts = [float(block["start"])]
        for left, right in zip(spoken, spoken[1:]):
            cuts.append((left[1] + max(right[0], left[1])) / 2.0)
        cuts.append(float(block["end"]))

        for order, text in enumerate(texts):
            phrases.append({
                "id": len(phrases),
                "role": block.get("role", "?"),
                "text": " ".join(text.split()),
                "start": round(cuts[order], 3),
                "end": round(cuts[order + 1], 3),
                "said": [round(spoken[order][0], 3), round(spoken[order][1], 3)],
            })
    return phrases


def phrase_span(phrases: list[dict], first: int, last: int) -> tuple[float, float]:
    """Границы показа для диапазона фраз. Номера — как их видел агент."""
    by_id = {p["id"]: p for p in phrases}
    if first not in by_id or last not in by_id or last < first:
        raise RuntimeError(
            f"фразы {first}–{last} нет: в озвучке фразы 0–{len(phrases) - 1}")
    return by_id[first]["start"], by_id[last]["end"]


def faceless_phrases(phrases: list[dict], clips: list[dict],
                     duration: float) -> list[int]:
    """Номера фраз, на которых ведущей в кадре нет физически.

    Аватар заказывают островами, и между ними остаются куски, где показывать
    нечего. Агенту это надо знать номерами фраз, а не секундами: секунд он не
    видит, а сцены назначает по фразам. Пересечение меньше кадра не считается —
    это стык, а не дыра.
    """
    from reels_factory.hf_layout import avatar_gaps, in_avatar_gap

    gaps = avatar_gaps(clips, duration)
    return [phrase["id"] for phrase in phrases
            if in_avatar_gap(float(phrase["start"]), float(phrase["end"]), gaps)]


#: Короче этого сцена читается вспышкой, а не планом. Число — из эталонов: там
#: самый короткий план 0,5 с (`reference-reels-montage-language`), берём с
#: запасом на кадр. Фразы бывают и по 0,2 с («вопроса.»), поэтому такую сцену
#: код дотягивает за счёт следующей, а не заворачивает план.
MIN_SCENE = 0.6


def lay_out_scenes(scenes: list[dict], phrases: list[dict], *,
                   duration: float) -> list[dict]:
    """Поставить сцены на таймлайн по названным фразам.

    Агент называет только `phrases: [первая, последняя]`. Секунды и сетку
    кадров держит этот код.

    Сцены **выстилают ролик целиком**, без зазоров: кадр теперь собран слоями, и
    промежутка «между сценами», где показывать нечего, не бывает — там всё
    равно стоит ведущая, просто это отдельная сцена, которую агент назвал сам.
    Прежний зазор был нужен другому кадру: непрозрачные карточки впритык
    детектор сцен считал одной склейкой, и зазор разводил их. Теперь смену даёт
    сама граница сцен — за это отвечает D21.

    Порядок правил:

    1. Границы берутся у фраз — сцена приходит на свою реплику.
    2. Сцены идут подряд и покрывают все фразы: дырка означает чёрный кадр.
    3. Сцена не короче MIN_SCENE: не хватило — двигаем границу вправо, за счёт
       следующей. Начало сцены не трогаем: оно сидит на произносимом слове.
    4. Сцена не длиннее восьми секунд — это D19, и он же предел здесь.
    5. Округление к сетке кадров последним действием.
    """
    duration = quantize(duration)
    if not scenes:
        raise RuntimeError("в плане нет ни одной сцены")

    placed: list[dict] = []
    for scene in scenes:
        span = scene.get("phrases")
        if not isinstance(span, (list, tuple)) or len(span) != 2:
            raise RuntimeError(
                f'{scene.get("id", "?")}: нет поля `phrases` — сцена обязана '
                "назвать первую и последнюю фразу, которые накрывает. Секунды "
                "(`startSec`, `endSec`) считает код, в плане их быть не должно")
        first, last = int(span[0]), int(span[1])
        start, end = phrase_span(phrases, first, last)
        # Копия, а не оригинал: план агента остаётся тем, что он написал, —
        # при пересборке его перечитывают с диска и раскладывают заново.
        placed.append({"scene": dict(scene), "start": start, "end": end,
                       "span": (first, last)})
    placed.sort(key=lambda item: item["start"])

    _check_tiling(placed, phrases)

    # Первая сцена начинается с нуля, последняя доходит до конца ролика: между
    # первым словом и нулём есть вдох, и он тоже чей-то кадр.
    placed[0]["start"] = 0.0
    placed[-1]["end"] = duration

    for index, item in enumerate(placed[:-1]):
        following = placed[index + 1]
        if item["end"] - item["start"] < MIN_SCENE:
            item["end"] = min(item["start"] + MIN_SCENE, following["end"])
        following["start"] = item["end"]
    if placed[-1]["end"] - placed[-1]["start"] < MIN_SCENE - 0.001:
        raise RuntimeError(
            f'{placed[-1]["scene"].get("id", "?")}: последней сцене осталось '
            f'{placed[-1]["end"] - placed[-1]["start"]:.2f} с, а сцена не бывает '
            f"короче {MIN_SCENE:g} с. Отдай ей больше фраз или объедини с соседней")

    for item in placed:
        scene = item["scene"]
        scene["startSec"] = quantize(item["start"])
        scene["endSec"] = quantize(item["end"])
        if scene["endSec"] - scene["startSec"] > MAX_STATIC_SPAN + 0.001:
            raise RuntimeError(
                f'{scene.get("id", "?")}: сцена идёт '
                f'{scene["endSec"] - scene["startSec"]:.1f} с, предел '
                f"{MAX_STATIC_SPAN:g} с — картинка застынет. Разрежь её на две")
        scene.pop("phrases", None)
    return [item["scene"] for item in placed]


def _check_tiling(placed: list[dict], phrases: list[dict]) -> None:
    """Сцены идут подряд по фразам, без дырок и без нахлёста.

    Дырка — это кусок ролика, который никто не оформил: раньше там показывали
    ведущую по умолчанию, но «по умолчанию» и давало неподвижные куски. Теперь
    каждый кусок ролика назван, и чем он занят — решение агента, а не побочный
    эффект.
    """
    expected = 0
    last_id = phrases[-1]["id"] if phrases else -1
    for item in placed:
        first, last = item["span"]
        if last < first:
            raise RuntimeError(
                f'{item["scene"].get("id", "?")}: фразы {first}–{last} идут '
                "задом наперёд")
        if first != expected:
            what = ("пропущены фразы" if first > expected
                    else "фразы уже заняты предыдущей сценой")
            raise RuntimeError(
                f'{item["scene"].get("id", "?")}: начинается с фразы {first}, '
                f"а ожидалась {expected} — {what}. Сцены обязаны выстилать всю "
                "озвучку подряд, без пропусков и без наложений")
        expected = last + 1
    if expected != last_id + 1:
        raise RuntimeError(
            f"сцены заканчиваются на фразе {expected - 1}, а в озвучке фразы "
            f"0–{last_id}. Хвост без сцены — это чёрный экран; отдай оставшиеся "
            "фразы последней сцене или добавь ещё одну")
