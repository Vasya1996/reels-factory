"""Хуманизация сценария: вызов скилла humanizing-speech через SkillRunner.

Режимы (выбираются путём, не пользователем): polish — переписать под живую
устную речь (факты неприкосновенны); phonetics — только фонетическая запись
терминов/брендов и числа прописью, больше ничего (путь «дословно»).
"""
import json
from pathlib import Path

from reels_factory.scenario import _extract_json, ScenarioError

MODES = ("polish", "phonetics")


class HumanizeError(Exception):
    pass


def humanize_scenario(runner, workdir, sc: dict, mode: str, language: str) -> dict:
    if mode not in MODES:
        raise HumanizeError(f"неизвестный режим {mode!r}, ожидается {MODES}")
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    task = {
        "mode": mode,
        "language": language,
        "blocks": [{"role": b["role"], "speech": b["speech"]} for b in sc["blocks"]],
    }
    payload = workdir / "humanize_task.json"
    payload.write_text(json.dumps(task, ensure_ascii=False, indent=1), encoding="utf-8")

    reply = runner.run_skill("humanizing-speech", payload)
    try:
        data = _extract_json(reply)
    except ScenarioError as e:
        raise HumanizeError(str(e)) from e

    new_blocks = data.get("blocks")
    if (not isinstance(new_blocks, list)
            or [b.get("role") for b in new_blocks] != [b["role"] for b in sc["blocks"]]):
        raise HumanizeError(
            f"скилл вернул блоки с другими ролями/количеством: {new_blocks!r}")

    out = {**sc, "blocks": [dict(orig, speech=str(nb.get("speech") or orig["speech"]))
                            for orig, nb in zip(sc["blocks"], new_blocks)]}
    return out
