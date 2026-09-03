import json
import re
from pathlib import Path

from reels_factory.llm import FakeRunner
from reels_factory.scenario import (
    ScenarioError,
    WORDS_PER_SEC,
    _mentions_theme,
    build_prompt,
    generate_scenario,
    validate_scenario,
)

CTA = "пиши кофе в комменты"


def _hyp(**kw):
    base = {"theme": "кофе", "theme_spoken": "кофе", "cta_phrase": CTA, "product_name": "Гайд"}
    base.update(kw)
    return base


def _ok_4blocks():
    return {
        "theme": "кофе", "hook_type": "insight_reveal", "premise": "p",
        "title": "t", "broll_query": "q",
        "blocks": [
            {"role": "hook", "start": 0.0, "end": 3.0,
             "speech": "Почему кофе дома всегда кислит?", "pause_after": 0.5},
            {"role": "development", "start": 3.0, "end": 15.0, "speech": "молол слишком мелко"},
            {"role": "payoff", "start": 15.0, "end": 22.0, "speech": "стало ровно и сладко"},
            {"role": "cta", "start": 22.0, "end": 25.0, "speech": f"{CTA} — скину гайд"},
        ],
    }


def _ok_5blocks():
    sc = _ok_4blocks()
    sc["blocks"] = [
        sc["blocks"][0],
        {"role": "context", "start": 3.0, "end": 6.0, "speech": "пробовал разные зёрна"},
        {"role": "development", "start": 6.0, "end": 15.0, "speech": "молол слишком мелко"},
        sc["blocks"][2], sc["blocks"][3],
    ]
    sc["blocks"][3]["start"] = 15.0
    return sc


def test_валидный_4блочный_проходит():
    assert validate_scenario(_ok_4blocks(), _hyp()) == []


def test_валидный_5блочный_проходит():
    assert validate_scenario(_ok_5blocks(), _hyp()) == []


def test_cta_без_дословной_фразы_ошибка():
    sc = _ok_4blocks()
    sc["blocks"][3]["speech"] = "подпишись на канал"
    errs = validate_scenario(sc, _hyp())
    assert any("cta" in e and "дословн" in e for e in errs)


def test_generate_пишет_файл_и_ретраит(tmp_path):
    bad = json.dumps({"blocks": []})
    good = json.dumps(_ok_4blocks(), ensure_ascii=False)
    runner = FakeRunner([bad, good])
    sc = generate_scenario(tmp_path, _hyp(hook_type="insight_reveal"), runner)
    assert sc["theme"] == "кофе"
    assert json.loads((tmp_path / "scenario.json").read_text(encoding="utf-8"))["theme"] == "кофе"
    assert len(runner.prompts) == 2


def test_эмоц_теги_не_считаются_словами():
    sc = _ok_4blocks()
    tags = " ".join(f"[тег{i}]" for i in range(30))
    sc["blocks"][1]["speech"] = tags + " короткая реплика"
    assert validate_scenario(sc, _hyp()) == []


def test_development_без_speech_ошибка():
    sc = _ok_4blocks()
    sc["blocks"][1]["speech"] = ""
    errs = validate_scenario(sc, _hyp())
    assert any("development" in e and "speech" in e for e in errs)


def test_болтливый_сценарий_отклоняется():
    sc = _ok_4blocks()
    sc["blocks"][1]["speech"] = "слово " * 80
    errs = validate_scenario(sc, _hyp())
    assert any("слишком длинная" in e for e in errs)


def test_target_90_расширяет_duration_и_word_budget():
    sc = _ok_4blocks()
    sc["blocks"][0]["end"] = 3.0
    sc["blocks"][1]["start"], sc["blocks"][1]["end"] = 3.0, 65.0
    sc["blocks"][2]["start"], sc["blocks"][2]["end"] = 65.0, 85.0
    sc["blocks"][3]["start"], sc["blocks"][3]["end"] = 85.0, 90.0
    sc["blocks"][1]["speech"] = "кофе " + "слово " * 150

    assert validate_scenario(sc, _hyp(target_duration_s=90)) == []
    assert any(
        "вне 14-40" in error
        for error in validate_scenario(sc, _hyp())
    )


