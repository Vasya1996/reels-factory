"""Монтажная арифметика: серии бироллов, планы камеры, вспышки.

Правила пришли из разбора Юли (ветка `codex/hyperframes-workflow-poc`,
`broll-zoom-toolkit/camera_plan.py` и `docs/HANDOFF-BROLL-ZOOM-V6.md`), её
эталон `reels_avatar5_broll_v12.mp4` собран ровно ими. Сама её сборка была на
ручном ffmpeg (`zoompan`/`xfade`/ASS) и сюда не переносится: у нас одна
композиция и один рендер их движком. Переносятся правила, а считает их код —
агент решает, ЧТО показать, код решает, СКОЛЬКО и КОГДА.

Что здесь:

1. `pick_series` — какие из названных агентом вставок доживут до кадра.
   Биролл ставится только серией из двух планов, между сериями лицо держится
   не меньше `FACE_GAP`, аватар виден в кадре не дольше
   `AVATAR_ON_SCREEN_MAX`.
2. `cut_into_plans` — нарезка речи на планы камеры по сильнейшей паузе,
   ровно её алгоритм (точка > запятая > пауза, фраза не рвётся).
3. `zoom_ladder` — ступени масштаба на этих планах.
4. `flash_moments` — где вспышка, и почему их не больше двух.

Секунды здесь настоящие, а не индексы фраз: модуль работает уже после
раскладки (`hf_phrases.lay_out_scenes`).
"""
from __future__ import annotations

from itertools import combinations

from reels_factory.hf_layout import avatar_gaps, in_avatar_gap

# ----------------------------------------------------------------- серии

#: План серии — один биролл. Ниже 1,2 с план читается вспышкой, выше 3 с
#: перестаёт быть планом серии и становится обычной длинной вставкой. У Юли
#: 1,5–2,5 с; вилка шире, потому что наши границы сидят на фразах озвучки, а
#: не назначаются свободно.
SHOT_MIN = 1.2
SHOT_MAX = 3.0

#: Серия — два плана подряд. Отсюда и границы сцены, которая её несёт.
SERIES_SHOTS = 2
SERIES_MIN = SHOT_MIN * SERIES_SHOTS
SERIES_MAX = SHOT_MAX * SERIES_SHOTS

#: Между сериями зритель обязан снова увидеть лицо, и не мельком. Планка её:
#: «между сериями лицо держится ≥2.5с» (HANDOFF-BROLL-ZOOM-V6.md, критерии
#: приёмки), и снята она с эталонных рилсов длиной 41,5 с — то есть 6 %
#: хронометража. Секундой её держать нельзя: на 30-секундном ролике те же
#: 2,5 с съедают вдвое большую долю и выбрасывают половину бироллов, а на
#: минутном, наоборот, разрешают их впритык. Поэтому доля, а не число.
#:
#: Пол и потолок — чтобы правило не выродилось: ниже 1,5 с лицо мелькает и
#: перестаёт быть передышкой, выше 3,5 с ролик превращается в говорящую голову
#: с редкими вставками.
FACE_GAP_SHARE = 2.5 / 41.5
FACE_GAP_MIN = 1.5
FACE_GAP_MAX = 3.5


def face_gap(duration: float) -> float:
    """Сколько лица держится между сериями на ролике такой длины."""
    if duration <= 0:
        return FACE_GAP_MIN
    return min(FACE_GAP_MAX, max(FACE_GAP_MIN, FACE_GAP_SHARE * float(duration)))

#: Потолок аватарного времени. Требование заказчика 10.08.2026: секунда
#: аватара — главные деньги ролика, поэтому её держат сверху.
#:
#: Меряется он на ЗАКАЗЕ, а не на показе. Куски аватара покупаются до того, как
#: агент напишет план (pipeline.py:365), поэтому спрятать ведущую из кадра
#: денег уже не экономит: клип куплен и просто не попадёт в ролик. Прогон
#: 462a1c62 так потерял 9,2 с из 27,5 заказанных — треть заказа в никуда.
#: Показом это число больше не управляет; сравнивает с ним заказ
#: `avatar_islands`, а `hf_gates` следит за обратным — чтобы оплаченное
#: попало в кадр.
#:
#: Прежняя вилка 65–70 % (её стандарт: «аватар 65–70%, b-roll 30–35%») мерила
#: другое — сколько ролика НЕ занято бироллом во весь кадр. В `pip-*` аватар
#: остаётся в уголке, и число показывало 66 % там, где зритель видел аватар
#: почти весь ролик.
AVATAR_ON_SCREEN_MAX = 0.60

