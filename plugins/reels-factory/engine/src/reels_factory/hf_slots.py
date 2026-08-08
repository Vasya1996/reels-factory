"""Слоты блоков каталога: паспорт для агента и подстановка кодом.

Блок каталога — готовая сцена с плейсхолдерами: строки вроде «первый пункт
списка» и пустые рамки под картинку. Раньше их заполнял агент, правя HTML
блока руками, и именно оттуда на экран попадали служебные надписи: он оставлял
плашку-рубрику блока как есть, только менял в ней текст.

Теперь блок описывается паспортом (какие слоты есть, что в них сейчас лежит),
агент присылает содержимое слотов строками, а подставляет код. Незаполненный
текстовый слот **удаляется**, а не остаётся плейсхолдером — это и есть гарантия,
что «подпись первая» и «источник · плейсхолдер» не доедут до кадра.

Сам HTML мы не разбираем: элементы, их атрибуты, собственный текст и список
твинов, целящихся в элемент, отдаёт их SDK (`hf_sdk.py`), правки идут его же
операциями. Каталог — единственное, что здесь наше: какой класс что значит,
знает только он.
"""
from __future__ import annotations

import math
import re

from reels_factory.hf_sdk import Node, add_element, remove_element, set_text

#: Какую долю родной длительности блока карточка обязана ему оставить: сцена
#: собирается своим таймлайном, и обрезать её сильно короче — значит показать
#: полусобранную сцену.
MIN_BLOCK_SHARE = 0.7

#: Слоты под файл. Значение атрибута `data-slot` в блоках каталога.
MEDIA_KINDS = ("image", "video")

#: Токен слова внутри строки: `<span class="gNN-w …">`. Такие строки движок
#: блока анимирует пословно (`words(".gNN-wa", …)`), поэтому при подстановке
#: их надо не заменить текстом, а пересобрать по слову на токен.
_WORD_CLASS = re.compile(r"^g\d\d-w$")

_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)

#: След плашки-рубрики: разделитель «·». Все блоки каталога несут такую плашку
#: — «Рубрика · Глава», «Хук · 0–3 секунды», «Финал · Подписка», «источник ·
#: плейсхолдер», «art / screen · slow zoom». Именно они в прогоне 03.08 вышли
#: на экран как «продажи · база» и «вопрос первый · кому продаём?»: агент не
#: убирал рубрику, он писал в неё свой текст. Такой слот агенту не предлагается
#: и удаляется всегда — заполнять там нечего.
#:
#: Слово «плейсхолдер» само по себе сюда не входит: у содержательных слотов
#: («первый шаг — плейсхолдер» в g15) оно значит «здесь будет твой текст», а не
#: «это служебная надпись». Незаполненными они всё равно из кадра уедут.
SERVICE_MARK = re.compile(r"·")


class Slot:
    """Одно место в блоке, которое заполняет агент."""

    __slots__ = ("name", "kind", "placeholder", "index", "role", "rect")

    def __init__(self, name: str, kind: str, placeholder: str, index: int,
                 role: str | None = None, rect=None):
        self.name = name
        self.kind = kind          # "text" | "words" | "image" | "video"
        self.placeholder = placeholder
        self.index = index        # позиция элемента в разборе блока
        self.role = role
        self.rect = rect

    def __repr__(self) -> str:  # pragma: no cover — для отладки
        return f"Slot({self.name!r}, {self.kind!r}, {self.placeholder!r})"

    @property
    def service(self) -> bool:
        """Плашка-рубрика или заглушка: агенту не предлагаем, из кадра убираем."""
        return (self.kind in ("text", "words")
                and bool(SERVICE_MARK.search(self.placeholder)))

    @property
    def required(self) -> bool:
        """Слот с буквами обязателен: не заполнил — элемент уедет из кадра.

        Цифры и значки (`01`, `✓`, `↓`) — оформление сцены, а не текст: их
        удаление ломало бы раскладку, а на экране они служебной надписью не
        читаются.
        """
        return self.kind in ("text", "words") and bool(
            _LETTER.search(self.placeholder))


def _slot_class(node: Node) -> str | None:
    """Имя слота из класса вида `gNN-<имя>`. Первый класс и есть смысловой."""
    for cls in node.classes:
        match = re.match(r"^g\d\d-(.+)$", cls)
        if match:
            return match.group(1)
    return None