def test_prompt_60_строит_динамический_skeleton_и_budget():
    prompt = build_prompt(_hyp(target_duration_s=60))
    assert "целевая длительность 60 секунд" in prompt
    # бюджет слов = target * WORDS_PER_SEC (scenario.py:66), не отдельное число
    assert f"около {round(60 * WORDS_PER_SEC)} слов" in prompt
    assert '"end": 60.0' in prompt


def test_hook_без_вопроса_валиден():
    sc = _ok_4blocks()
    sc["blocks"][0]["speech"] = "Кофе дома почти всегда кислит на этом шаге"
    assert validate_scenario(sc, _hyp()) == []


def test_hook_без_темы_ошибка():
    sc = _ok_4blocks()
    sc["blocks"][0]["speech"] = "Почему всегда получается кисло?"
    sc["blocks"][1]["speech"] = "и что теперь делать?"
    errs = validate_scenario(sc, _hyp())
    assert any("тема" in e and "перв" in e for e in errs)


def test_тема_только_в_development_валидна():
    sc = _ok_4blocks()
    sc["blocks"][0]["speech"] = "Зацените, что сейчас будет"
    sc["blocks"][1]["speech"] = "весь секрет кофе — в помоле"
    assert validate_scenario(sc, _hyp()) == []


def test_hook_с_брендом_в_речи_ошибка():
    sc = _ok_4blocks()
    sc["blocks"][0]["speech"] = "Гайд по кофе спасёт твой завтрак"
    errs = validate_scenario(sc, _hyp())
    assert any("hook" in e and ("продукт" in e or "бренд" in e) for e in errs)


def test_hook_упоминает_theme_spoken_из_гипотезы():
    sc = _ok_4blocks()
    sc["theme"] = "кофе"
    sc["blocks"][0]["speech"] = "Почему эспрессо всегда горчит?"
    # theme_spoken "эспрессо" встречается в хуке по корню
    assert validate_scenario(sc, _hyp(theme_spoken="эспрессо")) == []


def test_pause_after_вне_диапазона_ошибка():
    sc = _ok_4blocks()
    sc["blocks"][0]["pause_after"] = 2
    errs = validate_scenario(sc, _hyp())
    assert any("pause_after" in e for e in errs)


def test_pause_after_в_диапазоне_ок():
    sc = _ok_4blocks()
    sc["blocks"][0]["pause_after"] = 0.5
    assert validate_scenario(sc, _hyp()) == []


def test_нарушение_скелета_роли():
    sc = _ok_4blocks()
    sc["blocks"][1]["role"] = "middle"
    errs = validate_scenario(sc, _hyp())
    assert any("roles" in e for e in errs)


def test_mentions_theme_с_цифрой_матчится_по_корню():
    assert _mentions_theme("Почему в Доте 2 саппорт виноват?", None, "Дота 2") is True


def test_mentions_theme_без_упоминания_не_матчится():
    assert _mentions_theme("...с напарником по делу", None, "ПАБГ") is False


def test_mentions_theme_падежная_форма_матчится():
    assert _mentions_theme("Почему в ПАБГе бегут в Покровку?", None, "ПАБГ") is True


def test_mentions_theme_latin_theme_cyrillic_text():
    # Баг: тема "Vael" при русском тексте валила сценарий,
    # хотя theme_spoken («ваэль») в тексте есть.
    assert _mentions_theme("расскажу про ваэль и её фишки", "Vael", "ваэль") is True


def test_mentions_theme_skips_incomparable_alphabet():
    # Латинский кандидат без кириллического дубля не должен давать False,
    # если в тексте вообще нет латиницы — алфавиты несопоставимы.
    assert _mentions_theme("текст только кириллицей", "Vael") is True


def test_mentions_theme_still_fails_when_absent():
    assert _mentions_theme("текст про другое", "маркетинг", "маркетинга") is False


