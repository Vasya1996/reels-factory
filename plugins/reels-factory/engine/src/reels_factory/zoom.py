"""Зумы уровня монтажа: медленный наезд с easing на лицо, а не рывок в центр.

Чем это отличается от прежнего панча (который дёргал кадр на 0.6с и возвращал):

  * **push-in** — медленный наезд НА ПРОТЯЖЕНИИ фразы (2-4с), плавный вход и
    выход по кубической кривой, буквально +6-10%. Зритель его не замечает,
    только чувствует нарастание. Это и есть «нормальный зум» из монтажа.
  * **punch-in** — мгновенная смена крупности на границе фразы, кадр стал
    крупнее И ОСТАЛСЯ таким до следующей смены. Это разрез, а не отскок.
  * якорь наезда — **лицо**, найденное детектором, а не геометрический центр:
    если человек стоит не по центру, наезд в центр кадрирует его криво.

Техника — `zoompan` с двумя обязательными оговорками, без которых он ломается:
  1. ПЕРЕД zoompan ставим фильтр `fps=N`: iPhone пишет видео с переменным
     фреймрейтом (VFR), а zoompan считает по кадрам — на VFR это разъезжается
     со звуком. `fps=N` приводит к постоянному фреймрейту, и синхрон держится.
  2. звук перекодируем (`aac`), а не копируем: копия несёт старые VFR-тайминги,
     которые не совпадут с уже CFR-видео.
`crop` для зума не годится: он вычисляет размер окна один раз при конфигурации
и анимировать его через `t` нельзя (только позицию). zoompan умеет менять
масштаб покадрово через выражение от `on` (номер кадра = t*fps на CFR).

Easing зашит выражением (smoothstep: 3t^2-2t^3) — ffmpeg считает его сам, без
покадрового пайпа в numpy. Координаты лица берём OpenCV-детектором (Haar),
усредняем по ролику — говорящая голова стоит на месте, поэтому одной
устойчивой точки достаточно, покадровое ведение камеры тут избыточно.

zoom.py ничего не знает про план монтажа: на вход список сегментов
[(start, end, kind, strength)], на выход — путь к отрендеренному mp4. Кто и
почему поставил наезд именно сюда — решает editplan.py выше.
"""
import subprocess
from pathlib import Path

from reels_factory.config import FFMPEG, FPS

# Сила по умолчанию: +8% за наезд. Больше уже читается как «зумит», меньше —
# незаметно вовсе. Держим мягко, монтаж набирается числом наездов, не амплитудой.
DEFAULT_PUSH_STRENGTH = 0.08
DEFAULT_PUNCH_STRENGTH = 0.10
MAX_STRENGTH = 0.15  # выше — «дешёвый» зум, каким бы плавным ни был

PUSH = "push"        # медленный наезд по ходу фразы, к концу мягко отпускает
PUNCH = "punch"      # мгновенная смена крупности, держится всю фразу
PULSE = "pulse"      # наехал к середине фразы, отъехал к концу — один вдох
HOLD = "hold"        # без движения: широкий план, точка отдыха в ритме крупностей
ZOOM_OUT = "zoom_out"  # старт крупно, плавный отъезд к широкому по ходу фразы

# Чередование типов по фразам: подряд идущие одинаковые наезды выглядят
# однообразно, поэтому фразы получают разный тип по кругу. hold — обязательная
# пауза: без «широких» фраз всё превращается в непрерывное приближение.
KIND_CYCLE = (PUSH, HOLD, PUNCH, PULSE)


def detect_face_anchor(src, *, sample_fps: float = 2.0, run_probe=None,
                       detect=None) -> tuple:
    """Найти устойчивый якорь лица как доли кадра (fx, fy) в [0,1].

    Семплируем несколько кадров (говорящая голова не движется — частить незачем),
    берём медиану центров найденных лиц. Лицо не найдено ни на одном кадре —
    возвращаем чуть выше центра (0.5, 0.42): у головы должен быть headroom, и
    даже без детекта это лучше геометрического центра.
    """
    if detect is not None:
        centers = detect(src, sample_fps)
    else:
        try:
            centers = _detect_faces_opencv(src, sample_fps)
        except Exception:
            # нет OpenCV / не читается файл — дефолтный якорь лучше, чем падение
            centers = []
    if not centers:
        return (0.5, 0.42)
    xs = sorted(c[0] for c in centers)
    ys = sorted(c[1] for c in centers)
    return (_median(xs), _median(ys))


MAX_ZOOM_S = 8.0    # наезд длиннее просто ползёт — на длинной фразе режем окно
MIN_ZOOM_S = 0.4    # короче — движение не успевает прочитаться


def plan_zoom_segments(phrases: list, *, push=DEFAULT_PUSH_STRENGTH,
                       punch=DEFAULT_PUNCH_STRENGTH, cycle=KIND_CYCLE) -> list:
    """Раздать фразам типы движения по кругу (push/hold/punch/pulse).

    phrases: [(start, end), ...] — куски речи между паузами (speech_segments).
    Возвращает [(start, end, kind, strength), ...] для build_zoom_expr.

    Разные типы подряд = разные крупности = ритм, а не общий наезд. hold в
    цикле даёт «широкие» фразы-передышки. Наезд не длиннее MAX_ZOOM_S: у долгой
    фразы берём только первые секунды, дальше кадр стоит.
    """
    out = []
    ci = 0
    for (s, e) in phrases:
        length = e - s
        if length < MIN_ZOOM_S:
            continue  # слишком коротко для движения — оставляем как есть
        kind = cycle[ci % len(cycle)]
        ci += 1
        if kind == HOLD:
            continue
        # длинную фразу не тянем целиком — наезд до MAX_ZOOM_S от начала
        seg_e = min(e, s + MAX_ZOOM_S)
        strength = punch if kind == PUNCH else push
        out.append((s, seg_e, kind, strength))
    return out


