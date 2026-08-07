"""Фразы озвучки и раскладка карточек по ним.

Секунды карточек считает код, а не агент. Прогоны 9 и 10 показали цену обратного:
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

from reels_factory.editplan import _phrase_spans
from reels_factory.hf_layout import quantize
from reels_factory.hf_rhythm import MAX_STATIC_SPAN, MIN_CARD_GAP

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


def _has_clip(clips: list[dict], at: float) -> bool:
    return any(c["start"] <= at + 1e-6 < c["start"] + c["duration"] for c in clips)


def lay_out_cards(cards: list[dict], phrases: list[dict], *,
                  clips: list[dict], duration: float,
                  minimums: dict[str, float] | None = None) -> list[dict]:
    """Поставить карточки на таймлайн по названным фразам.

    Агент называет только `phrases: [первая, последняя]`. Секунды, зазоры,
    минимальные длительности сцен и сетку кадров держит этот код.

    Порядок правил важен, и он такой:

    1. Границы берутся у фраз — карточка приходит на свою реплику.
    2. Карточка не короче своего блока (`minimums`): не хватило — тянем вправо,
       пока не упрёмся в следующую карточку или в конец ролика.
    3. Карточка не длиннее восьми секунд: лишнее срезаем справа.
    4. Перед карточкой зазор, где под ним есть ведущая: не хватило — сдвигаем
       начало вправо, но не настолько, чтобы нарушить пункт 2.
    5. Всё округляется к сетке кадров последним действием, чтобы округление не
       съело зазор.
    """
    minimums = minimums or {}
    duration = quantize(duration)
    placed: list[dict] = []
    for card in cards:
        span = card.get("phrases")
        if not isinstance(span, (list, tuple)) or len(span) != 2:
            raise RuntimeError(
                f'{card.get("id", "?")}: нет поля `phrases` — карточка обязана '
                "назвать первую и последнюю фразу, которые накрывает. Секунды "
                "(`startSec`, `endSec`) считает код, в плане их быть не должно")
        first, last = span
        start, end = phrase_span(phrases, int(first), int(last))
        # Копия, а не оригинал: план агента остаётся тем, что он написал, —
        # при пересборке его перечитывают с диска и раскладывают заново.
        placed.append({"card": dict(card), "start": start, "end": end,
                       "span": (int(first), int(last))})
    placed.sort(key=lambda item: item["start"])

    for index, item in enumerate(placed):
        card = item["card"]
        ceiling = (placed[index + 1]["start"] if index + 1 < len(placed)
                   else duration)
        need = float(minimums.get(card.get("id"), 0.0))

        if item["end"] - item["start"] < need:
            item["end"] = min(ceiling, item["start"] + need)
        item["end"] = min(item["end"], item["start"] + MAX_STATIC_SPAN, duration)
        if item["end"] - item["start"] < need - 0.001:
            # Тянуть дальше некуда: справа стоит следующая карточка. Сдвигать её
            # нельзя — она сидит на своей реплике. Значит выбор блока и реплик
            # не сходится, а это решение агента, не наше.
            raise RuntimeError(
                f'{card.get("id", "?")}: на фразы {item["span"][0]}–'
                f'{item["span"][1]} приходится '
                f'{item["end"] - item["start"]:.1f} с, а блок '
                f'{(card.get("render") or {}).get("block")} собирается дольше и '
                f"требует {need:g} с. Дай этой карточке больше фраз или возьми "
                "блок покороче")

        floor = placed[index - 1]["end"] if index else 0.0
        gap = item["start"] - floor
        if gap < MIN_CARD_GAP and _has_clip(clips, floor):
            # Двигаем начало вправо, а не растягиваем предыдущую карточку:
            # предыдущая уже стоит на своей реплике, и трогать её — значит
            # сдвинуть картинку с произносимого слова.
            shifted = min(floor + MIN_CARD_GAP, item["end"] - need)
            item["start"] = max(item["start"], min(shifted, item["end"]))

    _close_faceless(placed, clips, duration)

    for item in placed:
        card = item["card"]
        card["startSec"] = quantize(item["start"])
        card["endSec"] = quantize(item["end"])
        card.pop("phrases", None)
    return [item["card"] for item in placed]


def _close_faceless(placed: list[dict], clips: list[dict],
                    duration: float) -> None:
    """Куски без ведущей закрыть карточками встык — иначе там чёрный кадр.

    Зазор в таком куске оставлять негде: под ним не ведущая, а пустота. Это же
    требует гейт D12, и раньше следить за этим приходилось агенту.
    """
    from reels_factory.hf_layout import avatar_gaps

    for start, end in avatar_gaps(clips, duration):
        inside = [item for item in placed
                  if item["end"] > start + 1e-6 and item["start"] < end - 1e-6]
        if not inside:
            raise RuntimeError(
                f"кусок {start:g}–{end:g} с идёт без ведущей, а карточки на него "
                "не назначено — там будет чёрный экран. Назови фразы этого куска "
                "какой-нибудь карточке")
        inside[0]["start"] = min(inside[0]["start"], start)
        inside[-1]["end"] = max(inside[-1]["end"], end)
        for left, right in zip(inside, inside[1:]):
            right["start"] = left["end"] = max(left["end"], right["start"])
