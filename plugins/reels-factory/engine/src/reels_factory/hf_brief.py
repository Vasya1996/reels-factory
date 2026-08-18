"""Задание агенту-сборщику: он режиссирует, композицию собирает код.

Первая версия этого файла выдавала агенту готовую пооконную раскадровку — агент
переставал быть режиссёром. Вторая отдала ему всё, включая изготовление: он
верстал `index.html` целиком. Третья оставила ему фрагменты карточек — и это
всё ещё было 42 тысячи токенов на выходе, то есть четверть часа прогона.
Четвёртая давала ему каталог наших полноэкранных блоков, и кадр из них выходил
слайд-шоу: пустые две трети, оставшиеся заглушки, недоигравшие анимации.

Здесь он не пишет разметку вовсе и блоков не выбирает. Кадр собран слоями —
ведущая, поверх неё вставка, поверх всего титр, — и решения агента ровно три на
сцену: какие фразы она накрывает, где в кадре ведущая и что показать вставкой.
Изготовление целиком у кода: секунды, геометрия, подбор файла, субтитры,
сборка композиции.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

from reels_factory.avatar_islands import (
    avatar_budget_targets, avatar_islands_settings,
)
from reels_factory.config import FPS, OUT_H, OUT_W
from reels_factory.editplan import MAX_FACE_ABSENCE_S, MIN_FULLSCREEN_S
from reels_factory.hf_gates import min_scenes
from reels_factory.hf_montage import (
    SERIES_MAX, SERIES_MIN, face_gap, inserts_wanted,
)
from reels_factory.hf_montage_skill import number, seconds, write_montage_skill
from reels_factory.hf_phrases import faceless_phrases
from reels_factory.hf_rhythm import MAX_STATIC_SPAN
from reels_factory.hf_schema import ICONS, min_seconds

# Manrope и Unbounded — единственные гарнитуры проекта, реально несущие
# кириллицу и (с донорским патчем в hf_fonts.py) казахские буквы в обоих
# регистрах.
FONTS = "Manrope, Unbounded"

#: Маршрут, который исполняет сборку. Роутер `/hyperframes` читает его из шапки
#: BRIEF.md и дальше не переспрашивает («`BRIEF.md` exists → Read `workflow` and
#: `flow`», hyperframes/SKILL.md:28; ключ описан в
#: hyperframes-core/references/brief-format.md:13).
#:
#: Не `talking-head-recut`: его контракт — «Existing talking-head... footage to
#: package. The underlying clip plays unchanged»
#: (hyperframes/references/routes/talking-head-recut.md:3). Мы клип ведущей
#: режем на острова, часть ролика идёт вовсе без неё и закрывается вставкой —
#: это «custom edit», и роутер такой случай отправляет сюда сам: «Retiming,
#: reordering... remixing footage is a custom edit and falls through to
#: `/general-video`» (hyperframes/SKILL.md:67).
WORKFLOW = "general-video"

#: Положения ведущей и что каждое значит для агента. Словаря позиций у них нет
#: ни в `/general-video`, ни в блоках реестра — это наше. Механизм родной:
#: обычный клип, которому таймлайн меняет геометрию обёртки
#: (hyperframes-creative/references/composition-patterns.md:11-14).
POSITIONS = [
    ("full", "во весь кадр", "вставки в этой сцене быть не может — её некуда "
     "поставить"),
    ("punch", "во весь кадр, наездом крупнее", "то же самое, но заметно ближе: "
     "это «поп» для ударной реплики"),
    ("pip-tr", "в окошке справа сверху", "кадр занимает вставка, ведущая поверх "
     "неё"),
    ("pip-tl", "в окошке слева сверху", "то же"),
    ("pip-br", "в окошке справа снизу", "то же"),
    ("pip-bl", "в окошке слева снизу", "то же"),
    ("stack", "в верхней части кадра", "вставка занимает нижнюю"),
    ("none", "её в кадре нет", "кадр занимает вставка либо фирменный фон"),
]


def _scenario_block(block: dict) -> str:
    return f'- **{block.get("role", "?")}**: {block.get("speech", "")}'


def _phrase_line(phrase: dict, faceless: set[int]) -> str:
    """Строка фразы для задания.

    Длина нужна, чтобы агент не назначал сцену на фразу короче минимума: код
    такую сцену дотянет за счёт соседней, и картинка съедет с реплики.
    """
    length = float(phrase["end"]) - float(phrase["start"])
    mark = "  ← **ведущей тут нет**" if phrase["id"] in faceless else ""
    return (f'- `{phrase["id"]}` **{phrase["role"]}** {seconds(length)} — '
            f'{phrase["text"]}{mark}')


def _positions_block() -> str:
    return "\n".join(f"- `{name}` — {what}; {note}" for name, what, note
                     in POSITIONS)


#: Поля, которые заказчик может назвать сам. Имена и смысл — их контракта брифа
#: (`hyperframes-core/references/brief-contract.md`, раздел «Shared fields»);
#: `notes` — свободная строка, их же «Capture answers verbatim… under `## Notes`»
#: (`hyperframes/references/intent-interview.md`, шаг 7).
WISHES = {
    "message": "главная мысль ролика",
    "audience": "кто это смотрит",
    "angle": "форма рассказа",
    "destination": "где ролик будет играть",
    "notes": "пожелания к оформлению и всё, что ещё сказал заказчик",
}


#: Шапка паспорта накладки: имя блока и пол сцены под него. Пишет её
#: `hf_slots.passport` — «### `name` — сцена собирается X с, карточка не короче
#: Y с», числа в формате `:g`, то есть с точкой.
_PASSPORT_HEAD = re.compile(
    r"^### `([^`]+)`.*?карточка не короче ([\d.]+) с", re.M)


def _overlay_index(passports: str) -> str:
    """Список установленных плашек СО СЛОВАМИ и пол сцены под каждую.

    Данные, которые агент вывести не может: какие блоки лежат в каталоге этого
    прогона и какой длины сцена под них нужна. Паспорта целиком уехали в
    `OVERLAYS.md` (шестнадцать карточек занимали шестую часть задания), и файл
    без единого слова о содержимом агент не открывал ни разу — в боевом плане
    прогона плашек ноль при шестнадцати доступных. Индекс из имени и числа
    стоит одну строку и отвечает на вопрос, который и решает выбор: влезет ли
    плашка в эту сцену.

    Плашки без текстовых слотов сюда не попадают, хотя в `OVERLAYS.md` лежат:
    это фактуры (протечка света, вспышка, обводка кадра), они кроют кадр целиком
    и ничего не говорят. Ровно такая — `editorial-flash-overlay` — и стояла
    единственным содержимым в тех 2,7 с пустого кадра: назвать её ответом на
    «чем закрыт кадр» значит повторить дефект.

    Пусто, когда установленных плашек со словами нет вовсе: звать в `overlay`
    тогда нечем, и свод правил печатает это прямым текстом.
    """
    cards = ("\n" + (passports or "")).split("\n### ")[1:]
    named = []
    for card in cards:
        head = _PASSPORT_HEAD.search("### " + card)
        # Слот паспорта печатается строкой «- `имя` — …»: у фактуры их нет.
        if head and re.search(r"^- `", card, re.M):
            named.append(f"`{head.group(1)}` — {seconds(float(head.group(2)))}")
    if not named:
        return ""
    return ("Плашки со словами, установленные в этом прогоне, и пол сцены под "
            f"каждую: {', '.join(named)}. Что лежит в слотах каждой — в "
            "`OVERLAYS.md`.")


def _wishes_block(wishes: dict | None) -> str:
    """Сказанное заказчиком — отдельной секцией, дословно.

    Их правило: спрашивают один раз, ответ уходит в бриф и больше не
    выводится заново, а сказанное и выведенное живут порознь. Незаполненное
    поле — не пустая строка в кадре, а разрешение вывести его самому: «Values
    inferred or derived by policy are stated in the brief, not asked».
    """
    said = {key: str((wishes or {}).get(key) or "").strip() for key in WISHES}
    said = {key: value for key, value in said.items() if value}
    if not said:
        return ""
    lines = "\n".join(f"- **{key}** ({WISHES[key]}): {value}"
                      for key, value in said.items())
    rest = [key for key in WISHES if key not in said and key != "notes"]
    tail = (f"\nОстальное ({', '.join(rest)}) выведи сам." if rest else "")
    return ("\n### Это сказал заказчик — бери как есть\n\n"
            f"{lines}\n{tail}\n")


#: На сколько образец отходит от порогов сцены без ведущей, выбирая, каким
#: сценам показать `avatarNeeded: false`. Гейты до заказа сравнивают длину
#: сцены с `MIN_FULLSCREEN_S` и `MAX_FACE_ABSENCE_S` и добавляют к порогу свой
#: запас на округления (`PHRASE_TIME_MARGIN`, hf_render.py): сцена ровно на
#: пороге его не проходит. Кадр — самая мелкая величина, которой в проекте
#: меряется время, и он крупнее любого такого запаса, поэтому образец отходит
#: от каждого порога на кадр.
SAMPLE_BLIND_MARGIN = 1.0 / FPS

#: До скольких сцен образец растёт, подбирая долю ведущей под бюджет.
#:
#: Четырёх сцен на это не хватает: крайние ведёт лицо (`D28_avatar_bookends`),
#: а двух отказов подряд образец не показывает — значит отказ достаётся ровно
#: одной сцене из четырёх, и ведущая в образце выходит на 75 % показанного,
#: выше любого потолка бюджета. Пятая сцена даёт второй отказ через одну и
#: приводит долю к бюджету. Шестая — запас на неровные фразы; дальше образец
#: дороже урока, который даёт: он показывает форму ответа, а не весь ролик.
SAMPLE_MAX_SCENES = 6


def _scene_lengths(shown: list[tuple[list[int], bool]],
                   phrases: list[dict]) -> list[float]:
    """Длина каждой показанной сцены — сумма длительностей её фраз.

    Тем же действием меряет сцену и агент (задание не даёт ему секунд иначе), и
    гейты до заказа (`D29_avatar_budget`, `D31_faceless_scenes`, hf_render.py).
    """
    spans = {int(p["id"]): float(p["end"]) - float(p["start"])
             for p in phrases}
    return [sum(spans.get(pid, 0.0) for pid in block) for block, _ in shown]


def _blind_scenes(shown: list[tuple[list[int], bool]], phrases: list[dict], *,
                  bar: float) -> list[int]:
    """Какие из показанных сцен идут в образце с `avatarNeeded: false`.

    Образец сильнее правила, стоящего рядом с ним, поэтому под отказ он берёт
    только такие сцены, какие примут гейты до заказа, и ровно столько, сколько
    нужно, чтобы доля ведущей в образце не спорила с бюджетом. Четыре гейта, и
    каждый режет свои сцены:

    - открытие и финал ролика ведёт лицо (`D28_avatar_bookends`) — отказы
      стоят между ними;
    - сцена без ведущей живёт не меньше `MIN_FULLSCREEN_S`, и меряется это её
      длиной целиком (`D31_faceless_scenes`): соседние окна сцены, которую
      лишил ведущей сам агент, код склеивает в одно (`apply_agent_coverage`),
      и гейт считает сумму её фраз;
    - лицо не пропадает дольше `MAX_FACE_ABSENCE_S` подряд
      (`D32_face_absence`) — отсюда и потолок длины такой сцены, и запрет на
      два отказа подряд;
    - фразы ролей `hook` и `cta` ролик говорит лицом (`D30_avatar_roles`) —
      сцена, накрывшая такую фразу, под отказ не годится.

    `bar` — доля ведущей, выше которой план заворачивает `D29_avatar_budget`.
    Прежний выбор отдавал под отказ ровно одну сцену и на бюджет не смотрел
    вовсе: образец из четырёх сцен показывал ведущую на трёх — 75 % показанного
    при потолке 60 %, то есть учил ровно тому плану, из-за которого пересдачи и
    жглись. Из подходящих раскладов берётся самая дорогая, уложившаяся в `bar`:
    экономить сверх бюджета образец учить не должен — лицо в кадре и есть
    рассказчик.

    Ни одна сцена не подошла — пустой список: отказа в образце не будет вовсе,
    и задание рядом назовёт признаки, по которым сцену под отказ выбирают
    самому.
    """
    from reels_factory.hf_render import SPEAKING_ROLES

    speaking = {int(p["id"]) for p in phrases
                if p.get("role") in SPEAKING_ROLES}
    lengths = _scene_lengths(shown, phrases)
    total = sum(lengths)
    if total <= 0:
        return []
    floor = MIN_FULLSCREEN_S + SAMPLE_BLIND_MARGIN
    roof = _BLIND_ROOF - SAMPLE_BLIND_MARGIN
    eligible = [index for index, (block, _) in enumerate(shown)
                if 0 < index < len(shown) - 1
                and not speaking.intersection(block)
                and floor <= lengths[index] <= roof]
    variants: list[tuple[float, list[int]]] = []
    for mask in range(1, 1 << len(eligible)):
        chosen = [eligible[bit] for bit in range(len(eligible))
                  if mask >> bit & 1]
        # Два отказа подряд образец не показывает: между сценами без ведущей
        # стоит сцена с ведущей — это и есть способ не потерять лицо дольше
        # предела.
        if any(right - left == 1 for left, right in zip(chosen, chosen[1:])):
            continue
        variants.append(((total - sum(lengths[i] for i in chosen)) / total,
                         chosen))
    if not variants:
        return []
    within = [item for item in variants if item[0] <= bar + 1e-9]
    if within:
        return max(within, key=lambda item: (item[0], -len(item[1])))[1]
    # В бюджет не уложился ни один расклад показанных сцен — берём самый
    # экономный из возможных: он ближе к бюджету, чем любой другой.
    return min(variants, key=lambda item: (item[0], len(item[1])))[1]


def _shown_scenes(groups: list[tuple[list[int], bool]], phrases: list[dict], *,
                  bar: float) -> tuple[list[tuple[list[int], bool]], list[int]]:
    """Сколько сцен показать в образце и какие из них идут без ведущей.

    Образец растёт ровно до тех пор, пока доля ведущей в нём не уложится в
    бюджет (`bar`), и не дальше `SAMPLE_MAX_SCENES`: длина образца — это токены
    каждого прогона, а урок он даёт один и тот же.
    """
    shown = groups[:4]
    blind: list[int] = []
    # Ролик короче четырёх сцен образец показывает целиком: расти там некуда, а
    # отказ в нём всё равно ищется — по тем же признакам.
    first = min(4, max(1, len(groups)))
    for count in range(first, min(SAMPLE_MAX_SCENES, len(groups)) + 1):
        shown = groups[:count]
        blind = _blind_scenes(shown, phrases, bar=bar)
        lengths = _scene_lengths(shown, phrases)
        total = sum(lengths)
        share = ((total - sum(lengths[i] for i in blind)) / total
                 if total > 0 else 0.0)
        if blind and share <= bar + 1e-9:
            break
    return shown, blind


def _sample_plan(phrases: list[dict], faceless: set[int], *,
                 duration: float, bar: float = 1.0,
                 avatar_ordered: bool = True) -> str:
    """Образец ответа, собранный из фраз этого же ролика.

    Раньше образец был написан руками и жил своей жизнью: пять сцен вместо
    минимума, ни одного `climax`, две последние сцены с одинаковым кадром и
    плашка со слотом, которого нет в её паспорте. Их правило про примеры —
    «Mirror your actual use case closely» (claude-prompting-best-practices), а
    образец в задании сильнее любого правила рядом с ним, поэтому он собирается
    из настоящих номеров фраз и по тем же правилам, что мы требуем от агента:
    фразы встык, один `climax`, соседние сцены различимы, фразы без ведущей —
    в своей сцене.

    `avatar_ordered=False` — план до заказа: пометок «без ведущей» в списке
    фраз нет вовсе, и отказ от ведущей агент принимает сам полем
    `avatarNeeded`. Поле стоит у каждой сцены образца: то, чего в образце нет,
    агент не заполняет, а заказ островов читает ровно его.

    `bar` — доля ведущей, выше которой план заворачивает `D29_avatar_budget`.
    Образец под неё подстраивается: сколько сцен показать и сколько из них
    отдать вставке, решают `_shown_scenes` и `_blind_scenes`. Прежний образец
    бюджета не знал и показывал ведущую на трёх сценах из четырёх — 75 %
    показанного при потолке 60 %; ровно этот перекос и жёг пересдачи, потому
    что образец сильнее правила, стоящего рядом с ним.

    Значение `false` образец показывает не всегда, а только когда среди
    показанных сцен есть годная под отказ по длине и по ролям своих фраз
    (`_blind_scenes`). На коротком ролике середины, свободной от краёв, не
    остаётся; на очень коротких фразах середина есть, но пола сцены без ведущей
    не набирает; хук во всю середину закрывает её ролями — и во всех трёх
    случаях образец показывает одни `true`, а задание рядом объясняет, почему.
    Учить отказу там нечем: сцена, отданная под него, была бы либо финалом —
    финал за лицом требуют и свод правил, и `D28_avatar_bookends`
    (hf_render.py), — либо планом, который заворачивает гейт до заказа.

    Положения ведущей в образце различаются причиной, а не чередованием по
    номеру сцены. Прежний образец ставил `full`/`punch` через одну, и канон
    предупреждает ровно об этом: пример учит и той закономерности, которой в
    правиле нет («vary enough that Claude doesn't pick up unintended patterns»,
    claude-prompting-best-practices).
    """
    ids = [int(p["id"]) for p in phrases] or [0]
    groups: list[tuple[list[int], bool]] = []
    for pid in ids:
        blind = pid in faceless
        if groups and groups[-1][1] == blind and len(groups[-1][0]) < 2:
            groups[-1][0].append(pid)
        else:
            groups.append(([pid], blind))
    # Показываем не весь ролик, а первые сцены: образец учит форме ответа, а
    # не содержанию. Хвост подписан многоточием прямо в JSON-комментарии ниже.
    # До заказа число показанных сцен подбирается под бюджет ведущей: на
    # четырёх сценах отказ достаётся ровно одной, и доля ведущей выходит выше
    # любого потолка (`_shown_scenes`).
    if avatar_ordered:
        shown, blind_at = groups[:4], []
    else:
        shown, blind_at = _shown_scenes(groups, phrases, bar=bar)
    blinds = [blind or index in blind_at
              for index, (_, blind) in enumerate(shown)]
    # Сцена, дальше которой образец не идёт, а ролик идёт. Когда показаны все
    # группы фраз, последняя показанная сцена И ЕСТЬ финал ролика, и ставить ей
    # уголок под схему нельзя: финал ведёт лицо во весь кадр (`full`/`punch`),
    # этого требует свод правил, и по этому же судит гейт до заказа
    # (`D28_avatar_bookends` в hf_render.py). На коротком ролике (две группы
    # фраз) сцена со схемой попадала ровно в финал и учила против правила.
    middle = [index for index in range(1, len(shown) - 1)
              if not blinds[index]] if len(shown) > 2 else []
    if not middle and len(shown) == 2 and len(shown) < len(groups):
        middle = [1]
    schema_at = middle[0] if middle else None
    # Вторая сцена с ведущей и вставкой: уголок поверх найденного видео. Так в
    # образце оказываются три разных окна — `full`, `punch` и уголок, — и ни
    # одно не выведено из чётности номера сцены.
    corner_at = middle[1] if len(middle) > 1 else None
    scenes = []
    for index, ((block, _), blind) in enumerate(zip(shown, blinds)):
        last = index == len(shown) - 1
        scene: dict = {"id": f"s-{index + 1:02d}",
                       "intent": "чем сцена держит зрителя",
                       "beat": "hook" if index == 0 else "point",
                       "phrases": [block[0], block[-1]],
                       "presenter": "punch" if last and index else "full"}
        if not avatar_ordered:
            scene["avatarNeeded"] = not blind
        scene["insert"] = None
        if blind or index == corner_at:
            scene["presenter"] = "none" if blind else "pip-tr"
            scene["insert"] = {
                "shots": ["hand writing checklist in notebook",
                          "closeup fingers underlining a line"],
                "kind": "video"}
            # Запасную схему образец показывает один раз, дальше запас
            # дописывает `_add_backups`: две одинаковые запасные подряд учат
            # тому, что ответ на потерянную вставку всегда один и тот же, а их
            # три. Ровно так прогон и вышел — три `fallback` и ни одного
            # значка при шестнадцати доступных плашках.
            if blind and not any(item.get("fallback") for item in scenes):
                scene["fallback"] = {"form": "items", "why": "набор равноправных",
                                     "items": [{"label": "кому", "icon": "человек"},
                                               {"label": "что", "icon": "документ"},
                                               {"label": "как", "icon": "поиск"}]}
        elif index == schema_at:
            # Схема держит кадр, ведущая остаётся нижним уголком: `none` на
            # оплаченной секунде — это выброшенные деньги, и D24 такой план
            # заворачивает.
            scene["presenter"] = "pip-br"
            scene["schema"] = {"form": "steps", "why": "порядок",
                               "nodes": ["кто", "что", "как"]}
        scenes.append(scene)
    # Моментов под вставку образец обязан показать столько же, сколько требует
    # гейт до заказа (`D34_inserts`): образец сильнее правила, и план, срисован­
    # ный с него, иначе заворачивают. Недостающие берут сцены из середины —
    # ведущая уезжает в верхнюю половину кадра, вставка занимает нижнюю.
    нужно = inserts_wanted(scenes)
    for index in range(1, len(scenes) - 1):
        if sum(1 for scene in scenes if scene.get("insert")) >= нужно:
            break
        scene = scenes[index]
        if scene.get("insert") or scene.get("schema"):
            continue
        scene["presenter"] = "stack"
        scene["insert"] = {"shots": ["hands sorting papers on a desk",
                                     "closeup pen marking a line"],
                           "kind": "video"}
    _add_backups(scenes)
    if len(scenes) > 1:
        scenes[-1]["beat"] = "climax"
    body = json.dumps(
        {"brollContext": {
            "domain": "sales and client communication in small business",
            "anti": "factories, robots, programming code, casino"},
         "scenes": scenes},
        ensure_ascii=False, indent=1)
    body = _compact_lists(body).rstrip()
    if len(shown) == len(groups):
        # Образец дошёл до последней фразы сам: хвост «остальные сцены до
        # фразы N» обещал бы продолжение, которого нет, и агент дописывал бы
        # сцены на фразы, уже накрытые выше.
        return body
    # Срезаем закрытие списка сцен и объекта, чтобы дописать многоточие хвоста:
    # образец показывает форму ответа, а не весь ролик.
    for closing in ("}", "]"):
        body = body.rstrip().rstrip(closing)
    # Хвост подписан не просто многоточием: сказано, ЧЕМ его продолжать.
    # Прежнее «тем же порядком» читалось как «дальше не важно», и план, где
    # весь хвост уходил с ведущей, бюджет заворачивал — хотя показанные сцены
    # образца в бюджет укладывались. Чередование отказов держится до конца
    # ролика, финал ведёт лицо (`D28_avatar_bookends`).
    #
    # Про чередование говорим только до заказа: когда аватар уже куплен,
    # прятать его нечем оправдать — там доктрина обратная, и это правило звало
    # бы выбрасывать оплаченные секунды.
    #
    # Закрытие собирается в одном литерале с многоточием: разрезанный хвост
    # уже унёс `}}` из f-строки в обычную, и образец переставал читаться как
    # JSON — а его разбирают и агент, и тесты.
    rule = ("та же длина, то же чередование сцен с ведущей и без неё, финал "
            "за лицом") if not avatar_ordered else "та же длина и та же форма"
    return (body.rstrip() + ",\n  … остальные сцены до фразы "
            f"{ids[-1]} тем же порядком: {rule}\n ]\n}}")


def _add_backups(scenes: list[dict]) -> None:
    """Дописать запас каждой сцене образца, у которой стоит `insert`.

    Правило круга 6 безусловно: у сцены со вставкой назван запас — `fallback`,
    `overlay` или `icon`. Образец сильнее правила, стоящего рядом с ним, и
    прежний показывал `fallback` ровно у одной сцены — той, где
    `avatarNeeded: false`. Агент прогона hf-live2 воспроизвёл именно эту
    структуру: три `fallback` на трёх сценах с отказом и ни одного на сцене со
    вставкой под ведущей — из чего и вышли 2,7 с фона с титром.

    Значок показывается ровно один раз и только там, где код его не снимет:
    рядом с полнокадровой ведущей и над `stack` места ему нет (`icon_fits`,
    hf_layout.py). Приёма, которого в образце нет, агент не применяет вовсе —
    в боевом плане прогона ноль значков и ноль плашек при шестнадцати
    доступных.
    """
    from reels_factory.hf_layout import icon_fits

    shown_icon = False
    for scene in scenes:
        if not scene.get("insert"):
            continue
        if scene.get("fallback") or scene.get("icon") or scene.get("overlay"):
            continue
        if not shown_icon and icon_fits(str(scene.get("presenter") or "none")):
            scene["icon"] = {"query": "checklist mark"}
            shown_icon = True
            continue
        scene["fallback"] = {"form": "pairs", "why": "характеристики пунктов",
                             "rows": [{"label": "формат",
                                       "value": "вертикальный"},
                                      {"label": "срок",
                                       "value": "две недели"}]}


def _compact_lists(text: str) -> str:
    """Списки простых значений — в одну строку.

    `json.dumps` с отступом ломает даже `[0, 1]` на три строки, и образец
    разрастается втрое. Читаемость образца тут важнее: их правило про примеры
    требует, чтобы он был похож на настоящий ответ, а не на распечатку
    структуры. Списки с объектами внутри не трогаем — там перенос помогает.
    """
    return re.sub(r"\[\s*\n((?:[^\[\]{}\n]*\n)+?)\s*\]",
                  lambda match: "[" + " ".join(
                      part.strip() for part in match.group(1).split("\n")
                      if part.strip()) + "]",
                  text)


def _share(value: float, duration: float) -> str:
    """Доля хронометража целым процентом: «60 %».

    Доля и секунды — одно и то же число, названное дважды, и оба написания
    нужны. Секундами агент считает (его мерка — длительности фраз), а доля
    названа потому, что решение заказчика про допуск сформулировано в долях:
    ориентир — одна доля, граница отказа — другая. Считается из тех же секунд,
    которые вернул `avatar_budget_targets`, — второго источника у числа нет.
    """
    if duration <= 0:
        return "0 %"
    return f"{round(100.0 * float(value) / float(duration))} %"


def _locked_seconds(phrases: list[dict]) -> float:
    """Секунды фраз, которые ролик обязан говорить лицом.

    Роли `hook` и `cta` уходят с ведущей всегда (`D30_avatar_roles`), то есть
    расходуются до первого свободного решения агента. Сумму знает код, а агент
    её не видел: роли напечатаны у каждой фразы порознь, итог не подводился.
    На боевом ролике эти роли забирали 81 % цели, и агент планировал так, будто
    весь бюджет в его распоряжении.
    """
    from reels_factory.hf_render import SPEAKING_ROLES

    return sum(float(p["end"]) - float(p["start"]) for p in phrases
               if p.get("role") in SPEAKING_ROLES)


def _faceless_phrase_floor(phrases: list[dict]) -> int:
    """Сколько фраз подряд набирают самую короткую сцену без ведущей.

    Пол сцены без ведущей — `MIN_FULLSCREEN_S` (`D31_faceless_scenes`), и
    сказан он секундами. На быстрой речи перевод этих секунд во фразы —
    отдельное действие, и агент на нём промахивался: сплошной перебор круга 5
    не нашёл на материале с фразами 2,42 с ни одного годного плана из 65 536 —
    все расстановки, где сцена без ведущей взяла одну фразу, валил именно этот
    пол. Число знает код, и оно печатается в задании.

    Считаем лучший случай: сколько фраз подряд нужно, если брать их с самого
    выгодного места ролика. Роли `hook` и `cta` пропускаем — их сцене без
    ведущей не отдать (`D30_avatar_roles`), крайние фразы тоже
    (`D28_avatar_bookends`). Ноль значит «отдать нечего вовсе».
    """
    from reels_factory.hf_render import SPEAKING_ROLES

    best = 0
    inner = list(phrases[1:-1]) if len(phrases or []) > 2 else []
    for start in range(len(inner)):
        if inner[start].get("role") in SPEAKING_ROLES:
            continue
        total = 0.0
        for step, phrase in enumerate(inner[start:], start=1):
            if phrase.get("role") in SPEAKING_ROLES:
                break
            total += float(phrase["end"]) - float(phrase["start"])
            if total > MAX_FACE_ABSENCE_S:
                break
            if total >= MIN_FULLSCREEN_S:
                best = step if not best else min(best, step)
                break
    return best


#: Потолок длины одной сцены без ведущей: раскадровку раньше всех гейтов
#: отбивает раскладка (`MAX_STATIC_SPAN`), а `MAX_FACE_ABSENCE_S` меряет
#: промежуток без лица целиком — в него влезает несколько сцен.
_BLIND_ROOF = min(MAX_FACE_ABSENCE_S, MAX_STATIC_SPAN)


def _faceless_candidates(phrases: list[dict]) -> list[list[dict]]:
    """Куски ролика, которые можно отдать вставке, не ломая ни одного гейта.

    Собираются жадно и по тем же меркам, которыми судят план: подряд идущие
    фразы без ролей `hook` и `cta` (`D30_avatar_roles`), сцена не короче
    `MIN_FULLSCREEN_S` (`D31_faceless_scenes`) и не длиннее `_BLIND_ROOF`,
    между двумя такими сценами остаётся хотя бы одна фраза с ведущей, а
    крайние фразы ролика не трогаются вовсе (`D28_avatar_bookends`).

    Потолок здесь — длина СЦЕНЫ, а не промежутка без лица: `MAX_FACE_ABSENCE_S`
    меряет промежуток, в который влезает несколько сцен, а одну сцену раньше
    всех гейтов отбивает раскладка по `MAX_STATIC_SPAN`. Считая по десяти
    секундам, пример звал агента в сцену на девять — и такой план срывался ещё
    до первой проверки.

    Нужны они одному месту — счёту-примеру в задании: показать арифметику на
    настоящих номерах фраз этого ролика дешевле, чем объяснять её словами
    («Multishot examples work with thinking», claude-prompting-best-practices).
    Планом это не является: сцены выбирает агент.
    """
    from reels_factory.hf_render import SPEAKING_ROLES

    def _length(items: list[dict]) -> float:
        return sum(float(p["end"]) - float(p["start"]) for p in items)

    found: list[list[dict]] = []
    current: list[dict] = []
    # Крайние фразы ролика не трогаем: открытие и финал ведёт лицо.
    queue = list(phrases[1:-1])
    while queue:
        phrase = queue.pop(0)
        length = float(phrase["end"]) - float(phrase["start"])
        if phrase.get("role") in SPEAKING_ROLES or length > _BLIND_ROOF:
            current = []
            continue
        if _length(current) + length > _BLIND_ROOF:
            # Сцена набрала свой предел — закрываем её и оставляем следующую
            # фразу ведущей.
            current = []
        current.append(phrase)
        room = queue and _length(current) + (
            float(queue[0]["end"]) - float(queue[0]["start"])
        ) <= _BLIND_ROOF and queue[0].get("role") not in SPEAKING_ROLES
        if _length(current) >= MIN_FULLSCREEN_S and not room:
            found.append(current)
            current = []
            # Следующая фраза остаётся ведущей: две сцены без лица подряд
            # сливаются в один кусок, и его меряет `D32_face_absence`.
            if queue:
                queue.pop(0)
    return found


def _budget_example(phrases: list[dict], *, duration: float, target: float,
                    ceiling: float) -> str:
    """Счёт бюджета, показанный на фразах этого ролика.

    Ревизия круга 4 замерила, что арифметика агента верна, а промахивается он
    на том, что план меряется целыми сценами: между соседними раскладами
    лежит целая сцена, и точное попадание в цель бывает недостижимо. Поэтому
    пример показывает не результат, а сам счёт — и обе его стороны: расклад,
    который потолок не пропускает, и расклад, который проходит. Пара
    «слабый/сильный» — их приём (faceless-explainer/references/story-design.md,
    Strong/Weak), и канон Sonnet 5 разрешает отрицательный пример только парой
    к положительному.

    Пусто, когда показать нечего: на ролике, где отдать вставке нечего или где
    хватает одной сцены, пример учил бы не тому.
    """
    picks = _faceless_candidates(phrases)
    need = duration - target
    if len(picks) < 2 or need <= 0:
        return ""
    taken: list[list[dict]] = []
    given = 0.0
    for scene in picks:
        if given >= need:
            break
        taken.append(scene)
        given += sum(float(p["end"]) - float(p["start"]) for p in scene)
    if given < need or len(taken) < 2:
        return ""

    def _named(scene: list[dict]) -> str:
        first, last = scene[0]["id"], scene[-1]["id"]
        return f"{first}" if first == last else f"{first}–{last}"

    def _sum(scenes: list[list[dict]]) -> float:
        return sum(float(p["end"]) - float(p["start"])
                   for scene in scenes for p in scene)

    one = _sum(taken[:1])
    weak = ""
    if duration - one > ceiling:
        weak = (f"Отдал вставке одну сцену на фразах {_named(taken[0])} — это "
                f"{seconds(one)}. С ведущей остаётся "
                f"{seconds(duration - one)} при границе {seconds(ceiling)}: "
                "план вернётся на пересдачу.\n")
    parts = " + ".join(number(_sum([scene])) for scene in taken)
    strong = (
        "Отдал вставке сцены на фразах "
        + ", ".join(_named(scene) for scene in taken)
        + f" — это {parts} = {seconds(given)}. С ведущей остаётся "
        f"{seconds(duration - given)} при цели {seconds(target)}: план "
        "проходит.")
    return f"\n\n<example>\n{weak}{strong}\n</example>"


def write_brief(rdir, *, scenario: dict, face: dict | None, duration: float,
                clips: list[dict] | None = None, language: str = "ru",
                retry_reason: str | None = None,
                phrases: list[dict] | None = None,
                overlay_passports: str = "",
                wishes: dict | None = None,
                avatar_ordered: bool = True,
                islands: dict | None = None) -> Path:
    """Записать BRIEF.md рядом с материалом. Возвращает путь.

    `avatar_ordered=False` — план до заказа аватара (работа 9): клипов ещё
    нет, дыры не навязаны, агент сам решает `avatarNeeded`, и по его решению
    острова закажут.

    `islands` — настройки нарезки островов того профиля, которым будут
    заказывать (`avatar_islands_settings`). Из них берутся числа, по которым
    заказ выходит длиннее показа: ручка с каждого края куска и минимальный
    кусок заказа. Без профиля берутся умолчания — они же и стоят у всех, кто
    островов не настраивал.

    `wishes` — то, что заказчик назвал сам. Шага «пожелания» у нас не было
    вовсе: агент выводил всё из материала, и указать ему «ролик про этот сайт,
    в таком-то тоне» было негде. Пропущенный шаг ничего не ломает — поля без
    ответа агент выводит, как выводил.
    """
    rdir = Path(rdir)
    rdir.mkdir(parents=True, exist_ok=True)

    blocks = "\n".join(_scenario_block(b) for b in scenario.get("blocks") or [])
    blocks = blocks or "Сценарий не передан."

    phrases = phrases or []
    faceless = (set(faceless_phrases(phrases, clips or [], duration))
                if avatar_ordered else set())
    phrases_block = "\n".join(_phrase_line(p, faceless) for p in phrases) or (
        "Фразы не размечены.")
    last_phrase = (phrases or [{"id": 0}])[-1]["id"]

    # Настройки той нарезки островов, которой будут заказывать: заказ выходит
    # длиннее показа ровно на эти числа (`_request_timing`, avatar_islands.py),
    # и агенту их называют, чтобы цель по бюджету он ставил с тем же запасом,
    # что и код.
    island = avatar_islands_settings({"avatar_islands": islands or {}})
    handle = seconds(island["handle_seconds"])
    least = seconds(island["min_request_seconds"])
    longest = seconds(island["max_shot_seconds"])
    # Потолок гейта и цель — разные числа, и агенту называются оба. Потолок
    # судит секунды ЗАКАЗА (`_avatar_order_seconds` в hf_render.py), а к
    # заказу код прикладывает по ручке с каждого края каждого куска. Целясь в
    # сам потолок сложением фраз, агент промахивался ровно на эти ручки.
    #
    # Все числа бюджета считает `avatar_budget_targets` — одна функция на
    # задание и на гейт бюджета (D29 читает её же). Пока их считали двое, отказ
    # гейта называл агенту не то число, в которое его послали целиться
    # заданием, и пересдача сгорала на нашей арифметике.
    budget = avatar_budget_targets(duration, island)
    pieces = budget["pieces"]
    # Чисел четыре, и агенту называются все, но разными словами. `ceiling` —
    # ориентир доли ведущей; `hard_ceiling` — граница, выше которой план и
    # правда заворачивают (`D29_avatar_budget`); `target` — тот же ориентир
    # минус ручки заказа, то есть число, в которое агент целится СВОИМ счётом
    # (сложением длительностей фраз, где ручек нет); `hard_target` — та же
    # граница в том же его счёте.
    #
    # Последнее нужно сверке в конце задания. Гейт судит секунды ЗАКАЗА, а агент
    # складывает длительности фраз, и пункт сверки, названный секундами заказа,
    # обещал бы проход плану, который заворачивают, — ровно на ручки. Считает
    # все четыре одна функция, `avatar_budget_targets`: два вычисления одной
    # границы разошлись бы, и задание спорило бы с причиной пересдачи.
    ceiling = budget["ceiling_seconds"]
    hard_ceiling = budget["hard_ceiling_seconds"]
    target = budget["target_seconds"]
    hard_target = budget["hard_target_seconds"]
    # То же требование, повёрнутое в действие: сколько секунд ролика придётся
    # отдать вставке и схеме, чтобы уложиться в цель. «Не выходи за потолок» —
    # не действие, а «набери столько-то секунд без ведущей» — действие, и их
    # канон требует именно второго («Tell Claude what to do instead of what not
    # to do», claude-prompting-best-practices).
    #
    # Чисел тут тоже два, и по той же причине, что и в бюджете: `give` набирает
    # цель, `give_least` — границу. Прежде «не меньше» стояло у числа цели, и
    # это спорило с допуском, объявленным абзацем выше: план между целью и
    # границей задание объявляло годным и тут же требовало отдать больше.
    give = max(0.0, duration - target)
    give_least = max(0.0, duration - hard_target)

    if not avatar_ordered:
        # Бюджет ведущей называем готовыми секундами: длину ролика агент видит
        # только во frontmatter, а сцены меряет сложением длительностей фраз.
        # Доля заставляла его пересчитывать проценты во фразы, и прогоны 9 и 10
        # на этой арифметике ошибались. Доля при этом названа рядом со
        # секундами: решение заказчика про допуск сформулировано долями —
        # ориентир одна, граница отказа другая, — и агент обязан видеть, что
        # чисел два и они значат разное. Оба считает `avatar_budget_targets` из
        # длины ролика и настроек островов.
        #
        # Цель и граница разведены глаголами: «целься» и «заворачивают». Sonnet
        # читает буквально и не обобщает одно указание на другое
        # (prompting-claude-sonnet-5), поэтому одно число он принял бы за
        # единственно допустимое и жертвовал бы монтажом ради цифры. Оговорка
        # «между ними план годен» обязательна — она и есть допуск.
        #
        # Сколько сцен без ведущей нужно, чтобы набрать эти секунды: каждая
        # живёт от пола сцены без ведущей до предела без лица. Вилка названа
        # потому, что мерка агента — целая сцена, а не секунда. На ролике, где
        # отдавать нечего (цель длиннее самого ролика), абзаца нет вовсе:
        # «отдай не меньше 0 с» — не требование.
        least_scenes = math.ceil(give / MAX_FACE_ABSENCE_S) if give else 0
        most_scenes = int(give // MIN_FULLSCREEN_S) if give else 0
        # Сколько фраз подряд набирают самую короткую сцену без ведущей на
        # ЭТОМ материале. На быстрой речи (фразы по 2,4 с) одной фразы не
        # хватает: сплошной перебор круга 5 не нашёл на ней ни одного годного
        # плана из 65 536 — все валил пол сцены без ведущей. Число агенту
        # называем прямо: правило «сцена не короче 3 с» он читал, а перевести
        # его в фразы этого ролика — отдельное действие, и на нём он промахивался.
        floor_note = ""
        floor_phrases = _faceless_phrase_floor(phrases)
        if floor_phrases >= 2:
            floor_note = (
                f" Фразы этого ролика короткие: одной фразы на такую сцену не "
                f"хватает — бери не меньше {floor_phrases} подряд, иначе сцена "
                f"не наберёт {seconds(MIN_FULLSCREEN_S)} "
                "(`D31_faceless_scenes`).")
        give_block = (
            "**То же требование действием: вставке и схеме отдай не меньше "
            f"{seconds(give_least)}, а целься в {seconds(give)}.** Это от "
            f"{least_scenes} до {most_scenes} сцен с "
            "`avatarNeeded: false`, каждая длиной от "
            f"{seconds(MIN_FULLSCREEN_S)} до {seconds(_BLIND_ROOF)}, и "
            "между двумя такими сценами стоит сцена с ведущей."
            + floor_note
            + " Реши это разом, до того как распишешь сцены: сколько кусков "
            "ролика идут без лица и где они стоят — одно решение на весь "
            "ролик.\n\n"
            if most_scenes >= 1 else "")
        locked = _locked_seconds(phrases)
        gaps_block = (
            "Аватар ещё **не заказан**: ведущую снимут у HeyGen ровно по "
            "твоему плану. Поле `avatarNeeded` ставь каждой сцене плана, а не "
            "только тем, где ведущая нужна: `true` — ведущую на эти секунды "
            'закажут, `false` — сцена идёт с `presenter: "none"`, и кадр '
            "держит вставка или схема. Этим полем ты называешь, за какие "
            "секунды платит заказчик, и вывести его за тебя некому: план, где "
            "хоть у одной сцены поля нет, вернётся к тебе на пересдачу с "
            "именем этой сцены (`D33_avatar_decisions`).\n\n"
            "Секунда ведущей — это главные деньги ролика, и чисел про них "
            "два: цель и граница.\n\n"
            f"**Цель — {seconds(target)} ведущей из {seconds(duration)} "
            "ролика.** Целься в неё так: складывай длительности фраз тех сцен, "
            "где ставишь `avatarNeeded: true`. Ориентир по ролику — "
            f"{_share(ceiling, duration)} хронометража, а в твоём счёте нет "
            "ручек, которые код докупает по краям кусков (числа ниже), "
            f"поэтому цель на {seconds(ceiling - target)} ниже ориентира. Это "
            "то, куда вести план, а не линия отказа.\n\n"
            f"**Граница — {seconds(hard_ceiling)}, это "
            f"{_share(hard_ceiling, duration)} хронометража.** Выше неё план "
            "заворачивают на пересдачу (`D29_avatar_budget`): счёт идёт по "
            "заказу, а не по показу — внутри купленного куска платятся все его "
            "секунды, даже закрытые непрозрачной вставкой, — и в заказ уходят "
            f"сцены с `avatarNeeded: true`. В твоём счёте, где ручек нет, эта "
            f"граница — {seconds(hard_target)}: сложенные длительности фраз "
            "сцен с ведущей выше этого числа не поднимай. "
            "Между целью и границей план годен, "
            "и переделывать его ради круглого числа не нужно: твоя мерка — "
            "целая сцена, полсцены вставке не отдашь, и попасть в цель ровно "
            "удаётся не всегда.\n\n"
            + give_block
            + "Фразы ролей `hook` и `cta` идут с ведущей всегда "
            "(`D30_avatar_roles`), и в этом ролике они забирают "
            f"{seconds(locked)} из цели. Свободно ты распоряжаешься "
            f"{seconds(max(0.0, duration - locked))} — отданное вставке "
            "набирается только из них.\n\n"
            "Вышло выше границы — отдай вставке самую длинную сцену середины, "
            "среди фраз которой нет ролей `hook` и `cta`: одна такая сцена "
            "снимает со счёта всю свою длину."
            # Слабую половину примера судим границей В СЧЁТЕ АГЕНТА: пример
            # складывает длительности фраз, и сравнивать эту сумму с секундами
            # заказа значило бы показывать арифметику, которой агент повторить
            # не может.
            + _budget_example(phrases, duration=duration, target=target,
                              ceiling=hard_target)
            + "\n\nЗаказ выходит длиннее показа: с каждого края куска код "
            f"докупает по {handle}, а кусок короче минимального куска заказа "
            f"({least}) дорастает до {least} за счёт соседнего звука — и "
            f"доплаченное в ролик не попадает. Кусок длиннее {longest} код "
            "режет на два заказа сам, и у каждого свои края. Кусков в ролике "
            f"такой длины выходит около {pieces}: лицо не пропадает дольше "
            f"{seconds(MAX_FACE_ABSENCE_S)} подряд, значит сцены без ведущей "
            "разделены сценами с ведущей. Поэтому сцены с ведущей ставь "
            "подряд: один длинный кусок дешевле трёх коротких.\n\n"
            "У каждой сцены с `insert` назови запас — `fallback`, `overlay` "
            "или `icon`: сток отвечает не всегда, а на сцене с "
            "`avatarNeeded: false` закрыть кадр без вставки больше нечем — "
            "ведущей в этих секундах не будет. Условие «где ведущей нет» ты "
            "проверить не можешь: ведущая в кадре — исход заказа и сборки, а "
            "не твоя пометка, поэтому правило висит на самой вставке и "
            "считается счётом. Сцене со схемой запасная не нужна: схему "
            "рисует код, и она в кадре уже стоит.")
    elif faceless:
        gaps_block = (
            "На эти фразы аватар не заказан — ведущей в кадре нет физически:\n"
            + "\n".join(f"- фраза `{pid}`" for pid in sorted(faceless))
            + '\n\nСцены на этих фразах стоят с `presenter: "none"` — ведущей '
              "там нет, кадр держит вставка. У каждой сцены с `insert` назови "
              "запас — `fallback`, `overlay` или `icon`: сток отвечает не "
              "всегда, серия живёт целиком, и на этих фразах закрыть кадр без "
              "вставки больше нечем — ведущей в этих секундах не существует. "
              "Правило висит на самой вставке, а не на дыре заказа: считать "
              "сцены со вставкой ты можешь сам, а исход сборки — нет. Сцене "
              "со схемой запасная не нужна: схему рисует код, и она в кадре "
              "уже стоит.\n\n"
              "Фразы с пометкой «без ведущей» держи в отдельных сценах: "
              "сцена, где такая фраза стоит рядом с обычной, теряет "
              "оплаченные секунды ведущей.")
    else:
        gaps_block = "Ведущая в кадре весь ролик."

    # Пол длительности под каждую форму. Число не наше — это время, за которое
    # блок досказывает свою анимацию; сцена короче показывает его
    # недорисованным, и код такую схему снимает молча. Прогон 38 встал ровно
    # на этом: `steps` из трёх узлов встал на сцену 2,5 с, схема снялась, и
    # кадр остался пустым. Считается из `hf_schema.min_seconds`, чтобы число в
    # задании не разошлось с кодом. Нижняя граница берётся по минимальному
    # числу элементов формы: столько же и меряет код по факту.
    def _floor(form: str, count: int) -> str:
        return seconds(min_seconds(form, count))

    form_floors = (
        f'`metric` — {_floor("metric", 1)}; '
        f'`items` — {_floor("items", 3)}; '
        f'`pairs` — {_floor("pairs", 2)}; '
        f'`steps` — {_floor("steps", 2)} на два узла и '
        f'{_floor("steps", 3)} на три; '
        f'`brand` — {_floor("brand", 1)}')
    # Значки перечисления — закрытый список из кода: агент выбирает из него, а
    # не придумывает имя, иначе карточка осталась бы без рисунка.
    icon_names = ", ".join(f"`{name}`" for name in ICONS)
    wishes_block = _wishes_block(wishes)
    # Что лежит в `public/` на этом шаге. До заказа папка пуста: клипы и звук
    # кладёт `prepare()` уже в сборке, после того как HeyGen снимет ведущую по
    # этому плану. Обещание готового материала стоило сессии ходов — агент шёл
    # искать файлы, которых на диске нет; тем же текстом открывается и первый
    # ход сессии (`MATERIAL_LATER` в hf_agent.py), и спорить с ним заданию
    # нельзя.
    clips_line = f"- клипы с ведущей, {OUT_W}×{OUT_H}, {FPS} кадров/с"
    voice_lines = ("- `voice.wav` — единственная аудиодорожка ролика, источник "
                   "истины по времени\n"
                   "- `words.json` — пословные тайминги, ими пользуется код")
    if avatar_ordered:
        material_block = (f"## Материал (лежит в `public/`)\n\n"
                          f"{clips_line}\n{voice_lines}")
    else:
        material_block = (
            "## Материал (появится в `public/`)\n\n"
            "Папка `public/` пока пуста, и это нормально: ведущую снимут у "
            "HeyGen ровно по твоему плану, а звук и клипы код положит туда "
            "после заказа. Планируй по списку фраз выше — их номера, роли и "
            "длительности и есть весь материал этого шага.\n\n"
            "После заказа в `public/` лягут:\n\n"
            f"{clips_line}, ровно на те сцены, где ты поставил "
            "`avatarNeeded: true`\n"
            f"{voice_lines}")
    # Пол числа сцен считается по длине ролика (`min_scenes`) и о фразах не
    # знает, а сцена называет номера фраз: на трёх фразах шести сцен не
    # собрать вовсе, и требование выходило невыполнимым.
    low = min_scenes(duration)
    if phrases:
        low = max(1, min(low, len(phrases)))
    # Доля ведущей, выше которой план заворачивает `D29_avatar_budget`. Образец
    # держится под ней: он сильнее правила, стоящего рядом, и образец с
    # ведущей на трёх сценах из четырёх учил ровно тому плану, из-за которого
    # жглись пересдачи.
    #
    # Доля берётся от границы В СЧЁТЕ АГЕНТА: сцены образца меряются сложением
    # длительностей фраз (`_scene_lengths`), а граница заказа тех же секунд не
    # значит — заказ добирает ручки по краям кусков. С долей от границы заказа
    # образец учил бы расстановке, которую гейт заворачивает.
    bar = hard_target / duration if duration > 0 else 1.0
    sample_plan = _sample_plan(phrases, faceless, duration=duration, bar=bar,
                               avatar_ordered=avatar_ordered)
    # Образец короче настоящего плана, а требование «сцен не меньше N» стоит
    # рядом. Без оговорки два соседних абзаца противоречат друг другу, и
    # образец — который сильнее правила — выигрывает: прогон отдавал ровно
    # столько сцен, сколько их в образце. Оговорка нужна всегда, когда сцен в
    # образце меньше пола, а не только когда у образца есть хвост: на восьми
    # фразах хвоста нет, и четыре сцены читаются законченным планом.
    sample_scenes = sample_plan.count('"id": "s-')
    sample_scope = ("" if sample_scenes >= low else
                    f"\nСцен в образце {sample_scenes} — меньше, чем нужно "
                    "тебе: он показывает форму\nответа, а не разбивку этого "
                    "ролика на сцены.")
    # Отказа от ведущей в образце может не быть вовсе: сцена под него живёт не
    # меньше пола сцены без ведущей, а края ролика ведёт лицо (`_blind_scenes`).
    # Молча образец в этом случае учит, что `false` не ставят никогда, — а
    # именно этим решением план и экономит деньги заказчика.
    sample_refusal = (
        "" if avatar_ordered or '"avatarNeeded": false' in sample_plan else
        "\n\nВсе сцены образца идут с `avatarNeeded: true`, и отказа от "
        "ведущей он не\nпоказывает: среди показанных сцен отдать его некому. "
        "Отказ живёт в сцене,\nкоторая набирает минимум сцены без ведущей — он "
        "назван в своде правил и\nмеряется длиной сцены целиком, то есть "
        "суммой её фраз, — и при этом не\nоткрывает ролик, не закрывает его и "
        "не накрывает фраз ролей `hook` и `cta`.\nВ своём плане собирай под "
        "отказ соседние короткие фразы в одну сцену: вместе\nони этот минимум "
        "набирают.")

    # Доктрина — скиллом рядом, задание ссылается на него первым шагом.
    # `min_fullscreen` и `max_face_absence` судят план агента (`editplan.py`),
    # а до сих пор он узнавал о них только отказом; числа подставляются из
    # кода, как уже сделано с `face_gap` и `max_static`.
    write_montage_skill(rdir, positions=_positions_block(),
                        form_floors=form_floors, icon_names=icon_names,
                        series_min=SERIES_MIN, series_max=SERIES_MAX,
                        face_gap=face_gap(duration),
                        max_static=MAX_STATIC_SPAN,
                        avatar_ordered=avatar_ordered,
                        min_fullscreen=MIN_FULLSCREEN_S,
                        max_face_absence=MAX_FACE_ABSENCE_S,
                        overlay_index=_overlay_index(overlay_passports))

    # Пересдача идёт в той же папке, и раздел обязан совпадать с тем, что на
    # диске: `plan_with_agent` снимает `storyboard.json` ПЕРЕД каждым запуском
    # агента (hf_agent.py), иначе файл прошлой попытки прошёл бы проверку как
    # новый ответ. Просить «поправь свой файл» после этого не о чем — плана на
    # диске нет, и агент уходил его искать. Дословная копия прошлого ответа
    # лежит рядом в `plan.json`, её и называем.
    #
    # Ветки по `avatar_ordered` здесь нет намеренно: `storyboard.json`
    # снимается, а `plan.json` пишется на обоих шагах одним и тем же кодом, так
    # что факт на диске один. Два текста об одном факте разошлись бы при первой
    # же правке.
    retry_block = (
        f"\n## Этот план не прошёл проверку\n\n{retry_reason}\n\n"
        "Прочитай это первым и считай каждое названное замечание жёстким "
        "ограничением: ни одно из них не должно повториться в новом плане. "
        "Твой прошлый ответ лежит рядом в `plan.json` — прочитай его, исправь "
        "названные сцены и положи исправленное новым файлом "
        "`storyboard.json`: прошлый с диска снят, и дальше по работе идёт тот "
        "план, который ты положишь сейчас. `frame.md` переписывай, только "
        "если проверка назвала оформление.\n"
        if retry_reason else ""
    )

    # Граница ответственности — списком с причиной у каждой строки, а не одной
    # фразой. Форма их: «## You do NOT decide — These belong to other steps —
    # touching them collides with a sibling or breaks an upstream contract»
    # (hyperframes-core/references/frame-worker-core.md:33-43). Причина в
    # строке нужна, потому что модель обобщает именно объяснение.
    own_block = """## Что решаешь не ты

