"""Хуманизация сценария: вызов скилла humanizing-speech через SkillRunner.

Режимы (выбираются путём, не пользователем): polish — переписать под живую
устную речь (факты неприкосновенны); phonetics — только фонетическая запись
терминов/брендов и числа прописью, больше ничего (путь «дословно»).

Плюс цикл редактор -> судья (refine_loop): polish -> judge, при браке -
повторный polish с претензиями судьи -> judge, до max_rounds или до pass.
"""
import json
from pathlib import Path

from reels_factory.scenario import _extract_json, ScenarioError

MODES = ("polish", "phonetics")


class HumanizeError(Exception):
    pass


def _call_humanizer(runner, workdir, sc: dict, payload: dict) -> dict:
    """Пишет payload в humanize_task.json, вызывает humanizing-speech,
    проверяет роли блоков в ответе, возвращает обновлённый сценарий."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    payload_path = workdir / "humanize_task.json"
    payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                             encoding="utf-8")

    reply = runner.run_skill("humanizing-speech", payload_path)
    try:
        data = _extract_json(reply)
    except ScenarioError as e:
        raise HumanizeError(str(e)) from e

    new_blocks = data.get("blocks")
    if (not isinstance(new_blocks, list)
            or [b.get("role") for b in new_blocks] != [b["role"] for b in sc["blocks"]]):
        raise HumanizeError(
            f"скилл вернул блоки с другими ролями/количеством: {new_blocks!r}")

    return {**sc, "blocks": [dict(orig, speech=str(nb.get("speech") or orig["speech"]))
                            for orig, nb in zip(sc["blocks"], new_blocks)]}


def humanize_scenario(runner, workdir, sc: dict, mode: str, language: str) -> dict:
    if mode not in MODES:
        raise HumanizeError(f"неизвестный режим {mode!r}, ожидается {MODES}")
    payload = {
        "mode": mode,
        "language": language,
        "blocks": [{"role": b["role"], "speech": b["speech"]} for b in sc["blocks"]],
    }
    return _call_humanizer(runner, workdir, sc, payload)


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
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    payload = workdir / "judge_task.json"
    payload.write_text(json.dumps(
        {"language": language, "task": task,
         "blocks": [{"role": b["role"], "speech": b["speech"]} for b in sc["blocks"]]},
        ensure_ascii=False, indent=1), encoding="utf-8")
    reply = runner.run_skill("judging-script", payload)
    try:
        v = _extract_json(reply)
    except ScenarioError as e:
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
