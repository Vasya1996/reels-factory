"""Сборка вертикального рилса из голоса блогерши и видеоряда (broll).

Два формата (config.format):
  split      — верх: аватар-блогерша от HeyGen (1080x672), низ: видеоряд
               (1080x1248), vstack; голос уже вшит в аватар-фрагменты.
  fullscreen — видеоряд на весь кадр (1080x1920), голос блогерши за кадром
               (только TTS, аватар HeyGen'ом НЕ рендерится — вдвое дешевле).

Звук = голос блогерши (volume 1.0) + ПОСТОЯННЫЙ слой видеоряда (volume=BROLL_VOLUME,
без дакинга) + whoosh'и на переходах, всё через один amix и alimiter от клиппинга.
Субтитры-караоке — ТОЛЬКО голос блогерши: дорожка на распознавание (voice.wav)
собирается без слоя видеоряда.

Конвейер `assemble` (каждый шаг — render.run):
  0) ретайминг сценария под фактические длительности фрагментов (retime_scenario);
  1) немой видеослой (vstack split | fullscreen broll, + опц. панч-ины);
  2) два аудиомикса — mix.wav (голос+видеоряд+whoosh) и voice.wav (только голос);
  3) transcribe(voice.wav) -> words -> apply_caption_fixes -> build_ass -> прожиг;
  4) двухпроходный loudnorm до LUFS_TARGET/TP_TARGET.

`build_video_filter`/`build_audio_filter`/`plan_broll_cuts`/`build_broll_concat_filter`
— чистые функции, тестируются без ffmpeg.

Низ может быть мультисегментным: `broll_segments=[{"role","offset","slow"?},...]` —
каждый блок ретаймленного сценария берёт свой отрезок исходника; `plan_broll_cuts`
считает отрезки, `_concat_broll` конкатенирует их в единый низовой слой.
`broll_segments=None` — один offset на весь ролик.
"""
import copy
import json
import re
from pathlib import Path

from reels_factory.config import (
    FFMPEG, OUT_W, OUT_H, FPS, LUFS_TARGET, TP_TARGET, CAPTION_FONT, WORK_ROOT,
)
from reels_factory.render import (
    run, media_dur, parse_loudnorm_json, load_words_file, VENC, AENC,
)
from reels_factory.captions import build_ass
from reels_factory.transcribe import transcribe_file

TOP_H = 672
BOT_H = 1248
BROLL_VOLUME = 0.6   # постоянный слой звука видеоряда под всю дорожку
WHOOSH_VOLUME = 0.5  # свуш на переходах
PUNCH_ZOOM = 1.12    # лёгкий наезд на панч-окнах
HOOK_PAUSE_S = 0.5   # дефолтная пауза-заморозка после хука, если pause_after не задан

# whoosh-ассет генерируется функцией (make_whoosh) при setup, не коммитится.
WHOOSH_WAV = WORK_ROOT / "assets" / "whoosh.wav"

# Слово по краям (ведущая/хвостовая пунктуация и дефисы игнорируются при матче,
# сохраняются при замене), корень слова — то, что внутри.
_EDGE_RE = re.compile(r"^([^\w]*)(\w+)([^\w]*)$", re.UNICODE)

# падежные окончания для авто-словоформ корня темы (пабг -> пабге/пабга/...)
_THEME_CASE_SUFFIXES = ("", "е", "а", "у", "ом")


