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
    apply_performance_recommendations,
    build_edit_plan,
    covered_block_indexes,
    enrich_performance_with_llm,
    finalize_edit_plan,
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


def test_validator_защищает_hook_face_absence_и_motion_contract(tmp_path):
    plan = _build_canonical(tmp_path)
    hook = next(window for window in plan["windows"] if window["role"] == "hook")
    hook["coverage"] = "hyperframes"
    for window in plan["windows"]:
        if window["role"] in {"hook", "development", "payoff"}:
            window["coverage"] = "hyperframes"
    plan["phrases"][0]["avatar_performance"]["motion_prompt"] = (
        "Zoom the camera around the kitchen for five seconds."
    )

    report = validate_edit_plan(plan)

    assert any("hook нельзя полностью скрывать" in error for error in report["errors"])
    assert any("лицо отсутствует дольше" in error for error in report["errors"])
    assert any("неподдерживаемым объектом" in error for error in report["errors"])


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


class _PerformanceRunner:
    def __init__(self, plan):
        self.prompt = None
        self.reply = json.dumps({
            "phrases": [
                {
                    "phrase_id": phrase["id"],
                    "expressiveness": (
                        "high" if phrase["role"] == "hook" else "medium"
                    ),
                    "motion_prompt": (
                        "Looks at the camera and nods gently, calm and clear."
                    ),
                    "rationale": "Matches the phrase intent.",
                }
                for phrase in plan["phrases"]
            ]
        })

    def run(self, prompt):
        self.prompt = prompt
        return self.reply


def test_llm_enrichment_требует_рекомендацию_для_каждой_фразы(tmp_path):
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

    incomplete = json.loads(runner.reply)
    incomplete["phrases"].pop()
    with pytest.raises(ValueError, match="phrase IDs"):
        apply_performance_recommendations(draft, incomplete)


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


def test_performance_recommendations_отклоняют_неподдерживаемый_prompt(tmp_path):
    draft = _build_canonical(tmp_path)
    recommendations = json.loads(_PerformanceRunner(draft).reply)
    recommendations["phrases"][0]["motion_prompt"] = (
        "Walk outside while the camera zooms in."
    )

    with pytest.raises(ValueError, match="неподдерживаемым объектом"):
        apply_performance_recommendations(draft, recommendations)
