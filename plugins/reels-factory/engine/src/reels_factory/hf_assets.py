"""Локальные ассеты композиции: внешние URL внутри карточек запрещены."""
from __future__ import annotations

import shutil
from pathlib import Path

SKILLS_DIR = Path.home() / ".claude" / "skills"
GSAP_SOURCE = SKILLS_DIR / "talking-head-recut" / "assets" / "vendor" / "gsap.min.js"


def vendor_gsap(public_dir) -> Path:
    """Положить gsap.min.js в public/vendor. Возвращает путь к копии."""
    target = Path(public_dir) / "vendor" / "gsap.min.js"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not GSAP_SOURCE.exists():
        from reels_factory.hyperframes_blocks import _HF_VERSION
        raise RuntimeError(
            "не найден gsap.min.js; выполни "
            f"npx hyperframes@{_HF_VERSION} skills update talking-head-recut")
    shutil.copyfile(GSAP_SOURCE, target)
    return target