Изготовление за кодом, и у каждой строки причина — что разойдётся, реши ты это
сам:

- **Секунды и границы сцен** — код считает их по `words.json`; названные
  тобой, они разойдутся с озвучкой.
- **Геометрия кадра и разметка** — кадр код собирает слоями по твоим решениям:
  фон, вставка, ведущая, схема, плашка или значок поверх них, титр поверх
  всего.
- **Файл вставки** — по твоему запросу его ищет сток, а выбирает отдельный
  судья; твоя работа — точный запрос.
- **Субтитры** — титр печатает озвучку слово в слово и в ту же секунду."""

    # Главная ошибка — отдельным блоком и в начале, как у них: «## Core rule …
    # **The single most common failure is paraphrasing the article in order —
    # do not do that.**» (faceless-explainer/references/story-design.md:29-31).
    # У нас самая частая ошибка измерена сплошным перебором: план валится на
    # бюджете заказа, пройдя все остальные правила.
    core_rule = ("""## Главная ошибка

Ведущая заказана почти на весь ролик. Каждая сцена по отдельности выглядит
разумно — говорит человек, лицо держит внимание, — а вместе они выходят за
границу заказа, и план возвращается на пересдачу. Решай, какие куски ролика
идут без лица, ДО того как распишешь сцены, и считай бюджет по ходу, а не
после.""" if not avatar_ordered else """## Главная ошибка

