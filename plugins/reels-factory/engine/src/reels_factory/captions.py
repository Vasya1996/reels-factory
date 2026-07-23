"""Сборка ASS-субтитров из списка слов с таймкодами: дизайнерские пресеты.

Слова приходят уже в координатах рилса (start/end от 0). Стили:

  * karaoke — 1-3 слова капсом, караоке-подсветка текущего слова жёлтым (\\kf),
    pop-in подписи. Стиль «Hormozi», дефолт.
  * popword — ОДНО слово на экране, крупно, с пружинкой (scale-bounce) и
    лёгким чередующимся наклоном. Стиль «по слову» из вирусных монтажей.
  * boxed  — 1-3 слова на полупрозрачной чёрной плашке (BorderStyle=3),
    без караоке, мягкий фейд. Спокойный «интервью»-стиль.

keywords — акцентные слова (от LLM-ТЗ): в popword/boxed красятся акцентным
цветом и чуть крупнее; в karaoke караоке-подсветка и так есть.

API:  build_ass(words, out_path, font="Arial Black", play_w=1080, play_h=1920,
                pos=None, style="karaoke", keywords=None)
      words = [{"start":float,"end":float,"text":str}, ...]
"""
import os
import re as _re

MAX_WORDS = 3        # слов в одной подписи (karaoke/boxed)
GAP_BREAK = 0.45     # пауза >0.45с — новая подпись
MAX_CHARS = 18       # не переполнять строку

STYLES = ("karaoke", "popword", "boxed")

# Цвета ASS (&HAABBGGRR): жёлтый акцент и белый текст.
ACCENT = "&H0000F0FF&"
WHITE = "&H00FFFFFF&"

# Pop-in подписи: появляется чуть меньше и за 90мс «допрыгивает» до 100% с
# коротким альфа-фейдом. Статичная смена текста читается как титры из
# телесуфлёра; пружинка — как субтитры, собранные монтажёром.
POP_TAG = "{\\fscx82\\fscy82\\t(0,90,\\fscx100\\fscy100)\\fad(40,0)}"

# Пружинка одного слова: 70% -> 106% -> 100% (перелёт и возврат читаются как
# «удар» слова в такт речи).
BOUNCE_TAG = "{\\fscx70\\fscy70\\t(0,70,\\fscx106\\fscy106)\\t(70,140,\\fscx100\\fscy100)\\fad(30,0)}"

# Наклон слова в popword чередуется по кругу — сетка из одинаково ровных слов
# выглядит машинной, лёгкий разнобой читается как ручная вёрстка.
TILT_CYCLE = (-4, 0, 4, 0)


def _cs(t):
    return max(0, int(round(t * 100)))


def _clean(words):
    """Убрать токены-«пустышки» из одних знаков препинания и зачистить края текста."""
    out = []
    for w in words:
        t = _re.sub(r"^[\s,.;:!?\-–—]+|[\s]+$", "", w["text"])
        if not _re.sub(r"[\W_]+", "", t, flags=_re.UNICODE):
            continue  # только пунктуация — пропускаем
        out.append({**w, "text": t})
    return out


def chunk_words(words):
    words = _clean(words)
    chunks, cur = [], []
    for w in words:
        if cur:
            gap = w["start"] - cur[-1]["end"]
            cur_len = sum(len(x["text"]) for x in cur) + len(cur)
            if gap > GAP_BREAK or len(cur) >= MAX_WORDS or cur_len + len(w["text"]) > MAX_CHARS:
                chunks.append(cur); cur = []
        cur.append(w)
    if cur:
        chunks.append(cur)
    return chunks