def build_zoom_expr(segments: list, duration: float, fps: int = FPS,
                    anchor: tuple = (0.5, 0.42)) -> dict:
    """Собрать выражение зум-фактора z(t) и crop x/y/w/h от времени.

    segments: [(start, end, kind, strength), ...]. Пересекать их не нужно —
    editplan следит, чтобы наезды не накладывались; здесь просто суммируем
    вклад каждого в общий зум-фактор (вне своего окна вклад = 0).

    Всё считается от `t` (секунды), а не от номера кадра: на VFR-видео номер
    кадра плывёт, а время — нет.
    """
    fx, fy = anchor

    # выражение считается по 'on' (номер выходного кадра); на CFR on = t*fps.
    # Каждый терм умножен на GATE окна фразы — вне своей фразы вклад строго 0,
    # поэтому наезды НЕ накапливаются в один общий зум, а сбрасываются между
    # фразами. Это ровно то, чего не хватало: без gate кадр наползал до конца.
    z_terms = ["1"]
    for (s, e, kind, strength) in segments:
        if kind == HOLD:
            continue  # широкий план — терма нет, точка отдыха в ритме крупностей
        s, e = float(s), float(e)
        stg = min(float(strength), MAX_STRENGTH)
        sf, ef = s * fps, e * fps
        span = max(1.0, ef - sf)
        gate = f"between(on,{sf:.1f},{ef:.1f})"
        prog = f"clip((on-{sf:.1f})/{span:.1f},0,1)"
        if kind == PUNCH:
            shape = "1"  # скачок к strength, держится всю фразу (обрежет gate)
        elif kind == ZOOM_OUT:
            # старт на полной крупности, smoothstep-отъезд к нулю к концу фразы
            shape = f"(1-(3*pow({prog},2)-2*pow({prog},3)))"
        elif kind == PULSE:
            # треугольник: пик в середине фразы, к краям — к нулю (один «вдох»)
            mid, half = (sf + ef) / 2, span / 2
            shape = f"(1-abs((on-{mid:.1f})/{half:.1f}))"
        else:  # PUSH — smoothstep-наезд, в последние 30% фразы мягко отпускает
            rel_start = ef - span * 0.3
            rel = f"(1-clip((on-{rel_start:.1f})/{span * 0.3:.1f},0,1))"
            shape = f"(3*pow({prog},2)-2*pow({prog},3))*{rel}"
        z_terms.append(f"{stg:.4f}*{shape}*{gate}")

    z = "(" + "+".join(z_terms) + ")"
    # окно зума сужается с ростом z; якорь лица держим в центре окна
    x = f"(iw-iw/zoom)*{fx:.4f}"
    y = f"(ih-ih/zoom)*{fy:.4f}"
    return {"z": z, "x": x, "y": y}


def render_zoom(src, out, segments, *, duration=None, fps: int = FPS,
                anchor=None, run=None) -> Path:
    """Отрендерить ролик с зумами. Возвращает путь к результату."""
    src, out = Path(src), Path(out)
    if duration is None:
        duration = _probe_duration(src)
    if anchor is None:
        anchor = detect_face_anchor(src)
    expr = build_zoom_expr(segments, duration, fps, anchor)

    w, h = _probe_wh(src)
    # zoompan округляет размер окна до целых пикселей на каждом кадре — на
    # медленном наезде это даёт микроступеньки. Рендерим на увеличенном холсте
    # (supersampling x2) и ужимаем обратно: дробное движение сглаживается.
    ss = 2
    vf = (
        f"fps={fps},"                       # VFR -> CFR: иначе рассинхрон
        f"scale={w * ss}:{h * ss}:flags=bicubic,"
        f"zoompan=z='{expr['z']}':x='{expr['x']}':y='{expr['y']}':"
        f"d=1:fps={fps}:s={w * ss}x{h * ss},"   # fps ОБЯЗАТЕЛЕН и здесь, иначе кадры надуваются
        f"scale={w}:{h}:flags=bicubic,setsar=1"
    )
    cmd = [FFMPEG, "-y", "-i", str(src), "-vf", vf,
           "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", str(out)]  # aac, не copy: VFR-тайминги не подойдут
    (run or _run)(cmd)
    if not out.exists():
        raise RuntimeError(f"ffmpeg не создал файл: {out}")
    return out


# --- внутреннее ---

def _detect_faces_opencv(src, sample_fps: float) -> list:
    import cv2

    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    cascade = cv2.CascadeClassifier(cascade_path)
    cap = cv2.VideoCapture(str(src))
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30
    step = max(1, int(round(src_fps / sample_fps)))
    centers, i = [], 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if i % step == 0:
            h, w = frame.shape[:2]
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, 1.1, 5, minSize=(w // 8, h // 8))
            if len(faces):
                fx, fy, fw, fh = max(faces, key=lambda f: f[2] * f[3])
                centers.append(((fx + fw / 2) / w, (fy + fh / 2) / h))
        i += 1
    cap.release()
    return centers


def _median(xs: list) -> float:
    n = len(xs)
    if n == 0:
        return 0.5
    m = n // 2
    return xs[m] if n % 2 else (xs[m - 1] + xs[m]) / 2


def _probe_duration(src) -> float:
    from reels_factory.render import media_dur
    return media_dur(str(src))


def _probe_wh(src) -> tuple:
    from reels_factory.render import probe_wh
    return probe_wh(str(src))


def _run(cmd: list) -> None:
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg zoom упал (код {p.returncode}): {(p.stderr or '')[:500]}")
