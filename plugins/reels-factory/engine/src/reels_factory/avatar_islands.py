"""Derived Photo Avatar IV render plan for a finalized canonical edit plan.

``edit_plan.json`` remains the creative source of truth.  This module only
projects its exact phrase timings into:

* continuous avatar islands (the face is actually visible);
* a small number of performance shots inside an island;
* exact master-audio slices, including short generation handles;
* a durable execution manifest and deterministic cache identities.

HeyGen accepts one ``motion_prompt`` and one ``expressiveness`` value per
Photo Avatar IV request.  Phrase-level recommendations are therefore kept as
intent, while compatible adjacent phrases are grouped into one request.  A
material performance change, hook/CTA boundary, full B-roll or the maximum
shot duration creates a boundary.  This avoids both a flat 90-second take and
the identity/motion seams caused by one request per phrase.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from reels_factory.avatar import avatar_cache_key, cached_generate
from reels_factory.billing import billable_seconds
from reels_factory.config import FFMPEG
# `_zone_for` берём у editplan, а не повторяем: зона окна — их канон
# (editplan.py:1290), и разойдись он с нашей копией, окно после правки
# рассказывало бы про себя неправду.
from reels_factory.editplan import (
    MAX_FACE_ABSENCE_S, MIN_FULLSCREEN_S, _refresh_blocks_and_summary,
    _zone_for, load_edit_plan, validate_edit_plan,
)

FORMAT_VERSION = 1
RENDER_PLAN_FILENAME = "avatar_render_plan.json"
RENDER_MANIFEST_FILENAME = "avatar_render_manifest.json"
_TRUE = {"1", "true", "yes", "on"}
_VISIBLE_COVERAGE = {"avatar", "mixed"}
_EXPRESSIVENESS_RANK = {"low": 0, "medium": 1, "high": 2}

DEFAULTS = {
    "enabled": False,
    "handle_seconds": 0.20,
    "min_request_seconds": 3.0,
    "target_shot_seconds": 10.0,
    "max_shot_seconds": 18.0,
    "max_shots_per_30_seconds": 5,
    "max_parallel": 2,
    # Informational only.  Never used for billing or provider authorization.
    "estimated_cost_per_second_usd": 0.05,
}


@dataclass(frozen=True)
class AvatarIslandArtifacts:
    clips: tuple[Path, ...]
    plan: dict
    manifest: dict


def avatar_islands_settings(config: dict | None) -> dict:
    raw = ((config or {}).get("avatar_islands") or {})
    result = {**DEFAULTS, **raw}
    env = os.environ.get("RF_AVATAR_ISLANDS_ENABLED")
    if env is not None:
        result["enabled"] = env.strip().lower() in _TRUE
    result["enabled"] = bool(result["enabled"])
    for key in (
        "handle_seconds",
        "min_request_seconds",
        "target_shot_seconds",
        "max_shot_seconds",
        "estimated_cost_per_second_usd",
    ):
        result[key] = float(result[key])
    for key in ("max_shots_per_30_seconds", "max_parallel"):
        result[key] = int(result[key])
    if not 0 <= result["handle_seconds"] <= 1:
        raise ValueError("avatar_islands.handle_seconds должен быть 0..1")
    if result["min_request_seconds"] <= 0:
        raise ValueError("avatar_islands.min_request_seconds должен быть > 0")
    if not (
        result["min_request_seconds"]
        <= result["target_shot_seconds"]
        <= result["max_shot_seconds"]
    ):
        raise ValueError(
            "avatar_islands требует min_request <= target_shot <= max_shot"
        )
    if result["max_shots_per_30_seconds"] < 1 or result["max_parallel"] < 1:
        raise ValueError("avatar_islands shot/parallel limits должны быть >= 1")
    if result["estimated_cost_per_second_usd"] < 0:
        raise ValueError("estimated_cost_per_second_usd должен быть >= 0")
    return result


def avatar_islands_enabled(config: dict | None) -> bool:
    return avatar_islands_settings(config)["enabled"]


def avatar_budget_targets(duration: float, settings: dict) -> dict:
    """Цель заказа ведущей, ориентир и граница отказа.

    Чисел три, и они разные. `ceiling_seconds` — ориентир: доля хронометража
    `AVATAR_ON_SCREEN_MAX`. `hard_ceiling_seconds` — граница:
    `AVATAR_ON_SCREEN_HARD_MAX`, и только выше неё гейт бюджета заворачивает
    план на пересдачу; между ориентиром и границей план годен.
    `target_seconds` — ориентир минус ручки, которые код докупает с каждого
    края каждого куска (`_request_timing`): агент меряет свои сцены сложением
    длительностей фраз, ручек в этом счёте нет, и, целясь в сам ориентир, он
    промахивался ровно на них.

    Четвёртое число — `hard_target_seconds`: та же граница, переведённая в
    мерку агента (граница минус те же ручки). Нужно оно сверке в задании: гейт
    судит СЕКУНДЫ ЗАКАЗА, а агент складывает длительности фраз, и пункт сверки,
    названный секундами заказа, пропускал бы планы, которые гейт заворачивает —
    ровно на ручки.

    Обещания «план под этим числом бюджет не завернёт» здесь больше нет, и это
    не оговорка. Перебор, которым его мерили (117 740 расстановок), считал
    заказ нашей оценкой; прогон `06eb0a8f` (01.09.2026) показал разницу в 6,8 с
    между оценкой и построенным заказом — секунды, которые докупает возврат
    ведущей короткому куску (`_restore_short_faceless`). Число остаётся
    ориентиром сверки, а не гарантией: судит гейт построенный заказ.

    Кусков считаем столько, сколько их навязывает правило «лицо не пропадает
    дольше `MAX_FACE_ABSENCE_S` подряд»: между сценами без ведущей обязана
    стоять сцена с ведущей, значит остров режется на столько кусков, сколько
    таких промежутков помещается в ролик, плюс один.

    Функция живёт здесь, потому что это единственный модуль, который читают оба
    — и задание агенту (`hf_brief.py`), и гейт до заказа (`hf_render.py`). Два
    вычисления одной цели разошлись бы, и агент увидел бы в задании одно число,
    а в причине пересдачи другое.
    """
    duration = float(duration or 0.0)
    pieces = (math.ceil(duration / MAX_FACE_ABSENCE_S) + 1
              if duration > 0 else 1)
    from reels_factory.hf_montage import (AVATAR_ON_SCREEN_HARD_MAX,
                                          AVATAR_ON_SCREEN_MAX)

    ceiling = AVATAR_ON_SCREEN_MAX * duration
    hard_ceiling = AVATAR_ON_SCREEN_HARD_MAX * duration
    handles = 2 * float(settings["handle_seconds"]) * pieces
    return {
        "ceiling_seconds": ceiling,
        "hard_ceiling_seconds": hard_ceiling,
        "target_seconds": max(0.0, ceiling - handles),
        "hard_target_seconds": max(0.0, hard_ceiling - handles),
        "max_ratio": AVATAR_ON_SCREEN_MAX,
        "hard_max_ratio": AVATAR_ON_SCREEN_HARD_MAX,
        "pieces": pieces,
        "handles_seconds": handles,
    }


def validate_photo_avatar_iv_config(config: dict) -> None:
    """Fail before paid work when Stage 3 is not on the Photo Avatar IV path."""
    avatar = (config or {}).get("avatar") or {}
    if str(avatar.get("heygen_look_id") or "").strip():
        raise ValueError(
            "avatar islands сейчас поддерживает только Photo Avatar IV; "
            "heygen_look_id/Avatar V запрещён"
        )
    if not str(avatar.get("heygen_asset_id") or "").strip():
        raise ValueError(
            "avatar islands требует avatar.heygen_asset_id фото-аватара"
        )
    engine = str(avatar.get("engine") or "avatar_iv").strip().lower()
    if engine != "avatar_iv":
        raise ValueError(
            "avatar islands сейчас поддерживает только engine=avatar_iv"
        )


def _canonical_hash(value) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _timing(start: float, end: float) -> dict:
    return {
        "start": round(float(start), 6),
        "end": round(float(end), 6),
        "duration": round(float(end) - float(start), 6),
    }


def _motion_family(prompt: str) -> str:
    value = str(prompt or "").lower()
    families = (
        ("lean", ("lean",)),
        # "still" стоит раньше "gesture": строка покоя из GESTURE_VOCABULARY
        # ("No hand gestures, ...") иначе попадает к активным жестам по слову
        # "gesture" и роднится с ними при кластеризации островов.
        ("still", ("no hand gesture", "hands still", "barely move")),
        ("invite", ("open-hand", "open hand", "open arms", "inviting")),
        ("nod", ("nod",)),
        ("smile", ("smile",)),
        ("gesture", ("gesture", "hand")),
        ("expression", ("expression", "eyebrow")),
    )
    for name, needles in families:
        if any(needle in value for needle in needles):
            return name
    return "neutral"


def _profile_distance(left: dict, right: dict) -> float:
    exp = abs(
        _EXPRESSIVENESS_RANK[left["expressiveness"]]
        - _EXPRESSIVENESS_RANK[right["expressiveness"]]
    )
    motion = 0 if _motion_family(left["motion_prompt"]) == _motion_family(
        right["motion_prompt"]
    ) else 1
    return exp * 2.4 + motion * 1.0


def _representative_phrase(phrases: list[dict]) -> dict:
    """Choose the phrase whose provider controls minimize group divergence."""
    role_bias = {"hook": -4.0, "cta": -3.5, "payoff": -0.4}
    best = None
    for candidate in phrases:
        profile = candidate["avatar_performance"]
        distance = sum(
            _profile_distance(profile, item["avatar_performance"])
            for item in phrases
        )
        distance += role_bias.get(candidate.get("role"), 0.0)
        key = (distance, int(candidate["index"]))
        if best is None or key < best[0]:
            best = (key, candidate)
    return best[1]


def _group_cost(phrases: list[dict], target_seconds: float) -> float:
    start = float(phrases[0]["final_timing"]["start"])
    end = float(phrases[-1]["final_timing"]["end"])
    duration = end - start
    representative = _representative_phrase(phrases)
    profile = representative["avatar_performance"]
    mismatch = sum(
        _profile_distance(profile, phrase["avatar_performance"])
        for phrase in phrases
    )
    # A request/seam is expensive visually and financially.  The duration
    # penalty prevents one flat take from swallowing a long island.
    return 4.0 + mismatch + max(0.0, duration - target_seconds) ** 2 * 0.08


def _group_allowed(phrases: list[dict], max_seconds: float) -> bool:
    start = float(phrases[0]["final_timing"]["start"])
    end = float(phrases[-1]["final_timing"]["end"])
    if end - start > max_seconds + 1e-6:
        return False
    roles = {phrase.get("role") for phrase in phrases}
    if ("hook" in roles or "cta" in roles) and len(roles) > 1:
        return False
    ranks = {
        _EXPRESSIVENESS_RANK[phrase["avatar_performance"]["expressiveness"]]
        for phrase in phrases
    }
    # low -> high is a meaningful directorial change and gets its own shot.
    return not ({0, 2} <= ranks)


def _partition_island(phrases: list[dict], settings: dict) -> list[list[dict]]:
    count = len(phrases)
    best: list[tuple[float, list[list[dict]]] | None] = [None] * (count + 1)
    best[0] = (0.0, [])
    for end in range(1, count + 1):
        for start in range(end - 1, -1, -1):
            group = phrases[start:end]
            if not _group_allowed(group, settings["max_shot_seconds"]):
                if start < end - 1:
                    break
                continue
            previous = best[start]
            if previous is None:
                continue
            candidate = (
                previous[0]
                + _group_cost(group, settings["target_shot_seconds"]),
                [*previous[1], group],
            )
            if best[end] is None or candidate[0] < best[end][0]:
                best[end] = candidate
    if best[count] is None:
        raise ValueError("не удалось разбить avatar island на performance shots")
    return best[count][1]


def _request_timing(
    visible_start: float,
    visible_end: float,
    total: float,
    settings: dict,
) -> dict:
    handle = settings["handle_seconds"]
    start = max(0.0, visible_start - handle)
    end = min(total, visible_end + handle)
    missing = settings["min_request_seconds"] - (end - start)
    if missing > 0:
        grow_left = min(start, missing / 2)
        start -= grow_left
        missing -= grow_left
        grow_right = min(total - end, missing)
        end += grow_right
        missing -= grow_right
        if missing > 0:
            grow_left = min(start, missing)
            start -= grow_left
    return _timing(start, end)


def _scene_at(scenes: list[dict], moment: float) -> dict | None:
    """Сцена агента, внутрь которой попадает момент ролика."""
    for scene in scenes:
        if (float(scene.get("startSec", 0)) - 0.001 <= moment
                < float(scene.get("endSec", 0))):
            return scene
    return None


def _span_timing(phrases: list[dict], key: str) -> dict:
    start = float((phrases[0].get(key) or {}).get("start", 0.0))
    end = float((phrases[-1].get(key) or {}).get("end", 0.0))
    return {"start": start, "end": end, "duration": round(end - start, 6)}


def _retarget_window(
    plan: dict, window: dict, coverage: str, previous: str
) -> None:
    """Перевести окно на новое покрытие по канону `editplan._downgrade_window`
    (editplan.py:2271).

    Одного `coverage` мало: в окне остаётся материал от снятого решения —
    ассет вставки, эффект графики, разрешение не заказывать HeyGen. Поэтому
    вместе с покрытием переписываются те же поля и в том же порядке, что у
    них, включая зону кадра: иначе окно рассказывает про себя две разные
    вещи, и валидатор ловит это уже после оплаты аватара.
    """
    reason = (
        "агент отдал кадр вставке"
        if coverage not in _VISIBLE_COVERAGE
        else "агент вернул в кадр ведущую"
    )
    window["coverage"] = coverage
    window["zone"] = _zone_for(coverage)
    window["asset"] = None
    window["material"] = None
    window["effect"] = {"type": "none"}
    window["camera"] = {
        "type": "hold" if window.get("role") == "payoff" else "ken_burns"
    }
    window["transition_in"] = "none"
    window["caption"] = "bottom"
    window["safe_to_skip_avatar"] = False
    window["decision_reason"] = f"Решение агента: {reason}"
    own = set(window.get("phrase_ids") or [])
    for phrase in plan.get("phrases") or []:
        if phrase.get("id") in own:
            phrase["asset"] = None
            phrase["decision_reason"] = window["decision_reason"]
    plan.setdefault("revisions", []).append({
        "window_id": window["id"],
        "from": previous,
        "to": coverage,
        "reason": reason,
    })


def _absorb_window(window: dict, extra: dict, phrase_by_id: dict) -> None:
    """Забрать фразы соседнего окна себе. Поля остаются у принимающего.

    Принимающее и отдающее окно к этому моменту уже приведены к одному
    покрытию одной и той же функцией (`_retarget_window`), поэтому спорить их
    полям не о чем: ассет снят у обоих, эффекта нет ни у одного, зона одна.
    Роль остаётся у принимающего — это роль его первой фразы, то есть первой
    фразы склеенного окна.
    """
    window["phrase_ids"] = [*window["phrase_ids"], *extra["phrase_ids"]]
    own = [phrase_by_id[item] for item in window["phrase_ids"]]
    for key in ("estimated_timing", "final_timing"):
        if key in window:
            window[key] = _span_timing(own, key)
    for phrase in own:
        phrase["window_id"] = window["id"]


def _merge_agent_windows(windows: list[dict], scene_of: dict,
                         phrase_by_id: dict) -> list[dict]:
    """Склеить соседние окна внутри одного решения агента.

    Окна `editplan` заводятся пофразно и не склеиваются никогда, а
    `validate_edit_plan` требует, чтобы окно без ведущей шло не короче
    `MIN_FULLSCREEN_S` (editplan.py:2668). На быстрой речи фраза идёт около
    2,4 с — и сцена, которую агент отдал вставке, разваливалась на окна короче
    порога: сплошной перебор планов не находил НИ ОДНОГО, который прошёл бы и
    гейты, и валидатор. Единственным принимаемым планом оставалась ведущая на
    весь ролик, то есть самый дорогой из всех.

    Склейка идёт только внутри одной сцены и только там, где ведущей лишил САМ
    АГЕНТ (`avatarNeeded: false`): сцена — это и есть единица его решения, и
    ровно её меряет гейт `D31_faceless_scenes` (hf_render.py). Границ сцен
    склейка не переходит: тогда окно оказалось бы длиннее того куска, который
    судили до заказа, и правило говорило бы одно, а валидатор проверял другое.
    Окна общего пути (`editplan`, ветка «аватар уже заказан») сюда не попадают
    вовсе — этой функции нет на их дороге.
    """
    merged: list[dict] = []

    def scene_key(window: dict):
        keys = {scene_of.get(item) for item in window["phrase_ids"]}
        return keys.pop() if len(keys) == 1 else None

    for window in windows:
        key = scene_key(window)
        previous = merged[-1] if merged else None
        if (previous is not None and key is not None
                and scene_key(previous) == key
                and previous["coverage"] == window["coverage"]):
            _absorb_window(previous, window, phrase_by_id)
            continue
        merged.append(window)
    return merged


def _restore_short_faceless(plan: dict, previous: dict,
                            phrase_by_id: dict) -> list[str]:
    """Вернуть ведущую окну, которое после склейки всё равно короче порога.

    Внутри одной сцены агента куски больше не расходятся: отказ накрывает и
    фразу с графикой (`apply_agent_coverage`), покрытие у всей сцены одно, и
    `_regroup_windows` режет и снова склеивает её в одно окно по границам
    самих сцен агента — не домонтажной раскадровки (прогон `artyom-early-2`,
    02.09.2026). Эта функция остаётся страховкой на два случая, которых тот
    разрез не лечит: сама сцена агента короче `MIN_FULLSCREEN_S` (её и
    склеивать не с чем — решение агента и есть источник короткого куска), и
    настоящий разрез на границе сцены, где покрытие по разные стороны и
    правда разное — кусок в сцене без ведущей уходит во вставку, кусок в
    соседней остаётся при своём, и один из них бывает короче порога. Любой из
    двух случаев `validate_edit_plan` заворачивает уже в
    `build_avatar_render_plan`, то есть с оплаченной озвучкой. Спросить агента
    там уже некого, поэтому короткий кусок возвращается тому покрытию, которое
    у него было до решения, а если решения на нём не было вовсе — ведущей:
    ведущая в кадре стоит денег, падение сборки — всей озвучки.

    Возвращает имена возвращённых окон: их число уезжает в `agent_coverage`,
    иначе тихая правка чужого решения осталась бы незаметной.
    """
    restored: list[str] = []
    for window in plan.get("windows") or []:
        if window.get("coverage") in _VISIBLE_COVERAGE:
            continue
        timing = window.get("final_timing") or {}
        duration = float(timing.get("end", 0)) - float(timing.get("start", 0))
        if duration >= MIN_FULLSCREEN_S - 1e-6:
            continue
        own_ids = [item for item in window.get("phrase_ids") or []
                   if item in previous]
        # Кусок, чьё покрытие совпало с исходным, до `previous` не доходит:
        # его фразу агент не трогал, а короче порога кусок стал от разреза
        # окна. Запасное покрытие тогда берётся из канона окна: ведущая в
        # кадре стоит денег, падение сборки — всей озвучки.
        back = previous[own_ids[0]] if own_ids else "avatar"
        if back not in _VISIBLE_COVERAGE:
            # Канон окна — тоже невидимое покрытие (`hyperframes`): сама
            # сцена агента была короче порога ещё до его решения (прогон
            # `artyom-early-2`, 02.09.2026, синтетика на такой сцене —
            # `test_домонтажное_окно_на_две_сцены_не_рвёт_сцену_агента`).
            # Отдать кусок обратно невидимому покрытию значит вернуть тот же
            # короткий кусок под другим именем — валидатор заворачивает его
            # снова. Гарантированно видимый исход только один.
            back = "avatar"
        for item in window.get("phrase_ids") or []:
            phrase_by_id[item]["coverage"] = back
        _retarget_window(plan, window, back, window["coverage"])
        restored.append(window["id"])
    return restored


def _regroup_windows(plan: dict, scene_of: dict | None = None) -> None:
    """Разложить окна по границам решения агента.

    Решение агента живёт на фразе, а `validate_edit_plan` судит окно: покрытие
    окна обязано совпасть с покрытием каждой его фразы (editplan.py:2650).
    Сцены агента приходят от `hf_phrases.lay_out_scenes` и режут окна
    посередине, поэтому окно делится, а не подгоняется: границы кадра ставит
    режиссёр, а не старая раскадровка. Разделив, соседние куски одного решения
    склеиваем обратно (`_merge_agent_windows`) — иначе порог трёх секунд достаётся
    каждой фразе.

    `scene_of` — какая сцена, лишившая кадр ведущей, накрыла фразу. Он же ставит
    разрез внутри домонтажного окна: покрытие двух соседних `avatarNeeded: false`
    сцен совпадает всегда (обе становятся `full_broll`), а домонтажное окно этого
    не знает и держит фразы обеих сцен куском, если совпало покрытие — разрез
    по одному покрытию его не находит. Прогон `artyom-early-2` (02.09.2026):
    окно `window-010` держало фразы сцен `s-06` и `s-07` без разреза между ними
    (обе — `full_broll`), соседнее окно `window-009` (одна фраза `s-06`, 2,88 с)
    остаться с ним не могло — `_merge_agent_windows` меряет сцену окна целиком, а
    окну на двух сценах сразу сцена не приписывается, — и `_restore_short_faceless`
    покупало ведущую туда, где агент отказался (заказ 30,68 с при границе
    29,77 с). Поэтому разрез ставится ещё и там, где меняется САМА сцена у двух
    подряд идущих фраз, уже отказавших ведущей — даже когда их итоговое
    покрытие совпало: границу решения ставит сцена агента, а не цвет окна.
    Фразу без решения (`scene_of` не знает её) разрез не трогает нигде — иначе
    домонтажная раскадровка резалась бы там, где агент молчал.
    """
    scene_of = scene_of or {}
    phrase_by_id = {
        phrase["id"]: phrase for phrase in plan.get("phrases") or []
    }
    rebuilt: list[dict] = []
    for window in plan.get("windows") or []:
        # Снимок ДО правки: куски режутся от исходного окна, иначе второй
        # кусок унаследовал бы уже переписанный первый.
        original = copy.deepcopy(window)
        runs: list[tuple[str, list[str]]] = []
        for phrase_id in original.get("phrase_ids") or []:
            phrase = phrase_by_id.get(phrase_id)
            if phrase is None:
                continue
            coverage = phrase.get("coverage")
            same_run = False
            if runs and runs[-1][0] == coverage:
                last_id = runs[-1][1][-1]
                last_scene = scene_of.get(last_id)
                this_scene = scene_of.get(phrase_id)
                # Разрез между двумя решёнными сценами — даже с одинаковым
                # покрытием; фразу без решения (None с любой стороны) разрез
                # не трогает.
                same_run = (
                    last_scene is None
                    or this_scene is None
                    or last_scene == this_scene
                )
            if same_run:
                runs[-1][1].append(phrase_id)
            else:
                runs.append((coverage, [phrase_id]))
        for offset, (coverage, phrase_ids) in enumerate(runs):
            part = window if offset == 0 else copy.deepcopy(original)
            if offset:
                part["id"] = f"{original['id']}-a{offset}"
            part["phrase_ids"] = list(phrase_ids)
            own = [phrase_by_id[item] for item in phrase_ids]
            # Роль куска — роль его первой фразы: её читает валидатор плана
            # монтажа для built-in visual и bubble — этим эффектам hook и cta
            # закрыты (editplan.py:2699, :2720), и Visual Director их не видит
            # кандидатами (editplan.py:3002, :3096).
            part["role"] = own[0].get("role")
            for key in ("estimated_timing", "final_timing"):
                if key in part:
                    part[key] = _span_timing(own, key)
            for phrase in own:
                phrase["window_id"] = part["id"]
            if coverage != original.get("coverage"):
                _retarget_window(plan, part, coverage, original.get("coverage"))
            rebuilt.append(part)
    rebuilt = _merge_agent_windows(rebuilt, scene_of or {}, phrase_by_id)
    for index, window in enumerate(rebuilt):
        window["index"] = index
    plan["windows"] = rebuilt


def apply_agent_coverage(edit_plan: dict, scenes: list[dict]) -> dict:
    """Вход островов — решение агента, а не эвристика (работа 9).

    Агент-планировщик ставит каждой сцене `avatarNeeded`; фраза наследует
    решение сцены, в которую попадает её середина, окно делится по границам
    этого решения, а куски одного решения склеиваются обратно в одно окно
    (`_merge_agent_windows`): порог трёх секунд валидатор меряет на окне, и без
    склейки на быстрой речи не проходил ни один план. Дальше нарезка на острова
    идёт прежним кодом
    (`_islands_from_phrases`) — меняется только вход, как и было задумано.
    Внутри заказанного острова платятся все секунды, поэтому
    `avatarNeeded: false` — это прямая экономия HeyGen.

    Возвращает копию плана; сцены без поля не меняют фразу — эвристика
    остаётся запасным мнением там, где агент решения не назвал. Сколько сцен
    он решил, а сколько промолчал, лежит в `agent_coverage`: по этому числу
    видно, была ли пересдача осмысленной.
    """
    plan = copy.deepcopy(edit_plan)
    ordered = sorted(scenes or [],
                     key=lambda scene: float(scene.get("startSec", 0)))
    changed: list[str] = []
    # Какая сцена без ведущей накрыла фразу и чем эта фраза была до решения
    # агента: первое нужно склейке окон, второе — возврату слишком короткого
    # куска обратно ведущей.
    scene_of: dict[str, int] = {}
    previous: dict[str, str] = {}
    for phrase in plan.get("phrases") or []:
        timing = phrase.get("final_timing") or {}
        middle = (float(timing.get("start", 0))
                  + float(timing.get("end", 0))) / 2
        scene = _scene_at(ordered, middle)
        if scene is None:
            continue
        needed = scene.get("avatarNeeded")
        current = phrase.get("coverage")
        if needed is False:
            scene_of[phrase["id"]] = id(scene)
        if needed is True and current not in _VISIBLE_COVERAGE:
            phrase["coverage"] = "avatar"
        elif needed is False and current != "full_broll":
            # Отказ печатается закрытым значением из `EDIT_PLAN_COVERAGE`
            # (editplan.py:223): имени "broll" валидатор не знает, и заказ по
            # такому плану не состоялся бы вовсе.
            #
            # Накрывает и `hyperframes`, то есть фразу, где кадр держит
            # графика плана монтажа. Прежде такую фразу отказ не трогал —
            # берегли показ, — но показывать нечего: на пути островов графика
            # `edit_plan` до кадра не доходит вовсе. `build_composition`
            # (hf_compose.py:1076) плана монтажа не получает, кадр рисуется по
            # плану агента, а единственный потребитель `edit_plan` в сборке
            # (`_media_from_plan`, hf_render.py:547) читает из окна только
            # `asset`. Зато оставленная фраза разрезала сцену агента на два
            # покрытия, `_merge_agent_windows` пару разных покрытий не
            # склеивает, кусок выходил короче `MIN_FULLSCREEN_S` — и
            # `_restore_short_faceless` возвращал туда ведущую. Прогон
            # `06eb0a8f` (01.09.2026): так вернулись два окна, заказ вырос с
            # 30,8 до 37,4 с. Ветка `needed is True` такую фразу ведущей
            # забирает симметрично, и обе стороны решения агента теперь
            # сильнее эвристики.
            phrase["coverage"] = "full_broll"
        else:
            continue
        previous[phrase["id"]] = current
        changed.append(phrase["id"])
    restored: list[str] = []
    if changed and plan.get("windows"):
        _regroup_windows(plan, scene_of)
        phrase_by_id = {item["id"]: item for item in plan.get("phrases") or []}
        restored = _restore_short_faceless(plan, previous, phrase_by_id)
        # Блоки идут за окнами — тем же кодом, каким их ведёт `editplan` после
        # каждого понижения окна (:2227). Блок с `avatar_required: false`
        # валидатор пускает только тогда, когда КАЖДОЕ его окно полноэкранное и
        # несёт `safe_to_skip_avatar` (editplan.py:2793-2806), а отказ агента
        # это разрешение снимает (`_retarget_window`). Оставь мы блоки как
        # были — план с окном графики, которому HeyGen был не нужен, падал бы
        # в `build_avatar_render_plan`, то есть после оплаченной озвучки. Заодно
        # `covered_block_indexes` (:2839) перестаёт врать про блок, которому
        # ведущая теперь нужна.
        _refresh_blocks_and_summary(plan)
    decisions = [scene.get("avatarNeeded") for scene in ordered]
    plan["agent_coverage"] = {
        "scenes": len(ordered),
        "avatar_scenes": sum(1 for item in decisions if item is True),
        "faceless_scenes": sum(1 for item in decisions if item is False),
        "undecided_scenes": sum(
            1 for item in decisions if item is not True and item is not False
        ),
        "changed_phrases": len(changed),
        "changed_phrase_ids": changed,
        # Окна, которым код вернул ведущую после решения агента: кусок вставки
        # вышел короче `MIN_FULLSCREEN_S`, а спросить агента заново уже некого.
        "restored_windows": restored,
    }
    return plan


def _covered_seconds(spans: list[tuple[float, float]]) -> float:
    """Секунды ролика, за которые заказана ведущая, без двойного счёта.

    Соседние запросы внутри острова перекрываются: с каждого края добавляется
    `handle_seconds`, а короткий кусок дорастает до `min_request_seconds` за
    счёт соседнего звука (`_request_timing`). Деньгам это разные запросы, и
    HeyGen берёт за оба, а доле хронометража — одни и те же секунды, и считать
    их дважды значит объявить бюджет превышенным на швах, которых в ролике
    нет.
    """
    total = 0.0
    start = end = None
    for span_start, span_end in sorted(spans):
        if end is None or span_start > end:
            if end is not None:
                total += end - start
            start, end = span_start, span_end
        else:
            end = max(end, span_end)
    if end is not None:
        total += end - start
    return total


def _islands_from_phrases(phrases: list[dict]) -> list[list[dict]]:
    islands: list[list[dict]] = []
    current: list[dict] = []
    for phrase in phrases:
        visible = phrase.get("coverage") in _VISIBLE_COVERAGE
        if not visible:
            if current:
                islands.append(current)
                current = []
            continue
        if current:
            previous_end = float(current[-1]["final_timing"]["end"])
            start = float(phrase["final_timing"]["start"])
            if start - previous_end > 0.002:
                islands.append(current)
                current = []
        current.append(phrase)
    if current:
        islands.append(current)
    return islands


def build_avatar_render_plan(
    edit_plan: dict,
    config: dict,
    *,
    master_audio_sha256: str | None = None,
) -> dict:
    """Build the derived, deterministic execution plan after exact alignment."""
    validate_photo_avatar_iv_config(config)
    settings = avatar_islands_settings(config)
    edit_report = validate_edit_plan(
        edit_plan, require_final=True, require_asset_files=False
    )
    if not edit_report["all_pass"]:
        raise ValueError(
            "avatar islands требует valid final edit plan: "
            + "; ".join(edit_report["errors"][:5])
        )
    total = float(edit_plan["timeline"]["final_duration_seconds"])
    if total <= 0:
        raise ValueError("final edit plan имеет неположительную длительность")

    phrases = sorted(
        copy.deepcopy(edit_plan["phrases"]),
        key=lambda item: float(item["final_timing"]["start"]),
    )
    raw_islands = _islands_from_phrases(phrases)
    shots: list[dict] = []
    islands: list[dict] = []
    for island_index, island_phrases in enumerate(raw_islands):
        island_id = f"avatar-island-{island_index:03d}"
        groups = _partition_island(island_phrases, settings)
        shot_ids = []
        for group in groups:
            shot_index = len(shots)
            shot_id = f"avatar-shot-{shot_index:03d}"
            shot_ids.append(shot_id)
            start = float(group[0]["final_timing"]["start"])
            end = float(group[-1]["final_timing"]["end"])
            visible = _timing(start, end)
            request = _request_timing(start, end, total, settings)
            representative = _representative_phrase(group)
            performance = copy.deepcopy(representative["avatar_performance"])
            performance.update({
                "source_phrase_id": representative["id"],
                "grouping": (
                    "exact"
                    if len(group) == 1
                    else "compatible_phrase_intents"
                ),
            })
            intents = [
                {
                    "phrase_id": phrase["id"],
                    "expressiveness":
                        phrase["avatar_performance"]["expressiveness"],
                    "motion_prompt":
                        phrase["avatar_performance"]["motion_prompt"],
                    "applied_exactly": phrase["id"] == representative["id"],
                }
                for phrase in group
            ]
            identity = {
                "edit_plan_sha256": _canonical_hash(edit_plan),
                "master_audio_sha256": master_audio_sha256,
                "avatar_asset_id":
                    str((config.get("avatar") or {}).get("heygen_asset_id")),
                "resolution":
                    str((config.get("avatar") or {}).get("resolution") or "1080p"),
                "phrase_ids": [phrase["id"] for phrase in group],
                "request_timing": request,
                "visible_timing": visible,
                "performance": {
                    "expressiveness": performance["expressiveness"],
                    "motion_prompt": performance["motion_prompt"],
                },
            }
            shots.append({
                "id": shot_id,
                "index": shot_index,
                "island_id": island_id,
                "phrase_ids": [phrase["id"] for phrase in group],
                "roles": list(dict.fromkeys(phrase.get("role") for phrase in group)),
                "text": " ".join(str(phrase.get("text") or "") for phrase in group),
                "visible_timing": visible,
                "request_timing": request,
                "trim": {
                    "start_seconds": round(start - request["start"], 6),
                    "duration_seconds": visible["duration"],
                },
                "avatar_performance": performance,
                "phrase_performance_intents": intents,
                "idempotency_key": _canonical_hash(identity),
            })
        islands.append({
            "id": island_id,
            "index": island_index,
            "phrase_ids": [phrase["id"] for phrase in island_phrases],
            "shot_ids": shot_ids,
            "visible_timing": _timing(
                island_phrases[0]["final_timing"]["start"],
                island_phrases[-1]["final_timing"]["end"],
            ),
        })

    shot_by_phrase = {
        phrase_id: shot["id"]
        for shot in shots
        for phrase_id in shot["phrase_ids"]
    }
    island_by_shot = {shot["id"]: shot["island_id"] for shot in shots}
    visual_timeline = []
    for window in edit_plan.get("windows") or []:
        timing = window["final_timing"]
        own_shots = list(dict.fromkeys(
            shot_by_phrase[item]
            for item in window["phrase_ids"]
            if item in shot_by_phrase
        ))
        visual_timeline.append({
            "id": window["id"],
            "start": timing["start"],
            "end": timing["end"],
            "duration": round(
                float(timing["end"]) - float(timing["start"]), 6
            ),
            "coverage": window["coverage"],
            "avatar_island_ids":
                list(dict.fromkeys(island_by_shot[item] for item in own_shots)),
            "avatar_shot_ids": own_shots,
        })

    visible_seconds = sum(
        island["visible_timing"]["duration"] for island in islands
    )
    # Два разных числа про одно и то же. `requested` — сколько секунд ролика
    # отдано ведущей: перекрытия запросов схлопнуты, поэтому число сравнимо с
    # хронометражом и годится для бюджета. `billed` — сколько секунд выставит
    # HeyGen: каждый запрос оплачивается целиком, включая ручки, поэтому в
    # деньги идёт именно оно.
    requested_seconds = _covered_seconds([
        (
            float(shot["request_timing"]["start"]),
            float(shot["request_timing"]["end"]),
        )
        for shot in shots
    ])
    billed_seconds = sum(
        shot["request_timing"]["duration"] for shot in shots
    )
    # Потолок аватарного времени меряется здесь — на заказе. Показом его
    # мерить бессмысленно: клипы покупаются раньше плана, и спрятанная в
    # монтаже ведущая денег не возвращает (hf_montage.AVATAR_ON_SCREEN_MAX).
    from reels_factory.hf_montage import (AVATAR_ON_SCREEN_HARD_MAX,
                                          AVATAR_ON_SCREEN_MAX)

    budget_seconds = total * AVATAR_ON_SCREEN_MAX
    hard_budget_seconds = total * AVATAR_ON_SCREEN_HARD_MAX
    over_seconds = requested_seconds - hard_budget_seconds
    # Допуск в полпроцента хронометража: ручки на границах островов дают
    # промах в доли секунды, и ради него пересдавать план незачем.
    #
    # Перерасходом числится только выход за ГРАНИЦУ — ту же, по которой судит
    # гейт до заказа (`D29_avatar_budget`, hf_render.py). Полоса между
    # ориентиром и границей планом-нарушителем не считается: иначе принятый
    # гейтом план приезжал бы в отчёт сборки перерасходом, и два наших
    # собственных числа спорили бы об одном плане. Переход ориентира виден
    # отдельным полем — он повод посмотреть на монтаж, а не на счёт.
    over_target = requested_seconds - budget_seconds > 0.005 * total
    over_budget = over_seconds > 0.005 * total
    max_shots = max(
        1,
        math.ceil(
            total / 30.0 * settings["max_shots_per_30_seconds"] - 1e-9
        ),
    )
    plan = {
        "format_version": FORMAT_VERSION,
        "status": "planned",
        "generated_by": "reels_factory.avatar_islands",
        "edit_plan_sha256": _canonical_hash(edit_plan),
        "master_audio_sha256": master_audio_sha256,
        "engine_scope": "photo_avatar_iv",
        "avatar": {
            "heygen_asset_id":
                str((config.get("avatar") or {}).get("heygen_asset_id")),
            # Look сейчас всегда пустой: `validate_photo_avatar_iv_config`
            # запрещает Avatar V на островах. Пишем его всё равно — по этому
            # полю пересборка решает, тем ли аватаром заказаны клипы, и без
            # него смена look'а прошла бы незамеченной, когда запрет снимут.
            "heygen_look_id":
                str((config.get("avatar") or {}).get("heygen_look_id") or ""),
            "engine": "avatar_iv",
            "resolution":
                str((config.get("avatar") or {}).get("resolution") or "1080p"),
        },
        "timeline": {"duration_seconds": round(total, 6)},
        "constraints": {
            key: settings[key] for key in (
                "handle_seconds",
                "min_request_seconds",
                "target_shot_seconds",
                "max_shot_seconds",
                "max_shots_per_30_seconds",
                "max_parallel",
            )
        },
        "islands": islands,
        "shots": shots,
        "visual_timeline": visual_timeline,
        "summary": {
            "duration_seconds": round(total, 3),
            "avatar_visible_seconds": round(visible_seconds, 3),
            "avatar_requested_seconds": round(requested_seconds, 3),
            "avatar_billed_seconds": round(billed_seconds, 3),
            "avatar_visible_ratio": round(visible_seconds / total, 4),
            "saved_vs_full_avatar_seconds": round(
                max(0.0, total - requested_seconds), 3
            ),
            "estimated_cost_usd": round(
                billed_seconds
                * settings["estimated_cost_per_second_usd"],
                2,
            ),
            "avatar_budget": {
                "max_ratio": AVATAR_ON_SCREEN_MAX,
                "hard_max_ratio": AVATAR_ON_SCREEN_HARD_MAX,
                "budget_seconds": round(budget_seconds, 3),
                "hard_budget_seconds": round(hard_budget_seconds, 3),
                "requested_seconds": round(requested_seconds, 3),
                "requested_ratio": round(requested_seconds / total, 4),
                "over_target": bool(over_target),
                "over_budget": bool(over_budget),
                "over_seconds": round(over_seconds, 3) if over_budget else 0.0,
            },
            "island_count": len(islands),
            "shot_count": len(shots),
            "max_shot_count": max_shots,
        },
    }
    # Сам заказ не режем: какие куски отдать бироллу, решает разметка
    # `coverage` по смыслу реплик, и урезать её вслепую значит менять
    # режиссуру ролика ради круглого числа. Числа промаха лежат в
    # `summary.avatar_budget` — оттуда их берёт отчёт по сборке; stderr
    # остаётся для живого прогона в консоли.
    if over_target:
        print(
            f"аватара заказано {requested_seconds / total * 100:.0f}% "
            f"хронометража при ориентире {AVATAR_ON_SCREEN_MAX * 100:.0f}% и "
            f"границе {AVATAR_ON_SCREEN_HARD_MAX * 100:.0f}% "
            + (f"(+{over_seconds:.1f} с сверх границы) — "
               if over_budget else "(в допуске) — ")
            + f'{plan["summary"]["estimated_cost_usd"]:.2f} $ за генерацию; '
            "меньше платят там, где кадр отдают бироллу",
            file=sys.stderr,
        )
    report = validate_avatar_render_plan(plan, edit_plan)
    plan["validation"] = report
    if not report["all_pass"]:
        raise ValueError(
            "avatar render plan invalid: " + "; ".join(report["errors"][:5])
        )
    return plan


def validate_avatar_render_plan(plan: dict, edit_plan: dict) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    if plan.get("format_version") != FORMAT_VERSION:
        errors.append("неподдерживаемая format_version avatar render plan")
    if plan.get("engine_scope") != "photo_avatar_iv":
        errors.append("engine_scope должен быть photo_avatar_iv")
    if plan.get("edit_plan_sha256") != _canonical_hash(edit_plan):
        errors.append("edit_plan_sha256 не совпадает с final edit plan")
    total = float((plan.get("timeline") or {}).get("duration_seconds") or 0)
    settings = plan.get("constraints") or {}
    visible_ids = {
        phrase["id"]
        for phrase in edit_plan.get("phrases") or []
        if phrase.get("coverage") in _VISIBLE_COVERAGE
    }
    assigned = [
        phrase_id
        for shot in plan.get("shots") or []
        for phrase_id in shot.get("phrase_ids") or []
    ]
    if sorted(assigned) != sorted(visible_ids) or len(assigned) != len(set(assigned)):
        errors.append("shots должны назначить каждую видимую phrase ровно один раз")

    shot_by_id = {shot.get("id"): shot for shot in plan.get("shots") or []}
    if len(shot_by_id) != len(plan.get("shots") or []):
        errors.append("shot IDs пусты или не уникальны")
    previous_global_end = 0.0
    for shot in plan.get("shots") or []:
        visible = shot.get("visible_timing") or {}
        request = shot.get("request_timing") or {}
        start, end = float(visible.get("start", -1)), float(visible.get("end", -1))
        req_start = float(request.get("start", -1))
        req_end = float(request.get("end", -1))
        if start + 0.002 < previous_global_end or end <= start:
            errors.append(f"{shot.get('id')}: visible timing пересекается/пустой")
        previous_global_end = max(previous_global_end, end)
        if req_start < -1e-6 or req_end > total + 1e-6:
            errors.append(f"{shot.get('id')}: request timing вне master timeline")
        if req_start > start + 1e-6 or req_end + 1e-6 < end:
            errors.append(f"{shot.get('id')}: request не покрывает visible timing")
        if req_end - req_start + 1e-6 < float(settings["min_request_seconds"]):
            # A whole reel shorter than provider minimum is the only exception.
            if total + 1e-6 >= float(settings["min_request_seconds"]):
                errors.append(f"{shot.get('id')}: request короче min_request")
        if end - start > float(settings["max_shot_seconds"]) + 1e-6:
            errors.append(f"{shot.get('id')}: visible shot длиннее max_shot")
        performance = shot.get("avatar_performance") or {}
        if performance.get("expressiveness") not in _EXPRESSIVENESS_RANK:
            errors.append(f"{shot.get('id')}: expressiveness не low|medium|high")
        if not str(performance.get("motion_prompt") or "").strip():
            errors.append(f"{shot.get('id')}: пустой motion_prompt")
        intents = shot.get("phrase_performance_intents") or []
        if [item.get("phrase_id") for item in intents] != shot.get("phrase_ids"):
            errors.append(
                f"{shot.get('id')}: performance intents не совпадают с phrases"
            )
        if not str(shot.get("idempotency_key") or ""):
            errors.append(f"{shot.get('id')}: пустой idempotency_key")

    island_ids = []
    for island in plan.get("islands") or []:
        island_ids.append(island.get("id"))
        own = [shot_by_id.get(item) for item in island.get("shot_ids") or []]
        if not own or any(item is None for item in own):
            errors.append(f"{island.get('id')}: неизвестные/пустые shots")
            continue
        timing = island.get("visible_timing") or {}
        if abs(float(timing["start"]) - float(own[0]["visible_timing"]["start"])) > 0.002:
            errors.append(f"{island.get('id')}: начало не совпадает с shots")
        if abs(float(timing["end"]) - float(own[-1]["visible_timing"]["end"])) > 0.002:
            errors.append(f"{island.get('id')}: конец не совпадает с shots")
        for left, right in zip(own, own[1:]):
            if abs(
                float(left["visible_timing"]["end"])
                - float(right["visible_timing"]["start"])
            ) > 0.002:
                errors.append(f"{island.get('id')}: gap/overlap между shots")
    if len(island_ids) != len(set(island_ids)):
        errors.append("island IDs пусты или не уникальны")

    visual = plan.get("visual_timeline") or []
    visual_by_id = {segment.get("id"): segment for segment in visual}
    if len(visual_by_id) != len(visual):
        errors.append("visual timeline IDs пусты или не уникальны")
    for window in edit_plan.get("windows") or []:
        segment = visual_by_id.get(window.get("id"))
        if segment is None:
            errors.append(f"{window.get('id')}: нет visual timeline segment")
            continue
        timing = window.get("final_timing") or {}
        if (
            segment.get("coverage") != window.get("coverage")
            or abs(float(segment.get("start", -1)) - float(timing["start"])) > 0.002
            or abs(float(segment.get("end", -1)) - float(timing["end"])) > 0.002
        ):
            errors.append(f"{window.get('id')}: visual timeline расходится с edit plan")
        if (
            window.get("coverage") not in _VISIBLE_COVERAGE
            and segment.get("avatar_shot_ids")
        ):
            errors.append(f"{window.get('id')}: avatar shot внутри hidden window")

    summary = plan.get("summary") or {}
    if int(summary.get("shot_count") or 0) > int(summary.get("max_shot_count") or 0):
        warnings.append(
            "число HeyGen shots выше целевого quality budget: "
            f"{summary.get('shot_count')}>{summary.get('max_shot_count')}"
        )
    if not plan.get("islands"):
        warnings.append("в edit plan нет видимых avatar windows")
    return {"all_pass": not errors, "errors": errors, "warnings": warnings}


def _save_json_atomic(path: Path, value) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)
    return path


def save_avatar_render_plan(plan: dict, workdir: Path | str) -> Path:
    return _save_json_atomic(Path(workdir) / RENDER_PLAN_FILENAME, plan)


def _order_rejected(reason: str) -> None:
    print(f"[make] заказ ведущей пересобирается: {reason}", file=sys.stderr)


def load_frozen_avatar_order(
    workdir: Path | str,
    config: dict,
    *,
    master_audio_sha256: str | None = None,
) -> dict | None:
    """Готовый заказ ведущей из папки задания — или None, если он не годен.

    Ведущая — самые дорогие секунды ролика, и пересборка той же папки не
    вправе покупать их второй раз. Кэш от второго заказа не спасает: его ключ
    считается от байтов нарезки, `motion_prompt` и настроек клиента
    (`avatar.avatar_cache_key`), а границы шотов и жесты на каждом прогоне
    заново выбирают два LLM-прохода — любое расхождение даёт новый ключ и
    платный заказ. Поэтому переиспользуется не кэш, а сам заказ: план, манифест
    и снятые клипы.

    Заказ считается годным, когда ВСЁ перечисленное верно:

    * в папке лежат `avatar_render_plan.json`, `avatar_render_manifest.json` и
      `edit_plan.json` нынешнего формата;
    * `master_audio_sha256` (если он известен вызывающему) совпадает и в
      плане, и в манифесте: клипы сняты под конкретные байты мастер-звука;
    * аватар, его look и разрешение в плане — те же, что в конфиге задания;
    * `edit_plan.json` тот самый, по которому считался план (сверка sha256):
      иначе монтаж рассказывал бы про ведущую не то, что заказано;
    * каждый шот плана есть в манифесте со `status: ready`, тем же
      `idempotency_key`, и файл клипа лежит на диске.

    Не сошлось хоть что-то — возвращаем None, и прогон честно пересчитывает
    план и заказывает заново. Причина уходит в stderr: молчаливый перезаказ
    выглядит как та же сборка, только со списанием.
    """
    workdir = Path(workdir)
    plan_path = workdir / RENDER_PLAN_FILENAME
    manifest_path = workdir / RENDER_MANIFEST_FILENAME
    if not plan_path.is_file() or not manifest_path.is_file():
        # Первая сборка этой папки: замораживать нечего, и говорить не о чем.
        return None
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        edit_plan = load_edit_plan(workdir)
    except (OSError, ValueError) as error:
        _order_rejected(f"файлы заказа не читаются ({error})")
        return None
    if (
        plan.get("format_version") != FORMAT_VERSION
        or manifest.get("format_version") != FORMAT_VERSION
    ):
        _order_rejected("формат заказа не нынешний")
        return None
    if master_audio_sha256 is not None:
        for name, saved in (
            ("плане", plan.get("master_audio_sha256")),
            ("манифесте", manifest.get("master_audio_sha256")),
        ):
            if str(saved or "") != str(master_audio_sha256):
                _order_rejected(
                    f"мастер-звук в {name} не тот, под который сняты клипы"
                )
                return None
    avatar_cfg = config.get("avatar") or {}
    saved_avatar = plan.get("avatar") or {}
    for field, want, title in (
        ("heygen_asset_id", avatar_cfg.get("heygen_asset_id"), "аватар"),
        ("heygen_look_id", avatar_cfg.get("heygen_look_id") or "",
         "look аватара"),
        ("resolution", avatar_cfg.get("resolution") or "1080p",
         "разрешение"),
    ):
        if str(saved_avatar.get(field) or "") != str(want or ""):
            _order_rejected(f"сменилось: {title}")
            return None
    if plan.get("edit_plan_sha256") != _canonical_hash(edit_plan):
        _order_rejected("edit_plan.json разошёлся с планом заказа")
        return None
    if manifest.get("edit_plan_sha256") != plan.get("edit_plan_sha256"):
        _order_rejected("манифест снят по другому плану монтажа")
        return None
    shots = plan.get("shots") or []
    if not shots:
        _order_rejected("в плане заказа нет шотов")
        return None
    saved_shots = {
        str(item.get("shot_id")): item for item in manifest.get("shots") or []
    }
    clips: list[Path] = []
    for shot in shots:
        item = saved_shots.get(str(shot.get("id")))
        if item is None:
            _order_rejected(f"в манифесте нет шота {shot.get('id')}")
            return None
        if item.get("status") != "ready":
            _order_rejected(
                f"шот {shot.get('id')} не доснят ({item.get('status')})"
            )
            return None
        if item.get("idempotency_key") != shot.get("idempotency_key"):
            _order_rejected(f"шот {shot.get('id')} снят по другому заданию")
            return None
        clip = Path(str(item.get("clip_path") or ""))
        if not clip.is_file():
            _order_rejected(f"клипа {item.get('clip_path')} нет на диске")
            return None
        clips.append(clip)
    summary = plan.get("summary") or {}
    billed = float(summary.get("avatar_billed_seconds") or 0.0)
    cost = float(summary.get("estimated_cost_usd") or 0.0)
    print(
        f"[make] заказ ведущей переиспользован: {len(shots)} шотов, "
        f"{billed:.1f} с — {cost:.2f} $ у HeyGen второй раз не просим",
        file=sys.stderr,
    )
    return {
        "plan": plan,
        "manifest": manifest,
        "edit_plan": edit_plan,
        "clips": tuple(clips),
    }


def _slice_audio(
    master_wav: Path,
    shot: dict,
    output: Path,
    *,
    run_cmd: Callable | None = None,
) -> Path:
    if run_cmd is None:
        from reels_factory.render import run
        run_cmd = run
    timing = shot["request_timing"]
    run_cmd([
        str(FFMPEG), "-y",
        "-ss", f"{float(timing['start']):.6f}",
        "-t", f"{float(timing['duration']):.6f}",
        "-i", str(master_wav),
        "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(output),
    ])
    return output


def render_avatar_islands(
    master_wav: Path,
    plan: dict,
    client,
    workdir: Path | str,
    cache_dir: Path | str,
    *,
    edit_plan: dict,
    run_cmd: Callable | None = None,
    generate_fn: Callable | None = None,
    meter: Callable | None = None,
) -> AvatarIslandArtifacts:
    """Slice master audio and render/cache Photo Avatar IV shots in parallel."""
    report = validate_avatar_render_plan(plan, edit_plan)
    if not report["all_pass"]:
        raise ValueError(
            "avatar render plan invalid: " + "; ".join(report["errors"][:5])
        )
    if getattr(client, "look_id", None):
        raise ValueError("Stage 3 запрещает Avatar V/Digital Twin client")
    if str(getattr(client, "engine", "avatar_iv")).lower() != "avatar_iv":
        raise ValueError("Stage 3 требует Photo Avatar IV client")

    master_wav = Path(master_wav)
    if not master_wav.is_file():
        raise ValueError(f"master audio не найден: {master_wav}")
    master_audio_sha256 = hashlib.sha256(master_wav.read_bytes()).hexdigest()
    planned_master_sha256 = str(plan.get("master_audio_sha256") or "")
    if (
        planned_master_sha256
        and planned_master_sha256 != master_audio_sha256
    ):
        raise ValueError(
            "avatar_render_plan построен для другого voice_master.wav"
        )
    workdir = Path(workdir)
    cache_dir = Path(cache_dir)
    audio_dir = workdir / "avatar_islands_audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    plan_path = save_avatar_render_plan(plan, workdir)
    _ = plan_path

    audio_paths: dict[str, Path] = {}
    # Whether each shot's cache key already has a file on disk, checked here
    # before any render call. After cached_generate/generate_fn runs the file
    # exists either way, so a hit can no longer be told apart from a miss.
    cache_hits: dict[str, bool] = {}
    manifest = {
        "format_version": FORMAT_VERSION,
        "engine_scope": "photo_avatar_iv",
        "edit_plan_sha256": plan["edit_plan_sha256"],
        "master_audio_sha256": master_audio_sha256,
        "shots": [],
    }
    for shot in plan.get("shots") or []:
        audio = audio_dir / f"{shot['id']}.wav"
        _slice_audio(master_wav, shot, audio, run_cmd=run_cmd)
        audio_paths[shot["id"]] = audio
        performance = shot["avatar_performance"]
        cache_key = avatar_cache_key(
            client,
            audio,
            motion_prompt=performance["motion_prompt"],
            expressiveness=performance["expressiveness"],
        )
        cache_hits[shot["id"]] = (cache_dir / f"{cache_key}.mp4").exists()
        manifest["shots"].append({
            "shot_id": shot["id"],
            "idempotency_key": shot["idempotency_key"],
            "cache_key": cache_key,
            "audio_path": str(audio),
            "audio_sha256": hashlib.sha256(audio.read_bytes()).hexdigest(),
            "status": "planned",
            "provider_job_id": None,
            "clip_path": None,
            "clip_sha256": None,
            "error": None,
        })
    manifest_path = workdir / RENDER_MANIFEST_FILENAME
    _save_json_atomic(manifest_path, manifest)

    manifest_by_id = {item["shot_id"]: item for item in manifest["shots"]}
    generate = generate_fn

    def render_one(shot: dict) -> tuple[str, Path]:
        performance = shot["avatar_performance"]
        audio = audio_paths[shot["id"]]
        if generate is not None:
            clip = generate(
                client,
                audio,
                cache_dir,
                motion_prompt=performance["motion_prompt"],
                expressiveness=performance["expressiveness"],
                role=(shot.get("roles") or [None])[0],
            )
        else:
            clip = cached_generate(
                client,
                audio,
                cache_dir,
                role=(shot.get("roles") or [None])[0],
                motion_prompt=performance["motion_prompt"],
                expressiveness=performance["expressiveness"],
            )
        return shot["id"], Path(clip)

    clips_by_id: dict[str, Path] = {}
    failures = []
    max_workers = int((plan.get("constraints") or {}).get("max_parallel") or 1)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_shot = {
            executor.submit(render_one, shot): shot
            for shot in plan.get("shots") or []
        }
        for future in as_completed(future_to_shot):
            shot = future_to_shot[future]
            item = manifest_by_id[shot["id"]]
            try:
                shot_id, clip = future.result()
                if not clip.is_file():
                    raise RuntimeError(f"HeyGen/cache не создал clip: {clip}")
                clips_by_id[shot_id] = clip
                item.update({
                    "status": "ready",
                    "clip_path": str(clip),
                    "clip_sha256": hashlib.sha256(clip.read_bytes()).hexdigest(),
                })
            except Exception as exc:
                item.update({"status": "failed", "error": str(exc)[:500]})
                failures.append((shot["id"], exc))
                _save_json_atomic(manifest_path, manifest)
                continue
            if meter is not None:
                # Owner: bill the full duration of the delivered clip, not
                # just the visible slice — HeyGen renders and bills the
                # whole handle-padded request, so the ledger has to match.
                # Measure the actual output mp4, never the planned
                # request_timing — but only on a real render: a cache hit
                # never gets charged (see JobMeter.heygen), so probing its
                # duration would only burn an ffprobe call for nothing. twin
                # is always False here: Stage 3 only allows Photo Avatar IV,
                # there is no Digital Twin rate to apply.
                cached = cache_hits[shot_id]
                seconds = 0.0 if cached else billable_seconds(clip)
                try:
                    meter(seconds, cached=cached, twin=False)
                except Exception as exc:
                    # Метр — бухгалтерия ПОСЛЕ уже оплаченного и доставленного
                    # HeyGen-рендера (contention с ботом за sqlite-ledger,
                    # запертый/битый файл). Сбой здесь не должен превращать
                    # готовый shot в failed и ронять всю сборку — деньги уже
                    # потрачены, просто эта секунда не будет учтена.
                    print(
                        f"[billing] avatar_islands: meter упал для "
                        f"{shot_id}, клип отрендерен, но не тарифицирован: "
                        f"{exc}",
                        file=sys.stderr,
                    )
            _save_json_atomic(manifest_path, manifest)
    if failures:
        raise RuntimeError(
            "avatar island render failed: "
            + "; ".join(f"{shot_id}: {exc}" for shot_id, exc in failures[:3])
        )
    clips = tuple(clips_by_id[shot["id"]] for shot in plan.get("shots") or [])
    return AvatarIslandArtifacts(clips=clips, plan=plan, manifest=manifest)
