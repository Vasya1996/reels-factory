"""Граундинг вставок: на экране только то, что звучит.

Для речи правило есть с самого начала (скил сценария, scenario.py:214).
Для картинки его не было — через эту дыру в ролик попадает предмет, которого
в сценарии нет. Проверяем пункты списка: заголовок может быть обобщением,
а пункты обязаны опираться на сказанное.
"""
from __future__ import annotations

import copy
import re

_WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9]{4,}")
_MIN_ROOT = 4

# Правило применяется к вставкам, содержание которых ПРИДУМАЛА МОДЕЛЬ.
# Детерминированные блоки (task_list, stat_number, before_after) собираются
# из речи окна кодом (editplan.py:806-817, :998-1002, :531-537, :552) —
# выдумать там нечего. Единственный путь, где в кадр может попасть предмет,
# которого нет в сценарии, — LLM Visual Director. Метку source в эффект
# кладёт _visual_director_effect (editplan.py:926-946), а значение "llm"
# приходит из apply_visual_recommendations(source="llm") (editplan.py:3253).
# Правиловые шаблоны несут ту же метку со значением "rules" — их пропускаем.
#
# Шаблонные подписи из словаря локализации («КОМУ», «ЧТО», «КАК» —
# editplan.py:1208, :1250) ничего не утверждают о фактах и пропускаются.
TEMPLATE_LABELS = {"кому", "что", "как", "кто", "было", "стало"}


def _root(word: str) -> str:
    word = word.lower()
    return word[: max(_MIN_ROOT, len(word) - 2)]


def _speech_roots(text: str) -> set[str]:
    return {_root(w) for w in _WORD_RE.findall(str(text or ""))}


# свободный текст шаблонов, который модель тоже придумывает
_FREE_TEXT_KEYS = ("offer", "actual", "resolution", "subtitle", "caption")


def _item_texts(effect: dict) -> list[str]:
    """Строки вставки из всех мест, где движок их держит."""
    variables = (effect.get("hyperframes") or {}).get("variables") or {}
    texts = [str(x) for x in (variables.get("items") or []) if isinstance(x, str)]
    texts += [str(variables[k]) for k in _FREE_TEXT_KEYS
              if isinstance(variables.get(k), str)]
    if texts:
        return texts
    out = []
    for item in effect.get("items") or []:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict):
            out.append(str(item.get("label") or ""))
    return [t for t in out if t]


def _is_grounded(item: str, roots: set[str]) -> bool:
    words = _WORD_RE.findall(str(item or ""))
    if not words:
        return True
    return any(
        any(root.startswith(_root(w)) or _root(w).startswith(root) for root in roots)
        for w in words
    )


def enforce_visual_grounding(plan: dict) -> dict:
    """Снять вставки, чьи пункты не опираются на речь накрытых фраз."""
    result = copy.deepcopy(plan)
    phrases = result.get("phrases") or []
    text_by_id = {p["id"]: p.get("text", "") for p in phrases}

    for window in result.get("windows") or []:
        effect = window.get("effect") or {}
        if (effect.get("visual_director") or {}).get("source") != "llm":
            continue   # содержание собрано кодом из речи — выдумать нечего
        items = [i for i in _item_texts(effect)
                 if i.strip().lower() not in TEMPLATE_LABELS]
        if not items:
            continue
        roots: set[str] = set()
        for phrase_id in window.get("phrase_ids") or []:
            roots |= _speech_roots(text_by_id.get(phrase_id, ""))
        stray = [item for item in items if not _is_grounded(item, roots)]
        if not stray:
            continue

        # Покрытие меняем и у окна, и у его фраз — иначе валидатор плана
        # поймает несовпадение и уронит finalize_edit_plan.
        # Сбрасываем то же, что штатный _downgrade_window (editplan.py:2102-2111),
        # только камеру ставим безусловно в hold — окно всё равно без вставки:
        # иначе у окна останутся caption="hidden" и переход от снятой вставки,
        # и у вернувшихся ведущей фраз пропадут субтитры.
        window["effect"] = {"type": "none"}
        window["coverage"] = "avatar"
        window["zone"] = "video-overlay"   # инвариант: аватарное окно — поверх видео
        window["camera"] = {"type": "hold"}
        window["transition_in"] = "none"
        window["caption"] = "bottom"
        window["asset"] = None
        window["material"] = None
        window["safe_to_skip_avatar"] = False
        window["decision_reason"] = (
            "Снято граундингом: в речи нет опоры для " + "; ".join(stray))
        own = set(window.get("phrase_ids") or [])
        for phrase in phrases:
            if phrase["id"] in own:
                phrase["coverage"] = "avatar"
                phrase["asset"] = None
                phrase["decision_reason"] = window["decision_reason"]
        result.setdefault("log", []).append(
            f"{window.get('id')}: вставка снята, нет опоры в речи — " + "; ".join(stray))
    checked = sum(
        1
        for window in result.get("windows") or []
        if (
            ((window.get("effect") or {}).get("visual_director") or {}).get("source")
            == "llm"
            or "Снято граундингом" in str(window.get("decision_reason") or "")
        )
    )
    stripped = sum(
        1 for line in result.get("log") or [] if "вставка снята" in line
    )
    result.setdefault("log", []).append(
        f"граундинг: снято {stripped}, проверено {checked}"
    )
    return result