def _is_word_token(node: Node) -> bool:
    return node.tag == "span" and any(
        _WORD_CLASS.match(cls) for cls in node.classes)


def _parse_rect(value: str | None):
    if not value:
        return None
    parts = [p.strip() for p in value.split(",")]
    if len(parts) != 4:
        return None
    try:
        return tuple(float(p) for p in parts)
    except ValueError:
        return None


def _scene_indices(nodes: list[Node]) -> set[int]:
    """Поддерево сцены: от корня композиции вниз.

    Разбор их SDK служебных тегов (`head`, `style`, `script`) и не отдаёт, но
    корень композиции всё равно нужен: за его пределами в блоке лежат обёртки
    страницы, слотами не являющиеся.
    """
    root = next((index for index, node in enumerate(nodes)
                 if node.attrs.get("data-composition-id")), None)
    if root is None:
        return set()
    inside: set[int] = set()

    def walk(index: int) -> None:
        inside.add(index)
        for child in nodes[index].children:
            walk(child)

    walk(root)
    return inside


def _descendants(nodes: list[Node], index: int) -> set[int]:
    found = {index}
    for child in nodes[index].children:
        found |= _descendants(nodes, child)
    return found


def find_slots(nodes: list[Node]) -> list[Slot]:
    """Перечислить слоты блока в порядке появления."""
    scene = _scene_indices(nodes)
    # Съеденные поддеревья: нутро слота под файл и токены слова. Ни то, ни
    # другое отдельным слотом не считается — файл кладётся целиком, строка
    # заполняется целиком.
    consumed: set[int] = set()
    for index, node in enumerate(nodes):
        if (node.attrs.get("data-slot") or "").lower() in MEDIA_KINDS:
            consumed |= _descendants(nodes, index)

    found: list[tuple[int, str, str]] = []   # индекс, вид, что лежит сейчас
    for index, node in enumerate(nodes):
        if index not in scene:
            continue
        kind = (node.attrs.get("data-slot") or "").lower()
        if kind in MEDIA_KINDS:
            found.append((index, kind, ""))
            continue
        if index in consumed:
            continue

        children = [nodes[c] for c in node.children]
        words = [c for c in children if _is_word_token(c)]
        if words and len(words) == len(children):
            consumed |= _descendants(nodes, index) - {index}
            line = " ".join((c.text or "").strip() for c in children)
            found.append((index, "words", " ".join(line.split())))
        elif node.text and node.text.strip():
            found.append((index, "text", " ".join(node.text.split())))

    slots: list[Slot] = []
    used: dict[str, int] = {}
    for index, kind, text in found:
        node = nodes[index]
        if kind in MEDIA_KINDS:
            role = node.attrs.get("data-slot-role")
            name = role or re.sub(r"^g\d\d-|-slot$", "",
                                  node.attrs.get("id") or f"media-{index}")
            slots.append(Slot(name=name, kind=kind, placeholder="", index=index,
                              role=role,
                              rect=_parse_rect(node.attrs.get("data-slot-rect"))))
            continue
        base = _slot_class(node) or node.tag
        used[base] = used.get(base, 0) + 1
        slots.append(Slot(name=f"{base}-{used[base]}", kind=kind,
                          placeholder=text, index=index))

    # Имя без номера читается лучше; номер оставляем только там, где слотов с
    # этим классом действительно несколько.
    for slot in slots:
        base, _, tail = slot.name.rpartition("-")
        if base and tail == "1" and used.get(base) == 1:
            slot.name = base
    return slots


def min_card_seconds(native: float) -> float:
    """Сколько блоку нужно времени, чтобы его сцена собралась.

    Число одно и то же для задания и для проверки: считать долю самому агенту
    незачем, а разойтись на сотые — значит потерять сессию. Прогон 04.08 так и
    вышел: карточка 3,13 с при пороге 3,15 завернула сборку.
    """
    return math.ceil(MIN_BLOCK_SHARE * float(native) * 10) / 10


