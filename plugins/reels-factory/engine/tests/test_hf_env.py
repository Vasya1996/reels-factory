"""Окружение: версия закреплена, облачные подкоманды не зовутся, GSAP локальный."""
import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "reels_factory"


def test_версия_движка_закреплена():
    """Версия одна на весь движок (`_HF_VERSION` в hyperframes_blocks.py);
    поднята на 0.8.27 — docs/research/hyperframes/findings.md снято под
    старый пин 0.7.84 и с этим подъёмом не сверялось заново."""
    text = (SRC / "hyperframes_blocks.py").read_text(encoding="utf-8")
    version = re.search(r'_HF_VERSION\s*=\s*"([\d.]+)"', text)
    assert version and version.group(1) == "0.8.27"
    assert "hyperframes@latest" not in text
    # Прежде версия дублировалась в подсказке hf_assets и разъезжалась молча.
    others = re.findall(r"hyperframes@(\d[\d.]*)",
                        "\n".join(p.read_text(encoding="utf-8")
                                  for p in SRC.glob("hf_*.py")))
    assert not others, f"версия продублирована: {others}"


def test_облачные_подкоманды_не_зовутся():
    """Подкоманда ищется как отдельный аргумент вызова, а не подстрока."""
    forbidden = {"cloud", "lambda", "cloudrun"}
    for path in list(SRC.glob("hf_*.py")) + [SRC / "capture_site.py"]:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for call in re.findall(r"_cli\(([^)]*)\)", text):
            args = re.findall(r'"([a-z-]+)"', call)
            assert not (forbidden & set(args)), f"{path.name}: облачный режим запрещён"


def test_gsap_кладётся_локально(tmp_path):
    from reels_factory.hf_assets import vendor_gsap

    if not (Path.home() / ".claude" / "skills" / "talking-head-recut").exists():
        pytest.skip("скилы HeyGen не установлены")
    target = vendor_gsap(tmp_path)
    assert target.exists() and target.stat().st_size > 10_000
