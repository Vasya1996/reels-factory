"""Сборка ASS-субтитров в стиле Hormozi из списка слов с таймкодами.

Слова приходят уже в координатах рилса (start/end от 0). Группируются по 1-3 слова,
КАПСом, по центру кадра (\\an5, вне нижней/правой safe-zone), караоке-подсветка
текущего слова жёлтым (\\kf).

API:  build_ass(words, out_path, font="Arial Black", play_w=1080, play_h=1920)
      words = [{"start":float,"end":float,"text":str}, ...]
"""
import os

MAX_WORDS = 3        # слов в одной подписи
GAP_BREAK = 0.45     # пауза >0.45с — новая подпись
MAX_CHARS = 18       # не переполнять строку


def _cs(t):
    return max(0, int(round(t * 100)))


def _clean(words):
    """Убрать токены-«пустышки» из одних знаков препинания и зачистить края текста."""
    import re as _re
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


def build_ass(words, out_path, font="Arial Black", play_w=1080, play_h=1920, pos=None):
    """pos=(x,y) — принудительная позиция центра текста (для верха сплит-экрана и т.п.)."""
    pos_tag = f"{{\\an5\\pos({pos[0]},{pos[1]})}}" if pos else ""
    fontsize = int(play_w * 0.10)        # ~108 для 1080
    outline = max(4, int(play_w * 0.006))
    shadow = max(2, int(play_w * 0.003))
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {play_w}
PlayResY: {play_h}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},{fontsize},&H0000F0FF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,{outline},{shadow},5,90,130,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for ch in chunk_words(words):
        c_start = ch[0]["start"]
        c_end = ch[-1]["end"]
        # минимальная видимость подписи
        if c_end - c_start < 0.30:
            c_end = c_start + 0.30
        parts = []
        prev_end = c_start
        for w in ch:
            gap = w["start"] - prev_end
            if gap > 0.02:
                parts.append(f"{{\\k{_cs(gap)}}}")
            dur = max(0.05, w["end"] - w["start"])
            txt = w["text"].upper().replace("{", "(").replace("}", ")")
            parts.append(f"{{\\kf{_cs(dur)}}}{txt} ")
            prev_end = w["end"]
        text = "".join(parts).strip()
        lines.append(f"Dialogue: 0,{_ts(c_start)},{_ts(c_end)},Cap,,0,0,0,,{pos_tag}{text}")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return out_path
