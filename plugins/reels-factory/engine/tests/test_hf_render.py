"""Сборка разбита на шаги; провал гейтов запускает повтор."""
import json
from pathlib import Path

import pytest

from reels_factory.hf_render import STEPS, reset_step, run_step, step_done


def test_шаги_в_нужном_порядке():
    assert STEPS == ("prepare", "plan", "compose", "gates", "render", "loudness")


def test_маркер_отмечает_шаг(tmp_path):
    assert step_done(tmp_path, "compose") is False
    run_step(tmp_path, "compose", lambda: None)
    assert step_done(tmp_path, "compose") is True
    reset_step(tmp_path, "compose")
    assert step_done(tmp_path, "compose") is False


def test_сделанный_шаг_не_повторяется(tmp_path):
    calls = []
    run_step(tmp_path, "render", lambda: calls.append(1))
    run_step(tmp_path, "render", lambda: calls.append(2))
    assert calls == [1]


def test_упавший_шаг_не_отмечается(tmp_path):
    with pytest.raises(RuntimeError):
        run_step(tmp_path, "check", lambda: (_ for _ in ()).throw(RuntimeError("упал")))
    assert step_done(tmp_path, "check") is False


def _fakes(monkeypatch, tmp_path, storyboards):
    from contextlib import contextmanager

    from reels_factory import hf_render

    calls = []

    def fake_cli(*args, cwd, log=None):
        calls.append(args)
        if args[0] == "render":
            Path(args[args.index("--output") + 1]).write_bytes(b"mp4")
        return ""

    monkeypatch.setattr(hf_render, "_cli", fake_cli)
    monkeypatch.setattr(hf_render, "_normalize_loudness",
                        lambda src, dst: (dst.write_bytes(b"n"), dst)[1])
    monkeypatch.setattr(hf_render, "_place_clips", lambda public, *a, **k: [
        {"file": "clips/clip-00.mp4", "start": 0.0, "duration": 20.0,
         "media_start": 0.0}])
    monkeypatch.setattr(hf_render, "vendor_gsap", lambda public: public)
    monkeypatch.setattr(hf_render, "face_box_for",
                        lambda video, out, **k: {"cx": 540, "cy": 520, "h": 260})
    monkeypatch.setattr(hf_render, "inject_fonts", lambda public, **k: [])

    # Каталог и проба живой композиции требуют реестра на диске и браузера —
    # здесь проверяется поток сборки, а не они сами.
    @contextmanager
    def fake_catalog():
        yield "http://127.0.0.1:0"

    monkeypatch.setattr(hf_render, "serve_catalog", fake_catalog)
    monkeypatch.setattr(hf_render, "probe_gates",
                        lambda rdir, **k: {"D8_face": "PASS",
                                           "D14_presenter_moves": "PASS",
                                           "D15_catalog_blocks": "PASS",
                                           "D17_service_text": "PASS"})
    monkeypatch.setattr(hf_render.hf_captions, "stage", lambda rdir: rdir)
    monkeypatch.setattr(hf_render, "_install_blocks", lambda rdir, names: None)
    monkeypatch.setattr(hf_render, "collect_intents", lambda sdk, public, board: [])
    monkeypatch.setattr(hf_render, "resolve_all", lambda public, requests: {})
    monkeypatch.setattr(hf_render, "rhythm_gates",
                        lambda mp4: {"D18_change_rate": "PASS",
                                     "D19_static_span": "PASS"})

    def fake_build(rdir, sdk, *, storyboard, clips, duration, words,
                   resolved=None):
        public = Path(rdir) / "public"
        (public / "media").mkdir(parents=True, exist_ok=True)
        (public / "media" / "hands.jpg").write_bytes(b"\xff\xd8\xff")
        (Path(rdir) / ".media").mkdir(exist_ok=True)
        (Path(rdir) / ".media" / "manifest.jsonl").write_text(
            '{"type":"image"}\n', encoding="utf-8")
        target = public / "index.html"
        target.write_text(
            '<html><body><img src="media/hands.jpg"></body></html>',
            encoding="utf-8")
        return target

    monkeypatch.setattr(hf_render, "build_composition", fake_build)

    @contextmanager
    def fake_sdk():
        yield None

    monkeypatch.setattr(hf_render, "sdk_session", fake_sdk)

    queue = list(storyboards)

    def fake_agent(rdir, *, runner=None):
        (Path(rdir) / "public").mkdir(parents=True, exist_ok=True)
        # Свой экземпляр на каждый вызов: настоящий агент пишет файл, и сборка
        # читает его с диска — общего объекта между попытками не бывает.
        board = json.loads(json.dumps(queue.pop(0)))
        (Path(rdir) / "storyboard.json").write_text(json.dumps(board), encoding="utf-8")
        return board

    monkeypatch.setattr(hf_render, "plan_with_agent", fake_agent)
    (tmp_path / "src.mp4").write_bytes(b"")
    (tmp_path / "voice.wav").write_bytes(b"")
    (tmp_path / "face.json").write_text(json.dumps({"cx": 540, "cy": 520, "h": 260}),
                                        encoding="utf-8")
    return calls


