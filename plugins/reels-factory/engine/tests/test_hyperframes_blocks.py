"""HyperFrames-блоки: генерация HTML и рендер (runner мокается, без npx)."""
from pathlib import Path

import pytest

from reels_factory import hyperframes_blocks as hb
from reels_factory import revideo_render as rr


def test_build_task_list_html_содержит_пункты_и_длительность():
    html = hb.build_task_list_html("ЧТО ЗАКРЫТЬ", ["Ответы", "Письма", "Анализ"], 5.0)
    assert "ЧТО ЗАКРЫТЬ" in html
    for label in ("Ответы", "Письма", "Анализ"):
        assert label in html
    assert 'data-duration="5.0"' in html
    assert 'window.__timelines["main"]' in html


def test_build_task_list_последний_пункт_акцентный():
    html = hb.build_task_list_html("T", ["a", "b", "c", "+ ещё"], 5.0)
    assert "row more" in html          # «+»-пункт помечен как акцентная строка


def test_build_task_list_экранирует_html():
    html = hb.build_task_list_html("T", ["<script>x</script>"], 4.0)
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html


def test_build_task_list_режет_до_5():
    html = hb.build_task_list_html("T", [f"i{k}" for k in range(9)], 6.0)
    assert html.count('class="row') == 5


def test_render_block_пишет_html_и_зовёт_runner(tmp_path):
    calls = {}

    def fake_runner(project, out, timeout):
        calls["project"] = project
        calls["out"] = out
        out.write_bytes(b"mp4")

    out = tmp_path / "clip.mp4"
    res = hb.render_block("task_list", {"title": "T", "items": ["a", "b", "c"]}, 5.0,
                          out, runner=fake_runner)
    assert res == out and out.exists()
    # index.html блока записан
    assert (hb.HF_DIR / "task_list" / "index.html").exists()
    assert calls["out"] == out.resolve()


def test_render_block_неизвестный_блок():
    with pytest.raises(ValueError):
        hb.render_block("нет-такого", {}, 5.0, "x.mp4", runner=lambda *a: None)


def test_render_block_падение_рендера_пробрасывается(tmp_path):
    def broken(project, out, timeout):
        raise RuntimeError("npx умер")
    with pytest.raises(RuntimeError):
        hb.render_block("task_list", {"title": "T", "items": ["a"]}, 5.0,
                        tmp_path / "c.mp4", runner=broken)


# ---- интеграция в revideo_render ----

def _hf_seg():
    return {"id": 7, "start": 17.0, "end": 23.0, "caption": "hidden",
            "effect": {"type": "chart_bars", "title": "T", "items": [],
                       "hyperframes": {"block": "task_list",
                                       "variables": {"title": "T", "items": ["a", "b", "c"]}}}}


def test_resolve_hyperframes_конвертит_в_fullscreen_broll(tmp_path):
    seg = _hf_seg()

    def fake_render(block, variables, duration, out_path):
        out_path.write_bytes(b"mp4")
        return out_path

    rr._resolve_hyperframes_segment(seg, tmp_path, hf_render=fake_render)
    eff = seg["effect"]
    assert eff["type"] == "broll" and eff["style"] == "fullscreen"
    assert eff["src"] == "hf_7.mp4"
    assert seg["caption"] == "hidden"
    assert (tmp_path / "hf_7.mp4").exists()


def test_resolve_hyperframes_фолбэк_на_ошибке(tmp_path):
    seg = _hf_seg()

    def broken(block, variables, duration, out_path):
        raise RuntimeError("нет node")

    rr._resolve_hyperframes_segment(seg, tmp_path, hf_render=broken)
    # эффект НЕ тронут — chart_bars остаётся как фолбэк
    assert seg["effect"]["type"] == "chart_bars"


def test_resolve_hyperframes_игнорит_обычные_сегменты(tmp_path):
    seg = {"id": 1, "start": 0, "end": 3, "effect": {"type": "none"}, "caption": "bottom"}
    rr._resolve_hyperframes_segment(seg, tmp_path, hf_render=lambda *a: None)
    assert seg["effect"]["type"] == "none"


# ---- stat_number / before_after билдеры ----

def test_build_stat_number_запекает_число_и_подписи():
    html = hb.build_stat_number_html(4.0, 42, prefix="×", suffix="%",
                                     label_top="рост", label_bottom="в месяц")
    assert "const target = 42;" in html
    assert 'data-duration="4.0"' in html
    assert "рост" in html and "в месяц" in html
    assert ">×<" in html or "×" in html


def test_build_stat_number_нечисло_в_ноль():
    html = hb.build_stat_number_html(4.0, "abc")
    assert "const target = 0;" in html


def test_build_before_after_запекает_значения():
    html = hb.build_before_after_html(4.5, "3 часа", "1 клик",
                                      before_label="было", after_label="стало")
    assert "3 часа" in html and "1 клик" in html
    assert 'data-duration="4.5"' in html


def test_build_before_after_экранирует():
    html = hb.build_before_after_html(4.0, "<b>x</b>", "y")
    assert "<b>x</b>" not in html and "&lt;b&gt;" in html


def test_blocks_реестр_содержит_все_три():
    assert set(hb.BLOCKS) == {"task_list", "stat_number", "before_after"}


def test_render_block_stat_number_мок(tmp_path):
    def fake(project, out, timeout):
        out.write_bytes(b"mp4")
    out = tmp_path / "s.mp4"
    hb.render_block("stat_number", {"value": 10}, 4.0, out, runner=fake)
    assert out.exists()
    assert (hb.HF_DIR / "stat_number" / "index.html").exists()