#: Положения, при которых кадр держит вставка, а не ведущая: её нет вовсе либо
#: она ушла в уголок. `stack`/`split` сюда не входят — там лицо занимает
#: половину кадра и считается аватарным временем.
_BROLL_POSITIONS = ("none", "pip")


def insert_of(scene: dict) -> dict | None:
    """Вставка сцены — объект со списком планов `shots`.

    Одиночных вставок не бывает: биролл входит в кадр серией. Сцена, которая
    назвала один план, — это ошибка плана, и она называется вслух.
    """
    found = scene.get("insert")
    if not isinstance(found, dict):
        return None
    shots = found.get("shots")
    if not isinstance(shots, list) or not shots:
        return None
    return found


def shot_queries(scene: dict) -> list[str]:
    """Запросы планов серии, как их написал агент."""
    found = insert_of(scene)
    if not found:
        return []
    out = []
    for shot in found["shots"]:
        text = shot.get("query") if isinstance(shot, dict) else shot
        out.append(str(text or "").strip())
    return out


def check_shots(scenes: list[dict]) -> None:
    """Сцена со вставкой обязана назвать ровно два плана."""
    for scene in scenes:
        found = scene.get("insert")
        if not isinstance(found, dict):
            continue
        queries = shot_queries(scene)
        if len(queries) != SERIES_SHOTS or not all(queries):
            raise RuntimeError(
                f'{scene.get("id", "?")}: биролл ставится серией из '
                f"{SERIES_SHOTS} планов — поле `insert.shots` должно быть "
                f"списком из {SERIES_SHOTS} непустых запросов, а пришло "
                f"{len(queries)}. Один план — это одиночная вставка, её в "
                "монтаже не бывает")


def ordered_gaps(clips: list[dict] | None,
                 duration: float) -> list[tuple[float, float]]:
    """Куски, на которых ведущей нет физически.

    Отличие от `avatar_gaps` одно, зато важное: клипов не передали вовсе —
    значит про заказ ничего не известно, и считать оплаченным нельзя ничего.
    Иначе сцена, которую агент честно назвал `none`, поднималась бы в кадр по
    пустому списку клипов.
    """
    if not clips:
        return [(0.0, float("inf"))]
    return avatar_gaps(clips, duration)


def scene_look(scene: dict) -> str:
    """Чем сцена занимает кадр — словами, по которым её видно.

    Жила в гейтах, переехала сюда: тем же сравнением код разводит соседей, а
    гейт после него только проверяет. Два места считать одинаковость по-разному
    не должны — иначе код чинит одно, а проверка судит другое.
    """
    shots = " ".join(shot_queries(scene))
    if shots:
        return shots
    icon = str((scene.get("icon") or {}).get("query") or "").strip()
    if icon:
        return f"значок {icon}"
    plan = scene.get("schema")
    if not (isinstance(plan, dict) and plan.get("form")):
        plan = scene.get("fallback") if scene.get("needsSchema") else None
    if isinstance(plan, dict) and plan.get("form"):
        # Форма и её содержимое: две схемы одной формы, но с разными словами —
        # это две разные картинки, а не один план. `rows` в этот список
        # попали не сразу, и без них две сцены подряд с разными парами
        # («кажется → товар» и «звонок → голосом») читались одной картинкой:
        # содержимое `pairs` живёт только в `rows`, и гейт его не видел.
        words = plan.get("items") or plan.get("nodes") or plan.get("brands") \
            or [f'{row.get("label")} {row.get("value")}'
                for row in (plan.get("rows") or []) if isinstance(row, dict)] \
            or [plan.get("value"), plan.get("label")]
        return f'схема {plan["form"]} ' + " ".join(
            str(word) for word in words if word)
    block = str((scene.get("overlay") or {}).get("block") or "").strip()
    return f"накладка {block}" if block else ""


def same_look(left: dict, right: dict) -> bool:
    """Два соседних куска зритель прочтёт как один план."""
    return (str(left.get("presenter") or "full")
            == str(right.get("presenter") or "full")
            and scene_look(left) == scene_look(right))