def build_caption_fixes(hypothesis: dict) -> dict:
    """Карта caption-фиксов display -> [варианты, которые мог услышать Whisper].

    Бренд/термины пользователя — из hypothesis["brand_captions"] (dict
    display->варианты; двусловный вариант через пробел = биграмма). Если задана
    тема — добавляется её display (hypothesis["theme"]) с вариантами из
    hypothesis["theme_captions"] плюс автоматически theme_spoken и его падежные
    словоформы (пабг -> пабг/пабге/пабга/...).
    """
    fixes: dict[str, list] = {}

    brand = hypothesis.get("brand_captions") or {}
    if isinstance(brand, dict):
        for display, variants in brand.items():
            fixes.setdefault(str(display), [])
            fixes[str(display)] += list(variants or [])

    theme = hypothesis.get("theme")
    if theme:
        theme_spoken = hypothesis.get("theme_spoken") or theme
        variants = list(hypothesis.get("theme_captions") or [])
        # Авто-словоформы корня — только когда theme само однословное (кейс
        # "theme — короткое имя/бренд типа «ПАБГ», theme_spoken — та же
        # словоформа в другом падеже"). Для МНОГОсловной темы ("домашний
        # кофе") theme_spoken обычно не падежная форма, а сокращение/другая
        # фраза — авто-генерация тогда подменяла бы ПРАВИЛЬНО распознанное
        # слово (например "кофе") на всю фразу темы, ломая субтитры вместо
        # починки. Явные theme_captions продолжают работать в любом случае.
        if len(str(theme).split()) == 1:
            root = str(theme_spoken).strip().lower()
            if root:
                variants += [root + suf for suf in _THEME_CASE_SUFFIXES]
        fixes.setdefault(str(theme), [])
        fixes[str(theme)] += variants

    return fixes


def _split_edges(text: str) -> tuple:
    m = _EDGE_RE.match(str(text))
    return m.groups() if m else ("", str(text), "")


def apply_caption_fixes(words: list, fixes: dict) -> list:
    """Применить карту caption-фиксов (display -> варианты) к словам транскрипции.

    Пословно: слово (без краевой пунктуации/дефисов, регистронезависимо)
    совпадает с однословным вариантом — точно, если вариант короткий (<4 букв),
    иначе по префиксу (с хвостом ≤3 лишних букв, чтобы ловить падежные формы) ->
    заменяется на display, краевая пунктуация сохраняется.
    Биграммно: вариант из двух слов через пробел — первое слово совпадает точно,
    второе — по префиксу -> оба слова сливаются в один display (+пунктуация
    второго слова), start от первого, end от второго.
    """
    single = []  # (variant_lower, display)
    bigrams = []  # (first_lower, second_prefix_lower, display)
    for display, variants in fixes.items():
        for v in variants:
            toks = str(v).strip().split()
            if len(toks) == 1:
                single.append((toks[0].lower(), display))
            elif len(toks) == 2:
                bigrams.append((toks[0].lower(), toks[1].lower(), display))

    def _match_single(core_low: str):
        for variant, display in single:
            if len(variant) < 4:
                if core_low == variant:
                    return display
            elif core_low.startswith(variant) and len(core_low) - len(variant) <= 3:
                return display
        return None

    out = []
    i, n = 0, len(words)
    while i < n:
        w = words[i]
        head, core, tail = _split_edges(w.get("text", ""))
        low = core.lower()

        if i + 1 < n:
            w_next = words[i + 1]
            head2, core2, tail2 = _split_edges(w_next.get("text", ""))
            low2 = core2.lower()
            merged_display = next(
                (display for first, second_prefix, display in bigrams
                 if low == first and low2.startswith(second_prefix)),
                None,
            )
            if merged_display is not None:
                out.append({**w, "text": f"{head}{merged_display}{tail2}",
                           "end": w_next.get("end")})
                i += 2
                continue

        display = _match_single(low)
        if display is not None:
            out.append({**w, "text": f"{head}{display}{tail}"})
        else:
            out.append(w)
        i += 1

    return out


def make_whoosh(out_wav: Path) -> Path:
    """Сгенерировать whoosh-ассет (~0.25с): розовый шум 200-6000 Гц + fade.
    Детерминированный ffmpeg-рендер; в конвейере только читается."""
    out_wav = Path(out_wav)
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    dur = 0.25
    af = ("highpass=f=200,lowpass=f=6000,"
          "afade=t=in:st=0:d=0.05,afade=t=out:st=0.15:d=0.10,volume=2.0")
    run([FFMPEG, "-y", "-f", "lavfi", "-i", f"anoisesrc=d={dur}:c=pink:a=0.6",
         "-af", af, "-ar", "48000", "-ac", "2", str(out_wav)])
    return out_wav


