"""Разбор 13.09.2026 (agent-profile): эта ветка — пустой склад скилов на
профиле сервиса — не была покрыта ни одним тестом (карта factory-librarian,
13.09.2026). Реальный склад проверяет `test_hf_env.py::test_gsap_кладётся_локально`
(пропускается, если скила нет); здесь — обратный случай, специально пустой."""
import pytest

from reels_factory import hf_assets


def test_отсутствующий_скил_даёт_подсказку_с_переменной(monkeypatch, tmp_path):
    """При пустом складе (`GSAP_SOURCE` не существует) ошибка должна не молчать,
    а называть и путь профиля сервиса, и переменную `CLAUDE_CONFIG_DIR` — без
    неё команда из подсказки положит скил в личный профиль, мимо склада
    (`hf_assets.py:19`, разбор пункт 3)."""
    monkeypatch.setattr(hf_assets, "GSAP_SOURCE", tmp_path / "нет-такого" / "gsap.min.js")

    with pytest.raises(RuntimeError) as упало:
        hf_assets.vendor_gsap(tmp_path / "public")

    сообщение = str(упало.value)
    assert "gsap.min.js" in сообщение
    assert "skills update talking-head-recut" in сообщение
    assert "CLAUDE_CONFIG_DIR" in сообщение
    assert str(hf_assets.SKILL_PROFILE_DIR) in сообщение
