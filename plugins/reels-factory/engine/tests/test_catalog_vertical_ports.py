"""Пять образцов реестра, перенесённых под вертикаль (работа B3).

Каждая карточка живёт на диске под `v-<имя>` и читается тем же `hf_catalog`,
которым каталог отдаётся агенту. Проверка кадром и `check --strict` пройдены
руками при переносе (см. `scratchpad/b3-report.md`); здесь — то, что держит
форму карточки и не даёт будущей правке тихо сломать вертикаль или гарнитуру.
"""
import json
from pathlib import Path

from reels_factory.hf_catalog import CATALOG_DIR, block_names

PORTED_BLOCKS = [
    "v-code-snippet-apple-terminal-basic",
    "v-code-diff",
    "v-world-map",
    "v-bar-chart-race",
    "v-macos-notification",
]


def _card(name: str) -> dict:
    path = CATALOG_DIR / "registry" / "blocks" / name / "registry-item.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _html_files(name: str) -> list[Path]:
    folder = CATALOG_DIR / "registry" / "blocks" / name
    card = _card(name)
    return [folder / f["path"] for f in card["files"]
            if str(f["path"]).endswith(".html")]


def test_пять_образцов_числятся_в_реестре():
    names = block_names()
    for block in PORTED_BLOCKS:
        assert block in names, f"{block} не в registry.json"


def test_карточка_читается_и_несёт_вертикальный_канвас():
    for block in PORTED_BLOCKS:
        card = _card(block)
        assert card["name"] == block
        assert card["dimensions"] == {"width": 1080, "height": 1920}
        for f in card["files"]:
            assert (CATALOG_DIR / "registry" / "blocks" / block / f["path"]).exists(), (
                f"{block}: файл {f['path']} из карточки отсутствует на диске")


def test_reels_kind_scene_и_text_slots_не_пусты():
    for block in PORTED_BLOCKS:
        reels = _card(block)["reels"]
        assert reels["kind"] == "scene"
        assert reels.get("text_slots"), f"{block}: text_slots пуст"


def test_v_macos_notification_больше_не_несёт_skip():
    """B2.5 (`scratchpad/strict-scoping-rootcause.md`): единственная причина
    `reels.skip` была одна находка их `--strict` —
    `composition_self_attribute_selector` — их же ложный срабатыватель,
    убранный апстримом коммитом 83ceaeb90; `_stage_overlay` и без того делает
    `data-composition-id` уникальным по построению (`hf_compose.py:585-594`).
    Приёмка `hf_render._check_verdict` больше не считает эту находку
    причиной провала, живая проба (`check --strict` + кадр 1080×1920 через
    настоящие `hf_compose`/`hf_render`) прошла чисто, и `skip` снят."""
    reels = _card("v-macos-notification")["reels"]
    assert not reels.get("skip")


def test_html_не_содержит_google_fonts():
    for block in PORTED_BLOCKS:
        for html_path in _html_files(block):
            html = html_path.read_text(encoding="utf-8")
            assert "fonts.googleapis" not in html, f"{block}: {html_path.name}"
            assert "fonts.gstatic" not in html, f"{block}: {html_path.name}"


def test_html_несёт_вертикальные_data_атрибуты():
    for block in PORTED_BLOCKS:
        for html_path in _html_files(block):
            html = html_path.read_text(encoding="utf-8")
            assert 'data-width="1080"' in html, f"{block}: {html_path.name}"
            assert 'data-height="1920"' in html, f"{block}: {html_path.name}"


def test_v_bar_chart_race_зеркалит_variables_из_html():
    """`reels.variables` — зеркало `data-composition-variables` для индекса
    агента (сам код парсит атрибут); тест держит зеркало не разошедшимся."""
    card = _card("v-bar-chart-race")
    html = (CATALOG_DIR / "registry" / "blocks" / "v-bar-chart-race"
            / "v-bar-chart-race.html").read_text(encoding="utf-8")
    for name in card["reels"]["variables"]:
        assert f'"id":"{name}"' in html, f"переменная {name} не найдена в HTML"
