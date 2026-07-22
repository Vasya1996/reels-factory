"""Наложение b-roll на ролик с говорящей головой — разные способы показать
видеоряд, не теряя (или временно теряя) лицо.

Три способа, каждый под свой момент:

  * FULL   — b-roll закрывает весь кадр на 2-4с, голос идёт за кадром, потом
             снова лицо. «Показал и вернулся» — самый частый приём. НИКОГДА не
             на хук: первые секунды зритель знакомится с лицом.
  * THIRD  — b-roll лентой в верхней или нижней трети поверх кадра, лицо
             остаётся. Быстрый акцент без ухода со спикера.
  * SPLIT  — кадр делится: спикер в одной половине, b-roll в другой. В отличие
             от FULL/THIRD это не окно поверх, а постоянная композиция; для
             отдельной вставки используется реже, но поддержан ради полноты.

Каждая вставка задаётся окном [start, end] в таймлайне ролика и источником
(файл + смещение). Тип наложения выбирается на уровень выше (editplan/LLM): здесь
только исполнение на ffmpeg overlay. Все окна собираются в ОДИН filter_complex —
меньше перекодировок, меньше потерь качества.

Согласовано с editplan-правилами: 1-3 вставки на ролик, 2-5с каждая, не на хук,
по возможности по биту.
"""
import subprocess
from pathlib import Path

from reels_factory.config import FFMPEG, FPS

FULL = "full"    # полное перекрытие на окно, потом возврат к лицу
THIRD = "third"  # лента в верхней/нижней трети поверх кадра
SPLIT = "split"  # деление кадра спикер|broll

# Доля высоты кадра под ленту в режиме THIRD.
THIRD_FRACTION = 0.33
# Длительность плавного входа/выхода вставки — резкое появление читается как
# сбой, короткий кроссфейд как монтаж.
FADE_S = 0.2
# Длительность заезда/выезда вставки (слайд). Дольше — вставка «плывёт»,
# короче — движение не успевает прочитаться.
ANIM_S = 0.35


def _ease_in_expr(s: float, anim: float = ANIM_S) -> str:
    """Кубический выезд: 1 в момент s, 0 после s+anim (ease-out прибытия)."""
    return f"pow(1-clip((t-{s:.3f})/{anim:.3f},0,1),3)"


def _ease_out_expr(e: float, anim: float = ANIM_S) -> str:
    """Кубический разгон: 0 до e-anim, 1 к моменту e (ease-in ухода)."""
    return f"pow(clip((t-{e - anim:.3f})/{anim:.3f},0,1),3)"


def insert_motion(kind: str, s: float, e: float, base_h: int,
                  pos: str = "bottom", anim: float = ANIM_S) -> tuple:
    """(x_expr, y_expr) для overlay: вставка ЗАЕЗЖАЕТ и ВЫЕЗЖАЕТ, а не мигает.

    FULL — слайд с правого края внутрь, уход за левый край (движение по X
    читается как переход, а не как «включили картинку»). THIRD/SPLIT — лента
    выдвигается из своего края кадра (top — сверху, bottom — снизу) и туда же
    уходит. Выражения зависят от t, overlay считает их покадрово.
    """
    s, e = float(s), float(e)
    ei = _ease_in_expr(s, anim)
    eo = _ease_out_expr(e, anim)
    if kind == FULL:
        return (f"W*{ei}-W*{eo}", "0")
    if kind == THIRD:
        bh = int(base_h * THIRD_FRACTION) // 2 * 2
        if pos == "top":
            return ("0", f"0-{bh}*{ei}-{bh}*{eo}")
        y0 = base_h - bh
        return ("0", f"{y0}+{bh}*{ei}+{bh}*{eo}")
    if kind == SPLIT:
        half = base_h // 2 // 2 * 2
        y0 = base_h - half
        return ("0", f"{y0}+{half}*{ei}+{half}*{eo}")
    raise ValueError(f"неизвестный тип наложения: {kind!r}")