def test_mentions_theme_mixed_candidate_uses_comparable_word():
    # «Vael бот»: Vael несопоставим с кириллицей, но «бот» — сопоставим и найден
    assert _mentions_theme("запускаем бота на сервере", "Vael бот") is True


def test_mentions_theme_mixed_candidate_can_fail():
    # «бот» сопоставим, в тексте отсутствует — честный провал, не пропуск
    assert _mentions_theme("текст про другое", "Vael бот") is False


def test_промпт_содержит_theme_spoken_и_cta(tmp_path):
    good = json.dumps(_ok_4blocks(), ensure_ascii=False)
    runner = FakeRunner([good])
    generate_scenario(tmp_path, _hyp(theme_spoken="эспрессо", hook_type="insight_reveal"), runner)
    prompt = runner.prompts[0]
    assert "эспрессо" in prompt
    assert CTA in prompt


def test_промпт_не_предлагает_v3_audio_tags(tmp_path):
    good = json.dumps(_ok_4blocks(), ensure_ascii=False)
    runner = FakeRunner([good])
    generate_scenario(tmp_path, _hyp(), runner)
    prompt = runner.prompts[0]
    assert "Eleven Multilingual v2" in prompt
    assert "[curious]" not in prompt
    assert "[excited]" not in prompt
    assert "[sighs]" not in prompt


def test_персона_и_манера_речи_в_промпте(tmp_path):
    good = json.dumps(_ok_4blocks(), ensure_ascii=False)
    runner = FakeRunner([good])
    hyp = _hyp(persona={"description": "девушка-бариста, 25 лет, дружелюбная",
                        "speech_style": "короткие фразы, прямота"})
    generate_scenario(tmp_path, hyp, runner)
    prompt = runner.prompts[0]
    assert "девушка-бариста, 25 лет, дружелюбная" in prompt
    assert "короткие фразы, прямота" in prompt
    assert "блогерш" not in prompt.lower()


def test_insight_и_facts_пробрасываются_в_промпт(tmp_path):
    good = json.dumps(_ok_4blocks(), ensure_ascii=False)
    runner = FakeRunner([good])
    hyp = _hyp(insight="мелкий помол даёт переэкстракцию",
               facts={"hook": "чашка кислого кофе", "payoff": "ровный вкус"})
    generate_scenario(tmp_path, hyp, runner)
    prompt = runner.prompts[0]
    assert "мелкий помол даёт переэкстракцию" in prompt
    assert "чашка кислого кофе" in prompt
    assert "ровный вкус" in prompt


# ---------------------------------------------------------------------------
# Task 2: Tests for split_verbatim, scenario_from_text, validate_integrity

from reels_factory.scenario import (
    split_verbatim, scenario_from_text, validate_integrity, ROLES_4,
)


def _norm(s):
    return re.sub(r"\s+", " ", s).strip()


TEXT = ("Мы запустили продукт в марте. Первый месяц не было ни одной продажи. "
        "Потом мы поменяли оффер. Продажи пошли на третий день. "
        "Сейчас у нас двадцать клиентов.")


def test_split_preserves_text_verbatim():
    blocks = split_verbatim(TEXT)
    joined = " ".join(b["speech"] for b in blocks)
    assert _norm(joined) == _norm(TEXT)


def test_split_roles_and_order():
    blocks = split_verbatim(TEXT)
    assert len(blocks) == 4
    assert [b["role"] for b in blocks] == ROLES_4[:len(blocks)]


def test_split_block_count_matches_sentences():
    # ровно min(4, n_предложений) блоков — роли не теряются
    for n in range(1, 8):
        text = " ".join(f"Предложение номер {i} тут." for i in range(n))
        blocks = split_verbatim(text)
        assert len(blocks) == min(4, n), f"n={n}: {[b['role'] for b in blocks]}"
        joined = " ".join(b["speech"] for b in blocks)
        assert joined.split() == text.split()


def test_split_timings_monotonic():
    blocks = split_verbatim(TEXT)
    assert blocks[0]["start"] == 0.0
    for prev, cur in zip(blocks, blocks[1:]):
        assert cur["start"] == prev["end"]
        assert cur["end"] > cur["start"]