def _schema_scene(scene: dict) -> bool:
    """Кадр держит схема — своя или запасная."""
    plan = scene.get("schema")
    if isinstance(plan, dict) and plan.get("form"):
        return True
    return bool(scene.get("needsSchema") or scene.get("schemaShown"))


def positions_for(scene: dict) -> tuple[str, ...]:
    """Положения ведущей, при которых кадр этой сцены остаётся закрытым.

    Порядок — по убыванию желательности. Со вставкой кадр держит она, а
    ведущая живёт уголком поверх или половиной над ней (`stack`). Со схемой
    остаются нижние уголки: схема стоит в верхней трети, и там они не спорят.
    Без того и другого кадр закрывает сама ведущая.
    """
    if insert_of(scene):
        return ("pip-tr", "pip-tl", "stack", "pip-br", "pip-bl")
    if _schema_scene(scene):
        return ("pip-br", "pip-bl")
    return ("full", "punch")


def _taken_near(scenes: list[dict], index: int, look: str) -> set[str]:
    """Положения соседей, у которых в кадре то же самое, что и здесь."""
    taken = set()
    for near in (index - 1, index + 1):
        if not 0 <= near < len(scenes) or near == index:
            continue
        if scene_look(scenes[near]) == look:
            taken.add(str(scenes[near].get("presenter") or "full"))
    return taken


def pick_position(scenes: list[dict], index: int) -> str:
    """Как показать ведущую в этой сцене, не повторив соседа.

    Ни одного свободного положения не осталось — берём первое подходящее:
    закрытый кадр важнее различимости, а пару близнецов потом разведёт
    `dedupe_neighbours`, склеив их в один кусок.
    """
    scene = scenes[index]
    allowed = positions_for(scene)
    taken = _taken_near(scenes, index, scene_look(scene))
    free = [name for name in allowed if name not in taken]
    return (free or list(allowed))[0]


def show_ordered_avatar(scenes: list[dict], clips: list[dict] | None,
                        duration: float) -> list[str]:
    """Ведущая, за которую заплачено, обязана быть в кадре.

    Куски аватара покупаются ДО плана агента (pipeline.py:365), и `presenter:
    "none"` на купленной секунде не экономит ничего — клип уже оплачен и
    просто не доедет до зрителя. В прогоне 462a1c62 так пропали 9,2 с из 27,5:
    две сцены агент отдал целиком под схему и биролл, а заказ на них уже стоял.

    Прятать ведущую можно только там, где её нет физически, — на дырах между
    островами. Всюду остальном она возвращается в кадр тем положением, которое
    не спорит ни со вставкой, ни со схемой, ни с соседями.

    Возвращает id сцен, которым положение подняли.
    """
    gaps = ordered_gaps(clips, duration)
    lifted = []
    for index, scene in enumerate(scenes):
        if str(scene.get("presenter") or "full") != "none":
            continue
        if in_avatar_gap(float(scene.get("startSec", 0)),
                         float(scene.get("endSec", 0)), gaps):
            continue
        scene["presenter"] = pick_position(scenes, index)
        lifted.append(f'{scene["id"]} → {scene["presenter"]}')
    if lifted:
        print("ведущая возвращена в кадр, её секунды уже оплачены: "
              + ", ".join(lifted))
    return [item.split(" ")[0] for item in lifted]


