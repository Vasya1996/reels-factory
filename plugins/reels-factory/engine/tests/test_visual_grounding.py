"""Вставка обязана быть выведена из слов, которые в этот момент звучат."""
from reels_factory.visual_grounding import enforce_visual_grounding


def _plan(items):
    return {
        "phrases": [{"id": "p1", "text": "Первый вопрос: кому продаём и кто наш клиент",
                     "coverage": "hyperframes", "window_id": "window-000"}],
        "windows": [{
            "id": "window-000",
            "phrase_ids": ["p1"],
            "coverage": "hyperframes",
            "safe_to_skip_avatar": False,
            "effect": {
                "type": "concept_nodes",
                "title": "Три вопроса",
                "items": [{"label": t, "v": 1} for t in items],
                "visual_director": {"source": "llm", "template": "concept_nodes"},
                "hyperframes": {"block": "concept_nodes",
                                "variables": {"title": "Три вопроса", "items": items}},
            },
        }],
        "log": [],
    }


def test_заземлённая_вставка_остаётся():
    plan = enforce_visual_grounding(_plan(["Кому продаём", "Кто клиент"]))
    assert plan["windows"][0]["effect"]["type"] == "concept_nodes"
    assert plan["log"] == ["граундинг: снято 0, проверено 1"]


def test_выдуманная_вставка_снимается():
    plan = enforce_visual_grounding(_plan(["Кому продаём", "Открыть сайт elevenlabs"]))
    assert plan["windows"][0]["effect"] == {"type": "none"}
    assert any("elevenlabs" in line for line in plan["log"])


def test_снятая_вставка_возвращает_окно_и_фразы_ведущему():
    plan = enforce_visual_grounding(_plan(["Открыть сайт elevenlabs"]))
    window = plan["windows"][0]
    assert window["coverage"] == "avatar"
    assert window["zone"] == "video-overlay"
    assert window["caption"] == "bottom"
    assert window["transition_in"] == "none"
    assert window["safe_to_skip_avatar"] is False
    assert plan["phrases"][0]["coverage"] == "avatar"


def test_детерминированная_вставка_не_трогается():
    """task_list собирается кодом из речи окна — выдумать там нечего."""
    plan = _plan(["Открыть сайт elevenlabs"])
    plan["windows"][0]["effect"].pop("visual_director", None)
    assert enforce_visual_grounding(plan)["windows"][0]["effect"]["type"] == "concept_nodes"


def test_шаблонные_подписи_не_считаются_выдумкой():
    """«КОМУ», «ЧТО», «КАК» приходят из словаря локализации."""
    plan = _plan(["КОМУ", "ЧТО", "КАК"])
    assert enforce_visual_grounding(plan)["windows"][0]["effect"]["type"] == "concept_nodes"


def test_вставка_без_текста_не_трогается():
    plan = {
        "phrases": [{"id": "p1", "text": "любые слова", "coverage": "full_broll"}],
        "windows": [{"id": "w", "phrase_ids": ["p1"], "coverage": "full_broll",
                     "effect": {"type": "broll", "style": "fullscreen", "src": "a.mp4"}}],
        "log": [],
    }
    assert enforce_visual_grounding(plan)["windows"][0]["effect"]["type"] == "broll"


def test_исходный_план_не_меняется():
    original = _plan(["Открыть сайт elevenlabs"])
    enforce_visual_grounding(original)
    assert original["windows"][0]["effect"]["type"] == "concept_nodes"


def test_статистика_граундинга_в_логе():
    plan = enforce_visual_grounding(
        _plan(["Кому продаём", "Открыть сайт elevenlabs"])
    )
    assert any(line.startswith("граундинг:") for line in plan["log"])