PLAN = {"windows": [], "phrases": [], "log": [],
        "timeline": {"final_duration_seconds": 20.0}}

# Десять коротких предложений: `_phrase_spans` режет по сильной пунктуации от
# трёх слов, значит каждое становится своей фразой, и агенту есть что называть.
_SENTENCES = ["Мы продаём людям.", "Мы решаем боль.", "Мы даём результат.",
              "Порядок тут решает.", "Сначала спроси кому.", "Потом спроси что.",
              "И только как.", "Всё прочее вторично.", "Сохрани это видео.",
              "Прогони свой продукт."]
TIMED = {"total": 20.0,
         "blocks": [{"role": "hook", "start": 0.0, "end": 20.0,
                     "speech": " ".join(_SENTENCES)}]}

# Слова идут ровно по сценарию — так их отдаёт синтез (alignment_to_words).
WORDS = []
for _i, _w in enumerate(" ".join(_SENTENCES).split()):
    WORDS.append({"start": round(_i * 0.6, 3), "end": round(_i * 0.6 + 0.5, 3),
                  "text": _w})


def _board(cards):
    return {"schemaVersion": 3,
            "composition": {"fps": 30, "width": 1080, "height": 1920,
                            "durationSeconds": 20.0, "layout": "portrait"},
            "videoTrack": {"sourcePath": "clips/clip-00.mp4", "startSec": 0,
                           "endSec": 20.0,
                           "bounds": {"x": 0, "y": 0, "width": 1080, "height": 1920}},
            "subtitles": {"enabled": True},
            "cards": cards}


# Карточки на нечётных фразах: чётные остаются свободными, и на них зритель
# видит ведущую — иначе смена картинки не считается (гейт D21).
GOOD = _board([{"id": f"c{i}", "intent": "зачем", "accentIndex": 0,
                "phrases": [i * 2 + 1, i * 2 + 1],
                "contentHints": {"title": "Т"},
                "render": {"kind": "block", "block": "g99-demo"}}
               for i in range(5)])
# Наше прежнее поле сверх схемы: соблюсти его и videoTrack.bounds разом нельзя.
BAD = _board([{"id": "c1", "intent": "зачем", "accentIndex": 0,
               "phrases": [1, 3], "contentHints": {"title": "Т"},
               "contentRect": {"left": 200, "top": 400, "width": 700, "height": 300}}])


def test_сборка_проходит_все_шаги(tmp_path, monkeypatch):
    from reels_factory import hf_render

    calls = _fakes(monkeypatch, tmp_path, [GOOD])
    res = hf_render.assemble_hyperframes(
        tmp_path, TIMED, edit_plan=PLAN, avatar_mp4s=[tmp_path / "src.mp4"],
        master_audio=tmp_path / "voice.wav",
        alignment_words=WORDS)

    assert (tmp_path / "BRIEF.md").exists()
    assert (tmp_path / "public" / "words.json").exists()
    assert not any(a[0] == "transcribe" for a in calls)
    assert any(a[0] == "check" for a in calls)
    assert any(a[0] == "render" for a in calls)
    assert res["gates"]["D8_face"] == "PASS"
    assert Path(res["mp4"]).exists()
    # каталог прописан до того, как агента позвали
    assert (tmp_path / "hyperframes.json").exists()


def test_провал_гейтов_вызывает_повтор(tmp_path, monkeypatch):
    from reels_factory import hf_render

    calls = _fakes(monkeypatch, tmp_path, [BAD, GOOD])
    # как будто прошлый прогон уже дошёл до конца — маркеры render/loudness
    # стоят ДО первой попытки этого запуска, на старой (непровалившейся) раскадровке
    (tmp_path / ".hf-render.done").write_text("ok", encoding="utf-8")
    (tmp_path / ".hf-loudness.done").write_text("ok", encoding="utf-8")

    res = hf_render.assemble_hyperframes(
        tmp_path, TIMED, edit_plan=PLAN, avatar_mp4s=[tmp_path / "src.mp4"],
        master_audio=tmp_path / "voice.wav", alignment_words=WORDS)
    assert res["gates"]["D11_schema"] == "PASS"
    assert "contentRect" in (tmp_path / "BRIEF.md").read_text(encoding="utf-8")
    assert Path(res["mp4"]).exists()
    assert any(a[0] == "check" for a in calls)
    assert any(a[0] == "render" for a in calls)