def merge_adjacent_series(scenes: list[dict], *,
                          clips: list[dict] | None = None,
                          duration: float = 0.0) -> list[str]:
    """Соседние сцены с бироллом — это одна серия, а не две.

    Агент называет моменты по смыслу и ставит их подряд там, где подряд идёт
    мысль. Отбор такие пары разводил силой: между сериями положено держать
    лицо, значит вторая сцена пары теряла биролл и уходила под ведущую —
    прогон 29 потерял так три вставки из пяти.

    Правильнее не разгонять, а склеить: два запроса соседей становятся двумя
    планами ОДНОЙ серии, и это ровно та же грамматика — «биролл не ходит в
    одиночку, он входит парой планов». Ролик от этого не теряет ни вставки,
    ни лица: пара занимает столько же места, сколько занимала одна сцена.

    Склеиваем только пару, влезающую в серию по длине (`SERIES_MAX`): более
    длинная пара — это два стоячих плана, а не монтаж. Возвращает id сцен,
    которые исчезли, слившись с предыдущей.
    """
    gaps = ordered_gaps(clips, duration)
    merged: list[str] = []
    index = 0
    while index < len(scenes) - 1:
        left, right = scenes[index], scenes[index + 1]
        if not (insert_of(left) and insert_of(right)):
            index += 1
            continue
        size = float(right["endSec"]) - float(left["startSec"])
        if size > SERIES_MAX + 0.001:
            index += 1
            continue
        left["endSec"] = right["endSec"]
        left["phrases"] = [left.get("phrases", [0, 0])[0],
                           right.get("phrases", [0, 0])[-1]]
        left["insert"] = {
            **(left.get("insert") or {}),
            "shots": [shot_queries(left)[0], shot_queries(right)[0]],
        }
        merged.append(right["id"])
        scenes.pop(index + 1)
        # Кадр держит биролл, но убрать ведущую совсем можно только там, где
        # её и не заказывали: на купленной секунде `none` — это выброшенные
        # деньги. Поэтому она уходит в уголок поверх серии, а на дыре
        # исчезает. Положение выбираем после `pop`: соседом стала уже
        # следующая сцена, а не та, что слилась. Плашка второй сцены уезжает
        # вместе с самой сценой.
        left["presenter"] = "none" if in_avatar_gap(
            float(left["startSec"]), float(left["endSec"]), gaps) \
            else pick_position(scenes, index)
    if merged:
        print("соседние бироллы склеены в одну серию: " + ", ".join(merged))
    return merged


def drop_series(scenes: list[dict], kept: list[str], *,
                clips: list[dict] | None = None,
                duration: float = 0.0) -> list[str]:
    """Снять серии, не прошедшие отбор, и оставить кадр закрытым.

    Просто убрать вставку нельзя: сцена с ведущей в уголке или в половине
    кадра без вставки — это чёрный прямоугольник на остальном кадре (их же
    находка, наш гейт D20), а сцена без ведущей вообще — голый фон с титром
    (D25). Кадр закрывает `refill_scene`.

    Возвращает id сцен, у которых серия снята.
    """
    from reels_factory.hf_layout import avatar_gaps

    gaps = ordered_gaps(clips, duration)
    dropped = []
    for index, scene in enumerate(scenes):
        if not insert_of(scene) or scene["id"] in kept:
            continue
        scene["insert"] = None
        dropped.append(scene["id"])
        refill_scene(scenes, index, gaps)
    return dropped


def refill_scene(scenes: list[dict], index: int, gaps) -> None:
    """Чем закрыть кадр сцены, оставшейся без вставки.

    Три исхода, по убыванию желательности:

    1. Ведущей на этом куске нет физически — кадр остаётся за схемой.
    2. Запасная схема из `fallback` закрывает кадр, а ведущая остаётся в
       нижнем уголке: схема стоит в верхней трети, они не спорят. Так у ролика
       сохраняется третье окно ведущей, которого требует приёмка (D14).
    3. Ведущая закрывает кадр сама — `full` или `punch`, и не такая, как у
       соседа с той же картинкой: две сцены подряд одним планом детектор не
       разделит (D21).

    Прежняя версия уводила в `none` любую сцену, которую агент так и назвал, —
    и оплаченные секунды исчезали из ролика. Теперь `none` остаётся только за
    дырой между островами; всюду остальном ведущая возвращается в кадр.
    Полнокадровое положение больше не «оставить как было»: раньше сцена,
    уже стоявшая во `full`, уходила отсюда нетронутой и повторяла соседа —
    ровно так прогон 462a1c62 получил два одинаковых куска подряд.
    """
    from reels_factory.hf_layout import in_avatar_gap

    scene = scenes[index]
    position = str(scene.get("presenter") or "full")
    faceless = in_avatar_gap(float(scene.get("startSec", 0)),
                             float(scene.get("endSec", 0)), gaps)
    has_fallback = any(str((scene.get("fallback") or {}).get(kind) or "").strip()
                       for kind in ("logo", "icon"))

    if faceless:
        scene["presenter"] = "none"
        scene["needsSchema"] = True
        return
    if has_fallback and position not in ("full", "punch"):
        scene["needsSchema"] = True
    scene["presenter"] = pick_position(scenes, index)
    if scene["presenter"] not in ("full", "punch"):
        return
    # Плашку агент ставил под ту раскладку, которой больше нет: на
    # полнокадровой ведущей её текст ложится прямо на лицо — прогон 24
    # поймал это гейтом D8 и их же `content_overlap`. Снимаем вместе с
    # серией; текст сцены всё равно несёт титр.
    if scene.pop("overlay", None) is not None:
        print(f'{scene["id"]}: плашка снята вместе с серией — под ведущей '
              "во весь кадр её текст лёг бы на лицо")


