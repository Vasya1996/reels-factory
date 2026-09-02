from reels_factory.editplan import (HOOK_S, PATTERN_BREAK_S, STATIC_LIMIT_S,
                                    detect_silences, plan_edit, speech_segments,
                                    validate_plan)


def test_паузы_разбираются_из_вывода_ffmpeg():
    out = ("[silencedetect] silence_start: 5.73415\n"
           "[silencedetect] silence_end: 6.034331 | silence_duration: 0.300181\n"
           "[silencedetect] silence_start: 10.544014\n"
           "[silencedetect] silence_end: 10.980635 | silence_duration: 0.436621\n")

    silences = detect_silences("x.mp4", run=lambda cmd: out)

    assert silences == [(5.73415, 6.034331), (10.544014, 10.980635)]


def test_куски_речи_между_паузами():
    segs = speech_segments(20.0, [(5.0, 5.5), (10.0, 10.4)])

    assert segs == [(0.0, 5.0), (5.5, 10.0), (10.4, 20.0)]


def test_план_ставит_наезды_на_начала_фраз():
    # после паузы 5.0-5.5 фраза начинается на 5.5 — там уже есть вдох и смена
    # интонации, наезд читается как задуманный
    plan = plan_edit(20.0, [(5.0, 5.5), (10.0, 10.4)])

    starts = [t for t, _ in plan["punch"]]
    assert 5.5 in starts and 10.4 in starts


def test_свуш_на_каждый_наезд():
    plan = plan_edit(20.0, [(5.0, 5.5)])

    assert plan["whoosh"] == [t for t, _ in plan["punch"]]


def test_хук_держится_плотнее_остального():
    plan = plan_edit(20.0, [])

    in_hook = [t for t, _ in plan["punch"] if t < HOOK_S]
    # в первые 3 секунды изменений больше, чем даёт обычный шаг 2 с
    assert len(in_hook) >= 2


def test_план_без_пауз_всё_равно_держит_ритм():
    plan = plan_edit(30.0, [])

    qa = validate_plan(plan)
    assert qa["all_pass"] is True
    assert qa["gates"]["rhythm_no_static"]["max_gap"] <= STATIC_LIMIT_S


def test_акценты_от_модели_попадают_в_план():
    plan = plan_edit(20.0, [], accents=[4.2, 12.7])

    starts = [t for t, _ in plan["punch"]]
    assert 4.2 in starts and 12.7 in starts


def test_гейт_ловит_статику():
    plan = {"duration": 20.0, "punch": [(1.0, 0.6)], "whoosh": []}

    qa = validate_plan(plan)

    assert qa["all_pass"] is False
    assert qa["gates"]["rhythm_no_static"]["pass"] is False
    assert qa["gates"]["rhythm_no_static"]["max_gap"] > STATIC_LIMIT_S


def test_гейт_ловит_мельтешение():
    punch = [(round(0.3 * i, 2), 0.6) for i in range(1, 60)]
    plan = {"duration": 20.0, "punch": punch, "whoosh": []}

    qa = validate_plan(plan)

    assert qa["gates"]["rhythm_density"]["pass"] is False
    assert qa["gates"]["rhythm_density"]["per_10s"] > 8


def test_гейт_не_пускает_вставку_на_хук():
    plan = plan_edit(20.0, [])

    qa = validate_plan(plan, insert_windows=[(1.0, 4.0)])

    assert qa["gates"]["hook_uncovered"]["pass"] is False
    assert validate_plan(plan, insert_windows=[(6.0, 9.0)])["gates"]["hook_uncovered"]["pass"]


def test_гейт_ограничивает_число_вставок():
    plan = plan_edit(30.0, [])
    many = [(5.0, 7.0), (9.0, 11.0), (13.0, 15.0), (17.0, 19.0)]

    assert validate_plan(plan, insert_windows=many)["gates"]["inserts_count"]["pass"] is False
    assert validate_plan(plan, insert_windows=many[:3])["gates"]["inserts_count"]["pass"]


def test_паттерн_прерывание_не_реже_пятнадцати_секунд():
    plan = plan_edit(60.0, [])
    qa = validate_plan(plan)

    assert qa["gates"]["pattern_break"]["pass"] is True
    assert qa["gates"]["pattern_break"]["limit"] == PATTERN_BREAK_S


# --- ритм-добивка: панчи в статические дыры ---

def test_fill_static_gaps_пустое_покрытие_панч_каждые_три_секунды():
    from reels_factory.editplan import fill_static_gaps

    punches = fill_static_gaps([], 10.0)
    times = [t for t, _ in punches]
    assert times[0] == 3.0
    assert all(b - a <= 3.7 for a, b in zip(times, times[1:]))  # шаг max_gap+dur


def test_fill_static_gaps_закрытые_интервалы_не_добиваются():
    from reels_factory.editplan import fill_static_gaps

    # движение есть всё время — добивать нечего
    assert fill_static_gaps([(0.0, 10.0)], 10.0) == []


def test_fill_static_gaps_панч_только_в_дыре():
    from reels_factory.editplan import fill_static_gaps

    punches = fill_static_gaps([(0.0, 4.0), (12.0, 20.0)], 20.0)
    times = [t for t, _ in punches]
    assert times  # дыра 4..12 длиннее 3с — добита
    assert all(4.0 < t < 12.0 for t in times)


def test_fill_static_gaps_пересекающиеся_интервалы_сливаются():
    from reels_factory.editplan import fill_static_gaps

    # два куска покрывают 0..9 без дыр — панчей нет (ролик 9с)
    assert fill_static_gaps([(0.0, 5.0), (4.0, 9.0)], 9.0) == []


# --- canonical edit_plan.json ---

import copy
import json

import pytest

