"""Окружение: версия закреплена, облачные подкоманды не зовутся, GSAP локальный."""
import json
import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "reels_factory"
ENGINE_DIR = SRC.parents[1]


def test_версия_движка_закреплена():
    """Версия одна на весь движок (`_HF_VERSION` в hyperframes_blocks.py);
    поднята на 0.8.33 — docs/research/hyperframes/findings.md снято под
    старый пин 0.7.84 и с этим подъёмом не сверялось заново."""
    text = (SRC / "hyperframes_blocks.py").read_text(encoding="utf-8")
    version = re.search(r'_HF_VERSION\s*=\s*"([\d.]+)"', text)
    assert version and version.group(1) == "0.8.33"
    assert "hyperframes@latest" not in text
    # Прежде версия дублировалась в подсказке hf_assets и разъезжалась молча.
    others = re.findall(r"hyperframes@(\d[\d.]*)",
                        "\n".join(p.read_text(encoding="utf-8")
                                  for p in SRC.glob("hf_*.py")))
    assert not others, f"версия продублирована: {others}"

    # Дописано 13.09.2026 (доработка PR #116, дельта C): пин движка и версия
    # `@hyperframes/sdk`, которую тянет node-бридж (`package.json`), — два
    # места, называющие одну и ту же зависимость, и раньше их дрейф друг с
    # другом не проверялся ничем. Сверяем ДЕКЛАРАЦИЮ (`package.json`, решение
    # в git), а не то, что фактически стоит в `node_modules`/`package-lock.json`
    # на этой машине, — установленный пакет лечится переустановкой, а не
    # сторожем.
    package_json = json.loads((ENGINE_DIR / "package.json").read_text(encoding="utf-8"))
    sdk_range = package_json["dependencies"]["@hyperframes/sdk"]
    sdk_version = sdk_range.lstrip("^~")
    assert sdk_version == version.group(1), (
        f"package.json называет @hyperframes/sdk {sdk_range!r}, "
        f"а _HF_VERSION — {version.group(1)!r}: движок и SDK-бридж разъехались")


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
    from reels_factory.hf_assets import GSAP_SOURCE, vendor_gsap

    # Разбор 13.09.2026 (agent-profile): склад скилов переехал в профиль
    # сервиса (GSAP_SOURCE теперь под SKILL_PROFILE_DIR, не под личным
    # профилем пользователя ОС) — гвардия сверяется с тем же путём, что
    # реально читает vendor_gsap, а не с прежним личным профилем.
    if not GSAP_SOURCE.exists():
        pytest.skip("скилы HeyGen не установлены")
    target = vendor_gsap(tmp_path)
    assert target.exists() and target.stat().st_size > 10_000
