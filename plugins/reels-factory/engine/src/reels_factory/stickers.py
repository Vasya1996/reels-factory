"""Всплывающие текстовые стикеры поверх ролика («напиши пост», «БЕСПЛАТНО»).

Отдельный слой от субтитров: субтитры дублируют речь, стикер — монтажный
акцент, который ставит ТЗ. Рендерится вторым ASS-файлом и жжётся тем же
проходом ffmpeg (ass=caps.ass,ass=stickers.ass) — лишней перекодировки нет.

Анимации:
  * pop        — текст выпрыгивает с пружинкой (70% -> 106% -> 100%).
  * typewriter — текст печатается по букве (~45мс/символ) с курсором,
                 допечатанный держится до конца окна. Читается как «ты сам
                 это набираешь» — идеально под фразы вида «просто говоришь:
                 напиши пост».

API: build_stickers_ass(stickers, out_path, font=..., play_w, play_h)
     stickers = [{"start","end","text","anim":"pop"|"typewriter","y"?}, ...]
     y — вертикаль центра в долях кадра (по умолчанию 0.30 — над лицом).
"""

ANIMS = ("pop", "typewriter")

TYPE_CPS_S = 0.045   # секунд на символ печати
CURSOR = "|"

POP_TAG = "{\\fscx70\\fscy70\\t(0,70,\\fscx106\\fscy106)\\t(70,140,\\fscx100\\fscy100)\\fad(30,40)}"


def _ts(t):
    h = int(t // 3600); t -= h * 3600
    m = int(t // 60); s = t - m * 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def _esc(text: str) -> str:
    return str(text).replace("{", "(").replace("}", ")")


def _header(font, play_w, play_h) -> str:
    fontsize = int(play_w * 0.085)
    outline = max(4, int(play_w * 0.006))
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {play_w}
PlayResY: {play_h}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Stick,{font},{fontsize},&H0000F0FF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,{outline},2,5,90,90,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _pos_tag(play_w, play_h, y_frac: float) -> str:
    return f"{{\\an5\\pos({play_w // 2},{int(play_h * y_frac)})}}"


def _pop_events(st, pos_tag):
    s, e = float(st["start"]), float(st["end"])
    return [f"Dialogue: 1,{_ts(s)},{_ts(e)},Stick,,0,0,0,,{pos_tag}{POP_TAG}{_esc(st['text'])}"]


def _typewriter_events(st, pos_tag):
    """По событию на каждый набранный префикс: [абв|] сменяется [абвг|].
    Последний префикс (полный текст, без курсора) держится до конца окна."""
    s, e = float(st["start"]), float(st["end"])
    text = str(st["text"])
    n = max(1, len(text))
    # не растягивать печать дольше 60% окна — текст должен успеть повисеть
    cps = min(TYPE_CPS_S, (e - s) * 0.6 / n)
    lines = []
    for i in range(1, n + 1):
        t0 = s + (i - 1) * cps
        t1 = s + i * cps if i < n else e
        frag = _esc(text[:i]) + (CURSOR if i < n else "")
        lines.append(f"Dialogue: 1,{_ts(t0)},{_ts(t1)},Stick,,0,0,0,,{pos_tag}{frag}")
    return lines


def build_stickers_ass(stickers, out_path, font="Arial Black",
                       play_w=1080, play_h=1920):
    lines = [_header(font, play_w, play_h)]
    for st in stickers:
        anim = st.get("anim", "pop")
        if anim not in ANIMS:
            raise ValueError(f"неизвестная анимация стикера: {anim!r} (есть {ANIMS})")
        pos_tag = _pos_tag(play_w, play_h, float(st.get("y", 0.30)))
        if anim == "typewriter":
            lines += _typewriter_events(st, pos_tag)
        else:
            lines += _pop_events(st, pos_tag)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return out_path