def build_overlay_filter(inserts: list, base_w: int, base_h: int,
                         fps: int = FPS) -> tuple:
    """Собрать filter_complex наложения b-roll на базовый кадр (спикер).

    inserts: [{"kind","start","end","pos"?}, ...] в порядке появления. Индекс
    входа ffmpeg для i-й вставки = i+1 ([0]=базовый кадр). pos для THIRD:
    "top"|"bottom" (по умолчанию bottom).

    Возвращает (filter_complex_str, out_label). Вставки применяются по очереди,
    каждая поверх результата предыдущей — окна не пересекаются (следит editplan),
    так что порядок не важен для картинки, только для нумерации входов.
    """
    parts = []
    cur = "0:v"
    for i, ins in enumerate(inserts):
        idx = i + 1
        s, e = float(ins["start"]), float(ins["end"])
        kind = ins["kind"]
        enable = f"between(t,{s:.3f},{e:.3f})"
        # СДВИГ PTS на начало окна: вход обрезан до [0, dur], а показать его надо
        # в окне [s, e] базы. Без сдвига кадры вставки к моменту окна уже кончились
        # и overlay ничего не рисует — ровно этот баг давал «b-roll не видно».
        shift = f"setpts=PTS+{s:.3f}/TB"
        # плавный вход/выход самой вставки (времена абсолютные, после сдвига)
        fade = (f"fade=t=in:st={s:.3f}:d={FADE_S}:alpha=1,"
                f"fade=t=out:st={max(s, e - FADE_S):.3f}:d={FADE_S}:alpha=1")
        pre = f"setsar=1,fps={fps},format=yuva420p,{shift},{fade}"

        # заезд/выезд вставки: overlay с покадровыми x/y (см. insert_motion)
        mx, my = insert_motion(kind, s, e, base_h, ins.get("pos") or "bottom")
        if kind == FULL:
            parts.append(
                f"[{idx}:v]scale={base_w}:{base_h}:force_original_aspect_ratio=increase,"
                f"crop={base_w}:{base_h},{pre}[bi{i}]")
        elif kind == THIRD:
            bh = int(base_h * THIRD_FRACTION) // 2 * 2
            parts.append(
                f"[{idx}:v]scale={base_w}:{bh}:force_original_aspect_ratio=increase,"
                f"crop={base_w}:{bh},{pre}[bi{i}]")
        elif kind == SPLIT:
            # спикер сверху (base_h/2), b-roll снизу — постоянная композиция в окне
            half = base_h // 2 // 2 * 2
            parts.append(
                f"[{idx}:v]scale={base_w}:{half}:force_original_aspect_ratio=increase,"
                f"crop={base_w}:{half},{pre}[bi{i}]")
        else:
            raise ValueError(f"неизвестный тип наложения: {kind!r}")
        parts.append(f"[{cur}][bi{i}]overlay=x='{mx}':y='{my}':enable='{enable}'[ov{i}]")
        cur = f"ov{i}"

    parts.append(f"[{cur}]null[v]")
    return ";".join(parts), "v"


def render_broll(base_mp4, inserts: list, out_mp4, *, fps: int = FPS,
                 run=None) -> Path:
    """Наложить b-roll на базовый ролик и вернуть путь к результату.

    Звук базового ролика сохраняется как есть: b-roll идёт немым слоем, голос
    спикера не перебивается (у FULL под картинкой продолжает звучать голос).
    """
    base_mp4, out_mp4 = Path(base_mp4), Path(out_mp4)
    if not inserts:
        raise ValueError("нет вставок для наложения")
    w, h = _probe_wh(base_mp4)
    fc, out_label = build_overlay_filter(inserts, w, h, fps)

    cmd = [FFMPEG, "-y", "-i", str(base_mp4)]
    for ins in inserts:
        src = ins["src"]
        off = float(ins.get("offset", 0))
        dur = float(ins["end"]) - float(ins["start"])
        cmd += ["-ss", f"{off}", "-t", f"{dur:.3f}", "-i", str(src)]
    cmd += ["-filter_complex", fc, "-map", f"[{out_label}]", "-map", "0:a?",
            "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-shortest", str(out_mp4)]
    (run or _run)(cmd)
    if not out_mp4.exists():
        raise RuntimeError(f"ffmpeg не создал файл: {out_mp4}")
    return out_mp4


def _probe_wh(src) -> tuple:
    from reels_factory.render import probe_wh
    return probe_wh(str(src))


def _run(cmd: list) -> None:
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg broll упал (код {p.returncode}): {(p.stderr or '')[:500]}")