def passport(nodes: list[Node], *, name: str, title: str = "",
             description: str = "", duration: float | None = None) -> str:
    """Паспорт блока для задания: что за сцена и какие в ней слоты."""
    slots = find_slots(nodes)
    head = f"### `{name}`"
    if duration:
        head += (f" — сцена собирается {duration:g} с, "
                 f"карточка не короче {min_card_seconds(duration):g} с")
    lines = [head]
    if title:
        lines.append(f"{title}. {description}".strip())
    for slot in slots:
        if slot.service:
            continue
        if slot.kind in MEDIA_KINDS:
            lines.append(f"- `{slot.name}` — {slot.kind}"
                         + (f", роль {slot.role}" if slot.role else ""))
        else:
            mark = "" if slot.required else " (можно не заполнять)"
            lines.append(f"- `{slot.name}` — сейчас «{slot.placeholder}»{mark}")
    return "\n".join(lines)


def _service_target(nodes: list[Node], slots: list[Slot], slot: Slot) -> int:
    """Что именно убрать вместе со служебным слотом.

    Плашка-рубрика — это не только надпись: вокруг неё обёртка с полосой и
    отступом (`.gNN-tech`). Убери одну надпись — останется висеть полоска.
    Поднимаемся до самого внешнего предка, внутри которого нет ни одного
    содержательного слота, и убираем его целиком.
    """
    meaningful = {s.index for s in slots if not s.service}
    target = slot.index
    parent = nodes[target].parent
    while parent is not None:
        node = nodes[parent]
        if node.attrs.get("data-composition-id") or node.has_class("clip"):
            break
        if _descendants(nodes, parent) & meaningful:
            break
        target, parent = parent, node.parent
    return target


def _base_name(name: str) -> str:
    head, _, tail = name.rpartition("-")
    return head if head and tail.isdigit() else name


def _plain_classes(nodes: list[Node], slots: list[Slot],
                   slot: Slot) -> str | None:
    """Классы «обычного» слова строки — без акцента последнего токена.

    В блоке подсветка живёт на последнем токене (`gNN-hl` плюс вложенный
    `<i>`). Если исходная строка была одним токеном, взять её классы для всех
    слов значило бы подсветить каждое слово. Общее у всех токенов родственных
    строк и есть «обычный» набор.
    """
    sets, order = [], None
    for other in slots:
        if other.kind != "words" or _base_name(other.name) != _base_name(slot.name):
            continue
        for index in nodes[other.index].children:
            classes = nodes[index].classes
            sets.append(set(classes))
            if order is None:
                order = classes
    if not sets or order is None:
        return None
    common = set.intersection(*sets)
    kept = [cls for cls in order if cls in common]
    return " ".join(kept) if kept else None


def _element_html(nodes: list[Node], index: int) -> str:
    """Пересобрать элемент разметкой по разбору: тег, классы, атрибуты.

    Их SDK отдаёт разбор, а не исходную разметку. Текст потомков не
    восстанавливается намеренно: этим сериализуются только пустые украшения.
    """
    node = nodes[index]
    attrs = "".join(f' {k}="{v}"' for k, v in node.attrs.items()
                    if not k.startswith("data-hf"))
    classes = f' class="{" ".join(node.classes)}"' if node.classes else ""
    inner = "".join(_element_html(nodes, child) for child in node.children)
    return f"<{node.tag}{classes}{attrs}>{inner}</{node.tag}>"


def _decoration(nodes: list[Node], index: int) -> str:
    """Пустые украшения токена — полоска подсветки `<i>` и ей подобные.

    Текста в них нет по построению — это фон под словом, нарисованный стилем
    блока (`.gNN-hl i{position:absolute;inset:0;background:…}`).
    """
    return "".join(_element_html(nodes, child)
                   for child in nodes[index].children)


def _subtree_text(nodes: list[Node], index: int) -> bool:
    """Есть ли в поддереве хоть один собственный текст."""
    node = nodes[index]
    if node.text and node.text.strip():
        return True
    return any(_subtree_text(nodes, child) for child in node.children)


