"""Сборка ролика движком HyperFrames, разбитая на возобновляемые шаги.

Длинная агентская сессия может оборваться посреди работы — это наблюдалось.
Каждый шаг пишет файл-маркер, повторный запуск подхватывает с места обрыва.

Шаг громкости пишет НОВЫЙ файл, а не заменяет исходный: иначе обрыв между
заменой и записью маркера привёл бы к повторной нормализации.
"""
from __future__ import annotations

import functools
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from types import CodeType

from reels_factory import hf_captions
from reels_factory.compose import VENC
from reels_factory.config import (
    FFMPEG, FPS, LUFS_TARGET, MAX_DELIVERY_BYTES, OUT_H, OUT_W, TP_TARGET,
    cli_env,
)
from reels_factory.editplan import MAX_FACE_ABSENCE_S, MIN_FULLSCREEN_S
from reels_factory.face_detect import face_box_for, load_face
from reels_factory.hf_agent import (
    AgentPlanMissing, AgentSpend, HeyGenAgentRunner, plan_with_agent,
)
from reels_factory.hf_assets import vendor_gsap
from reels_factory.hf_brief import POSITIONS, write_brief
from reels_factory.hf_catalog import serve_catalog, write_project_config
from reels_factory.hf_compose import (
    CAPTION_BAND_TOP, build_composition, clear_generated, collect_intents,
    complete_storyboard, icon_intents, needed_blocks, schema_intents,
    settle_fillers, settle_inserts,
)
from reels_factory.hf_fonts import inject_fonts
from reels_factory.hf_frame import read_frame
from reels_factory.hf_gates import (
    check_media, check_placeholders, check_storyboard, elements_delivered,
    elements_problems, frame_filled_problems,
)
from reels_factory.hf_layout import FULL_FRAME_PRESENTER, quantize
from reels_factory.hf_media import resolve_all
from reels_factory.hf_montage import (
    check_inserts, check_shots, dedupe_neighbours, drop_series,
    inserts_shortfall, inserts_wanted,
    merge_adjacent_series, ordered_gaps, pick_position, pick_series,
    settle_schemas,
    show_ordered_avatar,
)
from reels_factory.hf_montage_skill import SKILL_NAME, seconds
from reels_factory.hf_phrases import (
    lay_out_scenes, phrase_timeline, speech_between,
)
from reels_factory.hf_probe import probe_gates
from reels_factory.hf_rhythm import rhythm_gates
from reels_factory.hf_sdk import sdk_session
from reels_factory.hf_zoom import read_camera, zoom_gates
from reels_factory.hyperframes_blocks import _HF_VERSION
from reels_factory.render import media_dur

#: Качество финального рендера остаётся прежним. Черновой прогон включается
#: переменной окружения — на нём проверяют монтаж, а не картинку.
RENDER_QUALITY = os.environ.get("REELS_RENDER_QUALITY", "standard")

#: Рабочих у рендера. Их `auto` считает потолок по ядрам, памяти и размеру
#: кадра (`render.ts:1411-1419`) и на нашей машине (12 ядер, 7 ГБ) выбирает
#: слишком осторожно: 4 м 48 с даже на черновом качестве против 4 м 03 с на
#: чистовом в восемь рабочих. Число переопределяется переменной окружения —
#: на сервере ядер и памяти другое количество.
RENDER_WORKERS = os.environ.get("REELS_RENDER_WORKERS", "8")

#: Безопасный профиль рендера. Их рендер включает его сам, когда памяти машины
#: 8 ГБ или меньше (`render.ts:317-324`), и тогда захват кадра идёт скриншотом:
#: в прогоне 26 при восьми рабочих `captureMode: "screenshot"` и 319 с из 363 с
#: ушли ровно на захват. Мы его выключаем: 12 ядер тянут параллельный захват, а
#: памяти рабочему нужно порядка 256 МБ (`rendering.mdx:209`). Значения:
#: `off` — выключить (по умолчанию), `on` — включить, `auto` — отдать им.
RENDER_LOW_MEMORY = os.environ.get("REELS_RENDER_LOW_MEMORY", "off")

STEPS = ("prepare", "plan", "compose", "gates", "shots", "render", "loudness")
MAX_COMPOSE_ATTEMPTS = 2

#: Сколько раз агента спрашивают ДО заказа аватара: план и одна пересдача.
#: Заказ у HeyGen платный и необратимый, поэтому промах проверок плана стоит
#: одного переспроса. Второй промах уходит в отчёт по сборке, а не отклоняет
#: прогон: план всё равно лучше, чем ничего, а разбирать его будет человек.
MAX_PLAN_ATTEMPTS = 2

#: Маркер шага «план сделан до заказа аватара». В STEPS его нет намеренно: это
#: не отдельный шаг сборки, а память о том, ЧЕЙ план лежит в `plan.json`.
#: Аватар уже куплен ровно по нему, и пересдавать его после покупки нельзя.
EARLY_PLAN_STEP = "plan-early"

#: До скольких сцен контактный лист снимает ещё и пару кадров вокруг каждой
#: склейки. Выше — только середины: съёмка идёт по кадру за раз, и при видео в
#: композиции каждый кадр тянет за собой отдельный вызов ffmpeg.
SNAPSHOT_SEAM_LIMIT = 10

# Ключевой кадр на каждый кадр. Их рендерер перематывает видео покадрово, и на
# редком GOP (по умолчанию у x264 — 250 кадров) перемотка попадает мимо: под
# графикой встаёт замерший кадр. Требование их же скила —
# talking-head-recut/SKILL.md:789-794.
DENSE_GOP = ("-g", str(FPS), "-keyint_min", str(FPS))


def _marker(rdir: Path, step: str) -> Path:
    return Path(rdir) / f".hf-{step}.done"


def step_done(rdir, step: str) -> bool:
    return _marker(Path(rdir), step).exists()


def reset_step(rdir, step: str) -> None:
    _marker(Path(rdir), step).unlink(missing_ok=True)


#: Шаги, которые снимает пересборка монтажа. Это ровно та часть прогона, что
#: ничего не заказывает у подрядчиков: разметка, гейты, контактный лист, рендер
#: и громкость считаются на нашей машине из уже оплаченного материала.
MONTAGE_STEPS = ("compose", "gates", "shots", "render", "loudness")


def reset_montage_steps(rdir) -> None:
    """Снять маркеры монтажа, чтобы ролик пересобрался на той же папке.

    Нужно, когда сборка дошла до файла, но не прошла проверки качества: чинится
    это пересборкой монтажа, а не новым роликом.

    `prepare`, `plan` и `plan-early` не трогаем намеренно:

    * `prepare` держит снятые сайты и подобранные материалы — работа сделана и
      второй раз она только потратит время;
    * `plan-early` помечает план, ПО КОТОРОМУ УЖЕ КУПЛЕНА ведущая у HeyGen.
      Сняв его, `render_hyperframes` спросит агента заново (около 936), новый
      план разойдётся с заказанными клипами, и человек заплатит за ведущую
      второй раз;
    * `plan` — тот же `plan.json`, что и у `plan-early`, только на прогонах без
      раннего плана.

    Сам заказ ведущей маркерами не держится вовсе: его замораживают файлы
    папки — `avatar_render_plan.json`, `avatar_render_manifest.json`,
    `edit_plan.json` и снятые клипы (условия годности в
    `avatar_islands.load_frozen_avatar_order`). Пересборка монтажа их не
    трогает, поэтому ведущую не перезаказывает.

    Папка может быть и вовсе без маркеров (сборка упала до первого шага):
    падать тут нельзя — функцию зовут перед возвратом job в очередь, и её
    исключение оставило бы человека без продолжения.
    """
    for step in MONTAGE_STEPS:
        reset_step(rdir, step)


#: Чем прогон не прошёл проверки. Ритм и наезды меряются по ГОТОВОМУ файлу, то
#: есть уже за циклом попыток: внутри прогона агент про этот отказ не узнаёт
#: никогда, а продолжение зовёт сборку заново — и без записи в папке она
#: получила бы то же задание, тот же план и тот же отказ за деньги человека.
#: Папка job — единственное, что прогон переживает.
RETRY_REASON_FILE = "retry_reason.txt"


def save_retry_reason(rdir, reason: str | None) -> None:
    """Запомнить причину провала проверок рядом со сборкой (или забыть её)."""
    path = Path(rdir) / RETRY_REASON_FILE
    if reason:
        path.write_text(reason, encoding="utf-8")
    else:
        path.unlink(missing_ok=True)


#: Имя гейта: «D», номер и слово. Одно и то же и в отчёте, и в причине.
GATE_NAME = re.compile(r"D\d+_[a-z_]+")

#: Начало куска причины: имя гейта после начала строки или разделителя. Сам
#: вердикт внутри куска тоже склеен через «; », поэтому резать причину простым
#: split нельзя — куски рвались бы посреди перечисления виноватых сцен.
_REASON_PIECE = re.compile(r"(?:^|;\s+)(D\d+_[a-z_]+): ")


@functools.lru_cache(maxsize=1)
def known_gate_names() -> frozenset[str]:
    """Имена гейтов, которые НЫНЕШНИЙ код умеет выставлять.

    Спрашиваем у самого кода, а не у списка рядом: список — второе место, где
    имя надо править на каждое снятие гейта, и протух бы он ровно так же, как
    причина в папке задания.

    Читаем строковые константы скомпилированных модулей движка. Ключ словаря
    гейтов всегда лежит в коде отдельной строкой (`result["D34_inserts"]`,
    `{"D26_frame_content": …}`), а упоминание гейта в комментарии в константы
    не попадает вовсе; упоминание в docstring или в тексте отказа — часть
    длинной строки и на равенство имени не встаёт. Снятый `D26_flash` в коде
    так и остался — комментарием в `hf_compose.py` и строкой docstring в
    `hf_zoom.py`, — и сюда он не попадает.

    Спускаемся и по вложенным константам: словарь, все ключи которого —
    строки, компилятор складывает одним кортежем, и без этого шага гейты,
    написанные словарём (`D15_inserts_visible`, `D25_empty_frame`), считались
    бы несуществующими, а живая причина — протухшей.
    """
    names: set[str] = set()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        try:
            stack = [compile(path.read_text(encoding="utf-8"), str(path),
                             "exec")]
        except (OSError, SyntaxError, ValueError):
            continue
        while stack:
            value = stack.pop()
            if isinstance(value, str):
                if GATE_NAME.fullmatch(value):
                    names.add(value)
            elif isinstance(value, CodeType):
                stack.extend(value.co_consts)
            elif isinstance(value, (tuple, frozenset)):
                stack.extend(value)
    return frozenset(names)


def fresh_retry_reason(reason: str | None) -> str | None:
    """Причина пересдачи без гейтов, которых в нынешнем коде уже нет.

    Причина лежит в папке задания, а код тем временем едет: выкатка, снявшая
    гейт, оставляет по всем папкам причины с его именем. Боевой случай — папка
    с `D26_flash: FAIL: вспышка не видна…` после того, как гейт сняли
    (64ad5ae): прогон честно прочитал причину, снял маркер `plan`, переписал
    BRIEF.md разделом пересдачи и заплатил $3.48 за то, чтобы агент чинил
    проверку, которой больше нет. У живого пользователя на кнопке
    «продолжить» вышло бы то же самое.

    Причина не про гейты вовсе (например, «план не лёг на озвучку») остаётся
    как есть: имён в ней нет, судить о её свежести нечем, а молча терять её
    нельзя.
    """
    if not reason:
        return None
    pieces = list(_REASON_PIECE.finditer(reason))
    if not pieces:
        return reason
    known = known_gate_names()
    kept = []
    for index, piece in enumerate(pieces):
        end = (pieces[index + 1].start() if index + 1 < len(pieces)
               else len(reason))
        chunk = reason[piece.start(1):end].strip().rstrip(";").strip()
        if piece.group(1) in known:
            kept.append(chunk)
        else:
            print(f"причина пересдачи протухла: гейта {piece.group(1)} в коде "
                  "больше нет, чинить его агента не зову")
    return "; ".join(kept) or None


