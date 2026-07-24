"""Адаптер плана монтажа -> формат tz.json движка Revideo.

Единственное место, где решения пайплайна (ретаймленные блоки + слова + broll-
план + конфиг) переводятся в план для Revideo-рендера. Их `editplan`/
`timed_scenario` и наш `tz` — одна сущность (что и когда происходит).

Раскладка фразовая: слова из words.json режутся на фразы (по паузам/пунктуации,
не пересекая границы блоков), и на каждую фразу назначается приём ПО СОДЕРЖАНИЮ
(перечисление -> график, «стиль/формат/аудитория» -> эмодзи, «автоматизировать
всё» -> частицы, команда «напиши/скажи» -> чат-стикер, «инструкции/набор» ->
b-roll), с ротацией зумов, переходами и кривой интенсивности (часть фраз —
намеренно только лицо). Тяжёлые приёмы используются не больше раза за ролик.
"""
from __future__ import annotations

import re

# Правило Юлии: НИКАКИХ резких зумов (snap/shake/pulse/punch) — они мельтешат.
# Движение на «лицевых» сегментах даёт только медленный кинематографичный дрейф
# ken_burns (плавный push, сбрасывается в 1.0 каждый шот). payoff — статикой.
DRIFT_CAMERA = "ken_burns"
_CMD_VERBS = ("напиш", "спрос", "попрос")


def _norm(s: str) -> str:
    return re.sub(r"[^a-zа-яё]", "", s.lower())


def _keywords_from_config(config: dict) -> list:
    kws: list[str] = list(config.get("keywords") or [])
    product = config.get("product") or {}
    for src in (product.get("brand_captions"), config.get("theme_captions")):
        if src:
            kws += re.findall(r"[A-Za-zА-Яа-яЁё]{4,}", str(src))
    seen, out = set(), []
    for k in kws:
        if k.lower() not in seen:
            seen.add(k.lower())
            out.append(k.lower())
    return out[:8]


def _block_role_at(blocks: list, t: float) -> tuple:
    for i, b in enumerate(blocks):
        if float(b["start"]) <= t < float(b["end"]):
            return i, b.get("role")
    return len(blocks) - 1, blocks[-1].get("role") if blocks else (0, None)


def _split_phrases(words: list, blocks: list) -> list:
    """Слова -> фразы [{start,end,text,role,block}], не пересекая границы блоков."""
    phrases, cur = [], []
    cur_block = None
    for i, w in enumerate(words):
        bi, _ = _block_role_at(blocks, float(w["start"]))
        if cur and bi != cur_block:
            phrases.append(cur); cur = []
        if not cur:
            cur_block = bi
        cur.append(w)
        txt = w.get("text", "")
        ends_punct = bool(re.search(r"[,.!?…]$", txt))
        gap_next = (float(words[i + 1]["start"]) - float(w["end"])) if i + 1 < len(words) else 0
        if len(cur) >= 6 or (ends_punct and len(cur) >= 3) or gap_next > 0.5:
            phrases.append(cur); cur = []
    if cur:
        phrases.append(cur)

    out = []
    for ph in phrases:
        bi, role = _block_role_at(blocks, float(ph[0]["start"]))
        out.append({
            "start": float(ph[0]["start"]), "end": float(ph[-1]["end"]),
            "text": " ".join(w.get("text", "") for w in ph),
            "words": ph, "role": role, "block": bi,
        })
    return out


# Минимальная длительность любого биролла (правило Юлии: короче — мельтешит).
MIN_BROLL_S = 3.0


def _extend_to_min(phrases, i, block, min_len):
    """Индекс последней фразы блока так, чтобы окно [i..j] было не короче min_len.
    Возвращает j (>= i), не выходя за границу блока."""
    j = i
    while (phrases[j]["end"] - phrases[i]["start"]) < min_len \
            and j + 1 < len(phrases) and phrases[j + 1]["block"] == block:
        j += 1
    return j