def _text_ops(nodes: list[Node], slot: Slot, value: str) -> list[dict]:
    """Положить строку в текстовый слот, не задев украшений.

    Их `setText` при РОВНО ОДНОМ дочернем элементе пишет текст внутрь него
    (`resolveSingleChildTextTarget`, packages/sdk/src/engine/model.ts:338-343).
    На прогоне 13 так слова легли внутрь пустой полоски зачёркивания высотой
    8 пикселей, а заглушка «первая формулировка» осталась в кадре. Ветка с
    несколькими детьми у них правильная — меняет только собственные текстовые
    узлы. Поэтому единственное пустое украшение на время правки снимается и
    возвращается следом; если в единственном ребёнке есть текст, он сам
    отдельный слот, и трогать его нельзя — тогда остаётся их поведение.
    """
    node = nodes[slot.index]
    if len(node.children) != 1 or _subtree_text(nodes, node.children[0]):
        return [set_text(node.hfid, value)]
    child = nodes[node.children[0]]
    return [remove_element(child.hfid),
            set_text(node.hfid, value),
            add_element(node.hfid, 0, _element_html(nodes, node.children[0]))]


def _word_ops(nodes: list[Node], slots: list[Slot], slot: Slot,
              text: str) -> list[dict]:
    """Пересобрать строку по слову на токен, сохранив классы блока.

    Последний токен наследует классы последнего исходного — там живёт
    подсветка, и анимация блока целится в неё.
    """
    words = text.split()
    node = nodes[slot.index]
    tokens = [nodes[c] for c in node.children]
    ops: list[dict] = [remove_element(token.hfid) for token in tokens]
    # Между токенами в исходной разметке стоят пробелы текстовыми узлами, а
    # `removeElement` убирает только элементы: они пережили бы замену и легли
    # поверх наших — в кадре прогона 04.08 вышло «ТРИ  ВОПРОСА  ПО  ПОРЯДКУ» с
    # двойными пробелами. Пустой `setText` по опустевшему контейнеру вычищает и
    # их: их же модель считает элемент без потомков текстовым листом
    # (`packages/sdk/src/engine/model.ts:373-381`).
    ops.append(set_text(node.hfid, ""))
    if not words:
        return ops

    last = tokens[-1]
    plain = _plain_classes(nodes, slots, slot) or " ".join(tokens[0].classes)
    marker = _decoration(nodes, node.children[-1])
    for position, word in enumerate(words):
        final = position == len(words) - 1
        classes = " ".join(last.classes) if final else plain
        # Пробел между словами — отступом, а не символом. Текстовый узел между
        # спанами их операция вставки положить не даёт: она принимает только
        # элемент («html parses to zero element nodes»,
        # `packages/sdk/src/engine/mutate.ts:1647-1648`). Хвостовой пробел
        # внутри токена не годится дважды: обычный браузер срезает на конце
        # inline-block, а неразрывный попадает внутрь плашки слова — у блоков
        # вроде g21 у токена свой фон и падинги, и плашка становится шире
        # слова. Отступ снаружи повторяет то, чем был исходный пробел.
        gap = "" if final else "margin-right:.25em"
        ops.append(add_element(
            node.hfid, position,
            f'<span class="{classes}" style="{gap}">'
            f'{marker if final else ""}{word}</span>'))
    return ops


#: Растровые картинки. Слот блока объявлен под видео или под изображение, но
#: подобранный файл решает сам: `media-use` под «фотография переговоров»
#: отдаёт jpg, и подставлять его тегом <video> нельзя.
_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif", ".svg")


def _media_tag(node: Node, source: str, *, start: float = 0.0,
               duration: float = 0.0, media_start: float = 0.0) -> str:
    """Тег на месте плейсхолдера: рамку слота сохраняем, пунктир — нет."""
    attrs = [f'id="{(node.attrs.get("id") or "").removesuffix("-slot")}"',
             f'class="{" ".join(node.classes)}"',
             f'src="{source}"',
             'style="object-fit:cover;border-style:solid"']
    if source.lower().split("?")[0].endswith(_IMAGE_SUFFIXES):
        return f"<img {' '.join(attrs)} alt=\"\">"
    # `class="clip"` на видео обязателен: без него клип в кадре не появляется
    # вовсе — окно на месте, внутри пусто. Их `check` говорил это шесть раз на
    # прогоне 13 пометкой «к сведению», и мы прошли мимо; их же
    # `data-attributes.md:23` советует класс на `<video>` не ставить — это
    # проверенная кадрами ошибка их доки.
    attrs[1] = f'class="{" ".join([*node.classes, "clip"])}"'
    attrs += [f'data-start="{start:.4f}"', f'data-duration="{duration:.4f}"']
    if media_start:
        attrs.append(f'data-media-start="{media_start:.4f}"')
    attrs += ["muted", "playsinline"]
    return f"<video {' '.join(attrs)}></video>"