def ensure_whoosh(path=None) -> Path:
    """Вернуть путь к whoosh-ассету, сгенерировав его при отсутствии."""
    path = Path(path) if path else WHOOSH_WAV
    if not path.exists():
        make_whoosh(path)
    return path


def _pause_after(block: dict) -> float:
    """Пауза-заморозка после блока (сек): поле pause_after, либо HOOK_PAUSE_S у
    хука по умолчанию, иначе 0."""
    if "pause_after" in block:
        return max(0.0, min(1.0, float(block["pause_after"])))
    if block.get("role") == "hook":
        return HOOK_PAUSE_S
    return 0.0


def retime_scenario(scenario: dict, frag_durs: list) -> dict:
    """Копия сценария с ФАКТИЧЕСКОЙ шкалой времени (реальные длительности фрагментов).

    Номинальная сетка сценария — только скелет для LLM. Идём по блокам по порядку:
    start блока = накопленная сумма; длительность = frag_durs[i] + pause_after.
    Пересчитываем "total". frag_durs — список по всем блокам (длительность
    аватар-фрагмента для split или TTS-wav для fullscreen)."""
    sc = copy.deepcopy(scenario)
    blocks = sc["blocks"]
    cursor = 0.0
    for i, b in enumerate(blocks):
        frag = float(frag_durs[i])
        pause = _pause_after(b)
        b["start"] = cursor
        b["end"] = cursor + frag + pause
        cursor = b["end"]
    sc["total"] = cursor
    return sc


def build_concat_filter(n: int, holds: list) -> str:
    """filter_complex для конката аватар-фрагментов (split) с нормализацией к
    1080x672/FPS (scale+crop, чтобы фото/видео другого соотношения не
    растягивалось). Хвост фрагмента продлевается заморозкой последнего кадра
    на holds[i] секунд (видео tpad=stop_mode=clone, аудио apad) — на паузу
    после блока. holds — список по всем фрагментам."""
    parts, maps = [], []
    for i in range(n):
        vchain = (f"[{i}:v]scale={OUT_W}:{TOP_H}:force_original_aspect_ratio=increase,"
                  f"crop={OUT_W}:{TOP_H},fps={FPS},setsar=1")
        achain = f"[{i}:a]aresample=48000"
        hold = float(holds[i]) if i < len(holds) else 0.0
        if hold > 0:
            vchain += f",tpad=stop_mode=clone:stop_duration={hold:.3f}"
            achain += f",apad=pad_dur={hold:.3f}"
        parts.append(f"{vchain}[v{i}]")
        parts.append(f"{achain}[a{i}]")
        maps.append(f"[v{i}][a{i}]")
    return ";".join(parts) + ";" + "".join(maps) + f"concat=n={n}:v=1:a=1[v][a]"


def build_voice_concat_filter(n: int, holds: list) -> str:
    """filter_complex для конката TTS-wav'ов (fullscreen) в единую голосовую
    дорожку: каждый wav + apad-тишина на паузу после блока (holds[i]) -> concat."""
    parts, maps = [], []
    for i in range(n):
        achain = f"[{i}:a]aresample=48000"
        hold = float(holds[i]) if i < len(holds) else 0.0
        if hold > 0:
            achain += f",apad=pad_dur={hold:.3f}"
        parts.append(f"{achain}[a{i}]")
        maps.append(f"[a{i}]")
    return ";".join(parts) + ";" + "".join(maps) + f"concat=n={n}:v=0:a=1[a]"


