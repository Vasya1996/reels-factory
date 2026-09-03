"""Хуманизация сценария: вызов скилла humanizing-speech через SkillRunner.

Режимы (выбираются путём, не пользователем): polish — переписать под живую
устную речь (факты неприкосновенны); phonetics — только фонетическая запись
терминов/брендов и числа прописью, больше ничего (путь «дословно»).

У блока два текста (задача 15): `speech` — как показать (человеку на экране
утверждения и в титре), `speech_tts` — как произнести (ElevenLabs). polish
правит `speech` — это переписывание самой речи, его видит и утверждает
человек. phonetics правит только `speech_tts`: «Qaz AI Research» на экране
должно остаться латиницей, как написал человек, а ElevenLabs получит
«Казак Эй-Ай Рисёрч» отдельным полем — `build_canonical_script(...,
prefer_tts=True)` в master_audio.py берёт speech_tts, если он задан, иначе
speech.

Плюс цикл редактор -> судья (refine_loop): polish -> judge, при браке -
повторный polish с претензиями судьи -> judge, до max_rounds или до pass.
"""
import json
from pathlib import Path

from reels_factory.scenario import _skill_json, ScenarioError

MODES = ("polish", "phonetics")
_TARGET_FIELD = {"polish": "speech", "phonetics": "speech_tts"}

#: --json-schema для humanizing-speech (задача 12): форма, которую сам скилл
#: обещает вернуть (skills/humanizing-speech/SKILL.md:28) и которую
#: `_call_humanizer` ниже реально читает — role/speech по блокам, без
#: остального.
HUMANIZING_SPEECH_SCHEMA = {
    "type": "object",
    "properties": {
        "blocks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "role": {"type": "string"},
                    "speech": {"type": "string"},
                },
                "required": ["role", "speech"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["blocks"],
    "additionalProperties": False,
}


class HumanizeError(RuntimeError):
    """RuntimeError, а не голый Exception: обработчики bot.py уже ловят
    `(ScenarioError, RuntimeError)` вокруг step_scenario/step_verbatim
    (то же место, что алертит провал писателя) — голый Exception туда не
    попадал бы и падение хуманайзера/судьи проходило бы мимо и сообщения
    человеку, и алерта Васе."""


def _call_humanizer(runner, workdir, sc: dict, payload: dict, *,
                    target_field: str = "speech") -> dict:
    """Пишет payload в humanize_task.json, вызывает humanizing-speech через
    тот же _skill_json, что и писатель (scenario.py) — один повтор на
    таймаут/сбой claude -p или кривой JSON, а не немедленный провал с первой
    попытки. Раньше здесь стоял голый runner.run_skill() без повтора —
    асимметрия с writing-scenario, не заявленная в коммите c7d4b20.
    Проверяет роли блоков в ответе, кладёт результат в `target_field` блока
    (остальные поля блока, включая `speech`, если target_field другой —
    нетронуты)."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    payload_path = workdir / "humanize_task.json"
    payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                             encoding="utf-8")

    try:
        data = _skill_json(runner, "humanizing-speech", payload_path, workdir,
                           json_schema=HUMANIZING_SPEECH_SCHEMA)
    except (RuntimeError, ScenarioError) as e:
        raise HumanizeError(str(e)) from e

    new_blocks = data.get("blocks")
    if (not isinstance(new_blocks, list)
            or [b.get("role") for b in new_blocks] != [b["role"] for b in sc["blocks"]]):
        raise HumanizeError(
            f"скилл вернул блоки с другими ролями/количеством: {new_blocks!r}")

    return {**sc, "blocks": [
        dict(orig, **{target_field: str(
            nb.get("speech") or orig.get(target_field) or orig["speech"]
        )})
        for orig, nb in zip(sc["blocks"], new_blocks)
    ]}


def humanize_scenario(runner, workdir, sc: dict, mode: str, language: str) -> dict:
    if mode not in MODES:
        raise HumanizeError(f"неизвестный режим {mode!r}, ожидается {MODES}")
    payload = {
        "mode": mode,
        "language": language,
        "blocks": [{"role": b["role"], "speech": b["speech"]} for b in sc["blocks"]],
    }
    return _call_humanizer(runner, workdir, sc, payload,
                           target_field=_TARGET_FIELD[mode])


def _polish_with_task(runner, workdir, sc: dict, language: str, task: dict) -> dict:
    """Как humanize_scenario(mode=polish), но с полем task в задании."""
    payload = {
        "mode": "polish",
        "language": language,
        "task": task,
        "blocks": [{"role": b["role"], "speech": b["speech"]} for b in sc["blocks"]],
        **({"issues": task["issues"]} if task.get("issues") else {}),
    }
    return _call_humanizer(runner, workdir, sc, payload)


def judge_scenario(runner, workdir, sc: dict, task: dict, language: str) -> dict:
    """Тот же _skill_json, что и у писателя и у _call_humanizer выше — один
    повтор на таймаут/сбой claude -p или кривой JSON вместо немедленного
    провала с первой попытки."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    payload = workdir / "judge_task.json"
    payload.write_text(json.dumps(
        {"language": language, "task": task,
         "blocks": [{"role": b["role"], "speech": b["speech"]} for b in sc["blocks"]]},
        ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        v = _skill_json(runner, "judging-script", payload, workdir)
    except (RuntimeError, ScenarioError) as e:
        raise HumanizeError(f"судья вернул не-JSON: {e}") from e
    if not isinstance(v.get("pass"), bool):
        raise HumanizeError(f"вердикт без поля pass: {v!r}")
    return v


def _n_fails(verdict: dict) -> int:
    scores = (verdict or {}).get("scores") or {}
    return sum(1 for v in scores.values() if v is False)


def refine_loop(runner, workdir, sc: dict, task: dict, language: str,
                max_rounds: int = 2):
    """polish -> judge; брак -> polish с претензиями -> judge. Возвращает
    (лучший из имеющихся сценарий, последний вердикт).

    При исчерпании раундов без pass пишет workdir/judge_log.json со всеми
    попытками (лог для авторов, не для пользователя) и возвращает лучшую из
    них — с наименьшим числом False в verdict["scores"] (при равенстве —
    более позднюю попытку)."""
    current, verdict = sc, None
    issues = []
    attempts = []
    for _ in range(max_rounds):
        round_task = dict(task)
        if issues:
            round_task["issues"] = issues
        # humanize_scenario читает только mode/language/blocks; претензии и
        # задание кладём в тот же файл — скилл увидит их в JSON задания
        current = _polish_with_task(runner, workdir, current, language, round_task)
        judge_task = dict(task)
        if issues:
            judge_task["prior_issues"] = issues
        verdict = judge_scenario(runner, workdir, current, judge_task, language)
        attempts.append({"scenario": current, "verdict": verdict})
        if verdict["pass"]:
            return current, verdict
        issues = verdict.get("issues") or []

    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "judge_log.json").write_text(
        json.dumps({"attempts": attempts}, ensure_ascii=False, indent=1),
        encoding="utf-8")

    best = attempts[0]
    for a in attempts[1:]:
        if _n_fails(a["verdict"]) <= _n_fails(best["verdict"]):
            best = a
    return best["scenario"], best["verdict"]