Оплаченная ведущая спрятана под непрозрачной вставкой. Её клип уже куплен, и
эти секунды либо видит зритель, либо они выброшены. Вставку ставь уголком
поверх ведущей везде, где ведущая в кадре есть.""")

    # Порядок работы — нумерованными шагами: «Provide instructions as
    # sequential steps using numbered lists … when the order or completeness of
    # steps matters» (claude-prompting-best-practices). Двух шагов тут не было
    # вовсе — «посчитай бюджет» и «сверь план», — а промахивается прогон ровно
    # на них.
    skill_step = ("1. Прочитай свод правил `.claude/skills/reels-montage/"
                  "SKILL.md` — там монтажные\n   правила: положения ведущей, "
                  "вставки, формы схем, ритм.")
    scenes_step = (f"Разбей фразы озвучки на сцены встык, без пропусков. Сцен "
                   f"не меньше {low}:\n   столько нужно, чтобы ролик такой "
                   "длины не встал одним куском.")
    # Проход по запасу — отдельным шагом, а не оговоркой внутри шага про кадр.
    # Единственная строка, которая делает сцену непустой при любом исходе
    # стока, стояла последним абзацем раздела про бюджет: прогон hf-live2
    # оставил 2,7 с фона с титром, выполнив всё остальное.
    backup_step = ("Пройди сцены ещё раз: у каждой, где стоит `insert`, "
                   "назови запас —\n   `fallback`, `overlay` или `icon`. "
                   "Сцена со вставкой и без запаса выходит в\n   ролик фоном "
                   "с титром, если сток не ответил. Чем закрывают кадр и что "
                   "во что\n   ложится — в своде правил, раздел «Запас»; "
                   "паспорта плашек — в `OVERLAYS.md`\n   рядом с этим "
                   "файлом.")
    if avatar_ordered:
        steps_block = f"""{skill_step}
