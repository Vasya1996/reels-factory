"""Сборка ролика движком HyperFrames, разбитая на возобновляемые шаги.

Длинная агентская сессия может оборваться посреди работы — это наблюдалось.
Каждый шаг пишет файл-маркер, повторный запуск подхватывает с места обрыва.

Шаг громкости пишет НОВЫЙ файл, а не заменяет исходный: иначе обрыв между
заменой и записью маркера привёл бы к повторной нормализации.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from reels_factory import hf_captions
from reels_factory.compose import VENC
from reels_factory.config import (
    FFMPEG, FPS, LUFS_TARGET, OUT_H, OUT_W, TP_TARGET, cli_env,
)
from reels_factory.editplan import MAX_FACE_ABSENCE_S, MIN_FULLSCREEN_S
from reels_factory.face_detect import face_box_for, load_face
from reels_factory.hf_agent import (
    AgentPlanMissing, AgentSpend, HeyGenAgentRunner, plan_with_agent,
)
from reels_factory.hf_assets import vendor_gsap
from reels_factory.hf_brief import POSITIONS, write_brief
from reels_factory.hf_catalog import (
    overlay_passports as catalog_overlay_passports, serve_catalog,
    write_project_config,
)
from reels_factory.hf_compose import (
    CAPTION_BAND_TOP, build_composition, clear_generated, collect_intents,
    complete_storyboard, icon_intents, needed_blocks, schema_intents,
    settle_fillers, settle_inserts,
)
from reels_factory.hf_fonts import inject_fonts
from reels_factory.hf_frame import read_frame
from reels_factory.hf_gates import (
    check_media, check_placeholders, check_storyboard,
)
from reels_factory.hf_layout import FULL_FRAME_PRESENTER, quantize
from reels_factory.hf_media import resolve_all
from reels_factory.hf_montage import (
    check_inserts, check_shots, dedupe_neighbours, drop_series,
    inserts_shortfall, inserts_wanted,
    merge_adjacent_series, pick_series, settle_schemas, show_ordered_avatar,
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


def last_retry_reason(rdir) -> str | None:
    """Причина, с которой прошлый прогон этой папки ушёл в отказ."""
    try:
        text = (Path(rdir) / RETRY_REASON_FILE).read_text(encoding="utf-8")
    except OSError:
        return None
    return text.strip() or None


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


def _normalize_loudness(src: Path, dst: Path) -> Path:
    subprocess.run(
        [FFMPEG, "-y", "-i", str(src),
         "-af", f"loudnorm=I={LUFS_TARGET}:TP={TP_TARGET}:LRA=11",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
         "-movflags", "+faststart", str(dst)],
        check=True, capture_output=True)
    return dst


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
    """Вердикт их `check` — по полю `ok` отчёта.

    Код выхода у `check` есть: по построению это `report.ok ? 0 : 1`
    (check.ts:144 → checkPipeline.ts:1228), а на аварии — единица
    (check.ts:154). Судим всё равно по полю `ok`: это та же формула
    `errorCount === 0 && (!strict || warningCount === 0)`
    (packages/cli/src/utils/checkPipeline.ts:1344) без слоёв npx и shell
    между нами и процессом, и отчёт всё равно нужен — из него берутся
    находки для агента. На 0.7.84 через npx код выхода дважды наблюдался
    нулевым при «Check failed» — где он терялся, не выяснено.
    """
    if not log.exists():
        return "FAIL: их `check` не оставил отчёта"
    try:
        report = json.loads(log.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "FAIL: отчёт их `check` не разбирается"
    if report.get("ok"):
        return "PASS"
    found = _check_findings(log)
    return "FAIL: " + "; ".join(found[:6] or ["без находок, но ok=false"])


def _scene_midpoints(board: dict) -> list[float]:
    """Точка замера каждой сцены для их проверки.

    Обычной сцене — середина. Сцене с накладкой — момент, когда блок отыграл
    вход: середина попадает в его незавершённый твин, и аудит честно видит
    там наложение текстов (content_overlap на lt-kicker-name, прогон 23) —
    но это кадр перехода, а не кадр, который видит зритель большую часть
    сцены. Их же конвейер по той же причине не бьёт по границам твинов.
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