def test_split_short_text_single_block():
    blocks = split_verbatim("Одна фраза.")
    assert len(blocks) == 1
    assert blocks[0]["speech"] == "Одна фраза."


# ---------------------------------------------------------------------------
# Темп речи: одна константа вместо двух (задача 04, замер по прод-заданиям).

def test_words_per_second_target_не_существует_отдельно():
    """WORDS_PER_SECOND_TARGET и WORDS_PER_SEC были двумя копиями 2.5 —
    теперь темп речи только один: WORDS_PER_SEC (scenario.py:66)."""
    import reels_factory.scenario as scenario_module

    assert not hasattr(scenario_module, "WORDS_PER_SECOND_TARGET")
    assert scenario_module.WORDS_PER_SEC == WORDS_PER_SEC
    assert WORDS_PER_SEC < 2.5  # была верхней границей темпа, не серединой


def test_words_soft_hard_считаются_от_words_per_sec():
    """words_soft/words_hard — бюджет слов под заданную длину, тот же темп,
    что и у split_verbatim/run_verbatim_path (не отдельное число)."""
    from reels_factory.scenario import _duration_contract, WORDS_PER_SEC
    import math

    contract = _duration_contract({"target_duration_s": 20.0})
    assert contract["words_soft"] == max(30, round(20.0 * WORDS_PER_SEC))
    assert contract["words_hard"] == max(36, math.ceil(20.0 * WORDS_PER_SEC * 1.12))


def test_split_verbatim_считает_длительность_по_words_per_sec():
    from reels_factory.scenario import WORDS_PER_SEC

    blocks = split_verbatim(TEXT)
    for block in blocks:
        expected = round(len(block["speech"].split()) / WORDS_PER_SEC, 1)
        assert round(block["end"] - block["start"], 1) == expected


def test_темп_не_короче_факта_на_job_e00b740b():
    """Прод-job e00b740b (2026-09-03): 154 слова, реальная озвучка (по
    audio/tts/alignment.words.json на 134.209.80.75) — 72.82с. Черновой план
    по старой WORDS_PER_SEC=2.5 давал 59.6с (в scenario.json job'а) — короче
    факта на 22%. Оценка по новой константе должна лечь в ±10% факта, а не
    систематически строить план короче."""
    words = 154
    real_seconds = 72.82

    estimated = round(words / WORDS_PER_SEC, 1)

    assert abs(estimated - real_seconds) / real_seconds <= 0.10


def test_scenario_from_text_writes_file(tmp_path):
    sc = scenario_from_text(tmp_path, TEXT)
    on_disk = json.loads((tmp_path / "scenario.json").read_text(encoding="utf-8"))
    assert on_disk == sc
    assert sc["mode"] == "verbatim"
    assert validate_integrity(sc) == []


def test_validate_integrity_catches_empty_speech():
    sc = {"blocks": [{"role": "hook", "start": 0.0, "end": 2.0, "speech": ""}]}
    errs = validate_integrity(sc)
    assert any("speech" in e for e in errs)


def test_validate_integrity_catches_gap():
    sc = {"blocks": [
        {"role": "hook", "start": 0.0, "end": 2.0, "speech": "а"},
        {"role": "development", "start": 3.0, "end": 5.0, "speech": "б"},
    ]}
    assert validate_integrity(sc) != []


def test_validate_integrity_no_quality_rules():
    # 200 слов, нет CTA, латиница — целостность ДОЛЖНА пройти (качество не её дело)
    long_speech = "слово " * 200 + "Microsoft"
    sc = {"blocks": [{"role": "hook", "start": 0.0, "end": 80.0, "speech": long_speech}]}
    assert validate_integrity(sc) == []


# ---------------------------------------------------------------------------
# Task 6: Tests for run_verbatim_path

from reels_factory.llm import FakeSkillRunner
from reels_factory.scenario import run_verbatim_path