from reels_factory.editplan import (
    EDIT_PLAN_FILENAME,
    GESTURE_KEYS,
    GESTURE_VOCABULARY,
    MAX_FACE_ABSENCE_S,
    PERFORMANCE_BY_ROLE,
    _chart_variables,
    _language_rules,
    _motion_prompt_error,
    _norm_word,
    apply_performance_recommendations,
    apply_visual_recommendations,
    before_after_from_text,
    broll_query,
    build_edit_plan,
    covered_block_indexes,
    enrich_performance_with_llm,
    enrich_visuals_with_llm,
    ensure_assetless_visual_coverage,
    finalize_edit_plan,
    performance_analysis_prompt,
    save_edit_plan,
    validate_edit_plan,
)


def _canonical_scenario():
    return {
        "theme": "автоматизация",
        "blocks": [
            {
                "role": "hook",
                "start": 0.0,
                "end": 3.0,
                "speech": "Вы всё ещё делаете это вручную?",
            },
            {
                "role": "development",
                "start": 3.0,
                "end": 9.0,
                "speech": (
                    "Настройте один сценарий, и он сам собирает данные "
                    "и готовит отчёт."
                ),
            },
            {
                "role": "payoff",
                "start": 9.0,
                "end": 15.0,
                "speech": "Команда экономит 10 часов каждую неделю.",
            },
            {
                "role": "cta",
                "start": 15.0,
                "end": 18.0,
                "speech": "Подпишитесь, чтобы получить схему.",
            },
        ],
    }


def _canonical_config(**avatar):
    result = {
        "format": "avatar",
        "language": "ru",
        "avatar": {"engine": "avatar_iv"},
        "product": {"cta_button": "ПОЛУЧИТЬ"},
    }
    result["avatar"].update(avatar)
    return result


def test_kazakh_unicode_keywords_не_теряют_национальные_буквы():
    assert _norm_word("Қала!") == "қала"
    assert _norm_word("Ғала!") == "ғала"
    assert _norm_word("Қала!") != _norm_word("Ғала!")


def test_kazakh_language_pack_семантика_и_локализованные_подписи():
    rules = _language_rules("kk")
    assert rules["automation"].search("Барлығын автоматтандыруға болады")
    assert rules["instruction"].search("Үш қадамнан тұратын нұсқаулық")
    assert rules["payoff"].search("Бір рет баптап, дайын нәтижені алыңыз")

    before_after = before_after_from_text(
        "Бұрын есеп қолмен жасалды, қазір жүйе автоматты жұмыс істейді.",
        language="kk",
    )
    assert before_after == {
        "before_value": "есеп қолмен жасалды",
        "after_value": "жүйе автоматты жұмыс істейді",
    }
    assert broll_query(
        "Бұл жүйе және есеп үшін өте пайдалы", language="kk"
    ) == "жүйе есеп пайдалы"

    chart = _chart_variables(
        "талдау, есеп, жоспар, нәтиже",
        0.0,
        4.0,
        language="kk",
    )
    assert chart["title"] == "НЕГІЗГІ ТАРМАҚТАР"


def test_kazakh_edit_plan_берёт_казахский_cta_и_before_after():
    scenario = {
        "theme": "автоматтандыру",
        "blocks": [
            {
                "role": "hook",
                "start": 0.0,
                "end": 3.0,
                "speech": "Есепке қанша уақыт жұмсайсыз?",
            },
            {
                "role": "development",
                "start": 3.0,
                "end": 9.0,
                "speech": (
                    "Бұрын есеп қолмен жасалды, қазір жүйе автоматты "
                    "жұмыс істейді."
                ),
            },
            {
                "role": "cta",
                "start": 9.0,
                "end": 12.0,
                "speech": "Келесі кеңестер үшін жазылыңыз.",
            },
        ],
    }
    plan = build_edit_plan(
        scenario,
        {
            "format": "avatar",
            "language": "kk",
            "avatar": {"engine": "avatar_iv"},
            "product": {},
        },
        index={},
        require_asset_files=False,
    )

    assert plan["script"]["language"] == "kk"
    cta = next(window for window in plan["windows"] if window["role"] == "cta")
    assert cta["effect"]["button"] == "ЖАЗЫЛУ"
    assert any(
        (window.get("effect") or {}).get("hyperframes", {}).get("block")
        == "before_after"
        for window in plan["windows"]
    )
    # before_after window should skip avatar for development block
    assert plan["blocks"][1]["avatar_required"] is False


def _three_questions_scenario():
    return {
        "theme": "три вопроса продаж",
        "blocks": [
            {
                "role": "hook",
                "start": 0.0,
                "end": 6.2,
                "speech": (
                    "Все продажи на свете сводятся к трём вопросам. "
                    "И порядок этих вопросов решает всё."
                ),
            },
            {
                "role": "development",
                "start": 6.2,
                "end": 33.2,
                "speech": (
                    "Мы обожаем усложнять продажи. Учим хитрые приёмы. "
                    "Зубрим скрипты. Ищем волшебные фразы. "
                    "А в основе — три больших вопроса. Первый: кому продаём? "
                    "Кто этот человек, чем живёт, какая у него боль. "
                    "Второй: что продаём? Что человек на самом деле у нас "
                    "покупает. Третий: как продаём? Где встречаемся с ним, "
                    "какими словами говорим, в каком виде предлагаем. "
                    "Всё остальное — надстройка над этими тремя."
                ),
            },
            {
                "role": "payoff",
                "start": 33.2,
                "end": 40.0,
                "speech": (
                    "Звучит просто. Но самое важное — порядок. "
                    "Сначала кто, пото́м что, и только пото́м как."
                ),
            },
            {
                "role": "cta",
                "start": 40.0,
                "end": 44.7,
                "speech": (
                    "Сохрани это видео. Прогони свой продукт по трём вопросам. "
                    "Прямо сегодня."
                ),
            },
        ],
    }


def _library(tmp_path, *, duration=8.0):
    clip = tmp_path / "automation.mp4"
    clip.write_bytes(b"offline fixture")
    return {
        clip.name: {
            "path": str(clip),
            "duration": duration,
            "embedding": [1.0, 0.0],
        }
    }


def _build_canonical(tmp_path, *, config=None, duration=8.0):
    return build_edit_plan(
        _canonical_scenario(),
        config or _canonical_config(),
        index=_library(tmp_path, duration=duration),
        library_dir=tmp_path,
        embed_fn=lambda _text: [1.0, 0.0],
    )