def drop_schema(scenes: list[dict], scene: dict) -> None:
    """Схема в кадр не встала — закрывать его теперь ведущей.

    Пока схема стояла, ведущая могла жить нижним уголком: схема держит верхнюю
    треть, и они не спорят. Без неё уголок висит на пустом фоне — это их аудит
    переполнения и наш D20. Ведущая, которой на этом куске нет вовсе, остаётся
    как была: там сцена законно фоновая.
    """
    scene.pop("schema", None)
    scene.pop("needsSchema", None)
    if str(scene.get("presenter") or "full") == "none" or insert_of(scene):
        return
    scene["presenter"] = pick_position(scenes, scenes.index(scene))


def dedupe_neighbours(scenes: list[dict], *, clips: list[dict] | None = None,
                      duration: float = 0.0) -> list[str]:
    """Развести два соседних куска, которые зритель прочтёт как один план.

    Проверка D21 судит уже собранный план, а собирает его код: сняв вставку,
    он ставит на её место ведущую — и сцена становится копией соседа. Раньше
    за это отвечал агент, хотя ломал не он: какие серии снимет отбор, решается
    после него. Теперь чинит тот, кто ломает.

    Два средства, по порядку. Сначала меняем вид кадра у правой сцены —
    ролик от этого только выигрывает, у ведущей прибавляется положений (D14).
    Не вышло (дыра без аватара либо все подходящие положения заняты
    соседями) — склеиваем пару в один кусок, как и предлагает сама проверка.

    Склейка ограничена `MAX_STATIC_SPAN`: кусок длиннее восьми секунд без
    смены картинки валит D19 уже на готовом файле, после платного рендера.
    Первую сцену не трогаем — ролик обязан открываться лицом.

    Возвращает описания разведённых пар.
    """
    from reels_factory.hf_rhythm import MAX_STATIC_SPAN

    gaps = ordered_gaps(clips, duration)
    fixed: list[str] = []
    index = 0
    while index < len(scenes) - 1:
        left, right = scenes[index], scenes[index + 1]
        if not same_look(left, right):
            index += 1
            continue
        faceless = in_avatar_gap(float(right.get("startSec", 0)),
                                 float(right.get("endSec", 0)), gaps)
        # Считаемся только с левым соседом. Правого исключать нельзя: когда
        # без вставок остаётся цепочка сцен, каждая одинакова с обеими
        # соседками, свободных положений не остаётся ни у одной, и цепочка
        # так и стоит одним планом. Идём слева направо — правого разведёт
        # его собственный шаг, и выходит чередование `full`/`punch`.
        allowed = positions_for(right)
        taken = str(left.get("presenter") or "full")
        free = [name for name in allowed if name != taken]
        position = (free or list(allowed))[0]
        if not faceless and position != str(right.get("presenter") or "full"):
            right["presenter"] = position
            fixed.append(f'{right["id"]} → {position}')
            index += 1
            continue
        size = float(right["endSec"]) - float(left["startSec"])
        if index >= 1 and size <= MAX_STATIC_SPAN + 0.001:
            left["endSec"] = right["endSec"]
            left["phrases"] = [left.get("phrases", [0, 0])[0],
                               right.get("phrases", [0, 0])[-1]]
            fixed.append(f'{left["id"]} + {right["id"]} → один кусок')
            scenes.pop(index + 1)
            continue
        index += 1
    if fixed:
        print("одинаковые куски подряд разведены: " + ", ".join(fixed))
    return fixed


def shots_for(scene: dict) -> int:
    """Сколько планов реально встанет в эту сцену.

    Два — обычный случай. Один — только там, где сцена короче серии; такое
    бывает лишь на дырах, где аватар не заказан вовсе: отбор оставляет их вне
    очереди, потому что иначе там чёрный кадр. Резать полсекунды на два плана
    значит показать мигание вместо монтажа.
    """
    size = float(scene["endSec"]) - float(scene["startSec"])
    return SERIES_SHOTS if size >= SERIES_MIN - 0.001 else 1


