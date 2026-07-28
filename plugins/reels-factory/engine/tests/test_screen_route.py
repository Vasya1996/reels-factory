"""Экранный маршрут: сценарий действий -> кадры -> видео."""
import pytest

from reels_factory.screen_route import build_script, validate_steps

STEPS = [
    {"type": "goto", "url": "https://google.com"},
    {"type": "type", "selector": "textarea[name=q]", "text": "hyperframes github"},
    {"type": "click", "selector": "h3"},
    {"type": "scroll", "pixels": 1200},
]


def test_неизвестный_шаг_отклоняется():
    with pytest.raises(ValueError, match="неизвестный шаг"):
        validate_steps([{"type": "танцевать"}])


def test_маршрут_обязан_начинаться_с_перехода():
    with pytest.raises(ValueError, match="переход"):
        validate_steps([{"type": "scroll", "pixels": 400}])


def test_пустой_маршрут_отклоняется():
    with pytest.raises(ValueError, match="пустой"):
        validate_steps([])


def test_сценарий_содержит_путь_к_браузеру_и_кадрам(tmp_path):
    script = build_script(STEPS, width=1080, height=1920,
                          browser_path="C:/chrome/chrome-headless-shell.exe",
                          frames_dir=tmp_path / "frames")
    assert "executablePath" in script and "chrome-headless-shell" in script
    assert "page.goto" in script and "hyperframes github" in script
    assert "1080" in script and "1920" in script
    assert "frames" in script