def _timed_and_words(plan, *, development_end=9.0):
    timed = copy.deepcopy(_canonical_scenario())
    delta = development_end - 9.0
    timed["blocks"][1]["end"] = development_end
    timed["blocks"][2]["start"] = development_end
    timed["blocks"][2]["end"] = 15.0 + delta
    timed["blocks"][3]["start"] = 15.0 + delta
    timed["blocks"][3]["end"] = 18.0 + delta
    timed["total"] = 18.0 + delta

    words = []
    phrases_by_block = {}
    for phrase in plan["phrases"]:
        phrases_by_block.setdefault(phrase["block_index"], []).append(phrase)
    for block_index, phrases in phrases_by_block.items():
        block = timed["blocks"][block_index]
        span = (float(block["end"]) - float(block["start"])) / len(phrases)
        for index, phrase in enumerate(phrases):
            start = float(block["start"]) + span * index + 0.05
            end = float(block["start"]) + span * (index + 1) - 0.05
            words.append({
                "block_index": block_index,
                "start": start,
                "end": end,
                "text": phrase["text"],
                "character_start": phrase["character_start"],
                "character_end": phrase["character_end"],
            })
    return timed, words


def test_canonical_draft_фиксирует_script_phrase_windows_и_asset(tmp_path):
    plan = _build_canonical(tmp_path)

    assert plan["format_version"] == 1
    assert plan["status"] == "draft"
    assert plan["validation"]["all_pass"] is True
    assert covered_block_indexes(plan) == {1}
    assert plan["summary"]["full_broll_seconds"] == 6.0
    assert [phrase["id"] for phrase in plan["phrases"]] == [
        f"phrase-{index:03d}" for index in range(len(plan["phrases"]))
    ]
    for phrase in plan["phrases"]:
        start, end = phrase["character_start"], phrase["character_end"]
        assert plan["script"]["text"][start:end] == phrase["text"]
        assert phrase["window_id"]
        assert phrase["avatar_performance"]["expressiveness"] in {
            "low", "medium", "high"
        }
    development = next(
        window for window in plan["windows"] if window["role"] == "development"
    )
    assert development["coverage"] == "full_broll"
    assert development["safe_to_skip_avatar"] is True
    assert development["asset"]["path"].endswith("automation.mp4")


def test_three_questions_формирует_task_list_с_avatar_bubble():
    plan = build_edit_plan(
        _three_questions_scenario(),
        _canonical_config(),
        index={},
        require_asset_files=False,
    )

    bubbles = [
        window
        for window in plan["windows"]
        if (window.get("effect") or {}).get("bubble")
    ]
    assert len(bubbles) == 1
    bubble = bubbles[0]
    effect = bubble["effect"]
    assert bubble["coverage"] == "mixed"
    assert bubble["safe_to_skip_avatar"] is False
    assert effect["bubble"] == {
        "shape": "circle",
        "position": "bottom_left",
    }
    assert effect["hyperframes"]["block"] == "task_list"
    assert effect["hyperframes"]["variables"] == {
        "title": "3 · КАК ПРОДАЁМ",
        "items": [
            "Где встречаемся с ним",
            "какими словами говорим",
            "в каком виде предлагаем",
        ],
    }
    own = {
        phrase["id"]: phrase
        for phrase in plan["phrases"]
        if phrase["id"] in bubble["phrase_ids"]
    }
    assert all(phrase["coverage"] == "mixed" for phrase in own.values())
    bubble_index = plan["windows"].index(bubble)
    lead = plan["windows"][bubble_index - 1]
    assert lead["coverage"] == "avatar"
    assert lead["camera"]["type"] == "punch_in"
    assert "Третий: как продаём?" in " ".join(
        phrase["text"]
        for phrase in plan["phrases"]
        if phrase["id"] in lead["phrase_ids"]
    )
    assert plan["summary"]["bubble_windows"] == 1
    assert 3.0 <= plan["summary"]["bubble_seconds"] <= 6.0
    assert plan["validation"]["all_pass"] is True


def test_three_questions_получает_пять_встроенных_смысловых_визуалов():
    plan = build_edit_plan(
        _three_questions_scenario(),
        _canonical_config(),
        index={},
        require_asset_files=False,
    )

    visual_windows = [
        window
        for window in plan["windows"]
        if (window.get("effect") or {}).get("visual_director")
    ]
    assert [
        window["effect"]["visual_director"]["template"]
        for window in visual_windows
    ] == [
        "complexity_cloud",
        "persona_card",
        "value_layers",
        "concept_nodes",
        "sequence_flow",
    ]
    assert [
        (
            window["estimated_timing"]["start"],
            window["estimated_timing"]["end"],
        )
        for window in visual_windows
    ] == [
        (6.2, 14.624),
        (16.136, 19.448),
        (19.448, 23.768),
        (30.176, 33.2),
        (35.76, 40.0),
    ]
    assert all(
        window["coverage"] == "hyperframes"
        and window["caption"] == "hidden"
        and window["effect"]["hyperframes"]["block"]
        == window["effect"]["visual_director"]["template"]
        and window["effect"]["visual_director"]["source"] == "rules"
        for window in visual_windows
    )
    assert not any(
        (window.get("effect") or {}).get("visual_director")
        and window["role"] in {"hook", "cta"}
        for window in plan["windows"]
    )
    assert plan["summary"]["built_in_visual_windows"] == 5
    assert plan["summary"]["built_in_visual_seconds"] == 23.32

    avatar_only_run = 0.0
    max_avatar_only_run = 0.0
    for window in plan["windows"]:
        timing = window["estimated_timing"]
        duration = timing["end"] - timing["start"]
        if (
            window["coverage"] == "avatar"
            and (window.get("effect") or {}).get("type") == "none"
        ):
            avatar_only_run += duration
            max_avatar_only_run = max(max_avatar_only_run, avatar_only_run)
        else:
            avatar_only_run = 0.0
    assert max_avatar_only_run == pytest.approx(6.2)
    assert max_avatar_only_run <= 10.0
    assert plan["validation"]["all_pass"] is True