def test_находки_их_проверки_отправляют_на_повтор(tmp_path, monkeypatch):
    """Текст за полями или на лице их `check` видит, а мы — нет. Значит его
    вердикт обязан доходить до агента, а не ронять сборку."""
    from reels_factory import hf_render

    calls = _fakes(monkeypatch, tmp_path, [GOOD, GOOD])
    real_cli = hf_render._cli
    checks = []

    def flaky_cli(*args, cwd, log=None):
        if args[0] == "check":
            checks.append(args)
            if len(checks) == 1:
                raise RuntimeError("hyperframes check упал (1): canvas_overflow")
        return real_cli(*args, cwd=cwd, log=log)

    monkeypatch.setattr(hf_render, "_cli", flaky_cli)

    res = hf_render.assemble_hyperframes(
        tmp_path, TIMED, edit_plan=PLAN, avatar_mp4s=[tmp_path / "src.mp4"],
        master_audio=tmp_path / "voice.wav", alignment_words=WORDS)

    assert len(checks) == 2
    assert "canvas_overflow" in (tmp_path / "BRIEF.md").read_text(encoding="utf-8")
    assert Path(res["mp4"]).exists()
    assert any(a[0] == "render" for a in calls)


def test_две_неудачи_подряд_роняют_сборку(tmp_path, monkeypatch):
    from reels_factory import hf_render

    _fakes(monkeypatch, tmp_path, [BAD, BAD])
    with pytest.raises(RuntimeError, match="схемой не предусмотрено"):
        hf_render.assemble_hyperframes(
            tmp_path, TIMED, edit_plan=PLAN, avatar_mp4s=[tmp_path / "src.mp4"],
            master_audio=tmp_path / "voice.wav", alignment_words=WORDS)


def test_окно_с_материалом_снимает_сайт_или_маршрут(tmp_path, monkeypatch):
    """prepare вызывает capture_site/screen_route для окон с полем material
    и кладёт результат в public/media — агенту искать материал не надо."""
    from reels_factory import capture_site, hf_render, screen_route

    calls = _fakes(monkeypatch, tmp_path, [GOOD])

    def fake_cached_capture(url, cache_dir):
        shots_dir = Path(cache_dir) / "shots"
        shots_dir.mkdir(parents=True, exist_ok=True)
        shot = shots_dir / "scroll-000.png"
        shot.write_bytes(b"png")
        return {"dir": str(shots_dir), "screenshots": [str(shot)], "page": ""}

    def fake_record_route(steps, out_mp4, **kw):
        out_mp4 = Path(out_mp4)
        out_mp4.parent.mkdir(parents=True, exist_ok=True)
        out_mp4.write_bytes(b"mp4")
        return out_mp4

    monkeypatch.setattr(capture_site, "cached_capture", fake_cached_capture)
    monkeypatch.setattr(screen_route, "record_route", fake_record_route)

    plan = {
        "windows": [
            {"id": "window-000", "visual_intent": "Показать интерфейс",
             "material": {"kind": "site", "url": "https://elevenlabs.io"}},
            {"id": "window-001", "visual_intent": None,
             "material": {"kind": "route",
                          "steps": [{"type": "goto", "url": "https://www.google.com"}]}},
        ],
        "phrases": [], "log": [],
        "timeline": {"final_duration_seconds": 6.0},
    }

    hf_render.assemble_hyperframes(
        tmp_path, TIMED, edit_plan=plan, avatar_mp4s=[tmp_path / "src.mp4"],
        master_audio=tmp_path / "voice.wav",
        alignment_words=WORDS)

    media = json.loads((tmp_path / "media.json").read_text(encoding="utf-8"))
    by_window = {item["window_id"]: item for item in media}
    assert (tmp_path / "public" / by_window["window-000"]["file"]).exists()
    assert (tmp_path / "public" / by_window["window-001"]["file"]).exists()
    assert by_window["window-000"]["what"] == "Показать интерфейс"
    assert by_window["window-001"]["what"] == "запись маршрута"


def test_повторный_prepare_не_снимает_материал_заново(tmp_path, monkeypatch):
    """Маркер шага prepare делает capture/record одноразовыми: перезапуск
    сборки читает media.json, а не снимает сайт заново."""
    from reels_factory import capture_site, hf_render, screen_route

    _fakes(monkeypatch, tmp_path, [GOOD, GOOD])
    capture_calls = []
    monkeypatch.setattr(capture_site, "cached_capture",
                        lambda url, cache_dir: capture_calls.append(url) or {
                            "screenshots": []})
    monkeypatch.setattr(screen_route, "record_route",
                        lambda steps, out_mp4, **kw: capture_calls.append("route") or Path(out_mp4))

    plan = {
        "windows": [{"id": "window-000", "visual_intent": "Показать сайт",
                     "material": {"kind": "site", "url": "https://elevenlabs.io"}}],
        "phrases": [], "log": [],
        "timeline": {"final_duration_seconds": 6.0},
    }

    hf_render.assemble_hyperframes(
        tmp_path, TIMED, edit_plan=plan, avatar_mp4s=[tmp_path / "src.mp4"],
        master_audio=tmp_path / "voice.wav", alignment_words=WORDS)
    assert len(capture_calls) == 1

    # маркер prepare остался — второй прогон не должен снова звать capture
    hf_render.reset_step(tmp_path, "compose")
    hf_render.assemble_hyperframes(
        tmp_path, TIMED, edit_plan=plan, avatar_mp4s=[tmp_path / "src.mp4"],
        master_audio=tmp_path / "voice.wav", alignment_words=WORDS)
    assert len(capture_calls) == 1
