"""CLI-обвязка (__main__): проверяем понятные JSON-ошибки без трейсбека.

_cmd_verify вызывается напрямую (без argparse/load_config) — DI через простой
объект args и cfg-словарь, как test_pipeline.py тестирует run_make напрямую.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import reels_factory.__main__ as cli
from reels_factory import clients, config as cfgmod


def _run(monkeypatch, capsys, *argv):
    """Запустить CLI как из командной строки: (exit-код, разобранный JSON)."""
    monkeypatch.setattr("sys.argv", ["reels_factory", *argv])
    code = 0
    try:
        cli.main()          # успех — обычный возврат, это и есть exit 0
    except SystemExit as e:
        code = e.code
    return code, json.loads(capsys.readouterr().out)


BASE_CFG = {
    "theme": "ИИ-агенты",
    "format": "avatar",
    "language": "ru",
    "voice_id": "V_BASE",
    "persona": {"description": "ведущий канала"},
    "product": {"name": "Prod"},
    "avatar": {"heygen_asset_id": "ASSET_BASE"},
}


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """Пустая рабочая папка пользователя: свой factory/ и свой реестр клиентов."""
    monkeypatch.chdir(tmp_path)
    factory = tmp_path / "factory"
    factory.mkdir()
    (factory / "config.yaml").write_text(
        yaml.safe_dump(BASE_CFG, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(cfgmod, "FACTORY_DIR", factory)
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", factory / "config.yaml")
    monkeypatch.setattr(clients, "CLIENTS_DIR", factory / "clients")
    monkeypatch.setattr(cli, "WORK_ROOT", tmp_path / "work")
    return tmp_path


@pytest.fixture
def фейковый_аплоад(monkeypatch):
    """HeyGen не зовём: тесты CLI не должны зависеть от сети."""
    calls = []

    def fake(image_path, api_key=None, http=None):
        calls.append(Path(image_path))
        return "img_123"

    monkeypatch.setattr("reels_factory.avatar.upload_photo_asset", fake)
    return calls


def _фото(tmp_path) -> str:
    p = tmp_path / "face.jpg"
    p.write_bytes(b"jpeg")
    return str(p)


def test_upload_photo_заводит_нового_клиента(workspace, фейковый_аплоад,
                                             monkeypatch, capsys):
    code, out = _run(monkeypatch, capsys, "upload-photo",
                     "--image", _фото(workspace), "--client", "kaz1")

    assert code == 0 and out["ok"] is True
    assert out["asset_id"] == "img_123" and out["mode"] == "photo"

    profile = yaml.safe_load(
        (workspace / "factory" / "clients" / "kaz1.yaml").read_text(encoding="utf-8"))
    assert profile["avatar"]["heygen_asset_id"] == "img_123"
    assert "heygen_look_id" not in profile["avatar"]
    assert profile["voice_id"] == "V_BASE"  # унаследован из базового конфига


def test_upload_photo_переопределяет_голос(workspace, фейковый_аплоад,
                                           monkeypatch, capsys):
    code, _ = _run(monkeypatch, capsys, "upload-photo", "--image", _фото(workspace),
                   "--client", "kaz1", "--voice-id", "v_custom")

    assert code == 0
    assert clients.load_client("kaz1")["voice_id"] == "v_custom"


def test_upload_photo_без_overwrite_не_трогает_профиль(workspace, фейковый_аплоад,
                                                       monkeypatch, capsys):
    _run(monkeypatch, capsys, "upload-photo", "--image", _фото(workspace),
         "--client", "kaz1")
    было = (workspace / "factory" / "clients" / "kaz1.yaml").read_text(encoding="utf-8")
    фейковый_аплоад.clear()

    code, out = _run(monkeypatch, capsys, "upload-photo", "--image", _фото(workspace),
                     "--client", "kaz1")

    assert code == 1 and out["ok"] is False
    assert "--overwrite" in out["error"]
    assert фейковый_аплоад == []  # в HeyGen даже не пошли
    assert (workspace / "factory" / "clients" / "kaz1.yaml").read_text(
        encoding="utf-8") == было


def test_upload_photo_с_overwrite_меняет_только_фото(workspace, фейковый_аплоад,
                                                     monkeypatch, capsys):
    старый = dict(BASE_CFG, voice_id="v_old",
                  avatar={"heygen_look_id": "look_old"})
    d = workspace / "factory" / "clients"
    d.mkdir(parents=True)
    (d / "kaz1.yaml").write_text(yaml.safe_dump(старый, allow_unicode=True),
                                 encoding="utf-8")

    code, out = _run(monkeypatch, capsys, "upload-photo", "--image", _фото(workspace),
                     "--client", "kaz1", "--overwrite")

    assert code == 0 and out["ok"] is True
    профиль = clients.load_client("kaz1")
    assert профиль["voice_id"] == "v_old"          # голос клиента сохранён
    assert профиль["avatar"]["heygen_asset_id"] == "img_123"
    assert "heygen_look_id" not in профиль["avatar"]  # photo-режим стал явным


def test_upload_photo_не_пускает_id_с_путём(workspace, фейковый_аплоад,
                                            monkeypatch, capsys):
    code, out = _run(monkeypatch, capsys, "upload-photo", "--image", _фото(workspace),
                     "--client", "../evil")

    assert code == 1 and out["ok"] is False
    assert not (workspace / "factory" / "evil.yaml").exists()
    assert not (workspace / "evil.yaml").exists()


def test_upload_photo_без_базового_конфига_отправляет_в_setup(workspace, фейковый_аплоад,
                                                              monkeypatch, capsys):
    (workspace / "factory" / "config.yaml").unlink()

    code, out = _run(monkeypatch, capsys, "upload-photo", "--image", _фото(workspace),
                     "--client", "kaz1")

    assert code == 1 and out["ok"] is False
    assert "setup" in out["error"]


def test_реестр_показывает_нового_клиента_как_photo(workspace, фейковый_аплоад,
                                                    monkeypatch, capsys):
    _run(monkeypatch, capsys, "upload-photo", "--image", _фото(workspace),
         "--client", "kaz1")

    row = next(r for r in clients.list_clients() if r["id"] == "kaz1")
    assert row["mode"] == "photo" and row["asset_id"] == "img_123"


def test_профиль_подхватывается_make_и_падает_до_платных_шагов(
        workspace, фейковый_аплоад, monkeypatch, capsys):
    _run(monkeypatch, capsys, "upload-photo", "--image", _фото(workspace),
         "--client", "kaz1")
    (workspace / "work" / "empty_wd").mkdir(parents=True)  # без scenario.json

    code, out = _run(monkeypatch, capsys, "make", "--workdir", "empty_wd",
                     "--client", "kaz1")

    # профиль прошёл валидацию load_client, а сборка остановилась на чтении
    # сценария — до TTS и HeyGen дело не дошло
    assert code == 1 and out["ok"] is False and out["stage"] == "scenario"


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


def test_make_формат_fullscreen_не_поддерживается(capsys):
    args = SimpleNamespace(workdir="demo")

    with pytest.raises(SystemExit) as exc:
        cli._cmd_make(args, {"format": "fullscreen"})

    assert exc.value.code == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False
    assert "avatar" in out["error"]
    assert "archive/console-broll-workflow" in out["error"]


def test_make_формат_split_не_поддерживается(capsys):
    args = SimpleNamespace(workdir="demo")

    with pytest.raises(SystemExit) as exc:
        cli._cmd_make(args, {"format": "split"})

    assert exc.value.code == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False
    assert "avatar" in out["error"]
    assert "archive/console-broll-workflow" in out["error"]


def test_make_avatar_проходит(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "WORK_ROOT", tmp_path)

    def fake_run_make(cfg, wd, meter=None):
        return {"ok": True, "workdir": str(wd), "mp4": "reel.mp4", "qa_pass": True,
                "gates": {}, "stage": None, "error": None}

    monkeypatch.setattr("reels_factory.pipeline.run_make", fake_run_make)
    args = SimpleNamespace(workdir="demo")

    with pytest.raises(SystemExit) as exc:
        cli._cmd_make(args, {"format": "avatar"})

    assert exc.value.code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True


def test_build_meter_с_испорченным_job_input_печатает_предупреждение(
    monkeypatch, tmp_path, capsys
):
    """Fix 3: job.input.json ЕСТЬ, но неразбираем (чужая job, не ручной
    прогон разработчика) — раньше _build_meter тихо возвращал None, и
    run_make рендерил бы за реальные деньги без единой строчки в журнале."""
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", tmp_path / "нет-файла.yaml")
    wd = tmp_path / "job1"
    wd.mkdir()
    (wd / "job.input.json").write_text("не json совсем", encoding="utf-8")

    meter = cli._build_meter(wd)

    assert meter is None
    err = capsys.readouterr().err
    assert "job.input.json" in err


def test_build_meter_без_файла_молчит(monkeypatch, tmp_path, capsys):
    """Ручной прогон разработчика без job.input.json — платить некому,
    тишина здесь остаётся ожидаемым (не багом)."""
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", tmp_path / "нет-файла.yaml")
    wd = tmp_path / "job2"
    wd.mkdir()

    meter = cli._build_meter(wd)

    assert meter is None
    assert capsys.readouterr().err == ""


def test_verify_с_scenario_timed_работает(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "WORK_ROOT", tmp_path)
    wd = tmp_path / "demo"
    wd.mkdir()
    scenario = {"theme": "кофе", "total": 3.0, "blocks": [
        {"role": "hook", "start": 0.0, "end": 3.0, "speech": "кофе кислит"},
    ]}
    (wd / "scenario.timed.json").write_text(json.dumps(scenario, ensure_ascii=False),
                                             encoding="utf-8")

    def fake_verify(mp4, timed, words=None, hypothesis=None, format="split"):
        return {"all_pass": True, "gates": {}}

    monkeypatch.setattr("reels_factory.verify.verify_reel", fake_verify)
    args = SimpleNamespace(workdir="demo", mp4=None)

    with pytest.raises(SystemExit) as exc:
        cli._cmd_verify(args, {"theme": "кофе"})

    assert exc.value.code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["all_pass"] is True