def test_visual_director_можно_отключить_не_отключая_bubble():
    config = _canonical_config()
    config["edit_plan"] = {"visual_director": {"enabled": False}}

    plan = build_edit_plan(
        _three_questions_scenario(),
        config,
        index={},
        require_asset_files=False,
    )

    assert not any(
        (window.get("effect") or {}).get("visual_director")
        for window in plan["windows"]
    )
    assert any(
        (window.get("effect") or {}).get("bubble")
        for window in plan["windows"]
    )
    assert plan["constraints"]["visual_director"]["max_count"] == 0


def test_bubble_можно_отключить_в_config():
    config = _canonical_config()
    config["edit_plan"] = {"bubble": {"enabled": False}}

    plan = build_edit_plan(
        _three_questions_scenario(),
        config,
        index={},
        require_asset_files=False,
    )

    assert not any(
        (window.get("effect") or {}).get("bubble")
        for window in plan["windows"]
    )
    assert plan["constraints"]["bubble"]["max_count"] == 0


def test_bubble_и_semantic_фиксируются_в_финальном_плане():
    final = build_edit_plan(
        _three_questions_scenario(),
        _canonical_config(),
        index={},
        require_asset_files=False,
    )
    final["status"] = "final"
    final["timeline"]["final_duration_seconds"] = final["timeline"][
        "estimated_duration_seconds"
    ]
    for collection in ("phrases", "windows", "blocks"):
        for item in final[collection]:
            item["final_timing"] = copy.deepcopy(item["estimated_timing"])
    final["validation"] = validate_edit_plan(
        final, require_final=True, require_asset_files=False
    )
    assert final["validation"]["all_pass"] is True

    bubble = next(
        window
        for window in final["windows"]
        if (window.get("effect") or {}).get("bubble")
    )
    assert bubble["coverage"] == "mixed"
    assert bubble["effect"]["bubble"] == {
        "shape": "circle",
        "position": "bottom_left",
    }
    semantic = [
        window
        for window in final["windows"]
        if (window.get("effect") or {}).get("visual_director")
    ]
    assert len(semantic) == 5


def test_validator_защищает_avatar_bubble_contract():
    plan = build_edit_plan(
        _three_questions_scenario(),
        _canonical_config(),
        index={},
        require_asset_files=False,
    )
    bubble = next(
        window
        for window in plan["windows"]
        if (window.get("effect") or {}).get("bubble")
    )
    bubble["coverage"] = "avatar"

    report = validate_edit_plan(plan, require_asset_files=False)

    assert report["all_pass"] is False
    assert any("bubble требует mixed coverage" in error for error in report["errors"])


def test_validator_защищает_visual_director_contract():
    plan = build_edit_plan(
        _three_questions_scenario(),
        _canonical_config(),
        index={},
        require_asset_files=False,
    )
    visual = next(
        window
        for window in plan["windows"]
        if (window.get("effect") or {}).get("visual_director")
    )
    visual["coverage"] = "avatar"
    visual["caption"] = "bottom"
    visual["effect"]["hyperframes"]["variables"]["items"] = []
    visual["effect"]["items"] = []

    report = validate_edit_plan(plan, require_asset_files=False)

    assert report["all_pass"] is False
    assert any("built-in visual требует hyperframes" in error for error in report["errors"])
    assert any("built-in visual требует hidden caption" in error for error in report["errors"])
    assert any("visual items требуют" in error for error in report["errors"])


def _visual_llm_scenario():
    return {
        "theme": "выбор решения",
        "blocks": [
            {
                "role": "hook",
                "start": 0.0,
                "end": 3.0,
                "speech": "Почему клиент откладывает решение?",
            },
            {
                "role": "development",
                "start": 3.0,
                "end": 9.0,
                "speech": (
                    "Клиент видит проблему, сравнивает варианты "
                    "и выбирает решение."
                ),
            },
            {
                "role": "payoff",
                "start": 9.0,
                "end": 13.0,
                "speech": "Ясная система делает выбор понятным.",
            },
            {
                "role": "cta",
                "start": 13.0,
                "end": 16.0,
                "speech": "Сохрани эту схему.",
            },
        ],
    }


def _visual_recommendation(plan):
    development = [
        phrase["id"]
        for phrase in plan["phrases"]
        if phrase["role"] == "development"
    ]
    return {
        "visuals": [
            {
                "phrase_ids": development,
                "template": "concept_nodes",
                "variables": {
                    "title": "КАК КЛИЕНТ ВЫБИРАЕТ",
                    "items": ["ПРОБЛЕМА", "ВАРИАНТЫ", "РЕШЕНИЕ"],
                },
                "rationale": "Три смысловых узла объясняют путь выбора.",
            }
        ]
    }


def test_visual_llm_заменяет_только_целое_avatar_only_окно():
    draft = build_edit_plan(
        _visual_llm_scenario(),
        _canonical_config(),
        index={},
        require_asset_files=False,
    )

    enriched = apply_visual_recommendations(
        draft,
        _visual_recommendation(draft),
    )

    visual = next(
        window
        for window in enriched["windows"]
        if (window.get("effect") or {}).get("visual_director", {}).get("source")
        == "llm"
    )
    assert visual["role"] == "development"
    assert visual["coverage"] == "hyperframes"
    assert visual["estimated_timing"] == {"start": 3.0, "end": 9.0}
    assert visual["effect"]["hyperframes"]["block"] == "concept_nodes"
    assert visual["caption"] == "hidden"
    assert enriched["validation"]["all_pass"] is True


