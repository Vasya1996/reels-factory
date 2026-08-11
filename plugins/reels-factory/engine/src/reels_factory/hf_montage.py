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

#: Между сериями зритель обязан снова увидеть лицо, и не мельком. Число её:
#: «между сериями лицо держится ≥2.5с» (HANDOFF-BROLL-ZOOM-V6.md, критерии
#: приёмки).
FACE_GAP = 2.5

#: Потолок времени, когда аватар виден в кадре. Требование заказчика
#: 10.08.2026: каждая секунда аватара в кадре — это заказанная секунда
#: генерации, а она главные деньги ролика, поэтому число считается буквально
#: глазами зрителя и держится сверху.
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

    gaps = avatar_gaps(clips or [], duration)
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

    1. Ведущая в нижнем уголке остаётся на месте, а кадр закрывает запасная
       схема из `fallback`. Это единственный случай, где раскладка агента
       переживает потерю биролла: схема стоит в верхней трети, нижние уголки
       с ней не пересекаются. Заодно у ролика сохраняется третье окно ведущей,
       которого требует приёмка (D14).
    2. Ведущая занимает кадр целиком — `full` или `punch`, и не такая, как у
       соседей: две сцены подряд одним планом детектор не разделит (D21).
    3. Ведущей на этом куске нет физически — остаётся схема.
    """
    from reels_factory.hf_layout import in_avatar_gap

    scene = scenes[index]
    position = str(scene.get("presenter") or "full")
    near = {scenes[i].get("presenter")
            for i in (index - 1, index + 1) if 0 <= i < len(scenes)}
    faceless = in_avatar_gap(float(scene.get("startSec", 0)),
                             float(scene.get("endSec", 0)), gaps)
    has_fallback = any(str((scene.get("fallback") or {}).get(kind) or "").strip()
                       for kind in ("logo", "icon"))

    if not faceless and position in ("pip-br", "pip-bl") and has_fallback \
            and position not in near:
        scene["needsSchema"] = True
        return
    if faceless or position == "none":
        scene["presenter"] = "none"
        scene["needsSchema"] = True
        return
    if position in ("full", "punch"):
        return
    free = [name for name in ("full", "punch") if name not in near]
    scene["presenter"] = free[0] if free else "full"
    # Плашку агент ставил под ту раскладку, которой больше нет: на
    # полнокадровой ведущей её текст ложится прямо на лицо — прогон 24
    # поймал это гейтом D8 и их же `content_overlap`. Снимаем вместе с
    # серией; текст сцены всё равно несёт титр.
    if scene.pop("overlay", None) is not None:
        print(f'{scene["id"]}: плашка снята вместе с серией — под ведущей '
              "во весь кадр её текст лёг бы на лицо")


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
    4. Аватар виден в кадре не дольше `AVATAR_ON_SCREEN_MAX` хронометража.
       Долю считает `on_screen_seconds` по полю `presenter`, и сбить её
       можно единственным способом — увести сцену с бироллом в `none`:
       снятая серия аватар из кадра не убирает, он там остаётся уголком или
       полным кадром. Поэтому набор серий выбирается тот, с которого потолок
       достижим, а лишний аватар код снимает сам.

    Сцены, с которых аватар снят, метод правит на месте: `presenter` у них
    становится `none`. Их id перечислены в отчёте полем `stripped`.

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

    def hides_face(scene: dict, stripped: frozenset) -> bool:
        """Лицо ушло из кадра: либо так написал агент, либо так решил код."""
        return scene["id"] in stripped or dominant_broll(scene)

    def face_between(left: dict, right: dict, stripped: frozenset) -> float:
        """Секунды с лицом между двумя сериями."""
        seconds = 0.0
        for scene in scenes:
            if float(scene["startSec"]) < float(left["endSec"]):
                continue
            if float(scene["endSec"]) > float(right["startSec"]):
                break
            if not faceless(scene) and not hides_face(scene, stripped):
                seconds += length(scene)
        return seconds

    def spaced(chosen: list[dict], stripped: frozenset = frozenset()) -> bool:
        """Между выбранными сериями лицо держится FACE_GAP.

        Считаем только те серии, на которых лицо действительно уходит из
        кадра: при `stack` ведущая занимает половину кадра и никуда не
        девается, а правило — про то, чтобы зритель не терял лицо надолго.
        Дыры без аватара из счёта выброшены тоже: там лица нет физически,
        требовать его — требовать невозможного.

        `stripped` — сцены, с которых аватар снимает код: после этого лицо
        уходит из кадра и там, поэтому зазор считается уже с ними.
        """
        ordered = sorted((s for s in chosen
                          if hides_face(s, stripped) and not faceless(s)),
                         key=lambda s: float(s["startSec"]))
        return all(face_between(left, right, stripped) >= FACE_GAP
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

    on_screen = on_screen_seconds(scenes)
    ceiling = duration * AVATAR_ON_SCREEN_MAX

    def strip_plan(chosen: list[dict]) -> tuple[frozenset, float]:
        """С кого из выбранных серий снять аватар и сколько его останется.

        Снимаем с самых длинных сцен: одна длинная отдаёт больше секунд
        генерации, чем три коротких, и рвёт лицо на меньшее число кусков.
        Сцену, после которой между сериями перестанет хватать лица,
        пропускаем — правило зазора старше экономии. Сцена, где аватара и так
        нет, снимать нечего.
        """
        stripped: frozenset = frozenset()
        left = on_screen
        if duration <= 0:
            return stripped, left
        for scene in sorted(chosen, key=length, reverse=True):
            if left <= ceiling + 0.001:
                break
            if str(scene.get("presenter") or "full") == "none":
                continue
            planned = stripped | {scene["id"]}
            if not spaced(chosen, planned):
                continue
            stripped, left = planned, left - length(scene)
        return stripped, left

    # Перебираем подмножества, а не идём жадно по времени: жадность выбирает
    # первое, что влезло, и на прогоне 24 из трёх кандидатов взяла две
    # короткие вместо одной длинной — биролла вышло 25 % вместо 30–35 %.
    # Кандидатов единицы, перебор дешевле любой эвристики. Сначала те наборы,
    # где серий больше: больше серий — живее монтаж, и тем больше сцен, с
    # которых можно снять аватар.
    def rank(picked: list[dict], left: float) -> tuple:
        """Чем набор лучше: ближе к потолку, больше серий, целее плашки агента.

        Первое число — на сколько секунд аватар не влез в потолок с этим
        набором. Ноль значит, что потолок взят; когда его не взять ни одним
        набором, выигрывает ближайший снизу — тот, где аватара меньше.

        Плашка — решение агента про конкретный кадр; сняв под ней биролл, код
        меняет раскладку, и плашка вместе с ней уходит. Поэтому при прочих
        равных выбираем набор, где таких потерь меньше.
        """
        overlays = sum(1 for s in picked if s.get("overlay"))
        return (round(max(0.0, left - ceiling), 3), -len(picked), -overlays)

    best: tuple[list[dict], frozenset] | None = None
    best_rank: tuple | None = None
    for size in range(len(optional), -1, -1):
        for subset in combinations(optional, size):
            picked = list(subset)
            chosen = forced + picked
            if not spaced(chosen):
                continue
            stripped, left = strip_plan(chosen)
            key = rank(picked, left)
            if best_rank is None or key < best_rank:
                best, best_rank = (picked, stripped), key
        if best_rank is not None and best_rank[0] <= 0.001:
            break

    picked, stripped = best if best is not None else ([], frozenset())
    kept = sorted(forced + picked, key=lambda s: float(s["startSec"]))
    for scene in kept:
        if scene["id"] not in stripped:
            continue
        scene["presenter"] = "none"
        print(f'{scene["id"]}: аватар снят с кадра — иначе он виден дольше '
              f"{AVATAR_ON_SCREEN_MAX * 100:.0f} % ролика")
    on_screen -= sum(length(s) for s in kept if s["id"] in stripped)
    broll = sum(length(s) for s in kept if dominant_broll(s))
    for scene in optional:
        if scene not in picked:
            dropped.append(f'{scene["id"]}: не вошла в отбор серий')

    report = {"broll_seconds": round(broll, 2),
              "avatar_share": round(on_screen / duration, 4)
              if duration else 1.0,
              "series": len(kept), "dropped": dropped,
              "stripped": sorted(stripped),
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