2. {scenes_step}
3. Каждой сцене назначь положение ведущей и то, чем занят кадр.
4. {backup_step}
5. Оформление опиши в `frame.md` — как сказано ниже.
6. Сверь план по списку «Сверка перед сдачей» в конце задания и почини
   расхождения.
7. Верни два файла в этой папке, рядом с `BRIEF.md`."""
    else:
        steps_block = f"""{skill_step}
2. Реши разом, какие куски ролика идут без ведущей и сколько их: по бюджету ниже
   вставке и схеме уходит не меньше {seconds(give_least)}, а лучше {seconds(give)}.
3. {scenes_step}
4. Каждой сцене поставь `avatarNeeded`, положение ведущей и то, чем занят кадр.
5. Сложи бюджет: длительности фраз всех сцен с `avatarNeeded: true`. Вышло выше
   {seconds(hard_target)} — переставь решения, пока не уложится.
6. {backup_step}
7. Оформление опиши в `frame.md` — как сказано ниже.
8. Сверь план по списку «Сверка перед сдачей» в конце задания и почини
   расхождения.
9. Верни два файла в этой папке, рядом с `BRIEF.md`."""

    # Сверка перед сдачей вместо прежнего «Итога» из одной фразы. Приём взят
    # дважды. У них: «## Self-check before finishing (you do NOT run the CLI) …
    # the codes in parens are `hyperframes lint`'s and what the orchestrator may
    # cite back» (frame-worker-core.md:63-80) — имена проверок называются
    # агенту заранее, потому что он всё равно увидит их в отказе. У Anthropic:
    # «Ask Claude to self-check. Append something like "Before you finish,
    # verify your answer against [test criteria]." This catches errors
    # reliably… Claude Opus 5 is the exception» — наш планировщик Sonnet 5, то
    # есть исключение не про нас.
    #
    # Пункты повторяют уже сказанные выше требования в проверяемой форме: это
    # не второе издание правила, а проход сверки, и мерка в каждом пункте — та
    # же, которой меряет гейт.
    if avatar_ordered:
        self_check = f"""Прежде чем записывать файлы, сверь план по списку.