def test_visual_llm_prompt_и_guardrails():
    draft = build_edit_plan(
        _visual_llm_scenario(),
        _canonical_config(),
        index={},
        require_asset_files=False,
    )

    class Runner:
        prompt = None

        def run(self, prompt):
            self.prompt = prompt
            return json.dumps(_visual_recommendation(draft))

    runner = Runner()
    enriched = enrich_visuals_with_llm(draft, runner)

    assert "Visual Director" in runner.prompt
    assert "continuous seconds" in runner.prompt
    assert "Leave at least one avatar or mixed phrase" in runner.prompt
    assert enriched["summary"]["built_in_visual_windows"] == 1

    invalid = _visual_recommendation(draft)
    invalid["visuals"][0]["phrase_ids"] = [
        phrase["id"] for phrase in draft["phrases"] if phrase["role"] == "hook"
    ]
    with pytest.raises(ValueError, match="hook/CTA"):
        apply_visual_recommendations(draft, invalid)

    invalid = _visual_recommendation(draft)
    invalid["visuals"][0]["template"] = "invented_template"
    with pytest.raises(ValueError, match="template/variables"):
        apply_visual_recommendations(draft, invalid)


def _adjacent_visual_llm_scenario():
    return {
        "theme": "выбор",
        "blocks": [
            {
                "role": "hook",
                "start": 0.0,
                "end": 3.0,
                "speech": "Сейчас покажу важную закономерность.",
            },
            {
                "role": "context",
                "start": 3.0,
                "end": 9.0,
                "speech": "Команда долго изучает исходные данные.",
            },
            {
                "role": "development",
                "start": 9.0,
                "end": 15.0,
                "speech": "Затем она выбирает рабочее решение.",
            },
            {
                "role": "cta",
                "start": 15.0,
                "end": 18.0,
                "speech": "Сохрани эту полезную схему.",
            },
        ],
    }


def test_visual_llm_tolerant_не_роняет_план_из_за_суммарных_10_секунд():
    draft = build_edit_plan(
        _adjacent_visual_llm_scenario(),
        _canonical_config(),
        index={},
        require_asset_files=False,
    )
    context_id = next(
        phrase["id"] for phrase in draft["phrases"] if phrase["role"] == "context"
    )
    development_id = next(
        phrase["id"]
        for phrase in draft["phrases"]
        if phrase["role"] == "development"
    )
    recommendations = {
        "visuals": [
            {
                "phrase_ids": [context_id],
                "template": "concept_nodes",
                "variables": {
                    "title": "ИСХОДНЫЕ ДАННЫЕ",
                    "items": ["ФАКТЫ", "КОНТЕКСТ"],
                },
                "rationale": "Объясняет этап анализа.",
            },
            {
                "phrase_ids": [development_id],
                "template": "sequence_flow",
                "variables": {
                    "title": "ВЫБОР РЕШЕНИЯ",
                    "items": ["СРАВНИТЬ", "ВЫБРАТЬ"],
                },
                "rationale": "Объясняет следующий этап.",
            },
        ]
    }

    enriched = apply_visual_recommendations(
        draft,
        recommendations,
        strict=False,
    )

    review = enriched["visual_director_reviews"][-1]
    assert len(review["accepted"]) == 1
    assert len(review["rejected"]) == 1
    assert "лицо отсутствует дольше" in review["rejected"][0]["reason"]
    assert enriched["validation"]["all_pass"] is True
    assert next(
        phrase for phrase in enriched["phrases"] if phrase["id"] == development_id
    )["coverage"] == "avatar"


def _hotel_comparison_scenario():
    return {
        "title": "Бутик-отели окупаются вдвое быстрее",
        "language": "ru",
        "blocks": [
            {
                "role": "hook",
                "start": 0.0,
                "end": 3.0,
                "speech": (
                    "Обычная гостиница окупа́ется за пятнадцать лет. "
                    "Бутик-отель — вдвое быстрее."
                ),
            },
            {
                "role": "development",
                "start": 3.0,
                "end": 19.5,
                "speech": (
                    "Многие вкладывают в отели. И ждут прибыль десятилетиями. "
                    "Но дело не в отелях, а в формате. Бутик-отели, санатории "
                    "и медика́л спа окупа́ются всего за девять лет. Это почти "
                    "вдвое быстрее обычной гостиницы. Там ждут пятнадцать лет."
                ),
            },
            {
                "role": "payoff",
                "start": 19.5,
                "end": 27.0,
                "speech": (
                    "Рентабе́льность обычной гостиницы — двадцать пять "
                    "процентов. У бутик-отеля и спа — тридцать пять. "
                    "Вот и вся разница в доходе на вло́женный рубль."
                ),
            },
            {
                "role": "cta",
                "start": 27.0,
                "end": 30.0,
                "speech": (
                    "Сохрани, если задумываешься об инвести́циях в отели."
                ),
            },
        ],
    }


def test_assetless_fallback_иллюстрирует_отельные_сравнения_без_broll():
    draft = build_edit_plan(
        _hotel_comparison_scenario(),
        _canonical_config(),
        index={},
        require_asset_files=False,
    )

    enriched = ensure_assetless_visual_coverage(draft)
    visuals = [
        window
        for window in enriched["windows"]
        if (
            (window.get("effect") or {}).get("visual_director", {}).get("source")
            == "assetless_fallback"
        )
    ]

    assert len(visuals) == 3
    assert any(
        window["effect"]["hyperframes"]["block"] == "value_layers"
        for window in visuals
    )
    value_layers = [
        window["effect"]["hyperframes"]["variables"]
        for window in visuals
        if window["effect"]["hyperframes"]["block"] == "value_layers"
    ]
    assert any("ДЕВЯТЬ" in variables["offer"] for variables in value_layers)
    assert any(
        "ТРИДЦАТЬ ПЯТЬ" in variables["actual"]
        for variables in value_layers
    )
    assert enriched["summary"]["avatar_visible_seconds"] < 20.0
    assert enriched["validation"]["all_pass"] is True
    review = enriched["visual_director_reviews"][-1]
    assert review["source"] == "assetless_fallback"
    assert len(review["accepted"]) == 3
    assert review["rejected"] == []