def dominant_broll(scene: dict) -> bool:
    """Кадр этой сцены держит вставка, а не лицо."""
    position = str(scene.get("presenter") or "full")
    return position.startswith(_BROLL_POSITIONS)


def on_screen_seconds(scenes: list[dict]) -> float:
    """Сколько секунд аватар виден зрителю.

    Считается буквально по полю `presenter`: всё, что не `none`, — аватар в
    кадре. В `pip-*` он в уголке, в `stack` — в половине кадра, но из кадра
    никуда не девается, и у HeyGen эти секунды заказаны наравне с полным
    кадром. `dominant_broll` отвечает на другой вопрос — кто держит кадр, — и
    для правила зазора остаётся прежним.
    """
    return sum(float(scene["endSec"]) - float(scene["startSec"])
               for scene in scenes
               if str(scene.get("presenter") or "full") != "none")


def split_series(scene: dict, words: list[dict]) -> list[tuple[float, float]]:
    """Разрезать сцену на два плана серии — по сильнейшей паузе внутри неё.

    Шов ставится там же, где его поставил бы монтажёр: на самой заметной
    паузе речи. Нет ни одной подходящей — режем пополам.
    """
    start, end = float(scene["startSec"]), float(scene["endSec"])
    if shots_for(scene) == 1:
        return [(start, end)]
    inner = [w for w in words
             if start <= float(w["start"]) and float(w["end"]) <= end]
    best, seam = None, (start + end) / 2.0
    for index, word in enumerate(inner[:-1]):
        following = inner[index + 1]
        cut = (float(word["end"]) + float(following["start"])) / 2.0
        if cut - start < SHOT_MIN or end - cut < SHOT_MIN:
            continue
        weight = _pause_weight(word, following)
        if best is None or weight > best:
            best, seam = weight, cut
    return [(start, seam), (seam, end)]


def _pause_weight(word: dict, following: dict) -> float:
    """Сила паузы: её формула — зазор плюс надбавка за знак препинания."""
    gap = float(following["start"]) - float(word["end"])
    last = str(word.get("text") or "").rstrip()[-1:]
    return gap + (0.6 if last in ".!?" else 0.25 if last in ",…" else 0.0)