1. Сцены идут встык и покрывают фразы `0`–{last_phrase}, сцен не меньше {low}.
2. `climax` ровно один и не в первой сцене.
3. Соседние сцены отличаются картинкой — положением ведущей либо вставкой.
4. Сцен с `insert` ровно столько же, сколько сцен с запасом — с заполненным
   `fallback`, `overlay` или `icon`: посчитай и сравни числа.
5. Оба файла на месте: `storyboard.json` и `frame.md`.

Расхождение нашлось — почини план и только потом записывай файлы."""
    else:
        self_check = f"""Прежде чем записывать файлы, сверь план по списку. Имена в скобках — имена
проверок, которыми план судят; их же ты увидишь в причине пересдачи.

1. Поле `avatarNeeded` стоит у каждой сцены плана — `true` или `false`
   (`D33_avatar_decisions`).
2. Открытие и финал ролика: `presenter` `full` или `punch` и
   `avatarNeeded: true` (`D28_avatar_bookends`).
3. Ни одна сцена с `avatarNeeded: false` не накрывает фраз ролей `hook` и
   `cta` — роли напечатаны у каждой фразы выше (`D30_avatar_roles`).
4. Сумма длительностей фраз всех сцен с `avatarNeeded: true` не выше
   {seconds(hard_target)} при цели {seconds(target)} — это граница
   {seconds(hard_ceiling)} за вычетом ручек, которые заказ докупает по краям
   кусков (`D29_avatar_budget`).