def test_visual_llm_invalid_json_мягко_переходит_на_assetless_fallback():
    draft = build_edit_plan(
        _hotel_comparison_scenario(),
        _canonical_config(),
        index={},
        require_asset_files=False,
    )

    class Runner:
        def run(self, _prompt):
            return "not-json"

    enriched = enrich_visuals_with_llm(draft, Runner())

    assert enriched["validation"]["all_pass"] is True
    assert enriched["visual_director_reviews"][0]["source"] == "llm"
    assert enriched["visual_director_reviews"][0]["rejected"]
    assert any(
        (window.get("effect") or {}).get("visual_director", {}).get("source")
        == "assetless_fallback"
        for window in enriched["windows"]
    )


def test_save_canonical_пишет_только_edit_plan(tmp_path):
    plan = _build_canonical(tmp_path)
    out = save_edit_plan(plan, tmp_path)

    assert out.name == EDIT_PLAN_FILENAME
    assert json.loads(out.read_text(encoding="utf-8"))["format_version"] == 1
    assert not (tmp_path / "segment_plan.json").exists()
    assert not (tmp_path / f".{EDIT_PLAN_FILENAME}.tmp").exists()


def test_validator_ловит_отсутствующий_asset_и_low_confidence(tmp_path):
    plan = _build_canonical(tmp_path)
    development = next(
        window for window in plan["windows"] if window["role"] == "development"
    )
    development["asset"]["path"] = str(tmp_path / "missing.mp4")
    development["asset"]["confidence"] = 0.01

    report = validate_edit_plan(plan)

    assert report["all_pass"] is False
    assert any("low-confidence" in error for error in report["errors"])
    assert any("не существует" in error for error in report["errors"])


def test_validator_защищает_face_absence_и_motion_contract(tmp_path):
    plan = _build_canonical(tmp_path)
    for window in plan["windows"]:
        if window["role"] in {"hook", "development", "payoff"}:
            window["coverage"] = "hyperframes"
    plan["phrases"][0]["avatar_performance"]["motion_prompt"] = (
        "Zoom the camera around the kitchen for five seconds."
    )

    report = validate_edit_plan(plan)

    assert any("лицо отсутствует дольше" in error for error in report["errors"])
    assert any("неподдерживаемым объектом" in error for error in report["errors"])


def test_validator_не_запрещает_прятать_hook_и_cta_ролью(tmp_path):
    """Решение Васи: правило «роль hook/cta ролик всегда говорит лицом» снято
    и в раннем гейте до заказа, и здесь, в валидаторе. Окно роли `hook` может
    быть полностью скрыто, если это не ломает другие правила — тут оно одно
    и лицо пропадает меньше `MAX_FACE_ABSENCE_S`, так что план проходит целиком.
    """
    plan = _build_canonical(tmp_path)
    hook = next(window for window in plan["windows"] if window["role"] == "hook")
    hook["coverage"] = "hyperframes"

    report = validate_edit_plan(plan)

    assert not any("нельзя полностью скрывать" in error
                  for error in report["errors"]), report["errors"]


def test_finalize_добавляет_exact_timing_не_перепланируя(tmp_path):
    draft = _build_canonical(tmp_path)
    window_ids = [window["id"] for window in draft["windows"]]
    coverages = [window["coverage"] for window in draft["windows"]]
    timed, words = _timed_and_words(draft)

    final = finalize_edit_plan(draft, timed, words)

    assert final["status"] == "final"
    assert final["timeline"]["final_duration_seconds"] == 18.0
    assert [window["id"] for window in final["windows"]] == window_ids
    assert [window["coverage"] for window in final["windows"]] == coverages
    assert all(phrase["final_timing"] for phrase in final["phrases"])
    assert final["validation"]["all_pass"] is True


def test_finalize_exact_timing_делает_явный_asset_fallback(tmp_path):
    draft = _build_canonical(tmp_path, duration=8.0)
    timed, words = _timed_and_words(draft, development_end=12.0)

    final = finalize_edit_plan(draft, timed, words)
    development = next(
        window for window in final["windows"] if window["role"] == "development"
    )

    assert development["coverage"] == "avatar"
    assert development["safe_to_skip_avatar"] is False
    assert final["revisions"]
    assert "короче exact window" in final["revisions"][0]["reason"]
    assert covered_block_indexes(final) == set()


