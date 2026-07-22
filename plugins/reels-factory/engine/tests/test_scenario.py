import json
import re
from pathlib import Path

from reels_factory.llm import FakeRunner
from reels_factory.scenario import generate_scenario, validate_scenario, ScenarioError, _mentions_theme

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


def test_промпт_содержит_theme_spoken_и_cta(tmp_path):
    good = json.dumps(_ok_4blocks(), ensure_ascii=False)
    runner = FakeRunner([good])
    generate_scenario(tmp_path, _hyp(theme_spoken="эспрессо", hook_type="insight_reveal"), runner)
    prompt = runner.prompts[0]
    assert "эспрессо" in prompt
    assert CTA in prompt


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
