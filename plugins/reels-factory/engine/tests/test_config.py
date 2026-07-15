import subprocess

import pytest
import yaml

from reels_factory.config import FFMPEG, WORK_ROOT, load_config, ConfigError


def test_ffmpeg_запускается():
    p = subprocess.run([FFMPEG, "-version"], capture_output=True, text=True)
    assert p.returncode == 0
    assert "ffmpeg version" in p.stdout


def test_work_root_имя_work():
    assert WORK_ROOT.name == "work"


def _base_cfg():
    return {"theme": "кофе дома", "format": "fullscreen", "voice_id": "v1",
            "product": {"name": "Гайд", "cta_phrase": "пиши кофе в комменты"}}


def _write(tmp_path, cfg):
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return p


def test_валидный_конфиг_читается(tmp_path):
    cfg = load_config(_write(tmp_path, _base_cfg()))
    assert cfg["theme"] == "кофе дома"
    assert cfg["format"] == "fullscreen"


def test_нет_файла_ошибка(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "нет.yaml")


def test_плохой_format_ошибка(tmp_path):
    cfg = _base_cfg(); cfg["format"] = "vertical"
    with pytest.raises(ConfigError) as e:
        load_config(_write(tmp_path, cfg))
    assert "format" in str(e.value)


def test_split_требует_heygen_asset(tmp_path):
    cfg = _base_cfg(); cfg["format"] = "split"  # без avatar.heygen_asset_id
    with pytest.raises(ConfigError) as e:
        load_config(_write(tmp_path, cfg))
    assert "heygen" in str(e.value).lower()


def test_split_с_heygen_asset_ок(tmp_path):
    cfg = _base_cfg(); cfg["format"] = "split"; cfg["avatar"] = {"heygen_asset_id": "a1"}
    assert load_config(_write(tmp_path, cfg))["format"] == "split"


def test_без_cta_phrase_ошибка(tmp_path):
    cfg = _base_cfg(); cfg["product"] = {"name": "Гайд"}  # нет cta_phrase
    with pytest.raises(ConfigError) as e:
        load_config(_write(tmp_path, cfg))
    assert "cta_phrase" in str(e.value)


def test_без_voice_id_ошибка(tmp_path):
    cfg = _base_cfg(); cfg.pop("voice_id")
    with pytest.raises(ConfigError) as e:
        load_config(_write(tmp_path, cfg))
    assert "voice_id" in str(e.value)