_QUOTED_SELECTOR = re.compile(r'"([.#][^"]+)"')
_SCRIPT_BODY = re.compile(r"(<script>)(.*?)(</script>)", re.S)


def prune_timeline(html: str) -> str:
    """Убрать из таймлайна блока строки про элементы, которых уже нет.

    Незаполненный слот и плашка-рубрика уезжают из разметки, а нацеленная на
    них строка анимации остаётся и на каждом кадре пишет в консоль «GSAP target
    not found» — их `check` считает это предупреждением рантайма и показывает
    его десятками.

    Их SDK это место не закрывает, хотя и знает про твины: `animationIds`
    элемента видит только прямые вызовы `tl.<метод>(…)`. Блоки каталога почти
    всю анимацию строят через свои функции-обёртки (`fu(".g13-tech",0)`,
    `words(".g13-wa",…)`), и в разборе их нет — проверено на g13: из двадцати
    строк таймлайна SDK опознал шесть, ровно те, что вызывают `tl.to` напрямую.
    Значит `removeGsapTween` до остальных не дотягивается, и строку приходится
    убирать текстом.
    """
    head = html.split("<script>", 1)[0]
    present = set(re.findall(r'class="([^"]*)"', head))
    tokens = {token for value in present for token in value.split()}
    tokens |= set(re.findall(r'id="([^"]+)"', head))

    def alive(selector: str) -> bool:
        first = selector.split()[0].split(":")[0]
        return all(part in tokens for part in first.lstrip(".#").split("."))

    def prune(match: re.Match) -> str:
        kept = []
        for line in match.group(2).splitlines():
            found = _QUOTED_SELECTOR.findall(line)
            if found and not any(alive(selector) for selector in found):
                continue
            kept.append(line)
        return match.group(1) + "\n".join(kept) + match.group(3)

    return _SCRIPT_BODY.sub(prune, html)


def _drop(nodes: list[Node], index: int) -> list[dict]:
    """Убрать элемент. Строки таймлайна, целившиеся в него, снимает
    `prune_timeline` уже по сохранённому файлу."""
    return [remove_element(nodes[index].hfid)]


def fill_ops(nodes: list[Node], *, text: dict[str, str] | None = None,
             media: dict[str, dict] | None = None) -> list[dict]:
    """Правки, подставляющие содержимое в слоты блока.

    `text` — имя слота → строка. `media` — имя слота → `{"file": …}` и, для
    видео, `{"start": …, "duration": …}`.
    """
    text = {k: (v or "").strip() for k, v in (text or {}).items()}
    media = media or {}
    slots = find_slots(nodes)
    known = {slot.name for slot in slots if not slot.service}
    unknown = (set(text) | set(media)) - known
    if unknown:
        raise RuntimeError(
            f"в блоке нет слотов {sorted(unknown)}; есть {sorted(known)}")

    ops: list[dict] = []
    for slot in slots:
        node = nodes[slot.index]
        if slot.service:
            ops += _drop(nodes, _service_target(nodes, slots, slot))
            continue
        if slot.kind in MEDIA_KINDS:
            filled = media.get(slot.name)
            if not filled or not filled.get("file"):
                # Пустая рамка со словом «slot» — тот же плейсхолдер на экране.
                ops += _drop(nodes, slot.index)
                continue
            tag = _media_tag(node, filled["file"],
                             start=float(filled.get("start", 0.0)),
                             duration=float(filled.get("duration", 0.0)),
                             media_start=float(filled.get("media_start", 0.0)))
            ops.append(add_element(nodes[node.parent].hfid, node.index, tag))
            ops.append(remove_element(node.hfid))
            continue

        value = text.get(slot.name, "")
        if not value:
            if slot.required:
                ops += _drop(nodes, slot.index)
            continue
        if slot.kind == "words":
            ops += _word_ops(nodes, slots, slot, value)
        else:
            ops += _text_ops(nodes, slot, value)
    return ops
