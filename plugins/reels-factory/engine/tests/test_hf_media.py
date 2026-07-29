"""Сток/генерация через media-use: узкая сессия, кэш по запросу."""
from pathlib import Path

import pytest

from reels_factory import hf_media
from reels_factory.hf_media import resolve_stock


class _Runner:
    def __init__(self, make_file=True):
        self.make_file, self.prompts = make_file, []
        self.total_cost_usd = 0.0

    def run(self, prompt, cwd=None):
        self.prompts.append(prompt)
        if self.make_file:
            (Path(cwd) / "stock.png").write_bytes(b"png")
        return "готово"


@pytest.fixture
def local_cache(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    monkeypatch.setattr(hf_media, "stock_cache_dir", lambda: cache)
    return cache


def test_вход_через_media_use(tmp_path, local_cache):
    runner = _Runner()
    resolve_stock("нейросеть озвучка", tmp_path, runner=runner)
    assert runner.prompts and "/media-use" in runner.prompts[0]
    assert "нейросеть озвучка" in runner.prompts[0]
    assert "1080" in runner.prompts[0] and "1920" in runner.prompts[0]


def test_файл_возвращается_и_кэшируется(tmp_path, local_cache):
    runner = _Runner()
    first = resolve_stock("нейросеть озвучка", tmp_path, runner=runner)
    assert first.exists()
    second = resolve_stock("нейросеть озвучка", tmp_path, runner=runner)
    assert second == first
    assert len(runner.prompts) == 1, "кэш-хит не должен звать агента"


def test_разные_запросы_не_путаются(tmp_path, local_cache):
    runner = _Runner()
    first = resolve_stock("город ночью", tmp_path, runner=runner)
    second = resolve_stock("график роста", tmp_path, runner=runner)
    assert first != second


def test_сессия_без_файла_это_ошибка(tmp_path, local_cache):
    with pytest.raises(RuntimeError, match="media-use"):
        resolve_stock("пустота", tmp_path, runner=_Runner(make_file=False))