def test_finalize_разводит_цепочку_соседних_окон_на_точных_таймингах(tmp_path):
    """Прод-случай job e00b740b: оценка речи короче озвучки на 22%.

    Черновик разводит цепочку по `WORDS_PER_SEC = 2.5` (scenario.py:403) и
    укладывается в лимит — 9.0с из 10.0. Реальная озвучка длиннее, те же два
    окна занимают 12.0с, и до этой правки finalize не понижал цепочку, а
    валидатор ронял оплаченную сборку исключением.
    """
    scenario = _canonical_scenario()
    # Блоки короче канонических: цепочка из двух соседних окон укладывается
    # в лимит по оценке и вылезает за него только после озвучки.
    scenario["blocks"][1]["end"] = 8.0
    scenario["blocks"][2]["start"] = 8.0
    scenario["blocks"][2]["end"] = 12.0
    scenario["blocks"][3]["start"] = 12.0
    scenario["blocks"][3]["end"] = 15.0
    draft = build_edit_plan(
        scenario,
        _canonical_config(),
        index=_library(tmp_path, duration=30.0),
        library_dir=tmp_path,
        embed_fn=lambda _text: [1.0, 0.0],
    )
    development = next(
        window for window in draft["windows"] if window["role"] == "development"
    )
    payoff = next(
        window for window in draft["windows"] if window["role"] == "payoff"
    )
    # Соседнее fullscreen-окно планировщик сам не поставит (:1600), поэтому
    # цепочку собираем руками — так же, как её собрал Visual Director на проде.
    payoff["coverage"] = "full_broll"
    payoff["zone"] = development["zone"]
    payoff["asset"] = copy.deepcopy(development["asset"])
    payoff["material"] = copy.deepcopy(development.get("material"))
    payoff["safe_to_skip_avatar"] = True
    for phrase in draft["phrases"]:
        if phrase["window_id"] == payoff["id"]:
            phrase["coverage"] = "full_broll"
            phrase["asset"] = copy.deepcopy(payoff["asset"])
    estimated_chain = (
        payoff["estimated_timing"]["end"]
        - development["estimated_timing"]["start"]
    )
    assert estimated_chain <= MAX_FACE_ABSENCE_S

    # Озвучка длиннее оценки на четверть: те же окна уходят за лимит.
    timed = copy.deepcopy(scenario)
    stretched = [(0.0, 3.6), (3.6, 9.6), (9.6, 16.0), (16.0, 19.0)]
    for block, (start, end) in zip(timed["blocks"], stretched):
        block["start"], block["end"] = start, end
    timed["total"] = 19.0
    words = []
    phrases_by_block: dict[int, list] = {}
    for phrase in draft["phrases"]:
        phrases_by_block.setdefault(phrase["block_index"], []).append(phrase)
    for block_index, phrases in phrases_by_block.items():
        block = timed["blocks"][block_index]
        span = (float(block["end"]) - float(block["start"])) / len(phrases)
        for index, phrase in enumerate(phrases):
            words.append({
                "block_index": block_index,
                "start": float(block["start"]) + span * index + 0.05,
                "end": float(block["start"]) + span * (index + 1) - 0.05,
                "text": phrase["text"],
                "character_start": phrase["character_start"],
                "character_end": phrase["character_end"],
            })

    final = finalize_edit_plan(draft, timed, words)

    final_payoff = next(
        window for window in final["windows"] if window["role"] == "payoff"
    )
    final_development = next(
        window for window in final["windows"] if window["role"] == "development"
    )
    chain = (
        final_payoff["final_timing"]["end"]
        - final_development["final_timing"]["start"]
    )
    assert chain > MAX_FACE_ABSENCE_S
    assert final_development["coverage"] == "full_broll"
    assert final_payoff["coverage"] == "avatar"
    assert final_payoff["safe_to_skip_avatar"] is False
    assert any(
        "скрыли бы лицо дольше" in revision["reason"]
        for revision in final["revisions"]
    )
    assert final["validation"]["all_pass"] is True


class _PerformanceRunner:
    def __init__(self, plan):
        self.prompt = None
        self.reply = json.dumps({
            "phrases": [
                {
                    "phrase_id": phrase["id"],
                    "rationale": "Matches the phrase intent.",
                    "gesture": "nod_gentle",
                    "expressiveness": (
                        "high" if phrase["role"] == "hook" else "medium"
                    ),
                }
                for phrase in plan["phrases"]
            ]
        })

    def run(self, prompt):
        self.prompt = prompt
        return self.reply


def test_llm_enrichment_проставляет_рекомендацию_каждой_фразе(tmp_path):
    draft = _build_canonical(tmp_path)
    runner = _PerformanceRunner(draft)

    enriched = enrich_performance_with_llm(draft, runner)

    assert "Photo Avatar IV" in runner.prompt
    assert all(
        phrase["avatar_performance"]["source"] == "llm"
        for phrase in enriched["phrases"]
    )
    hook = next(phrase for phrase in enriched["phrases"] if phrase["role"] == "hook")
    assert hook["avatar_performance"]["expressiveness"] == "high"


def test_пропущенная_фраза_не_роняет_сборку_а_берёт_жест_по_роли(tmp_path):
    draft = _build_canonical(tmp_path)
    incomplete = json.loads(_PerformanceRunner(draft).reply)
    dropped = incomplete["phrases"].pop()["phrase_id"]

    enriched = apply_performance_recommendations(draft, incomplete)
    phrase = next(item for item in enriched["phrases"] if item["id"] == dropped)
    role_default = PERFORMANCE_BY_ROLE[phrase["role"]]

    assert phrase["avatar_performance"]["source"] == "role_default"
    assert (
        phrase["avatar_performance"]["motion_prompt"]
        == role_default["motion_prompt"]
    )


def test_llm_enrichment_не_перезаписывает_явный_avatar_config(tmp_path):
    draft = _build_canonical(
        tmp_path,
        config=_canonical_config(
            expressiveness="low",
            motion_prompt="Looks at the camera and nods gently, calm and sincere.",
        ),
    )
    enriched = enrich_performance_with_llm(draft, _PerformanceRunner(draft))

    assert all(
        phrase["avatar_performance"]["source"] == "config"
        and phrase["avatar_performance"]["expressiveness"] == "low"
        for phrase in enriched["phrases"]
    )


def test_жест_вне_словаря_даёт_ролевой_дефолт_и_не_роняет_сборку(tmp_path, capsys):
    draft = _build_canonical(tmp_path)
    recommendations = json.loads(_PerformanceRunner(draft).reply)
    recommendations["phrases"][0]["gesture"] = "raises_four_fingers"

    enriched = apply_performance_recommendations(draft, recommendations)
    first = enriched["phrases"][0]
    role_default = PERFORMANCE_BY_ROLE[first["role"]]

    assert first["avatar_performance"]["source"] == "role_default"
    assert first["avatar_performance"]["gesture"] == role_default["gesture"]
    assert (
        first["avatar_performance"]["motion_prompt"]
        == role_default["motion_prompt"]
    )
    assert "raises_four_fingers" in capsys.readouterr().err
    # остальные фразы разобраны как обычно — брак одной не задел соседей
    assert enriched["phrases"][1]["avatar_performance"]["source"] == "llm"


def test_валидный_ключ_подставляет_строку_словаря_а_не_текст_модели(tmp_path):
    draft = _build_canonical(tmp_path)
    recommendations = json.loads(_PerformanceRunner(draft).reply)
    recommendations["phrases"][0]["gesture"] = "open_arms_invite"
    # модель прислала и свой текст — он не должен доехать до HeyGen
    recommendations["phrases"][0]["motion_prompt"] = "Raises four fingers."

    enriched = apply_performance_recommendations(draft, recommendations)
    performance = enriched["phrases"][0]["avatar_performance"]

    assert performance["source"] == "llm"
    assert performance["gesture"] == "open_arms_invite"
    assert (
        performance["motion_prompt"]
        == GESTURE_VOCABULARY["open_arms_invite"]["motion_prompt"]
    )
    assert "four fingers" not in json.dumps(performance)