def _order_phrases(scenes: list[dict], phrases: list[dict]) -> list[dict]:
    """Фразы в том виде, в каком их читает нарезка островов.

    Нарезке нужны ровно четыре вещи: покрытие, секунды, роль и пластика. Первые
    три известны уже здесь, а пластику назначает `editplan` позже, и на разбивку
    она влияет только различием: одинаковая пластика границы куска не создаёт
    (`_group_allowed` в `avatar_islands.py`). Поэтому всем фразам кладётся один
    и тот же профиль, и оценка выходит снизу — настоящий заказ режет куски там
    же, где мы, и вдобавок на сменах выразительности.
    """
    items = []
    for scene, own in _scene_phrases(scenes, phrases):
        covered = _avatar_ordered_scene(scene)
        for phrase in own:
            items.append({
                "id": phrase["id"],
                "index": phrase["id"],
                "role": phrase.get("role"),
                "coverage": "avatar" if covered else "full_broll",
                "final_timing": {"start": float(phrase["start"]),
                                 "end": float(phrase["end"])},
                "avatar_performance": {"expressiveness": "medium",
                                       "motion_prompt": ""},
            })
    return items


def _avatar_order_seconds(scenes: list[dict], phrases: list[dict],
                          duration: float, settings: dict) -> float:
    """Сколько секунд ведущей выставит HeyGen по этому плану.

    Меряем на ЗАКАЗЕ, а не на показе: клип покупается кусками, и с каждого
    края куска код докупает `handle_seconds`, а короткий кусок дорастает до
    `min_request_seconds` за счёт соседнего звука (`_request_timing` в
    `avatar_islands.py`) — доплаченное в ролик не попадает, но в счёт попадает.

    Арифметику берём у самого заказа, тремя его же функциями: непрерывные
    фразы с ведущей — остров (`_islands_from_phrases`), остров режется на куски
    (`_partition_island`), и КАЖДЫЙ кусок покупается отдельно со своей парой
    ручек (`_request_timing`). Прежний счёт брал остров целиком, и на острове
    из двух кусков гейт говорил PASS, а счёт приходил на пару ручек больше.

    Соседние сцены с ведущей дают один остров — ровно за это агенту сказано
    ставить сцены с ведущей подряд.
    """
    from reels_factory.avatar_islands import (
        _islands_from_phrases, _partition_island, _request_timing,
    )

    total = 0.0
    for island in _islands_from_phrases(_order_phrases(scenes, phrases)):
        try:
            groups = _partition_island(island, settings)
        except ValueError:
            # Разбить не удалось — считаем остров одним куском. Это оценка
            # снизу, и она честнее отказа: гейт судит план до заказа, а
            # настоящий отказ разбивки прилетит из самого заказа.
            groups = [island]
        for group in groups:
            total += _request_timing(
                float(group[0]["final_timing"]["start"]),
                float(group[-1]["final_timing"]["end"]),
                duration, settings)["duration"]
    return total


#: Чем открытие и финал закрывают кадр целиком. Пересечение полнокадровых
#: положений с закрытым списком, который задание вообще предлагает агенту
#: (`POSITIONS` в `hf_brief.py`): `overlay` кадр закрывает, но в списке его нет,
#: и проверка, принимающая его, мягче контракта — план с ним прошёл бы гейт до
#: заказа и упёрся бы в сборку, когда клипы уже куплены.
BOOKEND_PRESENTER = FULL_FRAME_PRESENTER & {name for name, *_ in POSITIONS}


#: Роли, которые ролик обязан говорить лицом. Прятать их запрещает валидатор
#: плана монтажа (`validate_edit_plan`, editplan.py:2558-2562), и запрет тот же
#: самый: сорванный на нём план роняет сборку, когда озвучка уже оплачена.
SPEAKING_ROLES = ("hook", "cta")

#: Запас к порогам, которые меряются по фразам. Наши фразы округлены к
#: миллисекунде, а валидатор меряет неокруглённые (`final_timing` в
#: `finalize_edit_plan`), поэтому фразу ровно на пороге гейт заворачивает: промах
#: в тысячную стоит всей сборки, а пересдача — одной сессии планировщика. Запас
#: идёт в обе стороны: к полу длительности фразы (D31) и к потолку куска без
#: лица (D32) — в обоих случаях в сторону строгости.
PHRASE_TIME_MARGIN = 0.002