def pick_series(scenes: list[dict], clips: list[dict],
                duration: float) -> tuple[list[str], dict]:
    """Отобрать сцены, которые доживут до кадра сериями бироллов.

    Агент называет больше моментов, чем войдёт: выбор — арифметика, а не вкус.
    Порядок правил:

    1. Сцена, где аватара физически нет, обязана нести биролл — иначе там
       чёрный кадр. Такие серии берутся вне очереди.
    2. Сцена короче `SERIES_MIN` или длиннее `SERIES_MAX` серию не несёт: в
       первой два плана превратятся в мигание, во второй — в две стоячие
       картинки.
    3. Между соседними сериями остаётся `FACE_GAP` секунд с лицом в кадре.

    Четвёртым правилом здесь стоял потолок аватарного времени: код уводил
    самые длинные сцены с бироллом в `none`, пока доля не влезала в
    `AVATAR_ON_SCREEN_MAX`. Экономии в этом нет ни секунды — клипы куплены до
    того, как агент написал план, — а ролик терял и ведущую из кадра, и
    оплаченные деньги. Потолок остался один, на заказе.

    Возвращает (id оставленных сцен, отчёт с числами).
    """
    gaps = avatar_gaps(clips, duration)
    kept: list[dict] = []
    dropped: list[str] = []

    def length(scene: dict) -> float:
        return float(scene["endSec"]) - float(scene["startSec"])

    def faceless(scene: dict) -> bool:
        return in_avatar_gap(float(scene["startSec"]),
                             float(scene["endSec"]), gaps)

    def face_between(left: dict, right: dict) -> float:
        """Секунды с лицом между двумя сериями."""
        seconds = 0.0
        for scene in scenes:
            if float(scene["startSec"]) < float(left["endSec"]):
                continue
            if float(scene["endSec"]) > float(right["startSec"]):
                break
            if not faceless(scene) and not dominant_broll(scene):
                seconds += length(scene)
        return seconds

    gap = face_gap(duration)

    def spaced(chosen: list[dict]) -> bool:
        """Между выбранными сериями лицо держится `face_gap(duration)`.

        Считаем только те серии, на которых лицо действительно уходит из
        кадра: при `stack` ведущая занимает половину кадра и никуда не
        девается, а правило — про то, чтобы зритель не терял лицо надолго.
        Дыры без аватара из счёта выброшены тоже: там лица нет физически,
        требовать его — требовать невозможного.
        """
        ordered = sorted((s for s in chosen
                          if dominant_broll(s) and not faceless(s)),
                         key=lambda s: float(s["startSec"]))
        return all(face_between(left, right) >= gap
                   for left, right in zip(ordered, ordered[1:]))

    candidates = [s for s in scenes if insert_of(s)]
    forced = [s for s in candidates if faceless(s)]
    optional = []
    for scene in candidates:
        if faceless(scene):
            continue
        size = length(scene)
        if not (SERIES_MIN - 0.001 <= size <= SERIES_MAX + 0.001):
            dropped.append(f'{scene["id"]}: {size:.1f} с не серия')
            continue
        optional.append(scene)

    # Перебираем подмножества, а не идём жадно по времени: жадность выбирает
    # первое, что влезло, и на прогоне 24 из трёх кандидатов взяла две
    # короткие вместо одной длинной — биролла вышло 25 % вместо 30–35 %.
    # Кандидатов единицы, перебор дешевле любой эвристики. Сначала те наборы,
    # где серий больше: больше серий — живее монтаж.
    def rank(picked: list[dict]) -> tuple:
        """Чем набор лучше: больше серий, целее плашки агента.

        Плашка — решение агента про конкретный кадр; сняв под ней биролл, код
        меняет раскладку, и плашка вместе с ней уходит. Поэтому при прочих
        равных выбираем набор, где таких потерь меньше.
        """
        overlays = sum(1 for s in picked if s.get("overlay"))
        return (-len(picked), -overlays)

    best: list[dict] | None = None
    best_rank: tuple | None = None
    for size in range(len(optional), -1, -1):
        for subset in combinations(optional, size):
            picked = list(subset)
            if not spaced(forced + picked):
                continue
            key = rank(picked)
            if best_rank is None or key < best_rank:
                best, best_rank = picked, key
        # Наборы перебираются от большего к меньшему: как только на очередном
        # размере нашёлся проходящий, дальше будут только наборы беднее.
        if best is not None:
            break

    picked = best if best is not None else []
    kept = sorted(forced + picked, key=lambda s: float(s["startSec"]))
    broll = sum(length(s) for s in kept if dominant_broll(s))
    for scene in optional:
        if scene not in picked:
            dropped.append(f'{scene["id"]}: не вошла в отбор серий')

    report = {"broll_seconds": round(broll, 2),
              "avatar_share": round(on_screen_seconds(scenes) / duration, 4)
              if duration else 1.0,
              "series": len(kept), "dropped": dropped,
              "forced": [s["id"] for s in forced]}
    return [s["id"] for s in kept], report


# ---------------------------------------------------------- планы камеры

#: Вилка плана камеры. Её числа: «аватарное время нарезано на планы 1.2–3.9с
#: по сильнейшей паузе» (HANDOFF-BROLL-ZOOM-V6.md, пункт 4).
PLAN_MIN = 1.2
PLAN_MAX = 3.9

#: Ступени масштаба и правила их чередования — тоже её: наезд 100 → 118 % за
#: ≤1,5 с, статичные ступени 100/108/110/112, соседние отличаются ≥8 %.
PUSH_FROM, PUSH_TO = 1.00, 1.18
PUSH_RAMP = 1.5
STATIC_STEPS = (1.00, 1.08, 1.10, 1.12)
MIN_STEP = 0.08

#: Наезд не чаще каждого третьего плана: «наездов не больше трети»
#: (там же, критерии приёмки).
PUSH_EVERY = 3