def test_run_verbatim_path_full_flow(tmp_path):
    text = "Мы внедрили Microsoft. Продажи выросли в два раза. Клиенты довольны."
    phonetics_reply = json.dumps({"blocks": [
        {"role": "hook", "speech": "Мы внедрили Майкрософт."},
        {"role": "development", "speech": "Продажи выросли в два раза."},
        {"role": "payoff", "speech": "Клиенты довольны."},
    ]}, ensure_ascii=False)
    runner = FakeSkillRunner([phonetics_reply])

    res = run_verbatim_path(tmp_path, text, runner, language="ru")

    assert res["ok"] is True
    sc = res["scenario"]
    assert sc["mode"] == "verbatim"
    assert sc["language"] == "ru"
    assert "Майкрософт" in sc["blocks"][0]["speech"]
    assert (tmp_path / "scenario.json").exists()
    assert res["info"]["words"] > 0
    assert res["info"]["est_seconds"] > 0
    # задание фонетики получило текст одним блоком (разбивка — после)
    task = json.loads(runner.calls[0][1].read_text(encoding="utf-8"))
    assert task["mode"] == "phonetics"


def test_script_text_passes_language_to_transcribe(monkeypatch, tmp_path):
    import reels_factory.__main__ as cli

    seen = {}

    def fake_transcribe_file(src, workdir, model_size="large-v3",
                             language="ru", device="auto"):
        seen["language"] = language
        out = Path(workdir) / "words.json"
        out.write_text(json.dumps({"words": [
            {"id": 0, "start": 0.0, "end": 1.0, "text": "сәлем", "prob": 1.0}]},
            ensure_ascii=False), encoding="utf-8")
        return {"ok": True, "out": str(out)}

    import reels_factory.transcribe as tr
    monkeypatch.setattr(tr, "transcribe_file", fake_transcribe_file)

    class Args:
        workdir = str(tmp_path)
        text_file = None
        audio = "fake.wav"

    import reels_factory.llm as llm
    monkeypatch.setattr(llm, "ClaudeSkillRunner",
                        lambda: FakeSkillRunner([json.dumps(
                            {"blocks": [{"role": "hook", "speech": "сәлем"}]},
                            ensure_ascii=False)]))

    cli._cmd_script_text(Args, {"language": "kk"})
    assert seen["language"] == "kk"


# ---------------------------------------------------------------------------
# Task 9: Tests for run_generated_path

from reels_factory.scenario import run_generated_path

IDEA = {"idea": "скидка всем убивала средний чек", "length_s": 20,
        "quotes": ["средний чек вырос вдвое"], "persona": "владелец бизнеса"}


def _gen_reply():
    return json.dumps({"title": "Скидка-убийца", "blocks": [
        {"role": "hook", "start": 0.0, "end": 3.0, "speech": "Минус триста тысяч."},
        {"role": "development", "start": 3.0, "end": 12.0, "speech": "Скидка была всем."},
        {"role": "payoff", "start": 12.0, "end": 17.0, "speech": "Чек вырос вдвое."},
        {"role": "cta", "start": 17.0, "end": 20.0, "speech": "Сохрани."},
    ]}, ensure_ascii=False)


def _polish_pass_replies():
    blocks = json.loads(_gen_reply())["blocks"]
    polish = json.dumps({"blocks": [{"role": b["role"], "speech": b["speech"]}
                                    for b in blocks]}, ensure_ascii=False)
    verdict = json.dumps({"pass": True, "scores": {}, "issues": []})
    return [polish, verdict]


def test_run_generated_path_full_flow(tmp_path):
    runner = FakeSkillRunner([_gen_reply(), *_polish_pass_replies()])
    res = run_generated_path(tmp_path, IDEA, runner, language="ru")
    assert res["ok"] is True
    assert res["verdict"]["pass"] is True
    assert res["scenario"]["language"] == "ru"
    assert res["scenario"]["mode"] == "generated"
    assert (tmp_path / "scenario.json").exists()
    # порядок вызовов: генерация -> полировка -> судья
    assert [c[0] for c in runner.calls] == [
        "writing-scenario", "humanizing-speech", "judging-script"]
    gen_task = json.loads(runner.calls[0][1].read_text(encoding="utf-8"))
    assert gen_task["length_s"] == 20
    assert gen_task["language"] == "ru"