#: Сколько непредсказанных швов оплачивает допуск бюджета. Наш счёт заказа
#: кладёт всем фразам одну пластику (`_order_phrases`), потому что на этом шаге
#: её ещё нет: `avatar_performance` назначает `editplan` позже. Настоящая
#: нарезка режет остров ещё и на сменах выразительности (`_group_allowed` в
#: `avatar_islands.py`), и каждый такой шов докупает по ручке с обеих сторон.
#: Смоделировать смену подачи нечем — данных нет, — поэтому цена швов отдаётся
#: допуску.
#:
#: Швов держим два. Раньше стоял один (замер давал 0,4 с при ручке 0,2 с), но
#: сплошной перебор расстановок показал расхождение до 1,95 с на быстрой речи:
#: заказ добирает секунды ещё и там, где код сам возвращает ведущую слишком
#: короткому куску (`_restore_short_faceless` в `avatar_islands.py`). Запас в
#: один шов такие планы заворачивал, хотя заказ по ним собирается.
_UNPREDICTED_SEAMS = 2


def _blind_stretches(scenes: list[dict],
                     phrases: list[dict]) -> list[dict]:
    """Куски ролика, идущие подряд без ведущей.

    Считаем так же, как валидатор плана монтажа: он ведёт отсчёт от начала
    первого окна без лица и сбрасывает его на первом же окне с ведущей
    (`validate_edit_plan`, editplan.py:2548-2556). Сцена без фраз ни отсчёта не
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
                      phrases: list[dict], settings: dict) -> dict:
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

    ordered = _avatar_order_seconds(scenes, phrases, duration, settings)
    budget = avatar_budget_targets(duration, settings)
    # Допуск островов на их собственном замере заказа
    # (`build_avatar_render_plan` в `avatar_islands.py`) — полпроцента
    # хронометража: это округления сетки кадров, а не перерасход. Здесь к нему
    # добавляется цена непредсказанных швов (`_UNPREDICTED_SEAMS`), по ручке с
    # каждой стороны шва.
    slack = (0.005 * duration
             + 2 * _UNPREDICTED_SEAMS * settings["handle_seconds"])
    # Запас прибавляется к НАШЕЙ оценке, а не к границе. Прежде он двигал
    # границу вверх, и объявленные 70 % на деле превращались в 71,9 %, а на
    # длинной ручке клиента — заметно больше: перебор поймал 106 принятых
    # планов выше объявленного потолка. Неуверенность в собственном счёте
    # должна стоить нам пересдачи, а не заказчику лишних секунд HeyGen.
    #
    # Судим по ГРАНИЦЕ, а не по ориентиру: ориентир 60 % — то, куда агенту
    # велено целиться, и промах по нему монтажа не портит, а пересдача стоит
    # новой сессии планировщика. Перебор расстановок показал, почему полоса
    # нужна: расстановка квантована сценой, соседние планы отличаются на целую
    # сцену (27,3 → 34,5 с на ролике 56,1 с), и ориентир 33,7 с стоял ровно в
    # провале между ступенями.
    if duration <= 0 or ordered + slack <= budget["hard_ceiling_seconds"]:
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
        result["D29_avatar_budget"] = (
            "FAIL: секунда ведущей — самая дорогая секунда ролика, и её "
            "бюджет меряется сложением длительностей фраз: у сцен с "
            f"`avatarNeeded: true` сейчас выходит {seconds(spoken_avatar)} из "
            f"{seconds(duration)} ролика, а целься в "
            f'{seconds(budget["target_seconds"])} — это то же число, что '
            "названо тебе в задании. Заказ выходит длиннее показа на ручки по "
            f"краям кусков, поэтому HeyGen выставит {seconds(ordered)}, и это "
            f'выше границы {seconds(budget["hard_ceiling_seconds"])}, за '
            "которой план не берут; в твоём счёте фразами та же граница — "
            f'{seconds(budget["hard_target_seconds"])}, и это то же число, что '
            "стоит пунктом сверки в задании. Отдай одну сцену из середины "
            "вставке или схеме, поставив ей `avatarNeeded: false`: хватит "
            "самой длинной, "
            "которая не несёт фраз ролей hook и cta. Сейчас с ведущей идут: "
            f"{paid}")

    # Роль тянется по фразам, а не по сценам, поэтому D28 её не ловит: он
    # смотрит только первую и последнюю сцену ролика, а хук занимает несколько
    # фраз и может уехать во вторую сцену.
    hidden_roles = []
    short = []
    for scene, own in _scene_phrases(scenes, phrases):
        if _avatar_ordered_scene(scene):
            continue
        name = str(scene.get("id", "?"))
        speaking = [phrase for phrase in own
                    if phrase.get("role") in SPEAKING_ROLES]
        if speaking:
            hidden_roles.append(
                f"{name} — " + ", ".join(
                    f'фраза {phrase["id"]} роли {phrase.get("role")}'
                    for phrase in speaking))
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

    result["D30_avatar_roles"] = "PASS" if not hidden_roles else (
        "FAIL: хук и призыв ролик говорит лицом. На первых секундах зритель "
        "решает, смотреть ли дальше, а призыву без лица он не верит, и заказ "
        "по плану, где эти фразы спрятаны, не состоится вовсе. Поставь этим "
        "сценам `avatarNeeded: true` либо отдай фразы ролей hook и cta "
        "соседней сцене с ведущей: " + "; ".join(hidden_roles))

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
    # editplan.py:2548-2556): план, где сцены без ведущей идут подряд дольше
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


def plan_before_avatar(rdir, timed_scenario: dict, *, alignment_words: list,
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

    Возвращает `{"board": план, "scenes": сцены с секундами, "gates": отчёт}` —
    по сценам считаются интервалы заказа, `gates` уезжает в отчёт по сборке.
    Фреймворка это не касается: заказ у HeyGen идёт до композиции, HyperFrames
    видит уже готовые клипы.
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
        return {"board": board, "scenes": scenes,
                "gates": _early_plan_gates(scenes, duration, phrases,
                                           settings)}

    try:
        passports = catalog_overlay_passports()
    except Exception as error:
        print(f"паспорта накладок не собрались: {error}")
        passports = ""

    board: dict = {}
    scenes: list[dict] = []
    gates: dict = {}
    reason = None
    with serve_catalog() as registry_url:
        write_project_config(rdir, registry_url)
        for attempt in range(MAX_PLAN_ATTEMPTS):
            write_brief(rdir, scenario=timed_scenario, face=None,
                        duration=duration, clips=[], phrases=phrases,
                        overlay_passports=passports, retry_reason=reason,
                        avatar_ordered=False, islands=islands)
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
            gates = _early_plan_gates(scenes, duration, phrases, settings)
            failed = [f"{key}: {value}" for key, value in gates.items()
                      if value.startswith("FAIL")]
            if not failed:
                break
            reason = "; ".join(failed)

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
    return {"board": board, "scenes": scenes, "gates": gates}


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

    # Паспорта их накладок — в задание. Собираются их SDK по каталогу; отказ
    # каталога не роняет сборку: агент просто останется без накладок.
    passports_cache: dict[str, str] = {}

    def _passports() -> str:
        if "text" not in passports_cache:
            try:
                passports_cache["text"] = catalog_overlay_passports()
            except Exception as error:
                print(f"паспорта накладок не собрались: {error}")
                passports_cache["text"] = ""
        return passports_cache["text"]

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
                    overlay_passports=_passports(), wishes=wishes)
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
                            overlay_passports=_passports(), wishes=wishes)

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
                if attempt == MAX_COMPOSE_ATTEMPTS - 1:
                    raise
                continue
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
            # с одним фоном.
            settle_schemas(board["scenes"])
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
                        found.update(resolve_all(
                            public, icons, context=board.get("brollContext"),
                            agent_spend=spend))
                    # Значок без файла и плашку с непригодным блоком
                    # снимаем здесь же: раньше их снимала сама сборка, то
                    # есть после разбора пустых сцен, и сцена, стоявшая на
                    # одном значке, доезжала до зрителя фоном с титром.
                    settle_fillers(board, found)
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
                        found.update(resolve_all(public, schema,
                                                 agent_spend=spend))
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
            # Судим по полю `ok` отчёта, а не по коду выхода — почему, сказано
            # у _check_verdict. Ненулевой код здесь всё же возможен, и тогда
            # _cli бросает RuntimeError: ветка except читает находки из того же
            # отчёта, оба пути сходятся.
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
                     cwd=rdir, log=rdir / "check.json")
                result["D0_check"] = _check_verdict(rdir / "check.json")
            except RuntimeError as error:
                result["D0_check"] = "FAIL: " + "; ".join(
                    _check_findings(rdir / "check.json") or [str(error)])

            failed = [f"{k}: {v}" for k, v in result.items() if v.startswith("FAIL")]
            if not failed:
                gate_result = result
                (rdir / "gates.json").write_text(
                    json.dumps(result, ensure_ascii=False), encoding="utf-8")
                _marker(rdir, "gates").write_text("ok", encoding="utf-8")
                break
            reason = "; ".join(failed)
            if attempt == MAX_COMPOSE_ATTEMPTS - 1:
                raise RuntimeError("сборка не прошла проверки — " + reason)

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
