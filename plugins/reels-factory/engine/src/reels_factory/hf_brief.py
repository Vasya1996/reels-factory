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
import re
from pathlib import Path

from reels_factory.config import FPS, OUT_H, OUT_W
from reels_factory.hf_gates import min_scenes
from reels_factory.hf_montage import (
    AVATAR_ON_SCREEN_MAX, SERIES_MAX, SERIES_MIN, face_gap,
)
from reels_factory.hf_montage_skill import write_montage_skill
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
    return (f'- `{phrase["id"]}` **{phrase["role"]}** {length:.1f} с — '
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


def _sample_plan(phrases: list[dict], faceless: set[int], *,
                 duration: float) -> str:
    """Образец ответа, собранный из фраз этого же ролика.

    Раньше образец был написан руками и жил своей жизнью: пять сцен вместо
    минимума, ни одного `climax`, две последние сцены с одинаковым кадром и
    плашка со слотом, которого нет в её паспорте. Их правило про примеры —
    «Mirror your actual use case closely» (claude-prompting-best-practices), а
    образец в задании сильнее любого правила рядом с ним, поэтому он собирается
    из настоящих номеров фраз и по тем же правилам, что мы требуем от агента:
    фразы встык, один `climax`, соседние сцены различимы, фразы без ведущей —
    в своей сцене.
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
    shown = groups[:4]
    scenes = []
    insert_at = next((i for i, (_, blind) in enumerate(shown) if blind), None)
    for index, (block, blind) in enumerate(shown):
        scene: dict = {"id": f"s-{index + 1:02d}",
                       "intent": "чем сцена держит зрителя",
                       "beat": "hook" if index == 0 else "point",
                       "phrases": [block[0], block[-1]],
                       "presenter": "full" if index % 2 == 0 else "punch",
                       "insert": None}
        if blind or index == insert_at:
            scene["presenter"] = "none" if blind else "pip-tr"
            scene["insert"] = {
                "shots": ["hand writing checklist in notebook",
                          "closeup fingers underlining a line"],
                "kind": "video"}
            if blind:
                scene["fallback"] = {"form": "items", "why": "набор равноправных",
                                     "items": [{"label": "кому", "icon": "человек"},
                                               {"label": "что", "icon": "документ"},
                                               {"label": "как", "icon": "поиск"}]}
        elif index == 1:
            # Схема держит кадр, ведущая остаётся нижним уголком: `none` на
            # оплаченной секунде — это выброшенные деньги, и D24 такой план
            # заворачивает.
            scene["presenter"] = "pip-br"
            scene["schema"] = {"form": "steps", "why": "порядок",
                               "nodes": ["кто", "что", "как"]}
        scenes.append(scene)
    if len(scenes) > 1:
        scenes[-1]["beat"] = "climax"
    body = json.dumps(
        {"brollContext": {
            "domain": "sales and client communication in small business",
            "anti": "factories, robots, programming code, casino"},
         "scenes": scenes},
        ensure_ascii=False, indent=1)
    body = _compact_lists(body).rstrip()
    # Срезаем закрытие списка сцен и объекта, чтобы дописать многоточие хвоста:
    # образец показывает форму ответа, а не весь ролик.
    for closing in ("}", "]"):
        body = body.rstrip().rstrip(closing)
    return (body.rstrip() + ",\n  … остальные сцены до фразы "
            f"{ids[-1]} тем же порядком\n ]\n}}")


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


def write_brief(rdir, *, scenario: dict, face: dict | None, duration: float,
                clips: list[dict] | None = None, language: str = "ru",
                retry_reason: str | None = None,
                phrases: list[dict] | None = None,
                overlay_passports: str = "",
                wishes: dict | None = None,
                avatar_ordered: bool = True) -> Path:
    """Записать BRIEF.md рядом с материалом. Возвращает путь.

    `avatar_ordered=False` — план до заказа аватара (работа 9): клипов ещё
    нет, дыры не навязаны, агент сам решает `avatarNeeded`, и по его решению
    острова закажут.

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

    if not avatar_ordered:
        gaps_block = (
            "Аватар ещё **не заказан** — его купят у HeyGen ровно по твоему "
            "плану: сцены с `avatarNeeded: true` соберутся в заказ. Внутри "
            "заказанного куска платятся все его секунды, даже под "
            "непрозрачной вставкой, поэтому ведущую держи в кадре не дольше "
            f"{AVATAR_ON_SCREEN_MAX * 100:.0f} % хронометража — это главные "
            "деньги ролика. Сцена с `avatarNeeded: false` стоит с "
            '`presenter: "none"`.')
    elif faceless:
        gaps_block = (
            "На эти фразы аватар не заказан — ведущей в кадре нет физически:\n"
            + "\n".join(f"- фраза `{pid}`" for pid in sorted(faceless))
            + "\n\nСцены, накрывающие эти фразы, обязаны стоять с `presenter: "
              '"none"`: биролл во весь кадр либо фоновая сцена.')
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
        return f"{min_seconds(form, count):.1f}".replace(".", ",")

    form_floors = (
        f'`metric` — {_floor("metric", 1)} с; '
        f'`items` — {_floor("items", 3)} с; '
        f'`pairs` — {_floor("pairs", 2)} с; '
        f'`steps` — {_floor("steps", 2)} с на два узла и '
        f'{_floor("steps", 3)} с на три; '
        f'`brand` — {_floor("brand", 1)} с')
    # Значки перечисления — закрытый список из кода: агент выбирает из него, а
    # не придумывает имя, иначе карточка осталась бы без рисунка.
    icon_names = ", ".join(f"`{name}`" for name in ICONS)
    wishes_block = _wishes_block(wishes)
    low = min_scenes(duration)
    sample_plan = _sample_plan(phrases, faceless, duration=duration)

    # Доктрина — скиллом рядом, задание ссылается на него первым шагом.
    write_montage_skill(rdir, positions=_positions_block(),
                        form_floors=form_floors, icon_names=icon_names,
                        series_min=SERIES_MIN, series_max=SERIES_MAX,
                        face_gap=face_gap(duration),
                        max_static=MAX_STATIC_SPAN)

    retry_block = (
        f"\n## Повторная сборка\n\nПрошлая версия не прошла проверку:\n\n"
        f"{retry_reason}\n\nИсправь именно это.\n"
        if retry_reason else ""
    )

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
Ты режиссёр монтажа: решаешь, что показать в каждой сцене. Изготовление за
кодом — секунды, геометрия, разметка, подбор файлов, субтитры и проверки он
считает сам.

## Порядок работы

1. Прочитай `.claude/skills/reels-montage/SKILL.md` — там монтажные правила:
   положения ведущей, вставки, формы схем, ритм.
2. Разбей фразы озвучки (список ниже) на сцены встык, без пропусков.
3. Каждой сцене назначь положение ведущей и то, чем занят кадр. Сцен не
   меньше {low}: столько нужно, чтобы ролик такой длины не встал одним куском.
4. Оформление опиши в `frame.md` — как сказано ниже.
5. Верни два файла в этой папке, рядом с `BRIEF.md`.

## Сценарий

Речь уже записана. Это единственный источник смысла: монтаж строй от неё.

{blocks}

## Фразы озвучки

Сцена называет номера фраз, на которые приходит; когда она начнётся и
кончится, считает код по звуку. Длину сцены прикидывай сложением длительностей
её фраз — это вся арифметика времени, которая тебе нужна.

{phrases_block}

## Где ведущей нет

{gaps_block}

## Материал (лежит в `public/`)

- клипы с ведущей, {OUT_W}×{OUT_H}, {FPS} кадров/с
- `voice.wav` — единственная аудиодорожка ролика, источник истины по времени
- `words.json` — пословные тайминги, ими пользуется код

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
бери оттуда или собери свою. Гарнитуры не выбирай: кириллицу и казахский в
проекте несут только {FONTS}, они уже стоят.

## Что вернуть

Два файла, и никаких других: `storyboard.json` по образцу ниже и `frame.md`.
Секунд в плане быть не должно — ни `startSec`, ни `endSec`, ни длительностей:
их считает код по звуку.

```json
{sample_plan}
```

`phrases` — номера первой и последней фразы сцены, из списка выше (есть фразы
`0`–{last_phrase}). Диапазоны идут по возрастанию, встык, без пропусков: первая
сцена начинается с фразы `0`, последняя кончается фразой `{last_phrase}`.
Фразы с пометкой «без ведущей» держи в отдельных сценах: сцена, где такая
фраза стоит рядом с обычной, теряет оплаченные секунды ведущей.

`intent` — одна строка о том, чем сцена держит зрителя.

`brollContext` заполняется по-английски: `domain` — про что ролик одной фразой
(это и запасной запрос, когда точный ничего не нашёл), `anti` — чего в кадрах
быть не должно.
{wishes_block}
## Итог

Два файла: `storyboard.json` и `frame.md`. Фразы `0`–{last_phrase} покрыты
встык, `climax` один, соседние сцены отличаются картинкой.
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