def test_run_generated_path_fail_returns_variants(tmp_path):
    gen_blocks = json.loads(_gen_reply())["blocks"]
    polish1 = json.dumps({"blocks": [{"role": b["role"], "speech": b["speech"] + " A"}
                                     for b in gen_blocks]}, ensure_ascii=False)
    verdict1 = json.dumps({"pass": False,
                           "scores": {"hook": False, "speakable": False}, "issues": []},
                          ensure_ascii=False)
    polish2 = json.dumps({"blocks": [{"role": b["role"], "speech": b["speech"] + " B"}
                                     for b in gen_blocks]}, ensure_ascii=False)
    verdict2 = json.dumps({"pass": False, "scores": {"hook": False}, "issues": []},
                          ensure_ascii=False)
    runner = FakeSkillRunner([_gen_reply(), polish1, verdict1, polish2, verdict2])

    res = run_generated_path(tmp_path, IDEA, runner, language="ru")

    assert res["ok"] is True
    assert res["verdict"]["pass"] is False
    assert res["variants"] == 2
    on_disk = json.loads((tmp_path / "scenario.json").read_text(encoding="utf-8"))
    assert on_disk["blocks"] == res["scenario"]["blocks"]
    assert on_disk["blocks"][0]["speech"].endswith(" B")  # меньше провалов
    variant2_path = tmp_path / "scenario.variant2.json"
    assert variant2_path.exists()
    variant2 = json.loads(variant2_path.read_text(encoding="utf-8"))
    assert variant2["blocks"][0]["speech"].endswith(" A")
    assert variant2["blocks"] != res["scenario"]["blocks"]


def test_run_generated_path_bad_blocks_raises(tmp_path):
    runner = FakeSkillRunner([json.dumps({"title": "x", "blocks": []})])
    import pytest as _pytest
    with _pytest.raises(Exception):
        run_generated_path(tmp_path, IDEA, runner, language="ru")


def test_run_generated_path_error_surfaces_as_json(monkeypatch, tmp_path, capsys):
    import reels_factory.__main__ as cli
    import reels_factory.llm as llm
    from reels_factory.humanize import HumanizeError

    idea_path = tmp_path / "idea.json"
    idea_path.write_text('{"idea": "и", "length_s": 20, "quotes": []}', encoding="utf-8")

    def boom(workdir, idea, runner, language):
        raise HumanizeError("судья вернул не-JSON")

    import reels_factory.scenario as sc_mod
    monkeypatch.setattr(sc_mod, "run_generated_path", boom)
    monkeypatch.setattr(llm, "ClaudeSkillRunner", lambda: object())

    class Args:
        workdir = str(tmp_path)
        idea_file = str(idea_path)

    import pytest as _pytest
    with _pytest.raises(SystemExit) as exc:
        cli._cmd_script_idea(Args, {"language": "ru"})
    assert exc.value.code == 1
    import json as _json
    out = _json.loads(capsys.readouterr().out.strip())
    assert out["ok"] is False and "не-JSON" in out["error"]


# ---------------------------------------------------------------------------
# Task 10: Tests for run_ideas

from reels_factory.scenario import run_ideas

IDEAS_REPLY = json.dumps({"ideas": [
    {"idea": "и1", "emotion": "удивление", "draft_hook": "х1",
     "quotes": ["ц1"], "length_s": 30, "why": "спорное мнение"},
    {"idea": "и2", "emotion": "злость", "draft_hook": "х2",
     "quotes": ["ц2"], "length_s": 60, "why": "история"},
]}, ensure_ascii=False)


def test_run_ideas_flow(tmp_path):
    runner = FakeSkillRunner([IDEAS_REPLY])
    res = run_ideas(tmp_path, "длинный транскрипт встречи", runner, "ru")
    assert res["ok"] is True
    assert len(res["ideas"]) == 2
    assert (tmp_path / "ideas.json").exists()
    task = json.loads(runner.calls[0][1].read_text(encoding="utf-8"))
    assert task["transcript"] == "длинный транскрипт встречи"


