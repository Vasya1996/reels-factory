"""CLI-обвязка (__main__): проверяем понятные JSON-ошибки без трейсбека.

_cmd_verify вызывается напрямую (без argparse/load_config) — DI через простой
объект args и cfg-словарь, как test_pipeline.py тестирует run_make напрямую.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import reels_factory.__main__ as cli


def test_verify_без_scenario_timed_чистая_ошибка(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "WORK_ROOT", tmp_path)
    wd = tmp_path / "demo"
    wd.mkdir()  # scenario.timed.json отсутствует

    args = SimpleNamespace(workdir="demo", mp4=None)

    with pytest.raises(SystemExit) as exc:
        cli._cmd_verify(args, {"theme": "кофе"})

    assert exc.value.code == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False
    assert "scenario.timed.json" in out["error"]
    assert "reels_factory make" in out["error"]


def test_verify_с_scenario_timed_работает(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "WORK_ROOT", tmp_path)
    wd = tmp_path / "demo"
    wd.mkdir()
    scenario = {"theme": "кофе", "total": 3.0, "blocks": [
        {"role": "hook", "start": 0.0, "end": 3.0, "speech": "кофе кислит"},
    ]}
    (wd / "scenario.timed.json").write_text(json.dumps(scenario, ensure_ascii=False),
                                             encoding="utf-8")

    def fake_verify(mp4, timed, words=None, hypothesis=None):
        return {"all_pass": True, "gates": {}}

    monkeypatch.setattr("reels_factory.verify.verify_reel", fake_verify)
    args = SimpleNamespace(workdir="demo", mp4=None)

    with pytest.raises(SystemExit) as exc:
        cli._cmd_verify(args, {"theme": "кофе"})

    assert exc.value.code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["all_pass"] is True