def _slow_src_dur(screen_dur: float, slow: dict) -> float:
    """Сколько СЕКУНД ИСХОДНИКА покрывает блок экранной длительности screen_dur с
    эффектом slow. Замедленный кусок занимает slow["dur"] экранного времени, но
    берёт из исходника только dur/factor; остальное 1:1."""
    d = float(slow["dur"])
    f = float(slow["factor"])
    return screen_dur - d + d / f


def plan_broll_cuts(timed_scenario: dict, segments: list, src_dur: float) -> list:
    """Список отрезков-словарей исходника видеоряда — по одному на каждый блок
    ретаймленного сценария. segments=[{"role","offset","slow"?},...]: у блока,
    чья роль есть в segments, отрезок начинается с её offset; у ролей без записи
    — продолжение предыдущего отрезка (курсор = конец предыдущего по ИСХОДНОМУ
    времени). slow={"at","dur","factor"} — под-кусок [at, at+dur] экранного
    времени замедляется в factor раз (отрезок исходника короче, см. _slow_src_dur).
    Гард: отрезок не должен вылезать за конец исходника — RuntimeError с ролью.

    Каждый элемент: {"start","src_dur","screen_dur","slow"}."""
    seg_by_role = {s["role"]: s for s in segments}
    cuts = []
    cursor = None
    for b in timed_scenario["blocks"]:
        role = b.get("role")
        screen = float(b["end"]) - float(b["start"])
        seg = seg_by_role.get(role)
        if seg is not None:
            start = float(seg["offset"])
        elif cursor is not None:
            start = cursor
        else:
            raise RuntimeError(
                f"нет offset для роли {role!r} в broll-плане и нет предыдущего "
                "отрезка для продолжения")
        slow = seg.get("slow") if seg else None
        src = _slow_src_dur(screen, slow) if slow else screen
        if start + src > src_dur:
            raise RuntimeError(
                f"отрезок видеоряда для роли {role!r} выходит за конец исходника: "
                f"{start:.2f}+{src:.2f}с > {src_dur:.2f}с")
        cuts.append({"start": start, "src_dur": src, "screen_dur": screen, "slow": slow})
        cursor = start + src
    return cuts


def _atempo_chain(tempo: float) -> str:
    """Каскад atempo для скоростей вне диапазона [0.5, 100]. Произведение всех
    множителей в цепи равно исходному tempo (0.25 -> atempo=0.5,atempo=0.5)."""
    if tempo >= 0.5:
        return f"atempo={tempo:.3f}"

    chain = []
    remaining = tempo
    while remaining < 0.5:
        chain.append("atempo=0.5")
        remaining *= 2
    chain.append(f"atempo={remaining:.3f}")
    return ",".join(chain)


def build_broll_concat_filter(cuts: list) -> str:
    """filter_complex конката отрезков видеоряда (чистая функция, без ffmpeg).

    По одному входу на отрезок. Обычный отрезок — fps/aresample. Отрезок со
    slow={"at","dur","factor"} режется по исходному времени на три части (норма |
    замедление setpts*factor / atempo(1/factor) | норма) и склеивается concat'ом
    внутри себя. Итог — общий concat всех [v{i}][a{i}] -> [v][a]."""
    n = len(cuts)
    parts, maps = [], []
    for i, c in enumerate(cuts):
        slow = c.get("slow")
        if slow:
            at = float(slow["at"])
            f = float(slow["factor"])
            src_slow_end = at + float(slow["dur"]) / f
            parts.append(f"[{i}:v]fps={FPS},setsar=1,split=3[gv{i}a][gv{i}b][gv{i}c]")
            parts.append(f"[gv{i}a]trim=0:{at:.3f},setpts=PTS-STARTPTS[pv{i}a]")
            parts.append(f"[gv{i}b]trim={at:.3f}:{src_slow_end:.3f},"
                         f"setpts={f:.3f}*(PTS-STARTPTS)[pv{i}b]")
            parts.append(f"[gv{i}c]trim={src_slow_end:.3f},setpts=PTS-STARTPTS[pv{i}c]")
            parts.append(f"[pv{i}a][pv{i}b][pv{i}c]concat=n=3:v=1:a=0[v{i}]")
            parts.append(f"[{i}:a]aresample=48000,asplit=3[ga{i}a][ga{i}b][ga{i}c]")
            parts.append(f"[ga{i}a]atrim=0:{at:.3f},asetpts=PTS-STARTPTS[pa{i}a]")
            tempo_val = 1.0 / f
            atempo_filt = _atempo_chain(tempo_val)
            parts.append(f"[ga{i}b]atrim={at:.3f}:{src_slow_end:.3f},asetpts=PTS-STARTPTS,"
                         f"{atempo_filt}[pa{i}b]")
            parts.append(f"[ga{i}c]atrim={src_slow_end:.3f},asetpts=PTS-STARTPTS[pa{i}c]")
            parts.append(f"[pa{i}a][pa{i}b][pa{i}c]concat=n=3:v=0:a=1[a{i}]")
        else:
            parts.append(f"[{i}:v]fps={FPS},setsar=1[v{i}]")
            parts.append(f"[{i}:a]aresample=48000[a{i}]")
        maps.append(f"[v{i}][a{i}]")
    return ";".join(parts) + ";" + "".join(maps) + f"concat=n={n}:v=1:a=1[v][a]"