def test_run_ideas_rejects_wrong_shape(tmp_path):
    runner = FakeSkillRunner([json.dumps({"ideas": []})])
    import pytest as _pytest
    with _pytest.raises(Exception):
        run_ideas(tmp_path, "т", runner, "ru")


def test_script_text_missing_file_json_error(capsys, tmp_path):
    import reels_factory.__main__ as cli

    class Args:
        workdir = str(tmp_path)
        text_file = str(tmp_path / "нет-такого.txt")
        audio = None

    import pytest as _pytest
    with _pytest.raises(SystemExit) as exc:
        cli._cmd_script_text(Args, {"language": "ru"})
    assert exc.value.code == 1
    out = json.loads(capsys.readouterr().out.strip())
    assert out["ok"] is False


def test_script_idea_failing_verdict_exits_0_with_variants(monkeypatch, tmp_path, capsys):
    import reels_factory.__main__ as cli
    import reels_factory.llm as llm
    import reels_factory.scenario as sc_mod

    idea_path = tmp_path / "idea.json"
    idea_path.write_text(json.dumps({"idea": "и", "length_s": 20, "quotes": []}),
                         encoding="utf-8")

    def fake_run(workdir, idea, runner, language):
        return {"ok": True, "scenario": {"blocks": []},
                "verdict": {"pass": False}, "variants": 2}

    monkeypatch.setattr(sc_mod, "run_generated_path", fake_run)
    monkeypatch.setattr(llm, "ClaudeSkillRunner", lambda: object())

    class Args:
        workdir = str(tmp_path)
        idea_file = str(idea_path)

    cli._cmd_script_idea(Args, {"language": "ru"})  # не должен бросить SystemExit
    out = json.loads(capsys.readouterr().out.strip())
    assert out["variants"] == 2
    assert out["verdict"]["pass"] is False


def test_script_idea_missing_file_json_error(capsys, tmp_path):
    import reels_factory.__main__ as cli

    class Args:
        workdir = str(tmp_path)
        idea_file = str(tmp_path / "нет.json")

    import pytest as _pytest
    with _pytest.raises(SystemExit) as exc:
        cli._cmd_script_idea(Args, {"language": "ru"})
    assert exc.value.code == 1
    out = json.loads(capsys.readouterr().out.strip())
    assert out["ok"] is False


# Диагностика провала скилла: «bad json» без причины не отлаживается.

def test_не_json_от_скилла_сохраняется_и_виден_в_ошибке(tmp_path):
    from reels_factory.scenario import ScenarioError
    import pytest as _pytest

    proza = "Не могу выполнить: не нашёл файл задания."
    runner = FakeSkillRunner([proza, proza])
    with _pytest.raises(ScenarioError) as exc:
        run_generated_path(tmp_path, IDEA, runner, language="ru")

    assert "не нашёл файл задания" in str(exc.value)
    saved = tmp_path / "writing-scenario_reply.txt"
    assert saved.read_text(encoding="utf-8") == proza


def test_не_json_от_скилла_переспрашивается_один_раз(tmp_path):
    runner = FakeSkillRunner(["просто текст", _gen_reply(), *_polish_pass_replies()])
    res = run_generated_path(tmp_path, IDEA, runner, language="ru")
    assert res["ok"] is True
    assert [c[0] for c in runner.calls][:2] == ["writing-scenario", "writing-scenario"]


def test_не_json_от_скилла_идей_виден_в_ошибке(tmp_path):
    from reels_factory.scenario import ScenarioError
    import pytest as _pytest

    runner = FakeSkillRunner(["транскрипт пустой, идей нет", "и снова текст"])
    with _pytest.raises(ScenarioError) as exc:
        run_ideas(tmp_path, "сырьё", runner, "ru")
    assert "и снова текст" in str(exc.value)  # в ошибке — последняя попытка
    assert (tmp_path / "extracting-ideas_reply.txt").exists()
