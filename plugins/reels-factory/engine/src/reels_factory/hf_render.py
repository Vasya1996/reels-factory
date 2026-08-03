"""Сборка ролика движком HyperFrames, разбитая на возобновляемые шаги.

Длинная агентская сессия может оборваться посреди работы — это наблюдалось.
Каждый шаг пишет файл-маркер, повторный запуск подхватывает с места обрыва.

Шаг громкости пишет НОВЫЙ файл, а не заменяет исходный: иначе обрыв между
заменой и записью маркера привёл бы к повторной нормализации.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from reels_factory.compose import VENC
from reels_factory.config import FFMPEG, FPS, LUFS_TARGET, OUT_H, OUT_W, TP_TARGET
from reels_factory.face_detect import face_box_for, load_face
from reels_factory.hf_agent import build_with_agent
from reels_factory.hf_assets import vendor_gsap
from reels_factory.hf_brief import write_brief
from reels_factory.hf_catalog import serve_catalog, write_project_config
from reels_factory.hf_fonts import inject_fonts
from reels_factory.hf_gates import check_media, check_storyboard
from reels_factory.hf_layout import quantize
from reels_factory.hf_probe import probe_gates
from reels_factory.hyperframes_blocks import _HF_VERSION

STEPS = ("prepare", "compose", "gates", "check", "render", "loudness")
MAX_COMPOSE_ATTEMPTS = 2

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
    return [{"start": round(float(w["start"]), 3),
             "end": round(float(w["end"]), 3),
             "text": str(w.get("text") or w.get("word") or "")} for w in words]


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


def assemble_hyperframes(rdir, timed_scenario: dict, *, edit_plan: dict,
                         avatar_mp4s: list, master_audio, alignment_words: list,
                         avatar_render_plan: dict | None = None,
                         out_mp4=None, agent_runner=None) -> dict:
    """Материал -> агент под скилами -> гейты -> рендер -> громкость."""
    rdir = Path(rdir).resolve()
    public = rdir / "public"
    words = _normalize_words(alignment_words)
    duration = quantize(float(timed_scenario.get("total") or 0.0))

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
        write_brief(rdir, scenario=timed_scenario, face=load_face(rdir),
                    duration=duration, clips=clips)
        (rdir / "clips.json").write_text(
            json.dumps(clips, ensure_ascii=False, indent=1), encoding="utf-8")
        # media.json задание больше не читает: вставки агент ищет сам через
        # media-use. Файл остаётся как след того, что план успел положить в
        # public/ — на него смотрят при разборе прогона.
        (rdir / "media.json").write_text(
            json.dumps(media, ensure_ascii=False, indent=1), encoding="utf-8")

    run_step(rdir, "prepare", prepare)

    saved_clips = json.loads((rdir / "clips.json").read_text(encoding="utf-8"))

    gate_result, reason = None, None
    # Каталог поднимаем на всё время сборки: агент ходит в него и когда смотрит
    # `hyperframes catalog`, и когда ставит блок через `add`.
    with serve_catalog() as registry_url:
        write_project_config(rdir, registry_url)
        for attempt in range(MAX_COMPOSE_ATTEMPTS):
            if reason is not None:
                reset_step(rdir, "compose")
                reset_step(rdir, "gates")
                reset_step(rdir, "check")
                reset_step(rdir, "render")
                reset_step(rdir, "loudness")
                write_brief(rdir, scenario=timed_scenario, face=load_face(rdir),
                            duration=duration, clips=saved_clips,
                            retry_reason=reason)

            board = run_step(rdir, "compose",
                             lambda: build_with_agent(rdir, runner=agent_runner))
            if board is None:
                board = json.loads(
                    (rdir / "storyboard.json").read_text(encoding="utf-8"))

            # Шрифты врезаем до всех проверок: и наши гейты, и их `check` меряют
            # переполнение и перекрытие по отрисованному тексту, а без наших
            # @font-face кириллица считалась бы по подменному шрифту — судили бы
            # не тот текст, что увидит зритель. Вызов идемпотентен, поэтому
            # переживает и возобновление, и повторную сборку.
            inject_fonts(rdir / "public", work_dir=rdir)

            result = check_storyboard(board, clips=saved_clips, duration=duration)
            result.update(check_media(rdir))
            # Композиция, которая не открывается, — это тоже провал сборки, а не
            # авария движка: агенту есть что чинить, и он получит причину.
            try:
                result.update(probe_gates(rdir, face=load_face(rdir)))
            except RuntimeError as error:
                result["D8_face"] = f"FAIL: {error}"
            failed = [f"{k}: {v}" for k, v in result.items() if v.startswith("FAIL")]
            if not failed:
                # Их проверка идёт внутри цикла, а не после него: её находки —
                # это то, что агент умеет починить сам, и повтор ради них
                # дешевле ролика с текстом за полями. `--snapshots` кладёт
                # кадры (судить монтаж по кадрам — единственный честный
                # способ), `--at-transitions` добавляет выборки на границах
                # твинов: на девяти равномерных точках стык не поймать.
                try:
                    run_step(rdir, "check",
                             lambda: _cli("check", "public", "--snapshots",
                                          "--at-transitions", "--json",
                                          cwd=rdir, log=rdir / "check.json"))
                except RuntimeError as error:
                    failed = [str(error)]
                else:
                    gate_result = result
                    (rdir / "gates.json").write_text(
                        json.dumps(result, ensure_ascii=False), encoding="utf-8")
                    _marker(rdir, "gates").write_text("ok", encoding="utf-8")
                    break
            reason = "; ".join(failed)
            if attempt == MAX_COMPOSE_ATTEMPTS - 1:
                raise RuntimeError("сборка не прошла проверки — " + reason)

    raw = rdir / "reel.raw.mp4"
    run_step(rdir, "render",
             lambda: _cli("render", "public", "--output", str(raw),
                          "--fps", str(FPS), "--quality", "standard", cwd=rdir))

    final = Path(out_mp4) if out_mp4 else rdir / "reel.mp4"
    run_step(rdir, "loudness", lambda: _normalize_loudness(raw, final))

    (rdir / "scenario.timed.json").write_text(
        json.dumps(timed_scenario, ensure_ascii=False, indent=1), encoding="utf-8")
    (rdir / "words.fixed.json").write_text(
        json.dumps(words, ensure_ascii=False, indent=1), encoding="utf-8")

    return {"mp4": str(final), "dur": duration, "timed_scenario": timed_scenario,
            "words_fixed": words, "gates": gate_result,
            "agent_cost_usd": getattr(agent_runner, "total_cost_usd", 0.0)}