5. У каждой сцены с `avatarNeeded: false` сумма длительностей её фраз не
   меньше {seconds(MIN_FULLSCREEN_S)} (`D31_faceless_scenes`).
6. Идущие подряд сцены с `avatarNeeded: false` вместе не длиннее {seconds(MAX_FACE_ABSENCE_S)} —
   сложи длительности их фраз; между ними стоит сцена с ведущей
   (`D32_face_absence`).
7. Сцены идут встык и покрывают фразы `0`–{last_phrase}, сцен не меньше {low}.
8. `climax` ровно один и не в первой сцене; соседние сцены отличаются
   картинкой.
9. Сцен с `insert` ровно столько же, сколько сцен с запасом — с заполненным
   `fallback`, `overlay` или `icon`: посчитай и сравни числа. Сцена со
   вставкой и без запаса выйдет в ролик фоном с титром (`D25_empty_frame`).
10. Оба файла на месте: `storyboard.json` и `frame.md`.

Расхождение нашлось — почини план и только потом записывай файлы."""
    gaps_title = ("## Где ведущей нет" if avatar_ordered
                  else "## Бюджет ведущей")

    text = f"""---
workflow: {WORKFLOW}
flow: automation
storyboard: no
destination: reels
aspect: {OUT_W}x{OUT_H}
language: {language}
length: {duration:g}s
narration: yes
mode: autonomous
---