def last_retry_reason(rdir) -> str | None:
    """Причина, с которой прошлый прогон этой папки ушёл в отказ.

    Свежесть проверяется здесь, на чтении: дальше по коду причина снимает
    маркер `plan` и уезжает агенту разделом пересдачи, и место, где её ещё
    можно не взять в работу, — одно.
    """
    try:
        text = (Path(rdir) / RETRY_REASON_FILE).read_text(encoding="utf-8")
    except OSError:
        return None
    return fresh_retry_reason(text.strip() or None)


def run_step(rdir, step: str, fn):
    """Выполнить шаг, если он ещё не выполнен. Возвращает результат fn."""
    rdir = Path(rdir)
    if step_done(rdir, step):
        return None
    result = fn()
    _marker(rdir, step).write_text("ok", encoding="utf-8")
    return result


def _cli(*args: str, cwd, log: Path | None = None,
         err_log: Path | None = None) -> str:
    """Вызов CLI движка. На Windows npx резолвится только через shell.

    Кавычим КАЖДЫЙ аргумент: пути содержат пробелы, а значения флагов —
    разделители, которые cmd.exe и батник npx.cmd разберут по-своему.

    `err_log` — отдельный файл под stderr. Смешивать его с `log` нельзя:
    `check --json` читают как JSON, и строка предупреждения его ломает —
    поэтому предупреждения у них и уходят в stderr.
    """
    quoted = " ".join(f'"{a}"' for a in args)
    command = f'npx --yes hyperframes@{_HF_VERSION} {quoted}'
    result = subprocess.run(command, cwd=str(cwd), capture_output=True,
                            text=True, encoding="utf-8", errors="replace",
                            shell=True, env=cli_env())
    output = result.stdout or ""
    if log is not None:
        # Их отчёт нужен целиком и после успеха тоже: предупреждения он не
        # считает провалом, а судить монтаж по ним всё равно приходится.
        Path(log).write_text(output or (result.stderr or ""), encoding="utf-8")
    if err_log is not None:
        Path(err_log).write_text(f"{output}\n{result.stderr or ''}",
                                 encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(
            f"hyperframes {args[0]} упал ({result.returncode}): "
            f"{(result.stderr or output)[:500]}")
    return output


#: Их предупреждения рендера, после которых готовому mp4 верить нельзя. Оба
#: означают одно: какой-то `[data-composition-id]` не зарегистрировал свой
#: `window.__timelines[id]`, их ожидание истекло и `__hfForceTimelineRebind`
#: не позвался (packages/engine/src/services/frameCapture.ts:1523,1556) — а без
#: него НИ ОДИН дочерний таймлайн не вложен в корневой и не перематывается.
#: Практика прогона 23: пропал весь слой субтитров, при живых нижних слоях и
#: зелёных гейтах. Их рендер считает это предупреждением и отдаёт код 0; нам
#: это провал сборки.
RENDER_FATAL_WARNINGS = ("sub_timeline_readiness_timeout",
                         "sub_timeline_script_failure")


def _write_motion_sidecar(public: Path, board: dict, duration: float) -> None:
    """Намерение движения — их сайдкаром, а не нашей отдельной пробой.

    `check` читает `*.motion.json` рядом с композицией сам, без флага, и
    сверяет намерение с той же перемотанной шкалой, по которой идёт рендер:
    «the closest automated proxy for "render the MP4 and watch it"»
    (hyperframes-cli/references/lint-validate-inspect.md). Нам это закрывает
    два вопроса разом: вставка действительно въехала в кадр к своей секунде и
    не уехала за его край.

    Проверяем `appearsBy` — что вставка въехала в кадр к своей секунде.
    `staysInFrame` здесь не годится: наши вставки едут наездом, и их бокс
    законно выходит за канвас на десятки пикселей — прогон пересборки
    462a1c62 поймал ровно это (`motion_off_frame` на 14,61 с при вылете 30 px).

    Селектор, который ничего не нашёл, они считают провалом
    (`motion_selector_missing`), поэтому перечисляем только те вставки, что
    реально попали в разметку.
    """
    if not (public / "index.html").exists():
        return
    markup = (public / "index.html").read_text(encoding="utf-8")
    assertions = []
    for scene in board.get("scenes") or []:
        for shot in range(2):
            name = f'ins-{scene["id"]}-{shot}'
            if f'id="{name}"' not in markup:
                continue
            # Срок — конец сцены: шов между планами серии код ставит по
            # сильнейшей паузе речи, а не посередине (`split_series`), и
            # вычислять его здесь второй раз значит держать два разных
            # ответа на один вопрос. Проверка при этом делает своё: вставка,
            # которая не появилась вовсе, ловится.
            assertions.append({
                "kind": "appearsBy", "selector": f"#{name}",
                "bySec": round(float(scene.get("endSec", 0)) - 0.05, 2)})
    if not assertions:
        return
    (public / "index.motion.json").write_text(
        json.dumps({"duration": round(float(duration), 3),
                    "assertions": assertions},
                   ensure_ascii=False, indent=1),
        encoding="utf-8")


def _render_or_die(rdir: Path, raw: Path) -> None:
    """Рендер и разбор его предупреждений. Тихая деградация запрещена."""
    log = rdir / "render.log"
    safe_mode = {"off": ["--no-low-memory-mode"],
                 "on": ["--low-memory-mode"]}.get(RENDER_LOW_MEMORY, [])
    _cli("render", "public", "--output", str(raw), "--fps", str(FPS),
         "--quality", RENDER_QUALITY, "--workers", RENDER_WORKERS,
         *safe_mode, cwd=rdir, err_log=log)
    text = log.read_text(encoding="utf-8", errors="replace")
    hit = [code for code in RENDER_FATAL_WARNINGS if code in text]
    if hit:
        missing = re.findall(r"timelines not registered after \d+ms: ([^.]+)",
                             text)
        raise RuntimeError(
            "рендер отдал mp4 с неотыгранными таймлайнами "
            f"({', '.join(hit)}); без регистрации остались: "
            f"{'; '.join(missing) or 'см. render.log'}. Такой файл показывать "
            "нельзя: слой субтитров в нём мёртв")


def _normalize_words(words: list[dict]) -> list[dict]:
    """Слова к общему виду. Поля синтеза сохраняем.

    `character_start`/`character_end`/`block_index` кладёт `master_audio`
    (`alignment_to_words`), и по ним фраза находит свои слова без всякого
    угадывания. Раньше они здесь терялись, и расчёт времён не за что было
    зацепить — секунды приходилось называть агенту.
    """
    kept = ("character_start", "character_end", "block_index")
    result = []
    for word in words:
        item = {"start": round(float(word["start"]), 3),
                "end": round(float(word["end"]), 3),
                "text": str(word.get("text") or word.get("word") or "")}
        item.update({k: word[k] for k in kept if word.get(k) is not None})
        result.append(item)
    return result


#: Битрейт звука первого прохода. Из него же считается доля веса, которая
#: остаётся картинке.
_AUDIO_BITRATE = 192_000

#: Запас на заголовки контейнера и на перелёт регулятора битрейта: целимся не
#: в сам потолок, а чуть ниже.
_SIZE_HEADROOM = 0.93


def _fit_delivery_size(mp4: Path) -> Path:
    """Ужать ролик под потолок доставки, если он в него не влез.

    Картинка до сих пор шла `-c:v copy`, то есть с битрейтом рендера, и вес
    готового ролика не ограничивался ничем. Замер: 44 925 764 Б за 59,10 с —
    6,08 Мбит/с, то есть 50 МБ набегают к 69-й секунде. Верхней границы
    длительности при этом нет ни у сценария, ни у пути «дословно»
    (`split_verbatim` в scenario.py берёт любой текст), и дальше полностью
    оплаченный ролик становится невыдаваемым: Telegram его не берёт, а
    пересборка веса не меняет — кнопки продолжения на этой стадии нет вовсе
    (`delivery_too_big` в bot.py).

    Второй проход идёт ТОЛЬКО когда файл в потолок не влез: обычный ролик
    уезжает зрителю ровно тем же файлом, что и раньше. Звук копируется —
    он уже выровнен первым проходом, и второе сжатие ему ни к чему.
    """
    if mp4.stat().st_size <= MAX_DELIVERY_BYTES:
        return mp4
    duration = media_dur(str(mp4))
    # Нижняя граница — против ролика такой длины, на котором честная доля уже
    # отрицательна: считать битрейт по ней бессмысленно, а такой вес всё равно
    # поймает проверка на доставке.
    video_bitrate = max(300_000, int(
        MAX_DELIVERY_BYTES * 8 * _SIZE_HEADROOM / duration) - _AUDIO_BITRATE)
    fitted = mp4.with_name(mp4.name + ".fit.mp4")
    subprocess.run(
        [FFMPEG, "-y", "-i", str(mp4),
         "-c:v", "libx264", "-preset", "medium", "-pix_fmt", "yuv420p",
         "-b:v", str(video_bitrate), "-maxrate", str(video_bitrate),
         "-bufsize", str(video_bitrate * 2),
         "-c:a", "copy", "-movflags", "+faststart", str(fitted)],
        check=True, capture_output=True)
    os.replace(fitted, mp4)
    return mp4


def _normalize_loudness(src: Path, dst: Path) -> Path:
    subprocess.run(
        [FFMPEG, "-y", "-i", str(src),
         "-af", f"loudnorm=I={LUFS_TARGET}:TP={TP_TARGET}:LRA=11",
         "-c:v", "copy", "-c:a", "aac", "-b:a", f"{_AUDIO_BITRATE // 1000}k",
         "-movflags", "+faststart", str(dst)],
        check=True, capture_output=True)
    return _fit_delivery_size(dst)


def _place_clips(public: Path, avatar_mp4s: list, avatar_render_plan: dict | None,
                 timed_scenario: dict) -> list[dict]:
    """Разложить клипы аватара в public/clips и вернуть их расписание.

    Склеивать их своим ffmpeg не нужно: движок сам ставит несколько кусков на
    одну дорожку с точным началом, длительностью и обрезкой. Раньше склейка
    была нужна старой сцене, которой требовался один готовый файл.
    """
    target = public / "clips"
    target.mkdir(parents=True, exist_ok=True)

    if avatar_render_plan is not None:
        shots = avatar_render_plan.get("shots") or []
        timings = [(float(s["visible_timing"]["start"]),
                    float(s["visible_timing"]["end"]),
                    float((s.get("trim") or {}).get("start_seconds", 0.0)))
                   for s in shots]
    else:
        timings = [(float(b["start"]), float(b["end"]), 0.0)
                   for b in timed_scenario["blocks"]]

    if not avatar_mp4s:
        raise RuntimeError("нет ни одного клипа аватара")
    if len(timings) != len(avatar_mp4s):
        raise RuntimeError(
            f"клипов {len(avatar_mp4s)}, а мест на таймлайне {len(timings)}")

    clips = []
    for index, (source, (start, end, media_start)) in enumerate(
            zip(avatar_mp4s, timings)):
        name = f"clip-{index:02d}.mp4"
        duration = round(quantize(end) - quantize(start), 3)
        # HeyGen отдаёт клип на несколько кадров короче или длиннее заказанного,
        # поэтому каждый кусок подгоняется под длительность блока: не хватает —
        # достраиваем последним кадром, лишнее режем. Заодно приводим к нашему
        # кадру и частоте. Старый рендерер делал ровно это;
        # без подгонки на каждом стыке блоков будет дыра.
        # -ss ДО -i: точная перемотка с декодированием, иначе попадём на
        # ближайший ключевой кадр. Клип режется здесь целиком, поэтому агенту
        # отматывать внутри файла уже нечего.
        subprocess.run(
            [FFMPEG, "-y", "-ss", f"{media_start:.3f}", "-i", str(source),
             "-vf", (f"scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,"
                     f"crop={OUT_W}:{OUT_H},fps={FPS},setsar=1,"
                     f"tpad=stop_mode=clone:stop_duration={duration:.3f},"
                     f"trim=duration={duration:.3f},setpts=PTS-STARTPTS"),
             "-an", *VENC, *DENSE_GOP, str(target / name)],
            check=True, capture_output=True)
        clips.append({"file": f"clips/{name}",
                      "start": quantize(start),
                      "duration": duration})
    return clips


def _report_resolve(resolved: dict, what: str) -> None:
    """Почему подбор не дал файла — поимённо, в лог.

    `resolve_all` кладёт на каждый ненайденный запрос свою причину в поле
    `error` (hf_media.py:874-889): «Pexels не дал кандидатов», «судья забраковал
    всех кандидатов», «сцену не судили», «биролл не скачался». Не читал их
    никто — вызывающие спрашивают только `file`, — и упавший прогон, где из
    десяти запросов файлы получились у трёх, разбирать было нечем.

    Печать чисто диагностическая: выбор вставок она не трогает.

    Строка НИКОГДА не начинается с `{`: бот берёт из stdout движка последнюю
    строку, которая начинается с `{` и читается как JSON, и считает её ответом
    (`bot.py:1417-1426`).
    """
    if not resolved:
        return
    lost = [(key, str(answer.get("error") or "причина не названа"))
            for key, answer in sorted(resolved.items())
            if not (isinstance(answer, dict) and answer.get("file"))]
    got = len(resolved) - len(lost)
    print(f"{what}: файлы у {got} из {len(resolved)} запросов")
    for key, reason in lost:
        print(f"{what} без файла — {key}: {reason}")


def _media_from_plan(plan: dict, public: Path) -> list[dict]:
    """Локальные файлы вставок: копируем в public/media и описываем агенту.

    Путь считает _asset_path: у библиотечных ассетов ключ path пустой всегда
    (broll_index.py:171-175 его не кладёт), а реальный файл ищется по имени
    в LIBRARY_DIR (editplan.py:665-669). Брать asset["path"] напрямую —
    значит молча остаться без всего видеоряда.
    """
    from reels_factory.editplan import _asset_path

    media = []
    for window in plan.get("windows") or []:
        asset = window.get("asset") or {}
        name = asset.get("src") or asset.get("name")
        if not name:
            continue
        # library_dir=None — _asset_path сам подставит broll_library.LIBRARY_DIR
        source = _asset_path(name, None, asset)
        if not source or not Path(source).exists():
            continue
        target = public / "media" / Path(source).name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        media.append({"file": f"media/{target.name}",
                      "window_id": window["id"],
                      "what": window.get("visual_intent") or "материал вставки"})
    return media


def _prepare_material(plan: dict, public: Path, rdir: Path) -> list[dict]:
    """Материал для окон, которым планировщик заказал снимок сайта или
    запись маршрута (editplan.py: material_for_phrase).

    Импорт внутри функции: capture_site сам импортирует hf_render._cli,
    импорт на уровне модуля дал бы кольцо.
    """
    from reels_factory import capture_site, screen_route

    cache_dir = Path.home() / ".reels-factory" / "site-cache"
    media = []
    for window in plan.get("windows") or []:
        material = window.get("material")
        if not material:
            continue
        window_id = window["id"]
        what = window.get("visual_intent") or (
            "снимок сайта" if material["kind"] == "site" else "запись маршрута")
        if material["kind"] == "site":
            result = capture_site.cached_capture(material["url"], cache_dir)
            shots = result.get("screenshots") or []
            if not shots:
                continue
            # первый кадр прокрутки — единственный, что уходит в задание как
            # материал вставки; остальные кадры и HTML агенту не нужны.
            source = Path(shots[0])
            target = public / "media" / f"{window_id}-{source.name}"
        else:
            source = screen_route.record_route(
                material["steps"], rdir / "route" / f"{window_id}.mp4")
            target = public / "media" / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        media.append({"file": f"media/{target.name}", "window_id": window_id,
                      "what": what})
    return media


#: Секции их отчёта `check`, где лежат находки. Их пять, и `ok` считается по
#: сумме ошибок и (под `--strict`) предупреждений всех пяти
#: (packages/cli/src/utils/checkPipeline.ts:1331-1344).
CHECK_SECTIONS = ("lint", "runtime", "layout", "motion", "contrast")

#: Коды правил их линтера, чьи находки не считаются причиной провала.
#:
#: `composition_self_attribute_selector` (packages/lint/src/rules/
#: core.ts:515-547 на пине 0.7.84) бьёт тревогу на СЫРОМ файле блока в
#: изоляции: "а если тот же `data-composition-id` встретится дважды
#: непереименованным". Сам фреймворк выше по пину признал это ложным
#: срабатыванием и убрал правило коммитом 83ceaeb90 ("refactor(lint): drop
#: seven rules that fire on correct compositions (#3366)", между v0.7.111
#: и v0.8.5 — после нашего пина 0.7.84, но правило уже названо ошибочным
#: их же словами: "It was also the pattern the rest of the toolchain
#: prescribes"). Для нашего пайплайна вопрос вдобавок закрыт ДО check:
#: `_stage_overlay` (hf_compose.py:585-594) переименовывает
#: `data-composition-id` каждой сцены в `{block}--{scene_id}` и тем самым
#: делает селектор уникальным по построению, независимо от того, работает
#: ли их собственный пересчёт scope в компиляторе
#: (`inlineSubCompositions.ts`/`compositionScoping.ts`). Разбор целиком —
#: scratchpad/strict-scoping-rootcause.md. Любой другой код правила
#: по-прежнему валит `--strict` в полную силу.
CHECK_IGNORED_CODES = frozenset({"composition_self_attribute_selector"})


def _check_ok(report: dict) -> bool:
    """Пересчитать вердикт `check`, не давая находкам `CHECK_IGNORED_CODES`
    участвовать в подсчёте.

    Их формула (`checkPipeline.ts:1345`): `ok = errorCount === 0 &&
    (!strict || warningCount === 0)`, посчитанная по ПЯТИ секциям сразу
    (:1331-1338). Здесь та же формула, но по находкам, отфильтрованным от
    игнорируемых кодов, а не по готовым счётчикам секций — иначе одна
    находка `composition_self_attribute_selector` рядом с любой другой
    сохранила бы провал за компанию, а не только за свою собственную.
    """
    strict = bool(report.get("strict"))
    has_error = False
    has_warning = False
    for name in CHECK_SECTIONS:
        section = report.get(name) or {}
        for item in section.get("findings") or []:
            if not isinstance(item, dict) or item.get("code") in CHECK_IGNORED_CODES:
                continue
            severity = item.get("severity")
            has_error = has_error or severity == "error"
            has_warning = has_warning or severity == "warning"
    return not has_error and (not strict or not has_warning)


def _check_findings(log: Path, *, severities=("error", "warning")) -> list[str]:
    """Находки из их отчёта `check` — чтобы они дошли до агента словами.

    Формат отчёта — `CheckReport` (packages/cli/src/utils/checkTypes.ts:260-282):
    на верхнем уровне никаких `errors`/`issues`, находки лежат в `findings`
    каждой из пяти секций.
    """
    if not log.exists():
        return []
    try:
        report = json.loads(log.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    found = []
    for name in CHECK_SECTIONS:
        section = report.get(name) or {}
        for item in section.get("findings") or []:
            if not isinstance(item, dict):
                found.append(str(item))
                continue
            if item.get("severity") not in severities:
                continue
            where = item.get("selector") or item.get("sourceFile") or ""
            found.append(f'{item.get("code", "?")} [{name}] {where}: '
                         f'{item.get("message", "")}')
    return found


def _check_verdict(log: Path) -> str:
    """Вердикт их `check` — по отчёту, но не по их полю `ok` напрямую.

    Код выхода у `check` есть: по построению это `report.ok ? 0 : 1`
    (check.ts:144 → checkPipeline.ts:1228), а на аварии — единица
    (check.ts:154). Их `ok` при этом не годится как есть: это формула
    `errorCount === 0 && (!strict || warningCount === 0)`
    (packages/cli/src/utils/checkPipeline.ts:1344), а `warningCount`
    считает и находки `CHECK_IGNORED_CODES` — вычисляем вердикт заново
    через `_check_ok`, которая ту же формулу применяет без них. Отчёт
    нужен в любом случае — из него берутся находки для агента. На 0.7.84
    через npx код выхода дважды наблюдался нулевым при «Check failed» —
    где он терялся, не выяснено.
    """
    if not log.exists():
        return "FAIL: их `check` не оставил отчёта"
    try:
        report = json.loads(log.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "FAIL: отчёт их `check` не разбирается"
    if _check_ok(report):
        return "PASS"
    found = _check_findings(log)
    return "FAIL: " + "; ".join(found[:6] or ["без находок, но ok=false"])


def _scene_midpoints(board: dict) -> list[float]:
    """Точка замера каждой сцены для их проверки.

    Обычной сцене — середина. Сцене с накладкой — момент, когда блок отыграл
    вход: середина попадает в его незавершённый твин, и аудит честно видит
    там наложение текстов (content_overlap на lt-kicker-name, прогон 23) —
    но это кадр перехода, а не кадр, который видит зритель большую часть
    сцены.

    Сдвиг закрывает только находки редкой сетки — `text_box_overflow`,
    `clipped_text`, `text_occluded`: их считают по выборкам из `--at`
    (`__hyperframesLayoutAudit`, layout-audit.browser.js:1440-1449).
    `content_overlap` он НЕ закрывает: их конвейер пересчитывает его отдельным
    проходом по плотной сетке 8 кадров в секунду на всю длительность,
    независимо от `--at` (`collectMotionOverlapSamples`,
    packages/cli/src/utils/checkPipeline.ts:437-465 на пине 0.7.84). Шаг такой
    сетки — 1/8 с, то есть 125 мс: наложение, попавшее в две её выборки,
    остаётся предупреждением (а под `--strict` это падение), и с 500 мс
    поднимается до ошибки (layoutAudit.ts:185-186,265-313). Сдвинуть точку
    замера от такого наложения нельзя — его чинят кадром, а не выборкой.
    """
    times = set()
    for scene in board.get("scenes") or []:
        start = float(scene["startSec"])
        end = float(scene["endSec"])
        if isinstance(scene.get("overlay"), dict):
            times.add(round(min(end - 0.2, start + 3.6), 3))
        else:
            times.add(round((start + end) / 2, 3))
    return sorted(times)


def _snapshot_times(board: dict, duration: float) -> list[float]:
    """Когда снимать кадры контактного листа.

    Их же рецепт: середина каждой сцены плюс пара кадров вокруг каждой склейки
    — «--at <frame-midpoints-and-each-cut-minus-0.1s-and-plus-0.2s>»
    (product-launch-video/SKILL.md:195). Съёмка последовательная, один кадр —
    один seek (packages/cli/src/commands/snapshot.ts:403), поэтому пара вокруг
    склейки берётся только тогда, когда кадров и так немного.
    """
    times = set(_scene_midpoints(board))
    if len(times) <= SNAPSHOT_SEAM_LIMIT:
        for scene in board.get("scenes") or []:
            start = float(scene["startSec"])
            if start > 0:
                times.add(round(max(0.0, start - 0.1), 3))
                times.add(round(start + 0.2, 3))
    return sorted(time for time in times if 0 <= time < duration)


def _capture_shots(rdir: Path, board: dict, duration: float) -> Path:
    """Контактный лист композиции до рендера. Возвращает путь к нему."""
    times = _snapshot_times(board, duration)
    _cli("snapshot", "public", "--output", "snapshots",
         "--at", ",".join(f"{time:g}" for time in times), "--no-end",
         cwd=rdir, log=rdir / "snapshot.log")
    shots = rdir / "snapshots"
    sheets = sorted(shots.glob("contact-sheet*.jpg"))
    if not sheets:
        raise RuntimeError(
            f"`hyperframes snapshot` не оставил контактный лист в {shots} — "
            "судить кадры до рендера нечем")
    return sheets[0]


def _avatar_ordered_scene(scene: dict) -> bool:
    """Закажут ли ведущую на этой сцене.

    Поле `avatarNeeded` ставит агент (работа 9). Сцена без поля решения не
    несёт, и острова оставляют её фразам эвристическое покрытие
    (`apply_agent_coverage` в `avatar_islands.py`), то есть ведущую там скорее
    закажут, чем нет. Считаем такую сцену заказанной: ошибиться в сторону
    «дороже» безопаснее, чем прозевать перерасход и узнать о нём по счёту.

    Само молчание агента план не спасает: сцену без решения заворачивает
    `D33_avatar_decisions`, и до заказа такой план не доходит. Эта функция
    отвечает только на вопрос «сколько будет стоить», а не «принят ли план».
    """
    needed = scene.get("avatarNeeded")
    return True if needed is None else bool(needed)


def islands_settings(config: dict | None) -> dict:
    """Настройки нарезки островов того профиля, которым будут заказывать.

    Числа заказа (ручка по краям куска, минимальный кусок, предел длины куска)
    берутся из настроек клиента, а не из `DEFAULTS`: у клиента с другим
    профилем задание, гейт и счёт HeyGen считались бы по трём разным числам.
    Без настроек функция отдаёт те же умолчания — они и стоят у всех, кто
    островов не настраивал.
    """
    from reels_factory.avatar_islands import avatar_islands_settings

    return avatar_islands_settings(config)


def _scene_phrases(scenes: list[dict],
                   phrases: list[dict]) -> list[tuple[dict, list[dict]]]:
    """Какие фразы накрывает каждая сцена — так же, как это разберёт заказ.

    Решение сцены наследует фраза, чья СЕРЕДИНА попала внутрь сцены
    (`apply_agent_coverage` в `avatar_islands.py`). Своего второго правила тут
    не заводим: границы сцен округлены к сетке кадров и с границами фраз
    совпадают не всегда, и разойдись эти два ответа — гейт судил бы план не по
    тем фразам, за которые заплатят.
    """
    from reels_factory.avatar_islands import _scene_at

    ordered = sorted(scenes or [],
                     key=lambda scene: float(scene.get("startSec", 0)))
    # Ключ по `id` объекта, а не по самой сцене: две сцены плана могут совпасть
    # всеми полями, и словарь по значению склеил бы их в одну.
    pockets: dict[int, list[dict]] = {id(scene): [] for scene in ordered}
    for phrase in phrases or []:
        middle = (float(phrase["start"]) + float(phrase["end"])) / 2
        scene = _scene_at(ordered, middle)
        if scene is not None:
            pockets[id(scene)].append(phrase)
    return [(scene, pockets[id(scene)]) for scene in ordered]


def _restored_scenes(covered: dict, scenes: list[dict]) -> list[str]:
    """Сцены, которым код вернул ведущую вместо решения агента.

    `agent_coverage.restored_windows` называет ОКНА, а агент правит СЦЕНЫ и
    других имён не знает: скажи ему «окно window-011», и чинить он будет
    вслепую. Сцену ищем по середине окна — тем же правилом, каким заказ
    раздаёт решения сцен фразам (`_scene_at` в `avatar_islands.py`), чтобы имя
    в отказе и имя в заказе не разъехались.
    """
    from reels_factory.avatar_islands import _scene_at

    ordered = sorted(scenes or [],
                     key=lambda scene: float(scene.get("startSec", 0)))
    restored = set((covered.get("agent_coverage") or {})
                   .get("restored_windows") or [])
    names: list[str] = []
    for window in covered.get("windows") or []:
        if window.get("id") not in restored:
            continue
        timing = window.get("final_timing") or {}
        middle = (float(timing.get("start", 0))
                  + float(timing.get("end", 0))) / 2
        scene = _scene_at(ordered, middle)
        name = str(scene.get("id", "?")) if scene is not None else "?"
        if name not in names:
            names.append(name)
    return names


def order_facts(edit_plan: dict, scenes: list[dict],
                config: dict | None = None) -> dict:
    """Настоящий заказ ведущей по этому плану — тот, который выставит HeyGen.

    Оценку заказа мы держали здесь своей арифметикой, и прогон `06eb0a8f`
    (01.09.2026) её оплатил: по сценам агента выходило 29,4 с, а собранный
    заказ — 36,2 с. Оценка не знала про `_restore_short_faceless`
    (`avatar_islands.py`), который возвращает ведущую куску короче
    `MIN_FULLSCREEN_S`; допуск покрывал 1,0 с из 6,8, гейт бюджета завернул
    план, `pipeline.py` из-за красного гейта выбросил решение агента, ведущую
    купили по эвристике — и сборка легла уже после оплаты. $18 за
    недоставленный ролик.

    Поэтому числа берутся у самого заказа: решение агента переносится на план
    монтажа (`apply_agent_coverage`), и по нему строится заказ
    (`build_avatar_render_plan`). Это чистая арифметика — HeyGen тут не зовут,
    и стоит она ноль.

    Возвращает словарь:
    `plan` — заказ или None, если он не собрался;
    `edit_plan` — план монтажа с покрытием агента, то есть РОВНО тот, по
    которому посчитан заказ: сохранять на диск надо его, иначе заморозка
    заказа (`edit_plan_sha256`) укажет на другой файл;
    `billed_seconds` — сколько секунд выставит HeyGen;
    `restored` — имена сцен, которым код вернул ведущую сам;
    `error` — чем заказ не собрался.

    Несобравшийся заказ авария не поднимает: до заказа это причина пересдачи,
    а после неё — повод остаться на прежней разметке. И то и другое решает
    вызывающий, поэтому исключение превращается в текст.
    """
    from reels_factory.avatar_islands import (
        apply_agent_coverage, build_avatar_render_plan,
    )

    facts = {"plan": None, "edit_plan": edit_plan, "billed_seconds": 0.0,
             "restored": [], "error": ""}
    try:
        covered = apply_agent_coverage(edit_plan, scenes)
    except Exception as error:
        facts["error"] = f"покрытие агента не легло на план монтажа: {error}"
        return facts
    facts["edit_plan"] = covered
    facts["restored"] = _restored_scenes(covered, scenes)
    try:
        plan = build_avatar_render_plan(covered, config or {})
    except Exception as error:
        facts["error"] = str(error)
        return facts
    facts["plan"] = plan
    facts["billed_seconds"] = float(
        plan["summary"]["avatar_billed_seconds"])
    return facts


#: Чем открытие и финал закрывают кадр целиком. Пересечение полнокадровых
#: положений с закрытым списком, который задание вообще предлагает агенту
#: (`POSITIONS` в `hf_brief.py`): `overlay` кадр закрывает, но в списке его нет,
#: и проверка, принимающая его, мягче контракта — план с ним прошёл бы гейт до
#: заказа и упёрся бы в сборку, когда клипы уже куплены.
BOOKEND_PRESENTER = FULL_FRAME_PRESENTER & {name for name, *_ in POSITIONS}


#: Запас к порогам, которые меряются по фразам. Наши фразы округлены к
#: миллисекунде, а валидатор меряет неокруглённые (`final_timing` в
#: `finalize_edit_plan`), поэтому фразу ровно на пороге гейт заворачивает: промах
#: в тысячную стоит всей сборки, а пересдача — одной сессии планировщика. Запас
#: идёт в обе стороны: к полу длительности фразы (D31) и к потолку куска без
#: лица (D32) — в обоих случаях в сторону строгости.
PHRASE_TIME_MARGIN = 0.002


def _blind_stretches(scenes: list[dict],
                     phrases: list[dict]) -> list[dict]:
    """Куски ролика, идущие подряд без ведущей.

    Считаем так же, как валидатор плана монтажа: он ведёт отсчёт от начала
    первого окна без лица и сбрасывает его на первом же окне с ведущей
    (`validate_edit_plan`, editplan.py:2672-2680). Сцена без фраз ни отсчёта не
    начинает, ни не сбрасывает: окна заводятся по фразам, и такой сцены в плане
    монтажа не будет вовсе.

    Какие фразы возьмёт схема, на этом шаге неизвестно, и раньше эта оценка
    считалась заниженной: валидатор ведёт отсчёт и по окнам `hyperframes`.
    Плана, принятого гейтами, это не касается — счёт сходится с валидатором:
    фразу, где кадр держит схема, сцена с `avatarNeeded: true` забирает
    ведущей (`apply_agent_coverage` переписывает покрытие вне
    `_VISIBLE_COVERAGE` на `avatar`), сцены выстилают ролик без зазоров
    (`lay_out_scenes` в hf_phrases.py), и сцену без решения вовсе заворачивает
    `D33_avatar_decisions`. Держит это
    `test_схема_в_сцене_с_ведущей_не_считается_пропажей_лица`
    (tests/test_avatar_islands.py): снимут перевод покрытия — гейт снова начнёт
    считать меньше валидатора, и тест упадёт до заказа, а не сборка после него.
    """
    stretches: list[dict] = []
    current: dict | None = None
    for scene, own in _scene_phrases(scenes, phrases):
        if not own:
            continue
        if _avatar_ordered_scene(scene):
            current = None
            continue
        if current is None:
            current = {"scenes": [], "start": float(own[0]["start"]),
                       "end": float(own[-1]["end"])}
            stretches.append(current)
        current["scenes"].append(str(scene.get("id", "?")))
        current["end"] = float(own[-1]["end"])
    return stretches


def _early_plan_gates(scenes: list[dict], duration: float,
                      phrases: list[dict], settings: dict,
                      order: dict | None = None) -> dict:
    """Что проверяем в плане ДО заказа аватара (работа D).

    Все проверки — про то, что после заказа уже не поправить. Ведущую на
    открытии и в финале потом взять неоткуда: клипов на эти секунды просто не
    будет; бюджет — это деньги, которые к тому времени уже уйдут; а план,
    который заворачивает `validate_edit_plan`, роняет сборку уже с оплаченной
    озвучкой и купленными клипами. Место всем таким проверкам здесь: падать
    после оплаты нельзя.

    Провал не отклоняет план, а становится причиной пересдачи: формулировка
    называет виноватую сцену и говорит, что сделать, — этот же текст уезжает
    агенту разделом пересдачи в BRIEF.md вместе с именем гейта.

    `order` — построенный заказ (`order_facts`). Бюджет судится по нему и
    только по нему: своей оценки заказа у гейта больше нет, потому что она
    разошлась с настоящим счётом на 6,8 с и стоила прогону `06eb0a8f` $18.
    Заказа нет или он не собрался — `D29_avatar_budget` снимается в SKIP:
    выдуманный PASS тут дороже честного «судить нечем».
    """
    from reels_factory.avatar_islands import avatar_budget_targets

    result = {}
    wrong = []
    for scene, place in ((scenes[0], "открытие"), (scenes[-1], "финал")):
        position = str(scene.get("presenter") or "full")
        if position in BOOKEND_PRESENTER and _avatar_ordered_scene(scene):
            continue
        wrong.append(f'{scene.get("id", "?")} — {place} ролика: presenter '
                     f'`{position}`, avatarNeeded '
                     f'{json.dumps(scene.get("avatarNeeded"))}')
    result["D28_avatar_bookends"] = "PASS" if not wrong else (
        "FAIL: ролик открывает и закрывает ведущая во весь кадр — лицо "
        "встречает зрителя и провожает его. Поставь этим сценам presenter "
        "`full` или `punch` и `avatarNeeded: true`: " + "; ".join(wrong))

    budget = avatar_budget_targets(duration, settings)
    # Судим по ГРАНИЦЕ, а не по ориентиру: ориентир 60 % — то, куда агенту
    # велено целиться, и промах по нему монтажа не портит, а пересдача стоит
    # новой сессии планировщика. Перебор расстановок показал, почему полоса
    # нужна: расстановка квантована сценой, соседние планы отличаются на целую
    # сцену (27,3 → 34,5 с на ролике 56,1 с), и ориентир 33,7 с стоял ровно в
    # провале между ступенями.
    #
    # Допуска здесь нет намеренно. Прежний допуск (полпроцента хронометража
    # плюс два «непредсказанных шва») лечил неточность НАШЕЙ оценки заказа —
    # оценки больше нет, судим построенный заказ, и прибавлять к нему нечего.
    # Заодно это снимает вред допуска: на прогоне `06eb0a8f` он покрывал 1,0 с
    # из 6,8 промаха и при этом заворачивал планы, чей заказ в границу
    # укладывался.
    billed = float((order or {}).get("billed_seconds") or 0.0)
    if order is None or order.get("plan") is None:
        причина = str((order or {}).get("error") or "")
        result["D29_avatar_budget"] = (
            f"{SKIPPED_VERDICT}: заказ ведущей по этому плану не построен — "
            "судить бюджет нечем. Секунды бюджета берутся у самого заказа "
            "(`order_facts` в hf_render.py), и без него вердикт был бы "
            "выдуман" + (f": {причина}" if причина else "."))
    elif duration <= 0 or billed <= budget["hard_ceiling_seconds"]:
        result["D29_avatar_budget"] = "PASS"
    else:
        paid = ", ".join(str(scene.get("id", "?")) for scene in scenes
                         if _avatar_ordered_scene(scene))
        # Тот же счёт, которым велено считать агенту: сложение длительностей
        # фраз тех сцен, где он попросил ведущую. Ручек в нём нет, и потому это
        # не то число, которое выставит HeyGen, — оба и называем.
        spoken_avatar = sum(float(phrase["end"]) - float(phrase["start"])
                            for scene, pocket in _scene_phrases(scenes, phrases)
                            if _avatar_ordered_scene(scene)
                            for phrase in pocket)
        # Сцены, где ведущую вернул КОД, а не агент. Без этой строки агент
        # видит перебор, которого не заказывал: на прогоне `06eb0a8f` таких
        # окон было пять, и 6,8 с из промаха пришли именно оттуда — пересдача
        # без имён сцен ушла бы в пустоту.
        вернули = ""
        restored = list((order or {}).get("restored") or [])
        if restored:
            вернули = (
                "Часть этих секунд заказал не ты: кусок без ведущей короче "
                f"{seconds(MIN_FULLSCREEN_S)} код возвращает ведущей сам, "
                "иначе сборка упадёт после оплаты, — и здесь это случилось в "
                f'сценах {", ".join(restored)}. Их и чини первыми: удлини '
                "такую сцену или отдай её ведущей целиком. ")
        result["D29_avatar_budget"] = (
            "FAIL: секунда ведущей — самая дорогая секунда ролика, и её "
            "бюджет меряется сложением длительностей фраз: у сцен с "
            f"`avatarNeeded: true` сейчас выходит {seconds(spoken_avatar)} из "
            f"{seconds(duration)} ролика, а целься в "
            f'{seconds(budget["target_seconds"])} — это то же число, что '
            "названо тебе в задании. Заказ по этому плану уже собран, и HeyGen "
            f"выставит за него {seconds(billed)} — выше границы "
            f'{seconds(budget["hard_ceiling_seconds"])}, за которой план не '
            "берут; в твоём счёте фразами та же граница — "
            f'{seconds(budget["hard_target_seconds"])}, и это то же число, что '
            "стоит пунктом сверки в задании. " + вернули
            + "Отдай одну сцену из середины вставке или схеме, поставив ей "
            "`avatarNeeded: false`: хватит самой длинной сцены середины. "
            f"Сейчас с ведущей идут: {paid}")

    short = []
    for scene, own in _scene_phrases(scenes, phrases):
        if _avatar_ordered_scene(scene):
            continue
        name = str(scene.get("id", "?"))
        # Меряем сцену, а не каждую её фразу: заказ склеивает окна одного
        # решения агента в одно (`_merge_agent_windows` в `avatar_islands.py`),
        # и валидатор увидит длину всей сцены. Считаем сложением длительностей
        # фраз — тем же действием, которым велено считать агенту.
        spoken = sum(float(phrase["end"]) - float(phrase["start"])
                     for phrase in own)
        if own and spoken < MIN_FULLSCREEN_S + PHRASE_TIME_MARGIN:
            named = (f'фраза {own[0]["id"]}' if len(own) == 1
                     else f'фразы {own[0]["id"]}–{own[-1]["id"]}')
            short.append(f"{name} — {named}, вместе {seconds(spoken)}")

    # Смягчать D31 до мерки валидатора нельзя, и это замерено. Валидатор
    # такие планы принимает — но только потому, что код сам возвращает
    # слишком короткому куску ведущую (`_restore_short_faceless` в
    # `avatar_islands.py`). Сплошной перебор (обычная речь, 1024 плана): из 26
    # планов, которые D31 валит, а заказ собирает, возврат случился во всех 26,
    # и после возврата 21 план заказывает больше границы 70 %. То есть
    # смягчение меняет пересдачу на молчаливый перерасход поверх границы.
    result["D31_faceless_scenes"] = "PASS" if not short else (
        f"FAIL: сцена без ведущей идёт не короче {seconds(MIN_FULLSCREEN_S)} — "
        "кадр там держит одна вставка, и на более коротком куске зритель не "
        "успевает её прочитать. Меряется сцена целиком: сложи длительности её "
        "фраз. Отдай такой сцене соседнюю фразу либо поставь ей "
        "`avatarNeeded: true`: " + "; ".join(short))

    # Тот же запрет, что и у валидатора (`validate_edit_plan`,
    # editplan.py:2672-2680): план, где сцены без ведущей идут подряд дольше
    # предела, роняет сборку уже с оплаченной озвучкой. Запас берём в сторону
    # строгости — наши секунды округлены к миллисекунде, а меряют неокруглённые.
    blind = [stretch for stretch in _blind_stretches(scenes, phrases)
             if stretch["end"] - stretch["start"]
             > MAX_FACE_ABSENCE_S - PHRASE_TIME_MARGIN]
    result["D32_face_absence"] = "PASS" if not blind else (
        f"FAIL: лицо не пропадает дольше {seconds(MAX_FACE_ABSENCE_S)} подряд — "
        "без рассказчика зритель бросает ролик, и заказ по такому плану не "
        "состоится вовсе. Поставь посреди этих сцен сцену с "
        "`avatarNeeded: true`: " + "; ".join(
            ", ".join(stretch["scenes"])
            + f" идут подряд без ведущей "
              f'{seconds(stretch["end"] - stretch["start"])}'
            for stretch in blind))

    # Решение обязано быть у каждой сцены. Сцену, где поля нет, гейты считают
    # заказанной, а перенос решения на фразы её не трогает вовсе
    # (`apply_agent_coverage` в `avatar_islands.py`): покрытие там остаётся
    # эвристическим и с планом агента не совпадает. Прогон это и показал —
    # все гейты зелёные, а заказ упал на «лицо отсутствует дольше 10 с», когда
    # озвучка уже оплачена.
    silent = [str(scene.get("id", "?")) for scene in scenes
              if not isinstance(scene.get("avatarNeeded"), bool)]
    result["D33_avatar_decisions"] = "PASS" if not silent else (
        "FAIL: поле `avatarNeeded` стоит у каждой сцены — по нему у HeyGen "
        "заказывают ведущую. Сцена без него решения не несёт: код оставляет "
        "там свою догадку о кадре, она расходится с твоим планом, и сборка "
        "падает уже с оплаченной озвучкой. Поставь `true` там, где фразу "
        "ведёт лицо, и `false` там, где кадр держит вставка или схема: "
        + ", ".join(silent))

    # Число моментов под вставку требовала только сборка — и роняла её отказом
    # (`check_inserts`). До работы 9 это стоило одного прогона; после — падения
    # с оплаченной озвучкой и заказанной ведущей. Живой прогон 17.08 именно так
    # и кончился: шесть ранних гейтов зелёные, сборка легла на «вставок 3, а
    # нужно 4». Счёт тот же самый, чтобы два места не разъехались.
    shortfall = inserts_shortfall(scenes)
    result["D34_inserts"] = "PASS" if not shortfall else f"FAIL: {shortfall}"

    # То же самое судит D20 (`check_frame_filled` в hf_gates.py) — но уже после
    # рендеров HeyGen: боевой прогон лёг там на `s-06: ведущая 'pip-tl' без
    # вставки`, отдал $11,86 и не отдал ролика. Здесь чинить это ещё бесплатно:
    # ведущая уголком, вставка и схема — решения агента, и все три стоят в
    # плане уже сейчас (образец ответа показывает их до заказа,
    # `_sample_plan` в hf_brief.py). Судим тем же кодом, а не своей копией:
    # разойтись двум местам иначе нечем.
    #
    # Про схему гейт не спрашивает отдельно — `frame_filled_problems` считает
    # `schema_scene` наравне со вставкой.
    # Имя позиции каталога сверяется до заказа по той же причине: их
    # `hyperframes add` неизвестное имя не ставит и роняет попытку сборки, а
    # ставит он блоки уже после того, как ведущую сняли и оплатили. Тот же
    # список сверяет D11 после сборки, и считает его тот же код —
    # `elements_problems`.
    named = elements_problems(scenes)
    result["D36_elements"] = "PASS" if not named else (
        "FAIL: позицию каталога код ставит их же `hyperframes add`, и "
        "неизвестное имя он не ставит вовсе — сборка встанет уже с оплаченной "
        "ведущей. Имена, слоты и переменные позиций перечислены в "
        "`catalog.index.md` рядом с заданием: " + "; ".join(named))

    empty = frame_filled_problems(scenes)
    result["D35_frame_filled"] = "PASS" if not empty else (
        "FAIL: ведущая уголком (`pip-*`) или половиной кадра (`stack`) "
        "оставляет остальной кадр пустым, и закрыть его нечем — зритель "
        "увидит дыру. Дай такой сцене вставку `insert` из двух планов или "
        "схему `schema`, а если закрывать нечем — поставь ей presenter "
        "`full` или `punch`: " + "; ".join(empty))
    return result


#: Копии задания раннего шага. Что копируем и куда: задание и свод правил,
#: рядом с оригиналом.
EARLY_BRIEF_COPIES = (("BRIEF.md", "BRIEF.plan.md"),
                      (f".claude/skills/{SKILL_NAME}/SKILL.md",
                       "SKILL.plan.md"))

#: План, по которому куплена ведущая. `plan.json` его не заменяет: пересдача
#: монтажа спрашивает агента заново и переписывает `plan.json` (см. цикл
#: попыток в `assemble_hyperframes`), а возобновлённый прогон обязан разложить
#: ведущую ровно так, как её заказали, — иначе куски мастер-звука разъедутся,
#: кэш островов промахнётся и HeyGen снимет деньги второй раз.
EARLY_PLAN_FILE = "plan.early.json"

#: Вердикт гейта, которому нечего судить. От PASS отличается намеренно: гейт не
#: пройден, он снят — и в отчёте это должно быть видно словом.
SKIPPED_VERDICT = "SKIP"


def frozen_plan_gates(gates: dict) -> dict:
    """Вердикты ранних гейтов по плану, который уже заморожен заказом.

    Ранние гейты судят то, что ещё можно переписать: провал становится
    причиной пересдачи внутри `plan_before_avatar`, агент правит план, и
    ведущую заказывают уже по исправленному. Как только заказ сделан, план
    заморожен (`EARLY_PLAN_FILE`, `reset_montage_steps`), и тот же провал
    поправить нечем — чинить его значит платить за ведущую второй раз.

    Отказ на замороженном плане не отклонить и не исправить, поэтому он
    становится вечным: `qa_pass` уходит в False на каждой пересборке, и кнопка
    «продолжить» до успеха не доводит никогда. Боевой случай — задание
    f6e14bfcfe3f40afa875abf2ea8a174f после 4b031f0: `D34_inserts` завернул
    ранний план из длинных сцен, при том что в готовом ролике `D15` насчитал
    десять вставок в кадре, а `D18` — 35 смен картинки.

    Поэтому на пересборке вердикт остаётся в отчёте (иначе о промахе плана не
    узнает никто), но качество ролика больше не решает. Гейты готового файла на
    его месте не пустуют: вставки в кадре судит `D15_inserts_visible`, ритм —
    `D18_change_rate`, и эти двое меряют то, что пересборка ещё меняет.

    На ПЕРВОЙ сборке ничего не меняется: там гейты считает
    `plan_before_avatar`, и их провал по-прежнему возвращает агенту пересдачу
    до заказа — ради этого проверка и стоит.
    """
    softened = {}
    for name, verdict in gates.items():
        text = str(verdict)
        softened[name] = text if not text.startswith("FAIL") else (
            f"{SKIPPED_VERDICT}: план заморожен оплаченным заказом ведущей — "
            "переписать его нечем, не заказав её второй раз. Вердикт до "
            f"заказа: {text}")
    return softened


def _keep_early_brief(rdir: Path) -> None:
    """Оставить на диске задание, по которому сделан ранний план.

    Сборка зовёт `write_brief` заново и переписывает и `BRIEF.md`, и свод правил
    версией «аватар уже заказан» (`prepare` ниже), а решал агент `avatarNeeded`
    по другой версии — по той, где ведущей ещё нет. Разбирать прогон по
    переписанным файлам значит читать не то задание, поэтому ранняя версия
    остаётся рядом отдельными именами.
    """
    for source, name in EARLY_BRIEF_COPIES:
        path = rdir / source
        if path.exists():
            shutil.copyfile(path, rdir / name)


def _fill_frame_holes(rdir: Path, board: dict, scenes: list[dict]) -> list[str]:
    """Закрыть дыру в кадре кодом, когда попытки агента кончились.

    Провал раннего гейта прогон не останавливает: после `MAX_PLAN_ATTEMPTS`
    план ложится на диск как есть, а `pipeline.py:550-556` печатает «покрытие
    оставлено прежним» и идёт заказывать ведущую. Остальным ранним гейтам это
    сходит с рук — покрытие потом пересчитает код. `D35_frame_filled` — нет:
    `presenter` и `insert` эвристика не переписывает, и план с дырой доезжает
    до оплаченного заказа, а потом гарантированно валится на
    `D20_frame_filled` уже после списания денег. Боевой прогон так и кончился:
    $11,86 за недоставленный ролик.

    Трогаем только положение ведущей: вставку, схему и порядок сцен решает
    агент, и переписывать их за него значит собрать не тот ролик, который он
    задумал. Положение берём не своё — `pick_position` (hf_montage.py:349)
    выбирает его из `positions_for` (hf_montage.py:322), то есть из списка,
    согласованного с наполнением сцены; клипов и дыр аватара на этом шаге ещё
    нет, и им они не нужны — в отличие от `refill_scene`, который спрашивает
    `gaps`.

    Сцену, где ведущей не закажут вовсе (`avatarNeeded: false`), закрывать
    ведущей нельзя: `full` на ней — обещание кадра, которого HeyGen не снимет.
    До заказа `avatarNeeded: false` читается ровно как дыра аватара
    (hf_montage.py:179-185), а на дыре `refill_scene` ставит `none` — законную
    фоновую сцену, которую `fills_frame` принимает (hf_layout.py:135).

    Возвращает список поправок словами. Пустой — гейт зелёный, ничего не
    трогали.
    """
    fixed = []
    for index, scene in enumerate(scenes):
        # Гейт судит каждую сцену отдельно (hf_gates.py:381-399), поэтому
        # вопрос о ней одной — тот же самый вопрос. Своей копии правила у нас
        # тут нет: разойтись двум местам иначе нечем.
        if not frame_filled_problems([scene]):
            continue
        was = str(scene.get("presenter") or "full")
        scene["presenter"] = ("none" if scene.get("avatarNeeded") is False
                              else pick_position(scenes, index))
        fixed.append(f'{scene.get("id", "?")}: {was} → {scene["presenter"]}')
    if not fixed:
        return fixed

    # План агента лежит на диске, и по нему поедет всё дальнейшее: заказ читает
    # `plan.json`, возобновлённый прогон — снимок `EARLY_PLAN_FILE`, который
    # сейчас снимут с него же. Поправить только сцены в памяти значит починить
    # один прогон и оставить дыру во втором.
    by_id = {str(scene.get("id")): scene for scene in board.get("scenes") or []}
    for scene in scenes:
        twin = by_id.get(str(scene.get("id")))
        if twin is not None:
            twin["presenter"] = scene["presenter"]
    (rdir / "plan.json").write_text(
        json.dumps(board, ensure_ascii=False, indent=1), encoding="utf-8")
    print("положение ведущей поправлено кодом: агент исчерпал попытки, а "
          "уголок или половина кадра так и остались без вставки и без схемы — "
          "закрываем кадр до заказа, иначе за дыру заплатит пользователь: "
          + "; ".join(fixed))
    return fixed


def plan_before_avatar(rdir, timed_scenario: dict, *, alignment_words: list,
                       edit_plan: dict | None = None,
                       config: dict | None = None,
                       agent_runner=None, agent_spend=None) -> dict:
    """План агента ДО заказа аватара (работа 9).

    Клипов ещё нет, поэтому бриф не навязывает дыр: агент сам решает
    `avatarNeeded` по сценам, и острова закажут по его решению
    (`avatar_islands.apply_agent_coverage`). План и маркеры шага ложатся на
    диск — последующая сборка `assemble_hyperframes` агента повторно не
    зовёт, она подхватит готовый `plan.json`.

    Окружение поднимаем то же, что и сборка: реестр блоков на localhost и
    `hyperframes.json` в обеих папках. Без конфига их `add` не отказывает, а
    заводит свой — с публичным реестром heygen-com/hyperframes
    (`write_project_config` в `hf_catalog.py`, со ссылкой на их
    `install-locations.md`), и в кадр поехал бы чужой блок.

    `config` — настройки клиента. Из них берутся числа заказа
    (`avatar_islands`): они уезжают и в задание, и в гейты, чтобы задание, гейт
    и счёт HeyGen считались одной арифметикой. Без настроек берутся умолчания.

    `agent_spend` — общий кошелёк ролика. Обёртку заводим здесь, а не оставляем
    её умолчанию `plan_with_agent`: там она осталась бы при функции вместе со
    своим расходом, и работа планировщика (по замеру $0,45 за ролик) в счёт бы
    не попала.

    `edit_plan` — финальный план монтажа. По нему на каждой попытке строится
    НАСТОЯЩИЙ заказ (`order_facts`), и по нему судит бюджет: своей оценки у
    гейта больше нет. Без плана монтажа заказ не строится вовсе, и бюджет
    уходит в SKIP — так зовут только те, кому вердикт бюджета не нужен.

    Возвращает `{"board": план, "scenes": сцены с секундами, "order": заказ,
    "gates": отчёт}` — по сценам считаются интервалы заказа, `order` забирает
    `pipeline.py` (в нём лежит и размеченный решением агента план монтажа), а
    `gates` уезжает в отчёт по сборке. Фреймворка это не касается: заказ у
    HeyGen идёт до композиции, HyperFrames видит уже готовые клипы.
    """
    rdir = Path(rdir).resolve()
    (rdir / "public").mkdir(parents=True, exist_ok=True)
    spend = agent_spend if agent_spend is not None else AgentSpend()
    words = _normalize_words(alignment_words)
    duration = quantize(float(timed_scenario.get("total") or 0.0))
    phrases = phrase_timeline(timed_scenario, words,
                              language=timed_scenario.get("language", "ru"))
    # Один набор чисел на задание и на гейты: профиль островов у клиента может
    # быть свой, и посчитанное по умолчаниям разошлось бы со счётом.
    islands = (config or {}).get("avatar_islands")
    settings = islands_settings(config)

    # Прерванный прогон возобновляем, а не переигрываем: аватар заказан ровно
    # по этому плану, и второй план после заказа оставил бы оплаченные секунды
    # без кадра — да ещё и стоил бы второй сессии планировщика.
    if step_done(rdir, EARLY_PLAN_STEP) and (rdir / "plan.json").exists():
        # Копии может не быть у папок, заведённых до неё, — тогда читаем
        # `plan.json` как раньше.
        early = rdir / EARLY_PLAN_FILE
        source = early if early.exists() else rdir / "plan.json"
        board = json.loads(source.read_text(encoding="utf-8"))
        scenes = lay_out_scenes(board.get("scenes") or [], phrases,
                                duration=duration)
        # Заказ считаем и здесь. Пропустить его на пересборке значит навсегда
        # оставить бюджет в SKIP: вердикт по замороженному плану всё равно
        # уезжает в отчёт (`frozen_plan_gates`), и «судить нечем» вместо числа
        # спрятало бы ровно тот промах, который стоил прогону `06eb0a8f` $18.
        order = (order_facts(edit_plan, scenes, config)
                 if edit_plan is not None else None)
        return {"board": board, "scenes": scenes, "order": order,
                "gates": _early_plan_gates(scenes, duration, phrases,
                                           settings, order=order)}

    board: dict = {}
    scenes: list[dict] = []
    gates: dict = {}
    order: dict | None = None
    reason = None
    with serve_catalog() as registry_url:
        write_project_config(rdir, registry_url)
        for attempt in range(MAX_PLAN_ATTEMPTS):
            write_brief(rdir, scenario=timed_scenario, face=None,
                        duration=duration, clips=[], phrases=phrases,
                        retry_reason=reason,
                        avatar_ordered=False, islands=islands,
                        attempt=attempt, max_attempts=MAX_PLAN_ATTEMPTS)
            # Ход без плана — такая же причина пересдачи, как и план, не легший
            # на озвучку: сессия обрывается по своим причинам, а стоит эта
            # осечка одного переспроса против всей сборки. Ловим только пустой
            # ответ агента (`AgentPlanMissing`): упавший процесс `claude` —
            # авария окружения, и второй заход по ней ничего не чинит.
            try:
                board = plan_with_agent(
                    rdir, runner=agent_runner or HeyGenAgentRunner(spend=spend),
                    avatar_ordered=False)
            except AgentPlanMissing as error:
                reason = (
                    f"{error}. Закончи ход двумя файлами на диске: "
                    "`storyboard.json` с непустым списком `scenes` и "
                    "`frame.md`. По этим сценам заказывают ведущую, и без них "
                    "заказывать нечего")
                if attempt == MAX_PLAN_ATTEMPTS - 1:
                    raise
                continue
            # Секунды считаем здесь: агент назвал только фразы. План, который
            # не лёг на озвучку, он поправит сам — это причина пересдачи, а не
            # авария. Но без сцен заказывать нечего, поэтому на последней
            # попытке это уже отказ.
            try:
                scenes = lay_out_scenes(board.get("scenes") or [], phrases,
                                        duration=duration)
            except RuntimeError as error:
                reason = str(error)
                if attempt == MAX_PLAN_ATTEMPTS - 1:
                    raise RuntimeError("план не лёг на озвучку — " + reason)
                continue
            # Заказ строим на КАЖДОЙ попытке: гейт бюджета судит его, а не
            # оценку, и после правки плана заказ выходит другой. Денег это не
            # стоит — HeyGen тут не зовут.
            order = (order_facts(edit_plan, scenes, config)
                     if edit_plan is not None else None)
            gates = _early_plan_gates(scenes, duration, phrases, settings,
                                      order=order)
            failed = [f"{key}: {value}" for key, value in gates.items()
                      if value.startswith("FAIL")]
            if order is not None and order["plan"] is None:
                # Заказ, который не собирается, — такая же причина пересдачи,
                # как план, не легший на озвучку: чинит его агент. Отказом это
                # не становится даже на последней попытке — озвучка уже
                # оплачена, и прогон доедет на прежней разметке покрытия
                # (`pipeline.py`), отдав человеку ролик.
                failed.append("заказ ведущей по этому плану не собирается: "
                              + order["error"])
            if not failed:
                break
            reason = "; ".join(failed)

    # Чиним здесь, а не там, где план читают перед заказом: ниже по этой же
    # функции план замораживают — снимок `EARLY_PLAN_FILE` и маркеры шага, — и
    # возобновлённый прогон разложит уже снимок, не спрашивая никого. Правка
    # на месте чтения досталась бы одному прогону, а в снимке дыра осталась бы
    # навсегда: `frozen_plan_gates` её потом даже не завернёт, а переведёт в
    # вечный SKIP. Это последняя точка, где план ещё чей-то, а не оплаченный.
    if _fill_frame_holes(rdir, board, scenes):
        # В отчёт и в снимок обязан уйти вердикт по тому плану, который
        # действительно поедет в заказ, а не по тому, что вернул агент. Заказ
        # пересчитываем вместе с вердиктом: починка трогает только `presenter`,
        # но связка «вердикт считан по этому заказу» должна держаться сама, а
        # не на памяти о том, что именно правит починка.
        order = (order_facts(edit_plan, scenes, config)
                 if edit_plan is not None else None)
        gates = _early_plan_gates(scenes, duration, phrases, settings,
                                  order=order)

    # Задание последней попытки — это то самое, по которому сделан лежащий
    # план: копию снимаем до того, как сборка перепишет оригинал.
    _keep_early_brief(rdir)
    # Отдельный снимок плана: `plan.json` перепишет пересдача монтажа, а по
    # этому файлу заказана ведущая, и возобновлённый прогон раскладывает её
    # именно по нему.
    shutil.copyfile(rdir / "plan.json", rdir / EARLY_PLAN_FILE)
    _marker(rdir, "plan").write_text("ok", encoding="utf-8")
    # Память о том, чей план лежит в `plan.json`: аватар закажут ровно по нему,
    # и сборка второй план спрашивать не вправе.
    _marker(rdir, EARLY_PLAN_STEP).write_text("ok", encoding="utf-8")
    return {"board": board, "scenes": scenes, "order": order, "gates": gates}


def assemble_hyperframes(rdir, timed_scenario: dict, *, edit_plan: dict,
                         avatar_mp4s: list, master_audio, alignment_words: list,
                         avatar_render_plan: dict | None = None,
                         out_mp4=None, agent_runner=None, agent_spend=None,
                         wishes: dict | None = None) -> dict:
    """Материал -> план агента -> сборка кодом -> гейты -> рендер -> громкость.

    `agent_spend` — кошелёк расхода сессий (`AgentSpend`). Своего кошелька у
    вызывающего обычно нет, поэтому сборка заводит его сама: расход планировщика
    и судьи бироллов уезжает в итог (`agent_cost_usd`, `agent_runs`), откуда его
    списывает счётчик денег (`meter.claude_agent` в `pipeline.py`). Кто передаёт
    свою обёртку через `agent_runner`, тот отдаёт её со своим кошельком —
    иначе её прогоны останутся при ней.

    На ПОСЛЕДНЕЙ попытке цикла compose ни провал `check_shots`/`check_inserts`,
    ни красные гейты (D0_check и весь `check_storyboard`) саму сборку больше не
    роняют (решение 05, Вася): к этому моменту ведущая уже куплена — клипы
    HeyGen оплачены до входа в этот цикл, — и ролик с изъяном (мало вставок,
    пустой угол, лишняя секунда без лица, предупреждение их `check`) для
    заказчика лучше, чем отсутствие ролика вовсе. Прогоны Лейлы, Nagimash и
    Артёма собрались именно так: мелкий изъян в карточке, ролик в чате.
    Вердикты остаются в `gates.json`/возвращаемом `"gates"` как есть, FAIL не
    прячется — честный отчёт важнее красивого. Настоящая поломка (файла нет,
    HeyGen отказал, рендер отдал мёртвый слой субтитров) по-прежнему
    поднимается исключением — эта уступка касается только суждений о качестве
    уже собранного плана, не механических отказов.
    """
    rdir = Path(rdir).resolve()
    spend = agent_spend if agent_spend is not None else AgentSpend()
    public = rdir / "public"
    words = _normalize_words(alignment_words)
    duration = quantize(float(timed_scenario.get("total") or 0.0))
    # Фразы озвучки — общий язык кода и агента: он называет их номерами, код по
    # ним считает секунды. Считаем один раз, до задания.
    phrases = phrase_timeline(timed_scenario, words,
                              language=timed_scenario.get("language", "ru"))

    def prepare() -> None:
        public.mkdir(parents=True, exist_ok=True)
        clips = _place_clips(public, avatar_mp4s, avatar_render_plan, timed_scenario)
        shutil.copyfile(str(master_audio), str(public / "voice.wav"))
        (public / "words.json").write_text(
            json.dumps(words, ensure_ascii=False, indent=1), encoding="utf-8")
        vendor_gsap(public)
        face_box_for(public / clips[0]["file"], rdir / "face.json")
        media = _media_from_plan(edit_plan, public) + _prepare_material(
            edit_plan, public, rdir)
        # Компонент субтитров тянется из их общего реестра по сети: делаем это
        # пока агент ещё не начал, чтобы сборка потом не ждала загрузку.
        hf_captions.stage(rdir)
        write_brief(rdir, scenario=timed_scenario, face=load_face(rdir),
                    duration=duration, clips=clips, phrases=phrases,
                    wishes=wishes,
                    attempt=0, max_attempts=MAX_COMPOSE_ATTEMPTS)
        (rdir / "phrases.json").write_text(
            json.dumps(phrases, ensure_ascii=False, indent=1), encoding="utf-8")
        (rdir / "clips.json").write_text(
            json.dumps(clips, ensure_ascii=False, indent=1), encoding="utf-8")
        # media.json задание больше не читает: вставки подбираются по намерениям
        # из плана. Файл остаётся как след того, что план успел положить в
        # public/ — на него смотрят при разборе прогона.
        (rdir / "media.json").write_text(
            json.dumps(media, ensure_ascii=False, indent=1), encoding="utf-8")

    run_step(rdir, "prepare", prepare)

    saved_clips = json.loads((rdir / "clips.json").read_text(encoding="utf-8"))

    # Причина прошлого отказа приходит из папки job: продолжение начинает с
    # неё тот же круг пересдачи, что и провал внутри прогона — план снимается,
    # задание переписывается разделом пересдачи. Иначе на продолжении агента не
    # зовут вовсе (маркер `plan` цел), и в кадр едет план, который проверки уже
    # завернули.
    gate_result, reason = None, last_retry_reason(rdir)
    # Каталог поднимаем на всё время сборки: `hyperframes add` ходит в него за
    # каждым блоком, который назвал агент.
    with serve_catalog() as registry_url:
        write_project_config(rdir, registry_url)
        for attempt in range(MAX_COMPOSE_ATTEMPTS):
            if reason is not None:
                # Пересдача снимает и `plan`: без неё в кадр едет тот самый
                # план, который проверки уже завернули, а прогон стоит денег —
                # один суд бироллов моделью считается заново на каждом заходе.
                # Ранний план (работа 9) тут не исключение: спрашивают агента
                # заново по УЖЕ КУПЛЕННЫМ клипам, то есть заданием в режиме
                # «аватар заказан», где ему называют, где ведущей нет. Сам
                # маркер `plan-early` остаётся — он про то, чем оплачена
                # ведущая, а не про монтаж.
                for step in ("plan", "compose", "gates", "shots", "render",
                             "loudness"):
                    reset_step(rdir, step)
                write_brief(rdir, scenario=timed_scenario,
                            face=load_face(rdir), duration=duration,
                            clips=saved_clips, retry_reason=reason,
                            phrases=phrases,
                            wishes=wishes,
                            attempt=attempt, max_attempts=MAX_COMPOSE_ATTEMPTS)

            # Обёртку заводим здесь, а не внутри `plan_with_agent`: там она
            # осталась бы при функции вместе со своим расходом, и работа
            # планировщика (по замеру $0,45 за ролик) в счёт бы не попала.
            board = run_step(rdir, "plan", lambda: plan_with_agent(
                rdir, runner=agent_runner or HeyGenAgentRunner(spend=spend)))
            if board is None:
                # Не `storyboard.json`: его переписывает сборка, дописывая
                # секунды и снимая `phrases`. Пересборка без агента обязана
                # читать то, что агент действительно вернул.
                board = json.loads(
                    (rdir / "plan.json").read_text(encoding="utf-8"))
            # Секунды считаем здесь: агент назвал только фразы. Не сошлось —
            # это причина пересборки, а не авария: план он поправит сам.
            try:
                board["scenes"] = lay_out_scenes(
                    board.get("scenes") or [], phrases, duration=duration)
            except RuntimeError as error:
                reason = str(error)
                if attempt == MAX_COMPOSE_ATTEMPTS - 1:
                    raise RuntimeError("план не лёг на озвучку — " + reason)
                continue
            board = complete_storyboard(board, clips=saved_clips,
                                        duration=duration)
            # Отбор серий — ДО подбора медиа: искать и судить кандидатов на
            # сцены, которые в кадр не попадут, значит платить временем и
            # квотой стока за выброшенное. Агент называет моментов больше,
            # чем войдёт; сколько их останется, считает арифметика.
            try:
                check_shots(board["scenes"])
                check_inserts(board["scenes"])
            except RuntimeError as error:
                reason = str(error)
                if attempt != MAX_COMPOSE_ATTEMPTS - 1:
                    continue
                # Последняя попытка: ведущая уже куплена, повторного плана не
                # будет. Слабый план (не хватает моментов под вставку, серия
                # названа не двумя планами) едет в сборку как есть — код ниже
                # соберёт то, что сможет, а не откажет в ролике из-за него.
            # Ведущая, за которую уже заплачено, обязана быть в кадре: клипы
            # куплены до плана, и `presenter: "none"` на купленной секунде
            # выбрасывает деньги, а не бережёт их.
            show_ordered_avatar(board["scenes"], saved_clips, duration)
            # Соседние бироллы — одна серия из двух планов, а не две сцены,
            # разведённые правилом «между сериями держим лицо».
            merge_adjacent_series(board["scenes"], clips=saved_clips,
                                  duration=duration)
            kept, series = pick_series(board["scenes"], saved_clips, duration)
            drop_series(board["scenes"], kept, clips=saved_clips,
                        duration=duration)
            # Снятая серия оставляет на своём месте ведущую — и сцена может
            # стать копией соседа. Разводим здесь, а не гейтом: план на этом
            # месте уже написан кодом, агенту чинить нечего.
            dedupe_neighbours(board["scenes"], clips=saved_clips,
                              duration=duration)
            # Схема, которой не хватит секунд, разбирается здесь, до сборки:
            # иначе она снималась уже в кадре, и сцена без ведущей оставалась
            # с одним фоном. Дыры отдаём вместе со сценами: секунды принимает
            # только соседка по ту же сторону границы острова (`absorb_scene`).
            settle_schemas(board["scenes"],
                           ordered_gaps(saved_clips, duration))
            print(f'серий бироллов {series["series"]}, доля аватара '
                  f'{series["avatar_share"] * 100:.0f}%'
                  + (("; выброшены — " + "; ".join(series["dropped"]))
                     if series["dropped"] else ""))

            def compose() -> dict:
                clear_generated(public)
                # Накладки ставит их же `add` из нашего каталога — сервер
                # реестра поднят на всё время сборки.
                for block in needed_blocks(board):
                    if not (public / "compositions" / f"{block}.html").exists():
                        _cli("add", block, "--no-clipboard", cwd=rdir,
                             log=rdir / "add.log")
                # Свуш на кульминации — их встроенная библиотека SFX
                # (media-use, 19 файлов, работает без сети). Без свуша стык
                # живёт: не падать из-за звука.
                whoosh = None
                if needed_blocks(board):
                    found_sfx = resolve_all(public, [
                        {"key": "sfx-whoosh", "type": "sfx",
                         "intent": "whoosh short"}])
                    whoosh = (found_sfx.get("sfx-whoosh") or {}).get("file")
                # Судье вставок нужна реплика диктора под каждой сценой и
                # тема ролика — без них он судил бы картинку без смысла.
                #
                # Сцену ищем по началу ключа, а не по всему ключу: с переходом
                # на серии ключ стал `s-02::shot0`, точное сравнение перестало
                # совпадать хоть с чем-нибудь, и реплика молча уходила пустой —
                # судья с прогона 24 судил по самому запросу.
                def with_speech(requests: list[dict]) -> list[dict]:
                    for request in requests:
                        owner = str(request["key"]).split("::")[0]
                        scene = next((s for s in board.get("scenes") or []
                                      if str(s.get("id")) == owner), {})
                        request["speech"] = speech_between(
                            phrases, float(scene.get("startSec", 0)),
                            float(scene.get("endSec", 0)))
                    return requests

                requests = with_speech(collect_intents(board))
                with sdk_session() as sdk:
                    found = resolve_all(public, requests,
                                        context=board.get("brollContext"),
                                        agent_spend=spend)
                    _report_resolve(found, "вставка")
                    lost = settle_inserts(board, found, saved_clips, duration,
                                          public=public)
                    if lost:
                        print(f"вставка не нашлась у сцен: {', '.join(lost)} — "
                              "ведущая там встала во весь кадр")
                    # Значки — вторым заходом, как и запасная схема: значок
                    # запас, и сцене с приехавшей вставкой он в кадр не
                    # встанет. Пока запросы шли вместе со вставками, за такой
                    # значок платили поиском, скачиванием превью и долей
                    # платной сессии судьи — и он же занимал `id` каталога,
                    # отбирая его у сцены, которой закрыть кадр больше нечем.
                    icons = with_speech(
                        icon_intents(board.get("scenes") or []))
                    if icons:
                        # Значки подбираются тем же `resolve_all` и молчат так
                        # же: значок без файла снимает `settle_fillers`, и
                        # сцена, стоявшая на нём одном, остаётся фоном.
                        picked = resolve_all(
                            public, icons, context=board.get("brollContext"),
                            agent_spend=spend)
                        _report_resolve(picked, "значок")
                        found.update(picked)
                    # Значок без файла и плашку с непригодным блоком
                    # снимаем здесь же: раньше их снимала сама сборка, то
                    # есть после разбора пустых сцен, и сцена, стоявшая на
                    # одном значке, доезжала до зрителя фоном с титром.
                    settle_fillers(board, found)
                    # Запасную схему назначает `settle_inserts` — то есть уже
                    # после первого прохода по схемам, — и её пол секунд до
                    # сих пор мерила одна сборка. Схема снималась там, когда
                    # чинить кадр было уже нечем: сцена на дыре без аватара
                    # оставалась с фоном и титром, и D25 с D26 валили сборку
                    # за то, чего агент не делал.
                    settle_schemas(board.get("scenes") or [],
                                   ordered_gaps(saved_clips, duration))
                    # Потеря вставки перекраивает кадр так же, как снятая
                    # серия, — и так же плодит пары одинаковых кусков.
                    # `dedupe_neighbours` заодно разбирает сцены, кадр
                    # которых закрыть уже нечем (`settle_empty_frames`).
                    dedupe_neighbours(board.get("scenes") or [],
                                      clips=saved_clips, duration=duration)
                    # Запасную схему подбираем вторым заходом и только для тех
                    # сцен, которым она реально понадобилась: в обычном прогоне
                    # сток отвечает, и этих запросов не будет вовсе.
                    theme = read_frame(rdir)
                    schema = schema_intents(board.get("scenes") or [],
                                            theme=theme)
                    if schema:
                        drawn = resolve_all(public, schema, agent_spend=spend)
                        _report_resolve(drawn, "схема")
                        found.update(drawn)
                    build_composition(rdir, sdk, storyboard=board,
                                      clips=saved_clips, duration=duration,
                                      words=words, resolved=found,
                                      sfx_whoosh=whoosh, theme=theme,
                                      face=load_face(rdir))
                _write_motion_sidecar(public, board, duration)
                # Шрифты врезаем до проверок: и наши гейты, и их `check` меряют
                # переполнение и перекрытие по отрисованному тексту, а без наших
                # @font-face кириллица считалась бы по подменному шрифту.
                inject_fonts(public, work_dir=rdir)
                return found

            try:
                run_step(rdir, "compose", compose)
            except RuntimeError as error:
                reason = str(error)
                if attempt == MAX_COMPOSE_ATTEMPTS - 1:
                    raise RuntimeError("сборка не состоялась — " + reason)
                continue

            # Судим то, что реально собралось: подбор вставок мог не ответить,
            # и тогда сцена уже переписана на ведущую во весь кадр.
            board = json.loads(
                (rdir / "storyboard.json").read_text(encoding="utf-8"))
            result = check_storyboard(board, clips=saved_clips, duration=duration)
            # …а «что просил агент» знает только его собственный ответ:
            # раскадровку сборка переписывает под собранный кадр и снятую
            # позицию каталога из неё вычищает. Поэтому `D36_elements` после
            # сборки сравнивает план с кадром, а не судит раскадровку саму по
            # себе — иначе потеря позиции проходит зелёной (пересборка
            # `artyom-rebuild-4b`, `count-up`).
            result.update(elements_delivered(
                json.loads((rdir / "plan.json").read_text(encoding="utf-8")),
                board))
            result.update(check_media(rdir))
            result.update(check_placeholders(rdir))
            # Композиция, которая не открывается, — это тоже провал сборки, а не
            # авария движка: агенту есть что чинить, и он получит причину.
            try:
                result.update(probe_gates(rdir, face=load_face(rdir)))
            except RuntimeError as error:
                result["D8_face"] = f"FAIL: {error}"
            # Их проверка идёт здесь же, одним заходом: агент композицию больше
            # не собирает и `check` не гоняет, значит две проверки подряд
            # схлопываются в одну, и её находки уходят агенту тем же путём, что
            # и наши.
            #
            # `--strict` роняет прогон и на предупреждениях: без него
            # `ok = errorCount === 0 && (!options.strict || warningCount === 0)`
            # (packages/cli/src/utils/checkPipeline.ts:1344), и в прогоне 13 все
            # находки прошли мимо именно так.
            #
            # `--at` вместо равномерной сетки: без него берутся середины девяти
            # равных отрезков (`buildLayoutSampleTimes`,
            # packages/cli/src/utils/layoutAudit.ts:79-92), и в прогоне 13 две
            # выборки из девяти пришлись на паузы, а одна сцена не проверялась
            # вовсе. Отдаём середину каждой сцены — тогда без проверки не
            # останется ни одна.
            #
            # Без `--at-transitions`: выборки на границах твинов стоят четыре
            # минуты из пяти (34 с против 4 м 8 с на том же проекте), а то же
            # место плотнее закрывает наша проба — она снимает живой DOM каждые
            # 0,25 с.
            #
            # Судим по полю `ok` отчёта, а не по коду выхода — почему,
            # сказано у `_check_verdict`. Их процесс тем не менее возвращает
            # код 1 всегда, когда `report.ok` ложно (`check.ts:144` →
            # `checkPipeline.ts:1228`) — а под `--strict` это ЛЮБОЕ
            # предупреждение, включая коды из `CHECK_IGNORED_CODES`, которые
            # для нас больше не провал (см. докстроку `_check_ok`). Раньше
            # код здесь принимал «процесс упал» за «FAIL» напрямую — до
            # B2.5 это было верно (их `ok=false` и наш вердикт совпадали
            # всегда), а с игнор-листом разошлось: находка из
            # `CHECK_IGNORED_CODES` даёт их `ok=false` и код выхода 1, но наш
            # вердикт обязан остаться PASS. Поэтому вердикт всегда берём из
            # `_check_verdict` по отчёту — `_cli` пишет его на диск ДО того,
            # как бросить исключение, — а голый текст аварии показываем
            # только когда отчёта нет вовсе (их процесс не запустился или
            # рухнул до JSON).
            log = rdir / "check.json"
            try:
                # `--caption-zone` и `--frame-check` — их собственные гейты
                # конвейера, выключенные по умолчанию («Opt-in pipeline gates
                # (used by orchestrators; off by default)»,
                # hyperframes-cli/references/lint-validate-inspect.md). Первый
                # ловит содержимое, заехавшее в полосу титра, второй — медиа,
                # вылезшее за кадр. Полоса у нас начинается на
                # `CAPTION_BAND_TOP` из 1920, то есть с доли 0,52.
                #
                # Долю пишем без ведущего нуля: их парсер принимает `.52` и
                # отвергает `0.52` — «Invalid --caption-zone; use
                # "x0=0;y0=.82;..."» (проверено на 0.7.84).
                band = f"{CAPTION_BAND_TOP / OUT_H:.2f}".lstrip("0")
                _cli("check", "public", "--json", "--strict",
                     "--caption-zone",
                     f"x0=0;y0={band};x1=1;y1=1;severity=error",
                     "--at", ",".join(f"{time:g}" for time in
                                      _scene_midpoints(board)),
                     # `--frame-check` — последним: поставленный перед
                     # `--caption-zone`, он съедает его значение, и разбор
                     # падает «Invalid --caption-zone» (0.7.84, проверено
                     # вручную обоими порядками).
                     "--frame-check",
                     cwd=rdir, log=log)
            except RuntimeError as error:
                result["D0_check"] = (_check_verdict(log) if log.exists()
                                      else f"FAIL: их `check` не запустился — {error}")
            else:
                result["D0_check"] = _check_verdict(log)

            failed = [f"{k}: {v}" for k, v in result.items() if v.startswith("FAIL")]
            # Красные гейты больше не роняют ПОСЛЕДНЮЮ попытку (решение 05):
            # ведущая куплена, повторного плана не будет, и ролик с изъяном
            # доезжает до заказчика — вердикты остаются в `result`/`gates.json`
            # как есть, FAIL не прячется. На attempt-ах ДО последнего поведение
            # то же, что раньше: причина уходит агенту, план пересдаётся заново
            # (`continue` ниже, реализован падением сквозь `if`).
            if not failed or attempt == MAX_COMPOSE_ATTEMPTS - 1:
                gate_result = result
                (rdir / "gates.json").write_text(
                    json.dumps(result, ensure_ascii=False), encoding="utf-8")
                _marker(rdir, "gates").write_text("ok", encoding="utf-8")
                if failed:
                    # Причину кладём в папку и на пересдающей попытке: сюда
                    # больше не ведёт исключение, но `retry_reason.txt` — это
                    # ещё и след для человека, который откроет папку руками.
                    # Ниже, после рендера и громкости (около 1820), тот же файл
                    # перезапишется полным `gate_result` вместе с ритмом и
                    # зумом — здесь достаточно того, что уже посчитано.
                    save_retry_reason(rdir, "; ".join(failed))
                break
            reason = "; ".join(failed)

    # Снимки композиции перед рендером — обязательный шаг их же конвейера
    # (product-launch-video/SKILL.md:195-197): «snapshot stitches the captured
    # frames into one contact sheet (snapshots/contact-sheet.jpg). Inspect the
    # midpoint frames for layout failures». Четыре минуты рендера, чтобы
    # увидеть пустой кадр, — слишком дорогой способ это узнать.
    board = json.loads((rdir / "storyboard.json").read_text(encoding="utf-8"))
    run_step(rdir, "shots", lambda: _capture_shots(rdir, board, duration))

    raw = rdir / "reel.raw.mp4"
    run_step(rdir, "render", lambda: _render_or_die(rdir, raw))

    final = Path(out_mp4) if out_mp4 else rdir / "reel.mp4"
    run_step(rdir, "loudness", lambda: _normalize_loudness(raw, final))

    # Ритм меряем по готовому файлу: планка эталонов — про то, что видит
    # зритель, а раскадровка о смене картинки врать умеет.
    if gate_result is None:
        gate_result = json.loads((rdir / "gates.json").read_text(encoding="utf-8"))
    gate_result.update(rhythm_gates(final))
    # Наезды и вспышки меряются числами по готовому файлу, а не глазами: на
    # стоп-кадре наклон говорящей к камере читается как наезд, которого в
    # файле нет (грабля Юли, стоила двух сданных версий с мёртвым зумом).
    gate_result.update(zoom_gates(final, read_camera(rdir)))
    (rdir / "gates.json").write_text(
        json.dumps(gate_result, ensure_ascii=False), encoding="utf-8")
    # Отказ по готовому файлу цикл попыток уже не догоняет: чинит его человек
    # кнопкой продолжения, а сама пересдача случится в СЛЕДУЮЩЕМ прогоне.
    # Пройденные проверки запись снимают — иначе причина висела бы на папке
    # вечно и гоняла агента заново на каждом продолжении.
    save_retry_reason(rdir, "; ".join(
        f"{name}: {verdict}" for name, verdict in gate_result.items()
        if str(verdict).startswith("FAIL")))

    (rdir / "scenario.timed.json").write_text(
        json.dumps(timed_scenario, ensure_ascii=False, indent=1), encoding="utf-8")
    (rdir / "words.fixed.json").write_text(
        json.dumps(words, ensure_ascii=False, indent=1), encoding="utf-8")

    return {"mp4": str(final), "dur": duration, "timed_scenario": timed_scenario,
            "words_fixed": words, "gates": gate_result,
            # Расход берём из кошелька, а не из обёртки: обёрток за сборку
            # несколько (план на Sonnet 5, суд бироллов на Haiku 4.5), и каждая
            # знает только про себя.
            "agent_cost_usd": spend.total_cost_usd,
            "agent_runs": spend.runs}