def _concat_broll(rdir: Path, broll_mp4: Path, cuts: list) -> Path:
    """Конкат отрезков видеоряда (видео+звук) в один клип по cuts. Результат —
    низовой слой полной длительности T с offset=0 для дальнейшего конвейера."""
    out = rdir / "broll_cut.mp4"
    cmd = [FFMPEG, "-y"]
    for c in cuts:
        cmd += ["-ss", f"{c['start']}", "-t", f"{c['src_dur']}", "-i", str(broll_mp4)]
    fc = build_broll_concat_filter(cuts)
    cmd += ["-filter_complex", fc, "-map", "[v]", "-map", "[a]", *VENC, *AENC, str(out)]
    run(cmd)
    return out


def build_punch_filter(in_label: str, punch_windows: list) -> tuple:
    """Ветка панч-инов (чистая функция). На каждом окне (start,dur) — лёгкий
    наезд PUNCH_ZOOM: split -> crop(iw/zoom,ih/zoom)+scale обратно -> overlay с
    enable на окно. Возвращает (список filter-частей, метка выхода)."""
    parts = []
    cur = in_label
    for i, (s, d) in enumerate(punch_windows):
        s, d = float(s), float(d)
        parts.append(f"[{cur}]split=2[pb{i}][pz{i}]")
        parts.append(f"[pz{i}]crop=iw/{PUNCH_ZOOM}:ih/{PUNCH_ZOOM},"
                     f"scale={OUT_W}:{OUT_H},setsar=1[pzs{i}]")
        parts.append(f"[pb{i}][pzs{i}]overlay=0:0:"
                     f"enable='between(t,{s},{s + d})'[pw{i}]")
        cur = f"pw{i}"
    return parts, cur


def build_video_filter(fmt: str, punch_windows: list | None = None) -> str:
    """Видео-часть filter_complex.

    split: [0:v]=аватар-верх (scale/crop 1080x672) + [1:v]=видеоряд (scale/crop
    1080x1248) -> vstack -> [base]. fullscreen: [0:v]=видеоряд (scale/crop
    1080x1920) -> [base]. Затем (опц.) панч-ины. Выход [v]."""
    if fmt == "split":
        parts = [
            f"[0:v]scale={OUT_W}:{TOP_H}:force_original_aspect_ratio=increase,"
            f"crop={OUT_W}:{TOP_H},setsar=1[top]",
            f"[1:v]scale={OUT_W}:{BOT_H}:force_original_aspect_ratio=increase,"
            f"crop={OUT_W}:{BOT_H},setsar=1,fps={FPS}[bot]",
            "[top][bot]vstack=inputs=2[base]",
        ]
    else:  # fullscreen
        parts = [
            f"[0:v]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,"
            f"crop={OUT_W}:{OUT_H},setsar=1,fps={FPS}[base]",
        ]
    cur = "base"
    if punch_windows:
        punch_parts, cur = build_punch_filter(cur, punch_windows)
        parts.extend(punch_parts)
    parts.append(f"[{cur}]null[v]")
    return ";".join(parts)