# Задание на монтаж рилса
{retry_block}
Ты режиссёр монтажа: решаешь, что показать в каждой сцене.

{own_block}

{core_rule}

## Сценарий

Речь уже записана. Это единственный источник смысла — монтаж строй от неё, а
не от порядка блоков.

{blocks}

## Фразы озвучки

Это весь материал, по которому ты планируешь: номер, роль и длительность каждой
фразы. Сцена называет номера фраз, на которые приходит; когда она начнётся и
кончится, считает код по звуку. Длину сцены прикидывай сложением длительностей
её фраз — это вся арифметика времени, которая тебе нужна.

{phrases_block}

{material_block}
{wishes_block}
## Порядок работы

{steps_block}

{gaps_title}

{gaps_block}

## Оформление: заполни `frame.md`

Формат — их канон спеки оформления: frontmatter с точными значениями, ниже
короткая проза с намерением. Читается только frontmatter, и он обязан идти
первой строкой файла:

```markdown
---
name: короткое имя стиля
colors:
  bg: "#0d0b10"
  ink: "#ffffff"
  accent: "#ff5a36"
---

Пара предложений: какое настроение держит ролик.
```

Цвета пиши в виде `#rrggbb`. Палитра работает на весь кадр: `ink` — цвет слов
титра, `accent` — плашка активного слова, этими же цветами набраны схемы,
поэтому фон выбирай так, чтобы `ink` на нём читался. Готовые палитры и пресеты
оформления — в скиле `hyperframes-creative` (`palettes/`, `frame-presets/`),
бери оттуда или собери свою. Гарнитуры уже выбраны и стоят в проекте: только
{FONTS} несут кириллицу и казахские буквы в обоих регистрах.
Поэтому во `frame.md` называй цвета и настроение, а шрифт код возьмёт свой.

