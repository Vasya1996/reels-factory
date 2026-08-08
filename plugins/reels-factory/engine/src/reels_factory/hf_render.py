"""Сборка ролика движком HyperFrames, разбитая на возобновляемые шаги.

Длинная агентская сессия может оборваться посреди работы — это наблюдалось.
Каждый шаг пишет файл-маркер, повторный запуск подхватывает с места обрыва.

Шаг громкости пишет НОВЫЙ файл, а не заменяет исходный: иначе обрыв между
заменой и записью маркера привёл бы к повторной нормализации.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from reels_factory import hf_captions
from reels_factory.compose import VENC
from reels_factory.config import FFMPEG, FPS, LUFS_TARGET, OUT_H, OUT_W, TP_TARGET
from reels_factory.face_detect import face_box_for, load_face
from reels_factory.hf_agent import plan_with_agent
from reels_factory.hf_assets import vendor_gsap
from reels_factory.hf_brief import write_brief
from reels_factory.hf_catalog import serve_catalog, write_project_config
from reels_factory.hf_compose import (
    build_composition, clear_generated, collect_intents, complete_storyboard,
    needed_blocks, settle_inserts,
)
from reels_factory.hf_fonts import inject_fonts
from reels_factory.hf_gates import (
    check_media, check_placeholders, check_storyboard,
)
from reels_factory.hf_layout import quantize
from reels_factory.hf_media import resolve_all
from reels_factory.hf_phrases import (
    lay_out_scenes, phrase_timeline, speech_between,
)
from reels_factory.hf_probe import probe_gates
from reels_factory.hf_rhythm import rhythm_gates
from reels_factory.hf_sdk import sdk_session
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

STEPS = ("prepare", "plan", "compose", "gates", "shots", "render", "loudness")
MAX_COMPOSE_ATTEMPTS = 2

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


def run_step(rdir, step: str, fn):
    """Выполнить шаг, если он ещё не выполнен. Возвращает результат fn."""
    rdir = Path(rdir)
    if step_done(rdir, step):
        return None
    result = fn()
    _marker(rdir, step).write_text("ok", encoding="utf-8")
    return result


def _cli(*args: str, cwd, log: Path | None = None) -> str:
    """Вызов CLI движка. На Windows npx резолвится только через shell.

    Кавычим КАЖДЫЙ аргумент: пути содержат пробелы, а значения флагов —
    разделители, которые cmd.exe и батник npx.cmd разберут по-своему.
    """
    quoted = " ".join(f'"{a}"' for a in args)
    command = f'npx --yes hyperframes@{_HF_VERSION} {quoted}'
    result = subprocess.run(command, cwd=str(cwd), capture_output=True,
                            text=True, encoding="utf-8", errors="replace",
                            shell=True)
    output = result.stdout or ""
    if log is not None:
        # Их отчёт нужен целиком и после успеха тоже: предупреждения он не
        # считает провалом, а судить монтаж по ним всё равно приходится.
        Path(log).write_text(output or (result.stderr or ""), encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(
            f"hyperframes {args[0]} упал ({result.returncode}): "
            f"{(result.stderr or output)[:500]}")
    return output


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
        # кадру и частоте. Старый рендерер делал ровно это (revideo_render.py:142-168);
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
    """Середина каждой сцены. Число выборок считается от плана, а не назначается
    константой: сцен бывает и семь, и двадцать пять."""
    return sorted({round((float(scene["startSec"]) + float(scene["endSec"])) / 2, 3)
                   for scene in board.get("scenes") or []})


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


def assemble_hyperframes(rdir, timed_scenario: dict, *, edit_plan: dict,
                         avatar_mp4s: list, master_audio, alignment_words: list,
                         avatar_render_plan: dict | None = None,
                         out_mp4=None, agent_runner=None) -> dict:
    """Материал -> план агента -> сборка кодом -> гейты -> рендер -> громкость."""
    rdir = Path(rdir).resolve()
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
                    duration=duration, clips=clips, phrases=phrases)
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

    gate_result, reason = None, None
    # Каталог поднимаем на всё время сборки: `hyperframes add` ходит в него за
    # каждым блоком, который назвал агент.
    with serve_catalog() as registry_url:
        write_project_config(rdir, registry_url)
        for attempt in range(MAX_COMPOSE_ATTEMPTS):
            if reason is not None:
                for step in ("plan", "compose", "gates", "shots", "render",
                             "loudness"):
                    reset_step(rdir, step)
                write_brief(rdir, scenario=timed_scenario, face=load_face(rdir),
                            duration=duration, clips=saved_clips,
                            retry_reason=reason, phrases=phrases)

            board = run_step(rdir, "plan",
                             lambda: plan_with_agent(rdir, runner=agent_runner))
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
                requests = collect_intents(board)
                for request in requests:
                    scene = next((s for s in board.get("scenes") or []
                                  if str(s.get("id")) == request["key"]), {})
                    request["speech"] = speech_between(
                        phrases, float(scene.get("startSec", 0)),
                        float(scene.get("endSec", 0)))
                with sdk_session() as sdk:
                    found = resolve_all(public, requests,
                                        context=board.get("brollContext"))
                    lost = settle_inserts(board, found, saved_clips, duration,
                                          public=public)
                    if lost:
                        print(f"вставка не нашлась у сцен: {', '.join(lost)} — "
                              "ведущая там встала во весь кадр")
                    build_composition(rdir, sdk, storyboard=board,
                                      clips=saved_clips, duration=duration,
                                      words=words, resolved=found,
                                      sfx_whoosh=whoosh)
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
                _cli("check", "public", "--json", "--strict",
                     "--at", ",".join(f"{time:g}" for time in
                                      _scene_midpoints(board)),
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
    run_step(rdir, "render",
             lambda: _cli("render", "public", "--output", str(raw),
                          "--fps", str(FPS), "--quality", RENDER_QUALITY,
                          "--workers", RENDER_WORKERS, cwd=rdir))

    final = Path(out_mp4) if out_mp4 else rdir / "reel.mp4"
    run_step(rdir, "loudness", lambda: _normalize_loudness(raw, final))

    # Ритм меряем по готовому файлу: планка эталонов — про то, что видит
    # зритель, а раскадровка о смене картинки врать умеет.
    if gate_result is None:
        gate_result = json.loads((rdir / "gates.json").read_text(encoding="utf-8"))
    gate_result.update(rhythm_gates(final))
    (rdir / "gates.json").write_text(
        json.dumps(gate_result, ensure_ascii=False), encoding="utf-8")

    (rdir / "scenario.timed.json").write_text(
        json.dumps(timed_scenario, ensure_ascii=False, indent=1), encoding="utf-8")
    (rdir / "words.fixed.json").write_text(
        json.dumps(words, ensure_ascii=False, indent=1), encoding="utf-8")

    return {"mp4": str(final), "dur": duration, "timed_scenario": timed_scenario,
            "words_fixed": words, "gates": gate_result,
            "agent_cost_usd": getattr(agent_runner, "total_cost_usd", 0.0),
            "agent_runs": getattr(agent_runner, "runs", [])}