def build_audio_filter(include_game: bool, whoosh_delays_ms: list | None = None) -> str:
    """Аудио-часть filter_complex (чистая функция, без ffmpeg).

    include_game=False (voice.wav, для субтитров): только голос [0:a] -> [mix].

    include_game=True (mix.wav, в ролик): [0:a]=голос, [1:a]=видеоряд, затем
    whoosh-wav'ы. Видеоряд — ПОСТОЯННЫЙ слой volume=BROLL_VOLUME (без дакинга);
    whoosh'и volume=WHOOSH_VOLUME на переходах. ОДИН amix, в конце alimiter=
    limit=0.95 от клиппинга -> [mix]."""
    if not include_game:
        return "[0:a]aresample=48000[mix]"

    whoosh_delays_ms = whoosh_delays_ms or []
    parts = ["[0:a]aresample=48000[a0]"]
    labels = ["[a0]"]
    idx = 2  # [1:a] — видеоряд
    for j, ms in enumerate(whoosh_delays_ms):
        parts.append(f"[{idx}:a]volume={WHOOSH_VOLUME},adelay={ms}:all=1,aresample=48000[w{j}]")
        labels.append(f"[w{j}]")
        idx += 1
    parts.append(f"[1:a]volume={BROLL_VOLUME},aresample=48000[bed]")
    labels.append("[bed]")
    parts.append("".join(labels) + f"amix=inputs={len(labels)}:normalize=0[mixraw]")
    parts.append("[mixraw]alimiter=limit=0.95[mix]")
    return ";".join(parts)


def _concat_avatars(rdir: Path, avatar_mp4s: list, holds: list) -> Path:
    """Склейка аватар-фрагментов (split) concat-фильтром -> top.mp4 (видео+голос)."""
    top = rdir / "top.mp4"
    n = len(avatar_mp4s)
    fc = build_concat_filter(n, holds)
    cmd = [FFMPEG, "-y"]
    for a in avatar_mp4s:
        cmd += ["-i", str(a)]
    cmd += ["-filter_complex", fc, "-map", "[v]", "-map", "[a]", *VENC, *AENC, str(top)]
    run(cmd)
    return top


def _concat_voice(rdir: Path, voice_wavs: list, holds: list) -> Path:
    """Склейка TTS-wav'ов (fullscreen) в единую голосовую дорожку voice_track.wav."""
    out = rdir / "voice_track.wav"
    n = len(voice_wavs)
    fc = build_voice_concat_filter(n, holds)
    cmd = [FFMPEG, "-y"]
    for w in voice_wavs:
        cmd += ["-i", str(w)]
    cmd += ["-filter_complex", fc, "-map", "[a]", "-ar", "48000", "-ac", "2", str(out)]
    run(cmd)
    return out


def _build_video(rdir: Path, fmt: str, top: Path | None, broll: Path, offset: float,
                 T: float, punch_windows: list | None = None) -> Path:
    """Немой видеослой 1080x1920 (split vstack | fullscreen broll + панч-ины)."""
    stacked = rdir / "stacked.mp4"
    fc = build_video_filter(fmt, punch_windows)
    cmd = [FFMPEG, "-y"]
    if fmt == "split":
        cmd += ["-i", str(top)]  # [0:v] = аватар-верх
    cmd += ["-ss", f"{offset}", "-t", f"{T}", "-i", str(broll)]  # видеоряд
    cmd += ["-filter_complex", fc, "-map", "[v]", *VENC, "-an", "-t", f"{T}", str(stacked)]
    run(cmd)
    return stacked


