import json
import pytest
from reels_factory.llm import FakeSkillRunner
from reels_factory.humanize import humanize_scenario, HumanizeError
from reels_factory.humanize import judge_scenario, refine_loop


class _FlakySkillRunner:
    """run_skill бросает RuntimeError, пока не кончится fail_times, потом
    отдаёт reply по очереди — тот же помощник, что и у писателя
    (test_scenario.py:_FlakySkillRunner), для проверки, что хуманайзер и
    судья ретраят через тот же _skill_json, что и writing-scenario."""

    def __init__(self, fail_times: int, replies):
        self.fail_times = fail_times
        self.replies = list(replies)
        self.calls = []

    def run_skill(self, skill, payload_path, json_schema=None):
        self.calls.append((skill, payload_path))
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("claude -p /humanizing-speech не ответил за 600с (таймаут)")
        return self.replies.pop(0)

SC = {"mode": "verbatim", "blocks": [
    {"role": "hook", "start": 0.0, "end": 2.0, "speech": "Мы внедрили Microsoft CRM."},
    {"role": "development", "start": 2.0, "end": 5.0, "speech": "Продажи выросли."},
]}


def test_humanize_writes_task_and_applies_reply(tmp_path):
    reply = json.dumps({"blocks": [
        {"role": "hook", "speech": "Мы внедрили Майкрософт Си-Ар-Эм."},
        {"role": "development", "speech": "Продажи выросли."},
    ]}, ensure_ascii=False)
    runner = FakeSkillRunner([reply])

    out = humanize_scenario(runner, tmp_path, SC, mode="phonetics", language="ru")

    # phonetics правит только speech_tts — то, что видит и утверждает
    # человек (speech), остаётся его собственным текстом нетронутым
    assert out["blocks"][0]["speech"] == "Мы внедрили Microsoft CRM."
    assert out["blocks"][0]["speech_tts"] == "Мы внедрили Майкрософт Си-Ар-Эм."
    assert out["blocks"][0]["start"] == 0.0  # тайминги сохранены
    skill, payload_path = runner.calls[0]
    assert skill == "humanizing-speech"
    task = json.loads(payload_path.read_text(encoding="utf-8"))
    assert task["mode"] == "phonetics"
    assert task["language"] == "ru"
    assert [b["role"] for b in task["blocks"]] == ["hook", "development"]


def test_humanize_phonetics_пропущенный_блок_сохраняет_старый_speech_tts(tmp_path):
    # Скилл вернул пустой speech для развития — старый speech_tts блока
    # (если уже был) остаётся, а не стирается в пустоту.
    sc = {**SC, "blocks": [
        SC["blocks"][0],
        {**SC["blocks"][1], "speech_tts": "Продажи. Уже. Выросли."},
    ]}
    reply = json.dumps({"blocks": [
        {"role": "hook", "speech": "Майкрософт Си-Ар-Эм."},
        {"role": "development", "speech": ""},
    ]}, ensure_ascii=False)
    runner = FakeSkillRunner([reply])

    out = humanize_scenario(runner, tmp_path, sc, mode="phonetics", language="ru")

    assert out["blocks"][1]["speech"] == "Продажи выросли."  # не тронут
    assert out["blocks"][1]["speech_tts"] == "Продажи. Уже. Выросли."  # сохранён


def test_humanize_rejects_block_mismatch(tmp_path):
    reply = json.dumps({"blocks": [{"role": "hook", "speech": "х"}]})
    runner = FakeSkillRunner([reply])
    with pytest.raises(HumanizeError):
        humanize_scenario(runner, tmp_path, SC, mode="polish", language="ru")


def test_humanize_rejects_bad_mode(tmp_path):
    with pytest.raises(HumanizeError):
        humanize_scenario(FakeSkillRunner([]), tmp_path, SC, mode="x", language="ru")


def test_humanize_зовёт_скилл_со_схемой_ответа(tmp_path):
    """Задача 12: humanizing-speech зовётся с --json-schema (role/speech по
    блокам, как обещает сам скилл) — форму принуждает CLI, а не проверка
    постфактум."""
    from reels_factory.humanize import HUMANIZING_SPEECH_SCHEMA

    class _Recording:
        def __init__(self, reply):
            self.reply = reply
            self.seen_schema = None

        def run_skill(self, skill, payload_path, json_schema=None):
            self.seen_schema = json_schema
            return self.reply

    reply = json.dumps({"blocks": [
        {"role": "hook", "speech": "х"},
        {"role": "development", "speech": "у"},
    ]}, ensure_ascii=False)
    runner = _Recording(reply)
    humanize_scenario(runner, tmp_path, SC, mode="phonetics", language="ru")
    assert runner.seen_schema == HUMANIZING_SPEECH_SCHEMA


TASK = {"idea": "как мы подняли продажи", "length_s": 30}


def _blocks_reply(suffix=""):
    return json.dumps({"blocks": [
        {"role": "hook", "speech": "Хук" + suffix},
        {"role": "development", "speech": "Развитие" + suffix},
    ]}, ensure_ascii=False)


VERDICT_FAIL = json.dumps({"pass": False,
                           "scores": {"hook": False},
                           "issues": [{"criterion": "hook", "where": "Хук",
                                       "what": "не цепляет", "fix": "начни с цифры"}]},
                          ensure_ascii=False)
VERDICT_PASS = json.dumps({"pass": True, "scores": {"hook": True}, "issues": []},
                          ensure_ascii=False)


def test_judge_scenario_parses_verdict(tmp_path):
    runner = FakeSkillRunner([VERDICT_PASS])
    sc = {"blocks": [{"role": "hook", "start": 0.0, "end": 2.0, "speech": "х"}]}
    v = judge_scenario(runner, tmp_path, sc, TASK, "ru")
    assert v["pass"] is True
    assert runner.calls[0][0] == "judging-script"