def _chart_items(ph: dict) -> list:
    """Перечисление через запятую -> бары с таймкодами по словам."""
    text = ph["text"]
    parts = [p.strip(" ,.") for p in re.split(r"[,;]| и ", text) if len(p.strip(" ,.")) > 2]
    parts = parts[:5]
    if len(parts) < 3:
        return []
    words = ph["words"]
    vals = [0.7, 0.55, 0.85, 0.75, 1.0]
    items = []
    step = max(1, len(words) // len(parts))
    for k, label in enumerate(parts):
        wi = min(k * step, len(words) - 1)
        items.append({"t": round(float(words[wi]["start"]), 2),
                      "label": label.capitalize(), "v": vals[k % len(vals)]})
    return items


def _chat_text(text: str) -> str:
    """Из команды вытащить короткую реплику (глагол + 1-2 слова)."""
    toks = text.replace(",", " ").split()
    for i, t in enumerate(toks):
        if _norm(t).startswith(_CMD_VERBS):
            return " ".join(toks[i:i + 2]).strip(",.!?…").lower()
    return text.split(",")[0][:20].lower()


# Служебные слова, которые ничего не дают семантическому запросу b-roll.
_QUERY_STOP = set((
    "и в на что как это то он она они мы вы бы же ли за по из у о а но да не нет "
    "для от до со во об про при или чтобы если когда уже ещё вот там тут так"
).split())


def _broll_query(text: str, hint: str = "") -> str:
    """Из текста фразы собрать визуальный запрос для семантического подбора (Модуль B).

    Это `broll_query` из docs/TZ_pipeline_v6.md: что показать под фразой. Берём
    содержательные слова фразы (CLIP-энкодер осмысляет естественную фразу),
    `hint` добавляет визуальный контекст под тип вставки (напр. «рабочий стол»).
    """
    toks = [t.strip(",.!?…:;«»\"'()-").lower() for t in text.split()]
    kept = [t for t in toks if len(t) > 2 and t not in _QUERY_STOP]
    query = " ".join(kept[:8]) or text.strip().lower()
    return f"{query}, {hint}".strip(", ") if hint else query


def plan_to_tz(timed: dict, broll_segments: list | None, config: dict,
               words: list | None = None, base_video: str = "base.mp4",
               broll_file: str = "broll.mp4", face: dict | None = None) -> dict:
    blocks = timed["blocks"]
    total = float(timed.get("total") or (blocks[-1]["end"] if blocks else 0))
    seg_by_role = {s["role"]: s for s in (broll_segments or [])}
    has_any_broll = bool(seg_by_role)
    # precut-покрытие: блоки с insert=true не генерились аватаром (base там
    # чёрный) — их обязательно закрывает один fullscreen-сегмент на весь блок
    covered_roles = {s["role"] for s in (broll_segments or []) if s.get("insert")}
    product = config.get("product") or {}

    # фразовая нарезка; без слов — фолбэк на блоки
    if words:
        phrases = _split_phrases(words, blocks)
    else:
        phrases = [{"start": float(b["start"]), "end": float(b["end"]),
                    "text": b.get("speech", ""), "words": [], "role": b.get("role"),
                    "block": i} for i, b in enumerate(blocks)]

    brand = {
        "keyword_color": "#FFE500", "font": "Unbounded", "captions_style": "accumulate",
        "progress_bar": True, "watermark": config.get("watermark") or config.get("handle") or "",
        "watermark_from": 2.0,
    }
    captions = {"base_style": "accumulate", "font_size": 46,
                "position_pct_from_bottom": 40, "keywords": _keywords_from_config(config)}

    used = {"chart": False, "particles": False, "pip": False, "bubble": False}
    trans_used = 0
    seg_off = lambda role, d: float(seg_by_role.get(role, {}).get("offset", d))

    def emit(segs, start, end, role, camera, transition, effect, caption):
        intensity = {"hook": 2, "development": 2, "payoff": 1, "cta": 2}.get(role, 2)
        if effect["type"] in ("chart_bars", "broll_bg_particles"):
            intensity = 3
        segs.append({
            "id": len(segs) + 1, "start": round(start, 3), "end": round(end, 3),
            "phrase": "", "beat": role, "intensity": intensity,
            "camera": camera, "transition_in": transition, "effect": effect, "caption": caption,
        })

    segments = []
    i, n = 0, len(phrases)
    while i < n:
        ph = phrases[i]
        role = ph["role"]
        text = ph["text"]
        low = " " + text.lower() + " "
        block = ph["block"]

        # ==== БЛОЧНЫЕ (поглощающие) эффекты: занимают область, а не одну фразу ====
        # Precut-покрытый блок: аватар не генерился, base здесь чёрный кадр —
        # ровно один fullscreen b-roll на ВЕСЬ блок (по границам блока, не фраз:
        # тайминги слов начинаются позже границы, зазор показал бы черноту).
        # Никаких bubble/pip внутри: они рисуют base. src закреплён
        # планировщиком (клип проверен на матч и длину) — retrieval его не трогает.
        if role in covered_roles:
            j = i
            while j + 1 < n and phrases[j + 1]["block"] == block:
                j += 1
            blk = blocks[block]
            seg = seg_by_role.get(role) or {}
            eff = {"type": "broll", "style": "fullscreen",
                   "broll_query": seg.get("query") or _broll_query(text),
                   "src": seg.get("clip") or broll_file,
                   "offset": float(seg.get("offset") or 0.0)}
            if seg.get("clip"):
                eff["src_locked"] = True
            emit(segments, float(blk["start"]), float(blk["end"]), role,
                 {"type": "hold"}, "none", eff, "bottom")
            i = j + 1
            continue

        # CTA: одна кнопка на весь cta-блок
        if role == "cta":
            j = i
            while j + 1 < n and phrases[j + 1]["block"] == block:
                j += 1
            emit(segments, ph["start"], phrases[j]["end"], role, {"type": DRIFT_CAMERA}, "none",
                 {"type": "cta_endcard", "button": product.get("cta_button") or "ПОДПИСАТЬСЯ"}, "bottom")
            i = j + 1
            continue

        # Эмодзи-последовательности УБРАНЫ (правило Юлии: эмодзи в монтаже
        # выглядят дёшево). Слова «стиль/формат/аудитория» и т.п. теперь
        # уходят под биролл или остаются лицом с keyword-pop.

        # Перечисление -> график. Смотрим вперёд по фразам блока, собираем регион
        # с запятыми, режем на пункты по запятым/«и», берём короткие (<=3 слов).
        if not used["chart"] and ("," in text) and role in ("development", "payoff"):
            def _has_cmd(t):
                return any(_norm(x).startswith(_CMD_VERBS) for x in t.split())
            j = i
            region = []
            while j < n and phrases[j]["block"] == block and ("," in phrases[j]["text"]) \
                    and not _has_cmd(phrases[j]["text"]):
                region.append(phrases[j])
                j += 1
            combined = " ".join(p["text"] for p in region)
            parts = [p.strip(" .,") for p in re.split(r"[,;]| и ", combined)]
            items_raw = [p for p in parts if 0 < len(p.split()) <= 3 and len(p) > 2]
            # настоящий список: >=3 запятых в регионе (иначе это запятые предложения)
            if len(items_raw) >= 3 and combined.count(",") >= 3 and region:
                used["chart"] = True
                rstart, rend = region[0]["start"], region[-1]["end"]
                span = max(0.1, rend - rstart)
                items = [{"t": round(rstart + span * k / len(items_raw[:5]), 2),
                          "label": l.capitalize()[:22], "v": [0.7, 0.55, 0.85, 0.75, 1.0][k % 5]}
                         for k, l in enumerate(items_raw[:5])]
                # chart_bars — фолбэк; при доступном HyperFrames рендерится блок
                # task_list (анимированный список) и подставляется как fullscreen.
                emit(segments, rstart, rend, role, {"type": "hold"}, "none",
                     {"type": "chart_bars", "title": "ЧТО МОЖНО ЗАКРЫТЬ", "items": items,
                      "hyperframes": {"block": "task_list",
                                      "variables": {"title": "ЧТО МОЖНО ЗАКРЫТЬ",
                                                    "items": [it["label"] for it in items]}}}, "hidden")
                i = j
                continue

        # payoff-вывод -> аватар в кружке (один раз, ключевой личный момент)
        if role == "payoff" and has_any_broll and not used["bubble"] and \
                re.search(r"настро|один раз|больше не|готов", low):
            used["bubble"] = True
            bub = {"shape": "circle", "position": "bottom_left"}
            if face:
                bub["face"] = {"cx": face["cx"], "cy": face["cy"], "h": face["h"]}
                bub["face_zoom"] = face.get("face_zoom", 3.1)
                bub["face_dy"] = face.get("face_dy", 45)
            j = i
            while j + 1 < n and phrases[j + 1]["block"] == block:
                j += 1
            emit(segments, ph["start"], phrases[j]["end"], role, {"type": "hold"}, "none",
                 {"type": "broll", "style": "fullscreen",
                  "broll_query": _broll_query(text, "крупный план, атмосфера"),
                  "src": broll_file, "offset": seg_off("payoff", 1.0), "bubble": bub}, "top")
            i = j + 1
            continue

        # «автоматизировать всё» -> полноэкранный биролл (частицы-иконки убраны как
        # эмодзи-подобные; zoom_blur убран как зум). Whip-переход, окно >= MIN_BROLL_S.
        if not used["particles"] and has_any_broll and i > 0 and \
                re.search(r"автоматизир|везде|многое", low):
            used["particles"] = True
            j = _extend_to_min(phrases, i, block, MIN_BROLL_S)
            emit(segments, ph["start"], phrases[j]["end"], role, {"type": "hold"}, "whip",
                 {"type": "broll", "style": "fullscreen",
                  "broll_query": _broll_query(text, "технологии, абстрактный фон"),
                  "src": broll_file, "offset": seg_off(role, 0.0)}, "bottom")
            i = j + 1
            continue

        # ==== ФРАЗОВЫЕ (лёгкие) эффекты ====
        caption, transition, camera, effect = "bottom", "none", {"type": "hold"}, {"type": "none"}
        # Биролл на «инструкц/набор/список...» — ПОЛНОЭКРАННЫЙ (не pip/половина),
        # окно >= MIN_BROLL_S, whip-переход. НЕ на первой фразе (i > 0): хук
        # открывается лицом.
        if not used["pip"] and has_any_broll and i > 0 and \
                re.search(r"инструкц|набор|блокнот|список|заметк|шаг", low):
            used["pip"] = True
            j = _extend_to_min(phrases, i, block, MIN_BROLL_S)
            emit(segments, ph["start"], phrases[j]["end"], role, {"type": "hold"}, "whip",
                 {"type": "broll", "style": "fullscreen",
                  "broll_query": _broll_query(text, "рабочий стол, заметки"),
                  "src": broll_file, "offset": seg_off(role, 0.0)}, "bottom")
            i = j + 1
            continue

        # Камера: медленный дрейф ken_burns на «лицевых» сегментах (движение без
        # резких зумов). payoff — статикой (hold) для контраста. Первая фраза
        # тоже получает дрейф, чтобы хук не был мёртвым.
        if role != "payoff":
            camera = {"type": DRIFT_CAMERA}

        emit(segments, ph["start"], ph["end"], role, camera, transition, effect, caption)
        i += 1

    return {
        "_generated_by": "revideo_adapter.plan_to_tz (фразовая, контентная)",
        "meta": {"duration": round(total, 3), "fps": 30, "size": [1080, 1920],
                 "language": config.get("language", "ru"),
                 "base_video": base_video, "words": "words.json"},
        "brand": brand, "captions": captions, "segments": segments,
    }