def _mix_audio(rdir: Path, voice_src: Path, broll: Path, offset: float, T: float,
               out_wav: Path, include_game: bool,
               whoosh_at: list | None = None, whoosh_wav: Path | None = None) -> Path:
    """Микс: голос блогерши + (опц.) постоянный слой видеоряда и whoosh'и
    (см. build_audio_filter). Порядок входов — голос, (опц.) видеоряд, whoosh-wav'ы."""
    whoosh_at = whoosh_at or []
    cmd = [FFMPEG, "-y", "-i", str(voice_src)]
    if include_game:
        cmd += ["-ss", f"{offset}", "-t", f"{T}", "-i", str(broll)]
    whoosh_ms = []
    if include_game and whoosh_wav is not None:
        for t in whoosh_at:
            cmd += ["-i", str(whoosh_wav)]
            whoosh_ms.append(int(round(float(t) * 1000)))

    fc = build_audio_filter(include_game, whoosh_ms)
    cmd += ["-filter_complex", fc, "-map", "[mix]", "-ar", "48000", "-ac", "2", str(out_wav)]
    run(cmd)
    return out_wav


def _default_transcribe(voice_wav: Path, rdir: Path) -> list:
    transcribe_file(str(voice_wav), str(rdir), model_size="small", language="ru")
    return load_words_file(str(rdir / "words.json"))