def cut_into_plans(words: list[dict], start: float, end: float) -> list[dict]:
    """Нарезать кусок речи на планы камеры — её `cut_into_plans` целиком.

    Граница плана — самая сильная пауза в окне 1,2–3,9 с; фраза не рвётся
    посередине. Окно без единой годной границы режется по длине.
    """
    inner = [w for w in words
             if float(w["end"]) > start and float(w["start"]) < end]
    if not inner:
        return [{"start": start, "end": end}] if end - start > 0.05 else []

    plans: list[dict] = []
    index = 0
    while index < len(inner):
        opened = max(start, float(inner[index]["start"]))
        best = None
        for step in range(index, len(inner)):
            word = inner[step]
            following = inner[step + 1] if step + 1 < len(inner) else None
            cut = min(end, float(following["start"]) if following else end)
            size = cut - opened
            if size < PLAN_MIN:
                continue
            if size > PLAN_MAX:
                break
            weight = (_pause_weight(word, following) if following
                      else 9.0)
            if best is None or weight > best[0]:
                best = (weight, step, cut)
        if best is not None:
            _, step, cut = best
        else:
            step = index
            while (step + 1 < len(inner)
                   and float(inner[step + 1]["start"]) - opened < PLAN_MAX):
                step += 1
            cut = (min(end, float(inner[step + 1]["start"]))
                   if step + 1 < len(inner) else end)
        plans.append({"start": opened, "end": cut})
        index = step + 1
    plans[0]["start"] = start
    plans[-1]["end"] = end
    return plans


def zoom_ladder(plans: list[dict], *, big: list[bool] | None = None,
                offset: int = 0) -> list[dict]:
    """Раздать планам масштабы: ступени и редкие наезды.

    `big` — можно ли на этом плане ехать: в окне-уголке наезд не виден, там
    только ступень. `offset` — сколько планов уже роздано раньше: наезды
    считаются на весь ролик, а не на каждый кусок заново.
    """
    def pushes(index: int) -> bool:
        order = index + offset
        wide = True if big is None else big[index]
        size = float(plans[index]["end"]) - float(plans[index]["start"])
        return order % PUSH_EVERY == 0 and wide and size >= PUSH_RAMP * 0.6

    out: list[dict] = []
    previous = 1.0
    for index, plan in enumerate(plans):
        order = index + offset
        size = float(plan["end"]) - float(plan["start"])
        if pushes(index):
            step = dict(plan, kind="push", scale_from=PUSH_FROM,
                        scale_to=PUSH_TO,
                        ramp=round(min(PUSH_RAMP, size), 3))
            previous = PUSH_TO
        else:
            scale = _next_static(previous, order)
            step = dict(plan, kind="static", scale_from=scale, scale_to=scale,
                        ramp=0.0)
            previous = scale
        out.append(step)
    return out


def _next_static(previous: float, order: int) -> float:
    """Следующая ступень. Ступени чередуются через 100 %.

    Так устроена и её лестница: `PATTERN` в `camera_plan.py` идёт
    100 → 110 → 100 → 112 → …, крупная ступень никогда не следует за крупной.
    Причина арифметическая: из набора 100/108/110/112 у 108 есть ровно один
    сосед в 8 пунктах — сотня, и любое другое чередование правило нарушит.
    Побочно это же разводит ступень и наезд: наезд стартует со 100 %, а перед
    ним по чередованию всегда стоит крупная ступень.
    """
    if previous > PUSH_FROM + 1e-9:
        return PUSH_FROM
    raised = [step for step in STATIC_STEPS if step > PUSH_FROM + 1e-9]
    return raised[(order // 2) % len(raised)]


# -------------------------------------------------------------- вспышки

#: Больше двух вспышек за ролик — это уже стробоскоп. Её предел.
FLASH_MAX = 2

#: Вспышки не ставятся вплотную: между ними не меньше этого.
FLASH_APART = 6.0

#: С какого масштаба возврат к 100 % считается «выдохом». Ступень 108 % — это
#: не крупный план, и вспышка на её отпускании читается как случайная.
FLASH_AFTER = 1.12


def flash_moments(plans: list[dict], *, climax: float | None = None,
                  duration: float = 0.0) -> list[float]:
    """Где вспыхнуть. Её правило: на «выдохе» — возврате к 100 % после крупного.

    Кульминация, названная агентом, идёт первой: это решение о рассказе, а не
    арифметика. Остальные места — возвраты масштаба к единице.
    """
    picked: list[float] = []
    if climax is not None:
        picked.append(round(float(climax), 3))
    for index, plan in enumerate(plans[1:], start=1):
        if len(picked) >= FLASH_MAX:
            break
        if plan["kind"] != "static" or plan["scale_from"] != 1.0:
            continue
        if plans[index - 1]["scale_to"] < FLASH_AFTER:
            continue
        at = round(float(plan["start"]), 3)
        if duration and at > duration - 1.0:
            continue
        if any(abs(at - other) < FLASH_APART for other in picked):
            continue
        picked.append(at)
    return sorted(picked)[:FLASH_MAX]