## Что вернуть

Верни ровно два файла — `storyboard.json` по образцу ниже и `frame.md`: дальше
по ним работает код, и читает он только их.

Время в плане называй номерами фраз: границы сцен код считает сам по звуку, по
пословным таймингам `words.json`.

Образец ниже показывает форму ответа: поля, их значения и порядок.{sample_scope}
В твоём плане сцен не меньше {low}, и вместе они покрывают фразы
`0`–{last_phrase}.{sample_refusal}

<example>
```json
{sample_plan}
```
</example>

`phrases` — два числа: номер первой и номер последней фразы сцены (есть фразы
`0`–{last_phrase}). Сцена из одной фразы пишется как
`[{last_phrase}, {last_phrase}]`. Диапазоны идут
по возрастанию, встык, без пропусков: первая сцена начинается с фразы `0`,
последняя кончается фразой `{last_phrase}`.

`intent` — одна строка о том, чем сцена держит зрителя.

`brollContext` заполняется по-английски: `domain` — про что ролик одной фразой
(это и запасной запрос, когда точный ничего не нашёл), `anti` — чего в кадрах
быть не должно.

## Сверка перед сдачей

{self_check}
"""
    path = rdir / "BRIEF.md"
    path.write_text(text, encoding="utf-8")
    # Паспорта накладок — данные, а не правила: шестнадцать карточек занимали
    # шестую часть задания и читались агентом в каждом прогоне, хотя накладка
    # нужна ему в двух-трёх сценах из десяти. Их канон на этот счёт прямой:
    # «No context penalty for large files» — файл, который не открыли, не стоит
    # ничего (agent-skills/best-practices). Ссылка одна и ведёт из задания
    # прямо сюда: глубже одного уровня их же дока ходить не советует.
    (rdir / "OVERLAYS.md").write_text(
        "# Паспорта накладок\n\n"
        "Каждая карточка — имя блока, его слоты и родная длительность.\n"
        "Имя и ключи `text` в плане пиши дословно отсюда.\n\n"
        + (overlay_passports or "Каталог накладок недоступен — обойдись без "
                                "`overlay`.\n"),
        encoding="utf-8")
    return path