def assemble(rdir, scenario: dict, broll_mp4, broll_offset_s: float, out_mp4, *,
             format: str = "split", avatar_mp4s: list | None = None,
             voice_wavs: list | None = None, transcribe_fn=None,
             broll_segments: list | None = None, punch_windows: list | None = None,
             whoosh_at: list | None = None, caption_fixes: dict | None = None) -> dict:
    """Полный конвейер сборки рилса. Возвращает {"mp4","dur","lufs",
    "timed_scenario","words_fixed"}; пишет scenario.timed.json и words.fixed.json.

    format="split" требует avatar_mp4s (по одному на блок, голос вшит).
    format="fullscreen" требует voice_wavs (TTS по одному на блок).

    broll_segments — мультисегментный низ (plan_broll_cuts), иначе один offset.
    caption_fixes — карта apply_caption_fixes (см. build_caption_fixes); None ->
    дефолт (без бренда/темы). transcribe_fn(voice_wav, rdir)->words — DI для тестов.
    """
    rdir = Path(rdir)
    rdir.mkdir(parents=True, exist_ok=True)
    out_mp4 = Path(out_mp4)
    broll_mp4 = Path(broll_mp4)
    transcribe_fn = transcribe_fn or _default_transcribe

    blocks = scenario["blocks"]
    if format == "split":
        if not avatar_mp4s:
            raise RuntimeError("format=split требует avatar_mp4s (аватар на каждый блок)")
        frag_srcs = avatar_mp4s
    elif format == "fullscreen":
        if not voice_wavs:
            raise RuntimeError("format=fullscreen требует voice_wavs (TTS на каждый блок)")
        frag_srcs = voice_wavs
    else:
        raise RuntimeError(f"неизвестный format: {format!r} (нужно split|fullscreen)")
    if len(frag_srcs) != len(blocks):
        raise RuntimeError(
            f"число фрагментов ({len(frag_srcs)}) != числу блоков ({len(blocks)})")

    # 0) ретайминг под фактические длительности
    frag_durs = [media_dur(str(a)) for a in frag_srcs]
    timed = retime_scenario(scenario, frag_durs)
    (rdir / "scenario.timed.json").write_text(
        json.dumps(timed, ensure_ascii=False, indent=1), encoding="utf-8")
    T = timed["total"]

    # видеоряд: один offset на весь ролик либо мультисегментный план
    broll_dur = media_dur(str(broll_mp4))
    if broll_segments is None:
        if broll_dur - broll_offset_s < T:
            raise RuntimeError(
                f"видеоряд короче offset+T: {broll_dur:.2f}с - offset {broll_offset_s:.2f}с "
                f"< нужных {T:.2f}с (увеличь длину записи или уменьши offset)")
        bottom_mp4, bottom_offset = broll_mp4, broll_offset_s
    else:
        cuts = plan_broll_cuts(timed, broll_segments, broll_dur)
        bottom_mp4 = _concat_broll(rdir, broll_mp4, cuts)
        bottom_offset = 0.0

    holds = [_pause_after(b) for b in timed["blocks"]]

    # голосовой источник: split -> top(видео+голос), fullscreen -> voice_track(звук)
    if format == "split":
        voice_src = _concat_avatars(rdir, avatar_mp4s, holds)
        top_for_video = voice_src
    else:
        voice_src = _concat_voice(rdir, voice_wavs, holds)
        top_for_video = None

    # свуши на переходах: по умолчанию — границы блоков (кроме нулевой) + панчи
    whoosh_wav = ensure_whoosh()
    if not whoosh_wav.exists():
        whoosh_wav = None
    if whoosh_at is None:
        pts = [float(b["start"]) for b in timed["blocks"][1:]]
        if punch_windows:
            pts += [float(s) for s, _ in punch_windows]
        whoosh_at = sorted(set(pts))

    # 1) немой видеослой
    stacked = _build_video(rdir, format, top_for_video, bottom_mp4, bottom_offset, T,
                           punch_windows)

    # 2) аудио: полный микс (в ролик) и голос (на субтитры)
    mix_wav = _mix_audio(rdir, voice_src, bottom_mp4, bottom_offset, T,
                         rdir / "mix.wav", include_game=True,
                         whoosh_at=whoosh_at, whoosh_wav=whoosh_wav)
    voice_wav = _mix_audio(rdir, voice_src, bottom_mp4, bottom_offset, T,
                           rdir / "voice.wav", include_game=False)

    # 3) субтитры: распознать голос -> ass -> прожечь
    fixes = caption_fixes if caption_fixes is not None else build_caption_fixes({})
    words = transcribe_fn(voice_wav, rdir)
    words = apply_caption_fixes(words, fixes)
    (rdir / "words.fixed.json").write_text(
        json.dumps(words, ensure_ascii=False, indent=1), encoding="utf-8")
    build_ass(words, str(rdir / "caps.ass"), font=CAPTION_FONT,
              play_w=OUT_W, play_h=OUT_H, pos=(540, 1500))
    subbed = rdir / "subbed.mp4"
    run([FFMPEG, "-y", "-i", str(stacked), "-i", str(mix_wav),
         "-vf", "ass=caps.ass", "-map", "0:v", "-map", "1:a",
         "-c:v", "libx264", "-crf", "19", "-preset", "medium", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "160k", "-shortest", str(subbed)], cwd=str(rdir))

    # 4) громкость: двухпроходный loudnorm (замер -> применение)
    ln = f"loudnorm=I={LUFS_TARGET}:TP={TP_TARGET}:LRA=11"
    measured = parse_loudnorm_json(
        run([FFMPEG, "-i", str(subbed), "-af", ln + ":print_format=json", "-f", "null", "-"]))
    if measured:
        ln += (f":measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
               f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
               f":offset={measured['target_offset']}:linear=true")
    run([FFMPEG, "-y", "-i", str(subbed), "-af", ln,
         "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", str(out_mp4)])

    # измерить фактическую громкость итога
    meas2 = parse_loudnorm_json(
        run([FFMPEG, "-i", str(out_mp4), "-af",
             f"loudnorm=I={LUFS_TARGET}:TP={TP_TARGET}:LRA=11:print_format=json",
             "-f", "null", "-"]))
    lufs = meas2["input_i"] if meas2 else None
    return {"mp4": str(out_mp4), "dur": media_dur(str(out_mp4)), "lufs": lufs,
            "timed_scenario": timed, "words_fixed": words}