def test_сбой_модели_не_роняет_сборку(tmp_path, capsys):
    draft = _build_canonical(tmp_path)

    class Broken:
        def run(self, prompt):
            raise RuntimeError("claude -p failed (code 1)")

    enriched = enrich_performance_with_llm(draft, Broken())

    assert enriched["validation"]["all_pass"] is True
    assert all(
        phrase["avatar_performance"]["source"] == "role_default"
        for phrase in enriched["phrases"]
    )
    assert "по ролям" in capsys.readouterr().err


def test_промпт_несёт_словарь_и_обходится_без_запретов(tmp_path):
    prompt = performance_analysis_prompt(_build_canonical(tmp_path))

    assert all(key in prompt for key in GESTURE_KEYS)
    for tag in ("<instructions>", "<gestures>", "<examples>", "<example>",
                "<phrases>"):
        assert tag in prompt
    # rationale объявлен раньше выбора жеста
    assert prompt.index('"rationale"') < prompt.index('"gesture"')
    for forbidden in ("must not", "subtle", "camera motion", "scene/location",
                      "props", "walking", "background", "lighting"):
        assert forbidden not in prompt


def test_каждая_строка_словаря_жестов_валидна():
    for key, entry in GESTURE_VOCABULARY.items():
        assert _motion_prompt_error(entry["motion_prompt"]) is None, key
        assert entry["definition"].strip()
    assert "hands_still" in GESTURE_VOCABULARY
    for role, profile in PERFORMANCE_BY_ROLE.items():
        assert profile["gesture"] in GESTURE_VOCABULARY, role
        assert (
            profile["motion_prompt"]
            == GESTURE_VOCABULARY[profile["gesture"]]["motion_prompt"]
        )


def _timed_two_blocks():
    return {"total": 20.0, "blocks": [
        {"role": "hook", "start": 0.0, "end": 6.0,
         "speech": "первый вопрос кому продаём и кто наш клиент"},
        {"role": "cta", "start": 6.0, "end": 20.0, "speech": "сохрани это видео"},
    ]}


def test_у_каждого_окна_есть_разрешённая_зона():
    from reels_factory.editplan import build_edit_plan
    from reels_factory.hf_layout import ALLOWED_ZONES

    plan = build_edit_plan(_timed_two_blocks(), {}, index={}, require_asset_files=False)
    assert plan["windows"], "план без окон — тест бессмыслен"
    for window in plan["windows"]:
        assert window["zone"] in ALLOWED_ZONES


def test_аватарное_окно_поверх_видео():
    from reels_factory.editplan import build_edit_plan

    plan = build_edit_plan(_timed_two_blocks(), {}, index={}, require_asset_files=False)
    for window in plan["windows"]:
        if window["coverage"] in {"avatar", "mixed"}:
            assert window["zone"] == "video-overlay"


def test_поле_камеры_не_потеряно():
    from reels_factory.editplan import build_edit_plan

    plan = build_edit_plan(_timed_two_blocks(), {}, index={}, require_asset_files=False)
    assert all("camera" in w for w in plan["windows"])


def test_даунгрейд_возвращает_зону_с_ведущим():
    from reels_factory.editplan import _downgrade_window

    window = {"id": "w", "phrase_ids": [], "role": "development",
              "coverage": "hyperframes", "zone": "fullscreen"}
    _downgrade_window({"phrases": []}, window, "нет ассета")
    assert window["zone"] == "video-overlay"


def test_полноэкранная_графика_разрешает_пропуск_аватара():
    from reels_factory.editplan import validate_edit_plan

    plan = {
        "format_version": 1, "status": "draft",
        "script": {"language": "ru"},
        "timeline": {"final_duration_seconds": 6.0},
        "blocks": [], "log": [],
        "phrases": [{"id": "p1", "text": "три вопроса", "block_index": 0,
                     "coverage": "hyperframes", "window_id": "w1"}],
        "windows": [{"id": "w1", "phrase_ids": ["p1"], "block_index": 0,
                     "coverage": "hyperframes", "zone": "fullscreen",
                     "safe_to_skip_avatar": True,
                     "effect": {"type": "chart_bars",
                                "hyperframes": {"block": "task_list"}}}],
    }
    report = validate_edit_plan(plan, require_final=False, require_asset_files=False)
    assert not any("HeyGen skip" in e for e in report["errors"])


def test_блок_без_ведущего_помечается_как_не_требующий_аватара():
    from reels_factory.editplan import _refresh_blocks_and_summary

    plan = {
        "blocks": [{"index": 0, "role": "development", "start": 0.0, "end": 6.0}],
        "phrases": [{"id": "p1", "block_index": 0, "coverage": "hyperframes",
                     "window_id": "w1"}],
        "windows": [{"id": "w1", "phrase_ids": ["p1"], "block_index": 0,
                     "coverage": "hyperframes", "zone": "fullscreen",
                     "effect": {"type": "chart_bars"},
                     "safe_to_skip_avatar": True}],
        "summary": {},
    }
    _refresh_blocks_and_summary(plan)
    assert plan["blocks"][0]["avatar_required"] is False


def test_названный_сайт_даёт_запрос_снимка():
    from reels_factory.editplan import material_for_phrase

    material = material_for_phrase("зайди на elevenlabs точка ай о и попробуй")
    assert material["kind"] == "site"
    assert "elevenlabs" in material["url"]


def test_последовательность_действий_даёт_маршрут():
    from reels_factory.editplan import material_for_phrase

    material = material_for_phrase(
        "открываешь гугл вводишь запрос выбираешь первую ссылку и листаешь")
    assert material["kind"] == "route"
    assert material["steps"][0]["type"] == "goto"


def test_без_предмета_материал_не_нужен():
    from reels_factory.editplan import material_for_phrase

    assert material_for_phrase("порядок этих вопросов решает всё") is None