def _ts(t):
    h = int(t // 3600); t -= h * 3600
    m = int(t // 60); s = t - m * 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def _is_keyword(text: str, keywords: set) -> bool:
    core = _re.sub(r"[\W_]+", "", str(text), flags=_re.UNICODE).lower()
    return bool(core) and core in keywords


def _header(font, play_w, play_h, style: str) -> str:
    fontsize = int(play_w * (0.12 if style == "popword" else 0.10))
    outline = max(4, int(play_w * 0.006))
    shadow = max(2, int(play_w * 0.003))
    if style == "boxed":
        # BorderStyle=3: BackColour становится плашкой; полупрозрачный чёрный
        style_line = (f"Style: Cap,{font},{fontsize},{WHITE[:-1]},{WHITE[:-1]},"
                      f"&H00000000,&H78000000,-1,0,0,0,100,100,0,0,3,"
                      f"{max(6, outline)},0,5,90,130,0,1")
    else:
        style_line = (f"Style: Cap,{font},{fontsize},&H0000F0FF,{WHITE[:-1]},"
                      f"&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,"
                      f"{outline},{shadow},5,90,130,0,1")
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {play_w}
PlayResY: {play_h}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{style_line}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _esc(text: str) -> str:
    return str(text).upper().replace("{", "(").replace("}", ")")


def _karaoke_events(words, pos_tag):
    lines = []
    for ch in chunk_words(words):
        c_start = ch[0]["start"]
        c_end = ch[-1]["end"]
        if c_end - c_start < 0.30:
            c_end = c_start + 0.30
        parts = []
        prev_end = c_start
        for w in ch:
            gap = w["start"] - prev_end
            if gap > 0.02:
                parts.append(f"{{\\k{_cs(gap)}}}")
            dur = max(0.05, w["end"] - w["start"])
            parts.append(f"{{\\kf{_cs(dur)}}}{_esc(w['text'])} ")
            prev_end = w["end"]
        text = "".join(parts).strip()
        lines.append(
            f"Dialogue: 0,{_ts(c_start)},{_ts(c_end)},Cap,,0,0,0,,{pos_tag}{POP_TAG}{text}")
    return lines


def _popword_events(words, pos_tag, keywords: set):
    """Одно слово на экране: держится до старта следующего (без «дыр» между
    словами — мигание пустотой выглядит как сбой), пружинка на входе."""
    ws = _clean(words)
    lines = []
    for i, w in enumerate(ws):
        start = w["start"]
        nxt = ws[i + 1]["start"] if i + 1 < len(ws) else None
        end = max(w["end"], start + 0.30)
        if nxt is not None:
            end = max(min(end, nxt), start + 0.15)
        tilt = TILT_CYCLE[i % len(TILT_CYCLE)]
        tags = BOUNCE_TAG
        if tilt:
            tags += f"{{\\frz{tilt}}}"
        if _is_keyword(w["text"], keywords):
            tags += f"{{\\1c{ACCENT}\\fscx108\\fscy108}}"
        lines.append(
            f"Dialogue: 0,{_ts(start)},{_ts(end)},Cap,,0,0,0,,{pos_tag}{tags}{_esc(w['text'])}")
    return lines


def _boxed_events(words, pos_tag, keywords: set):
    lines = []
    for ch in chunk_words(words):
        c_start = ch[0]["start"]
        c_end = max(ch[-1]["end"], c_start + 0.30)
        parts = []
        for w in ch:
            if _is_keyword(w["text"], keywords):
                parts.append(f"{{\\1c{ACCENT}}}{_esc(w['text'])}{{\\1c{WHITE}}} ")
            else:
                parts.append(f"{_esc(w['text'])} ")
        text = "".join(parts).strip()
        lines.append(
            f"Dialogue: 0,{_ts(c_start)},{_ts(c_end)},Cap,,0,0,0,,"
            f"{pos_tag}{{\\fad(80,60)}}{text}")
    return lines


def build_ass(words, out_path, font="Arial Black", play_w=1080, play_h=1920,
              pos=None, style="karaoke", keywords=None):
    """pos=(x,y) — принудительная позиция центра текста (для верха сплит-экрана и т.п.).
    style — один из STYLES; keywords — акцентные слова (список строк)."""
    if style not in STYLES:
        raise ValueError(f"неизвестный стиль субтитров: {style!r} (есть {STYLES})")
    kw = {_re.sub(r"[\W_]+", "", str(k), flags=_re.UNICODE).lower()
          for k in (keywords or []) if str(k).strip()}
    pos_tag = f"{{\\an5\\pos({pos[0]},{pos[1]})}}" if pos else ""

    lines = [_header(font, play_w, play_h, style)]
    if style == "popword":
        lines += _popword_events(words, pos_tag, kw)
    elif style == "boxed":
        lines += _boxed_events(words, pos_tag, kw)
    else:
        lines += _karaoke_events(words, pos_tag)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return out_path
