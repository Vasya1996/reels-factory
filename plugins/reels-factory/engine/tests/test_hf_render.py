"""Сборка разбита на шаги; провал гейтов запускает повтор."""
import json
from pathlib import Path

import pytest

from reels_factory.hf_render import STEPS, reset_step, run_step, step_done


def test_шаги_в_нужном_порядке():
    assert STEPS == ("prepare", "compose", "gates", "check", "render", "loudness")


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
    from reels_factory import hf_render

    calls = []

    def fake_cli(*args, cwd):
        calls.append(args)
        if args[0] == "render":
            Path(args[args.index("--output") + 1]).write_bytes(b"mp4")

    monkeypatch.setattr(hf_render, "_cli", fake_cli)
    monkeypatch.setattr(hf_render, "_normalize_loudness",
                        lambda src, dst: (dst.write_bytes(b"n"), dst)[1])
    monkeypatch.setattr(hf_render, "_place_clips", lambda public, *a, **k: [
        {"file": "clips/clip-00.mp4", "start": 0.0, "duration": 6.0, "media_start": 0.0}])
    monkeypatch.setattr(hf_render, "vendor_gsap", lambda public: public)
    monkeypatch.setattr(hf_render, "face_box_for",
                        lambda video, out, **k: {"cx": 540, "cy": 520, "h": 260})

    queue = list(storyboards)

    def fake_agent(rdir, *, runner=None):
        (Path(rdir) / "public").mkdir(parents=True, exist_ok=True)
        (Path(rdir) / "public" / "index.html").write_text("<html></html>", encoding="utf-8")
        board = queue.pop(0)
        (Path(rdir) / "storyboard.json").write_text(json.dumps(board), encoding="utf-8")
        return board

    monkeypatch.setattr(hf_render, "build_with_agent", fake_agent)
    (tmp_path / "src.mp4").write_bytes(b"")
    (tmp_path / "voice.wav").write_bytes(b"")
    (tmp_path / "face.json").write_text(json.dumps({"cx": 540, "cy": 520, "h": 260}),
                                        encoding="utf-8")
    return calls


PLAN = {"windows": [], "phrases": [], "log": [],
        "timeline": {"final_duration_seconds": 6.0}}
TIMED = {"total": 6.0, "blocks": [{"role": "hook", "start": 0.0, "end": 6.0,
                                   "speech": "кому продаём"}]}
GOOD = {"cards": []}
BAD = {"cards": [{"id": "c1", "startSec": 0.0, "endSec": 3.0, "zone": "video-overlay",
                  "contentRect": {"left": 200, "top": 400, "width": 700, "height": 300}}]}


def test_сборка_проходит_все_шаги(tmp_path, monkeypatch):
    from reels_factory import hf_render

    calls = _fakes(monkeypatch, tmp_path, [GOOD])
    res = hf_render.assemble_hyperframes(
        tmp_path, TIMED, edit_plan=PLAN, avatar_mp4s=[tmp_path / "src.mp4"],
        master_audio=tmp_path / "voice.wav",
        alignment_words=[{"start": 0.2, "end": 0.9, "text": "Кому"}])

    assert (tmp_path / "BRIEF.md").exists()
    assert (tmp_path / "public" / "words.json").exists()
    assert not any(a[0] == "transcribe" for a in calls)
    assert any(a[0] == "check" for a in calls)
    assert any(a[0] == "render" for a in calls)
    assert res["gates"]["D8_face"] == "PASS"
    assert Path(res["mp4"]).exists()


def test_провал_гейтов_вызывает_повтор(tmp_path, monkeypatch):
    from reels_factory import hf_render

    calls = _fakes(monkeypatch, tmp_path, [BAD, GOOD])
    # как будто прошлый прогон уже дошёл до конца — маркеры check/render/loudness
    # стоят ДО первой попытки этого запуска, на старой (непровалившейся) раскадровке
    (tmp_path / ".hf-check.done").write_text("ok", encoding="utf-8")
    (tmp_path / ".hf-render.done").write_text("ok", encoding="utf-8")
    (tmp_path / ".hf-loudness.done").write_text("ok", encoding="utf-8")

    res = hf_render.assemble_hyperframes(
        tmp_path, TIMED, edit_plan=PLAN, avatar_mp4s=[tmp_path / "src.mp4"],
        master_audio=tmp_path / "voice.wav", alignment_words=[])
    assert res["gates"]["D8_face"] == "PASS"
    assert "лицо" in (tmp_path / "BRIEF.md").read_text(encoding="utf-8")
    assert Path(res["mp4"]).exists()
    assert any(a[0] == "check" for a in calls)
    assert any(a[0] == "render" for a in calls)


def test_две_неудачи_подряд_роняют_сборку(tmp_path, monkeypatch):
    from reels_factory import hf_render

    _fakes(monkeypatch, tmp_path, [BAD, BAD])
    with pytest.raises(RuntimeError, match="лицо"):
        hf_render.assemble_hyperframes(
            tmp_path, TIMED, edit_plan=PLAN, avatar_mp4s=[tmp_path / "src.mp4"],
            master_audio=tmp_path / "voice.wav", alignment_words=[])


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
        alignment_words=[{"start": 0.2, "end": 0.9, "text": "Кому"}])

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
        master_audio=tmp_path / "voice.wav", alignment_words=[])
    assert len(capture_calls) == 1

    # маркер prepare остался — второй прогон не должен снова звать capture
    hf_render.reset_step(tmp_path, "compose")
    hf_render.assemble_hyperframes(
        tmp_path, TIMED, edit_plan=plan, avatar_mp4s=[tmp_path / "src.mp4"],
        master_audio=tmp_path / "voice.wav", alignment_words=[])
    assert len(capture_calls) == 1


def test_stock_материал_копируется_для_агента(tmp_path, monkeypatch):
    from reels_factory import hf_media, hf_render

    source = tmp_path / "resolved.webp"
    source.write_bytes(b"image")
    monkeypatch.setattr(
        hf_media, "resolve_stock", lambda query, out_dir: source
    )
    public = tmp_path / "public"
    plan = {
        "windows": [
            {
                "id": "window-002",
                "visual_intent": None,
                "material": {"kind": "stock", "query": "город ночью"},
            }
        ]
    }

    media = hf_render._prepare_material(plan, public, tmp_path)

    assert media == [
        {
            "file": "media/window-002-stock.webp",
            "window_id": "window-002",
            "what": "сток: город ночью",
        }
    ]
    assert (public / media[0]["file"]).read_bytes() == b"image"