def test_refine_loop_retries_until_pass(tmp_path):
    sc = {"blocks": [
        {"role": "hook", "start": 0.0, "end": 2.0, "speech": "а"},
        {"role": "development", "start": 2.0, "end": 4.0, "speech": "б"},
    ]}
    runner = FakeSkillRunner([
        _blocks_reply(" v1"), VERDICT_FAIL,   # круг 1: polish + брак
        _blocks_reply(" v2"), VERDICT_PASS,   # круг 2: polish с претензиями + pass
    ])
    final, verdict = refine_loop(runner, tmp_path, sc, TASK, "ru", max_rounds=2)
    assert verdict["pass"] is True
    assert final["blocks"][0]["speech"] == "Хук v2"
    # претензии судьи дошли до редактора на 2-м круге
    second_polish_task = json.loads(runner.calls[2][1].read_text(encoding="utf-8"))
    assert second_polish_task.get("issues")


def test_refine_loop_returns_last_on_exhaust(tmp_path):
    sc = {"blocks": [{"role": "hook", "start": 0.0, "end": 2.0, "speech": "а"}]}
    runner = FakeSkillRunner([
        json.dumps({"blocks": [{"role": "hook", "speech": "v1"}]}), VERDICT_FAIL,
        json.dumps({"blocks": [{"role": "hook", "speech": "v2"}]}), VERDICT_FAIL,
    ])
    final, verdict = refine_loop(runner, tmp_path, sc, TASK, "ru", max_rounds=2)
    assert verdict["pass"] is False
    assert final["blocks"][0]["speech"] == "v2"


def test_refine_loop_exhaust_picks_attempt_with_fewer_fails(tmp_path):
    sc = {"blocks": [{"role": "hook", "start": 0.0, "end": 2.0, "speech": "а"}]}
    v1 = json.dumps({"pass": False, "scores": {"hook": False, "speakable": False},
                     "issues": []}, ensure_ascii=False)
    v2 = json.dumps({"pass": False, "scores": {"hook": False}, "issues": []},
                    ensure_ascii=False)
    runner = FakeSkillRunner([
        json.dumps({"blocks": [{"role": "hook", "speech": "v1"}]}), v1,
        json.dumps({"blocks": [{"role": "hook", "speech": "v2"}]}), v2,
    ])
    final, verdict = refine_loop(runner, tmp_path, sc, TASK, "ru", max_rounds=2)
    assert final["blocks"][0]["speech"] == "v2"  # v2 has fewer False scores
    assert verdict["scores"] == {"hook": False}
    log = json.loads((tmp_path / "judge_log.json").read_text(encoding="utf-8"))
    assert len(log["attempts"]) == 2
    assert log["attempts"][0]["scenario"]["blocks"][0]["speech"] == "v1"
    assert log["attempts"][1]["scenario"]["blocks"][0]["speech"] == "v2"


# --- дефект 2 независимой проверки: хуманайзер и судья ретраят так же, как
# писатель (scenario.py:_skill_json), а не проваливаются с первой попытки ---

def test_хуманайзер_первая_попытка_таймаут_вторая_успешна(tmp_path):
    """Первый вызов humanizing-speech таймаутится (RuntimeError), второй
    отвечает нормально — _call_humanizer теперь ретраит его через тот же
    _skill_json, что и writing-scenario, вместо немедленного провала."""
    reply = json.dumps({"blocks": [
        {"role": "hook", "speech": "Хук v2"},
        {"role": "development", "speech": "Развитие v2"},
    ]}, ensure_ascii=False)
    runner = _FlakySkillRunner(1, [reply])

    out = humanize_scenario(runner, tmp_path, SC, mode="polish", language="ru")

    assert out["blocks"][0]["speech"] == "Хук v2"
    assert [c[0] for c in runner.calls] == ["humanizing-speech", "humanizing-speech"]


def test_хуманайзер_обе_попытки_проваливаются_runtimeerror_наружу(tmp_path):
    """Обе попытки провалились — исключение уходит наружу (HumanizeError,
    подкласс RuntimeError — тот же except, что уже алертит провал писателя
    в bot.py), вызовов ровно два, не больше."""
    runner = _FlakySkillRunner(2, [])

    with pytest.raises(RuntimeError, match="не ответил за 600с"):
        humanize_scenario(runner, tmp_path, SC, mode="polish", language="ru")

    assert len(runner.calls) == 2


def test_HumanizeError_подкласс_runtimeerror():
    """bot.py ловит провал сборки сценария как `(ScenarioError,
    RuntimeError)` — HumanizeError обязан попадать под это же except,
    иначе падение хуманайзера/судьи проходит мимо и сообщения человеку, и
    алерта Васе."""
    assert issubclass(HumanizeError, RuntimeError)


def test_судья_первая_попытка_таймаут_вторая_успешна(tmp_path):
    sc = {"blocks": [{"role": "hook", "start": 0.0, "end": 2.0, "speech": "х"}]}
    runner = _FlakySkillRunner(1, [VERDICT_PASS])

    v = judge_scenario(runner, tmp_path, sc, TASK, "ru")

    assert v["pass"] is True
    assert len(runner.calls) == 2


def test_судья_обе_попытки_проваливаются_runtimeerror_наружу(tmp_path):
    sc = {"blocks": [{"role": "hook", "start": 0.0, "end": 2.0, "speech": "х"}]}
    runner = _FlakySkillRunner(2, [])

    with pytest.raises(RuntimeError, match="не ответил за 600с"):
        judge_scenario(runner, tmp_path, sc, TASK, "ru")

    assert len(runner.calls) == 2
