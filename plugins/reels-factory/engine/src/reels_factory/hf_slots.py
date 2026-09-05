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

#: Виды слота, который заполняется файлом, а не строкой. `image`/`video` —
#: наши собственные блоки: там видом назван сам слот (`data-slot="video"`), и
#: тег встаёт ВМЕСТО него. `media` — контентный слот их полки: файл ложится
#: ВНУТРЬ слота, потому что так написан контракт позиции (см. `slot_contract`).
MEDIA_KINDS = ("image", "video", "media")

#: Слот, чьё содержимое их контракт ждёт `<template>`-ом в ХОСТОВОЙ странице:
#: «Callers supply content by placing inert templates anywhere in the HOST page»
#: (`catalog/registry/components/browser-device-stage/browser-device-stage.html:22-25`).
#: Наша сборка монтирует позицию сабкомпозицией и такой шаблон не пишет, а их
#: разбор внутрь обычного `<template>` намеренно не заходит
#: (`isCompositionTemplate`, `packages/parsers/src/hfIds.ts:125-132`) — узла
#: слота в снимке нет вовсе, заполнять нечего.
HOST_SLOT = "host"

#: Правило CSS: `селектор { тело }`. Разбирается ровно настолько, чтобы
#: увидеть, для какого предка автор позиции описал прямого потомка `img`/
#: `video` — это и есть его собственное объявление «сюда кладут файл».
_CSS_RULE = re.compile(r"([^{}@]+?)\{([^{}]*)\}", re.S)

#: Хвост селектора, целящегося в картинку или видео.
_CSS_MEDIA_TAIL = re.compile(r"(?:^|[\s>+~])(?:img|video)\s*(?:::?[\w-]+)?$")

#: Токены классов и id в голове селектора.
_CSS_TOKEN = re.compile(r"[.#]([A-Za-z_][\w-]*)")

#: Открывающий тег с атрибутами — тем же приёмом, каким читается корень
#: paste-примитива в `hf_compose`.
_HTML_TAG = re.compile(r'''<(\w[\w-]*)((?:"[^"]*"|'[^']*'|[^>"'])*)>''')
_ATTR_SLOT = re.compile(r'(?:^|\s)data-slot="([^"]+)"')
_ATTR_CLASS = re.compile(r'(?:^|\s)class="([^"]*)"')
_ATTR_ID = re.compile(r'(?:^|\s)id="([^"]*)"')


def slot_contract(html: str) -> dict[str, str]:
    """Слоты позиции по её собственной разметке: имя слота → чем заполняется.

    `data-slot` — единственный признак слота, который есть у фреймворка: в их
    коде и общих скиллах атрибут не упоминается вовсе, его контракт пишет
    автор позиции в шапке своего файла и в своём же CSS. Список имён
    (`"image"`/`"video"`) поэтому не годился: 29 позиций зовут свои слоты
    по-своему — `before`/`after`, `card-a`, `subject`, — и код их не видел.

    Три вида:

    - `image`/`video` — так слот назван в НАШИХ блоках `gNN-*`: имя слота и
      есть вид файла, а тег встаёт вместо самого слота.
    - `media` — контентный слот их позиции: «Replace the children of this
      element … Direct img/video children of a slot are sized to cover the
      panel» (`before-after-wipe.html:16-20`). Признак — не имя, а то, что
      автор позиции ОПИСАЛ такого потомка в своём CSS
      (`.baw-slot > video {…}`, `.tq-avatar video {…}`): описал — файл сюда
      кладут, не описал — слот заполняется переменной или скриптом позиции
      (`grid-card-assemble` — переменной `items`, `whiteboard-ink` — рисует
      скрипт), и файлу там не место.
    - `host` (`HOST_SLOT`) — тот же контентный слот, но объявленный
      `<template>`: его содержимое их контракт ждёт из хостовой страницы, и
      нашей сборкой он недостижим.
    """
    hosts: set[str] = set()
    for selector, _ in _CSS_RULE.findall(html):
        selector = selector.strip()
        if not selector or selector.startswith("@"):
            continue
        for part in selector.split(","):
            part = part.strip()
            tail = _CSS_MEDIA_TAIL.search(part)
            if tail:
                hosts |= set(_CSS_TOKEN.findall(part[:tail.start()]))
    found: dict[str, str] = {}
    for tag, attrs in _HTML_TAG.findall(html):
        slot = _ATTR_SLOT.search(attrs)
        if not slot:
            continue
        name = slot.group(1)
        if name.lower() in ("image", "video"):
            found[name] = name.lower()
            continue
        if tag.lower() == "template":
            found[name] = HOST_SLOT
            continue
        classes = _ATTR_CLASS.search(attrs)
        ident = _ATTR_ID.search(attrs)
        tokens = set((classes.group(1).split() if classes else [])
                     + ([ident.group(1)] if ident else []))
        if tokens & hosts:
            found[name] = "media"
    return found

#: Токен слова внутри строки: `<span class="gNN-w …">`. Такие строки движок
#: блока анимирует пословно (`words(".gNN-wa", …)`), поэтому при подстановке
#: их надо не заменить текстом, а пересобрать по слову на токен.
_WORD_CLASS = re.compile(r"^g\d\d-w$")

_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)

#: След плашки-рубрики: разделитель «·». Наши собственные блоки несут такую
#: плашку — «Рубрика · Глава», «Хук · 0–3 секунды», «Финал · Подписка»,
#: «источник · плейсхолдер», «art / screen · slow zoom». Именно они в прогоне
#: 03.08 вышли на экран как «продажи · база» и «вопрос первый · кому продаём?»:
#: агент не убирал рубрику, он писал в неё свой текст. Такой слот агенту не
#: предлагается и удаляется всегда — заполнять там нечего.
#:
#: Слово «плейсхолдер» само по себе сюда не входит: у содержательных слотов
#: («первый шаг — плейсхолдер» в g15) оно значит «здесь будет твой текст», а не
#: «это служебная надпись». Незаполненными они всё равно из кадра уедут.
SERVICE_MARK = re.compile(r"·")

#: Разметка нашего собственного блока: класс с префиксом `gNN-` (`g01-lbl`,
#: `g14-artlabel`). Только про них и написано правило `SERVICE_MARK`: в
#: перенесённых позициях «·» — обычный разделитель содержания, а не след
#: плашки-рубрики. У нижних плашек (`lt-role`, «Host · Neuroscientist»,
#: 9 позиций из 10) правило съедало вторую строку самой плашки: блок терял
#: `#lt-role`, его же скрипт получал на него `null` и на каждом кадре писал в
#: консоль «GSAP target null not found» (прогон scratchpad/catalog-sweep,
#: 05.09.2026; кадр — плашка с одним словом вместо имени и роли). То же «·»
#: стоит содержанием у `ch-mode` («SP · 16:9»), `reddit-post` («u/… · 3h») и
#: `ssc-strip-text`. Проверено грепом по каталогу: все 22 настоящие
#: плашки-рубрики лежат на классах `gNN-lbl` / `gNN-attr` / `gNN-artlabel`.
_OWN_BLOCK_CLASS = re.compile(r"^g\d\d-")


class Slot:
    """Одно место в блоке, которое заполняет агент."""

    __slots__ = ("name", "kind", "placeholder", "index", "role", "rect",
                 "decor", "own")

    def __init__(self, name: str, kind: str, placeholder: str, index: int,
                 role: str | None = None, rect=None, decor: bool = False,
                 own: bool = False):
        self.name = name
        self.kind = kind          # "text" | "words" | "image" | "video"
        self.placeholder = placeholder
        self.index = index        # позиция элемента в разборе блока
        self.role = role
        self.rect = rect
        self.decor = decor        # текст нарисован картой, а не плейсхолдер
        self.own = own            # разметка нашего блока (класс `gNN-…`)

    def __repr__(self) -> str:  # pragma: no cover — для отладки
        return f"Slot({self.name!r}, {self.kind!r}, {self.placeholder!r})"

    @property
    def service(self) -> bool:
        """Плашка-рубрика или заглушка: агенту не предлагаем, из кадра убираем.

        Только в нашей собственной разметке (`own`): «·» — след нашей
        плашки-рубрики, а в перенесённой позиции это обычный разделитель
        содержания (`_OWN_BLOCK_CLASS`, там же чем это измерено).
        """
        return (self.own and self.kind in ("text", "words")
                and bool(SERVICE_MARK.search(self.placeholder)))

    @property
    def required(self) -> bool:
        """Слот с буквами обязателен: не заполнил — элемент уедет из кадра.

        Цифры и значки (`01`, `✓`, `↓`) — оформление сцены, а не текст: их
        удаление ломало бы раскладку, а на экране они служебной надписью не
        читаются. Та же логика распространяется на текст из карточки
        (`decor=True`): таймстемп «now» или SVG-глиф «HF» у
        `v-macos-notification` тоже оформление, просто из букв, а не цифр —
        карточка (`reels.decor_texts`) знает об этом за нас (отчёт руки B2.5:
        настоящий SDK-мост удалял их как незаполненную заглушку).
        """
        return (self.kind in ("text", "words") and not self.decor
                and bool(_LETTER.search(self.placeholder)))


def _slot_class(node: Node) -> str | None:
    """Имя слота из класса элемента.

    Наши блоки несут классы `gNN-<имя>`, их накладки — короткий префикс
    (`lt-name`, `nt-headline`) либо семантическое имя целиком
    (`display-name`, `notification-title` в соц-карточках). Берём смысловую
    часть — паспорт с именем «div-3» агенту не годится.
    """
    for cls in node.classes:
        match = re.match(r"^(?:g\d\d|[a-z]{2})-(.+)$", cls)
        if match:
            return match.group(1)
    for cls in node.classes:
        if cls not in ("clip",) and re.match(r"^[a-z][a-z0-9-]+$", cls):
            return cls
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


def slot_kind(node: Node, contract: dict[str, str] | None) -> str | None:
    """Вид слота под файл у этого узла — или `None`, если узел не такой слот.

    `contract` — разбор разметки позиции (`slot_contract`). Без него остаётся
    прежнее правило по имени: `data-slot="image"`/`"video"` наших собственных
    блоков. Позиция полки зовёт слот своим именем (`before`, `card-a`,
    `subject`), и узнать его можно только по контракту её файла.
    """
    name = node.attrs.get("data-slot")
    if not name:
        return None
    if contract is None:
        kind = name.lower()
        return kind if kind in ("image", "video") else None
    kind = contract.get(name)
    return kind if kind in MEDIA_KINDS else None


def find_slots(nodes: list[Node],
               decor: set[str] | frozenset[str] | None = None,
               contract: dict[str, str] | None = None) -> list[Slot]:
    """Перечислить слоты блока в порядке появления.

    `contract` — `slot_contract` разметки позиции: чем заполняется каждый её
    `data-slot`. Без него слотом под файл считаются только `image`/`video`
    наших блоков, и 29 позиций полки со своими именами слотов остаются с
    пустым макетом в кадре.

    `decor` — видимые тексты карточки (`reels.decor_texts`, `hf_catalog.py`):
    надписи, нарисованные в блоке, а не оставленные агенту заполнить. Слот, чей
    текст совпал с одной из них, помечается `Slot.decor` и перестаёт быть
    обязательным — без этого он неотличим от незаполненной заглушки и уезжает
    из кадра.
    """
    # Сверяем нормализованное с нормализованным: текст узла ниже сводится к
    # одному пробелу между словами, а в карточке он записан как в разметке —
    # у `v-code-snippet-apple-terminal-basic` приглашение лежит там с хвостовым
    # пробелом («user@Mac ~ % »), и без этой нормализации оно не совпадало
    # само с собой.
    decor = {" ".join(str(text).split()) for text in (decor or ())}
    scene = _scene_indices(nodes)
    # Съеденные поддеревья: нутро слота под файл и токены слова. Ни то, ни
    # другое отдельным слотом не считается — файл кладётся целиком, строка
    # заполняется целиком.
    consumed: set[int] = set()
    for index, node in enumerate(nodes):
        if slot_kind(node, contract):
            consumed |= _descendants(nodes, index)

    found: list[tuple[int, str, str]] = []   # индекс, вид, что лежит сейчас
    for index, node in enumerate(nodes):
        if index not in scene:
            continue
        kind = slot_kind(node, contract)
        if kind:
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
            declared = str(node.attrs.get("data-slot") or "")
            # Слот полки зовут его собственным именем: агенту в паспорте
            # видно `before`/`card-a`, а не `media-7`. У наших блоков именем
            # слота назван вид файла, и имя по-прежнему берётся у `id`.
            name = (declared if kind == "media"
                    else role or re.sub(r"^g\d\d-|-slot$", "",
                                        node.attrs.get("id") or f"media-{index}"))
            slots.append(Slot(name=name, kind=kind, placeholder="", index=index,
                              role=role,
                              rect=_parse_rect(node.attrs.get("data-slot-rect"))))
            continue
        base = _slot_class(node) or node.tag
        used[base] = used.get(base, 0) + 1
        slots.append(Slot(name=f"{base}-{used[base]}", kind=kind,
                          placeholder=text, index=index,
                          decor=text in decor,
                          own=any(_OWN_BLOCK_CLASS.match(cls)
                                  for cls in node.classes)))

    # Имя без номера читается лучше; номер оставляем только там, где слотов с
    # этим классом действительно несколько.
    for slot in slots:
        base, _, tail = slot.name.rpartition("-")
        if base and tail == "1" and used.get(base) == 1:
            slot.name = base
    return slots


def text_slot_names(nodes: list[Node],
                    decor: set[str] | frozenset[str] | None = None,
                    contract: dict[str, str] | None = None) -> list[str]:
    """Имена слотов позиции, которые заполняет агент, в порядке разметки.

    Одно определение слота на всех: карточка каталога печатает этот список
    индексу (`hf_catalog.catalog_cards`), сборка раскладывает по нему `words`
    плана (`hf_compose`), а тест сверяет карточку с разметкой. Пока определений
    было два, карточка `v-code-diff` держала видимые демо-строки вместо имён, и
    любой план с этой позицией терял её на сборке (отчёт B4).

    Не всякий слот заполняется: плашка-рубрика удаляется всегда (`service`), а
    нарисованная надпись и цифра-оформление остаются в кадре как есть
    (`required` — там же сказано, почему). Ни то, ни другое агенту не
    предлагается и слов не принимает.
    """
    return [slot.name for slot in find_slots(nodes, decor, contract)
            if slot.required and not slot.service]


def min_card_seconds(native: float) -> float:
    """Сколько блоку нужно времени, чтобы его сцена собралась.

    Число одно и то же для задания и для проверки: считать долю самому агенту
    незачем, а разойтись на сотые — значит потерять сессию. Прогон 04.08 так и
    вышел: карточка 3,13 с при пороге 3,15 завернула сборку.
    """
    return math.ceil(MIN_BLOCK_SHARE * float(native) * 10) / 10


def passport(nodes: list[Node], *, name: str, title: str = "",
             description: str = "", duration: float | None = None,
             decor: set[str] | frozenset[str] | None = None,
             contract: dict[str, str] | None = None) -> str:
    """Паспорт блока для задания: что за сцена и какие в ней слоты."""
    slots = find_slots(nodes, decor, contract)
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


def _media_child(name: str, source: str) -> str:
    """Файл ВНУТРЬ контентного слота их позиции, а не вместо него.

    Так написан их контракт: «Replace the children of this element … Direct
    img/video children of a slot are sized to cover the panel»
    (`before-after-wipe.html:16-20`) — сам слот несёт рамку, маску и класс, по
    которому его находит скрипт позиции, и заменять его тегом значило бы снять
    с кадра панель вместе с содержимым. Размер файлу задаёт CSS самой позиции
    (`.baw-slot > video {…}`) — тем же правилом, по которому слот и опознан
    (`slot_contract`), поэтому своей геометрии тег не несёт.

    Только картинка. Видео в такой слот их линтер не пускает вовсе, и это
    проверено живой сборкой (прогон scratchpad/slots-deep 06.09.2026):
    слот лежит внутри клипа позиции, у которого есть свой `data-start`, и
    `<video data-start>` под таким предком — ошибка
    `video_nested_in_timed_element` («Time the wrapper OR the video, never
    both», `packages/lint/src/rules/media.ts:426-432`), а `<video src>` без
    `data-start` — ошибка `media_missing_data_start` (там же:517-519). Обе
    стороны их правила закрыты, и снять её можно только сняв время с клипа
    самой позиции — то есть сломав её таймлайн. Значит слот принимает кадр, а
    не ролик; сцене это говорит `D36_elements` до заказа ведущей.
    """
    del name  # рамку и класс держит сам слот; тегу от них ничего не нужно
    return f'<img src="{source}" alt="">'


#: Чем слот под файл заполняется: их линтер пускает в него только картинку
#: (см. `_media_child`). Проверяется по имени файла, как и у `_media_tag`.
def is_slot_file(source: str) -> bool:
    """Годится ли файл в контентный слот позиции."""
    return source.lower().split("?")[0].endswith(_IMAGE_SUFFIXES)


_QUOTED_SELECTOR = re.compile(r'"([.#][^"]+)"')
_SCRIPT_BODY = re.compile(r"(<script>)(.*?)(</script>)", re.S)


def _markup_tokens(page: str) -> set[str]:
    """Классы и id разметки блока — всё, что стоит до его скрипта."""
    head = page.split("<script>", 1)[0]
    tokens = {token for value in re.findall(r'class="([^"]*)"', head)
              for token in value.split()}
    return tokens | set(re.findall(r'id="([^"]+)"', head))


def prune_timeline(html: str, original: str) -> str:
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

    `original` — разметка блока ДО подстановки, и она здесь обязательна: целью
    считается только то, что в разметке БЫЛО, а мёртвой — цель, которая после
    подстановки пропала. Прежнее правило («в разметке нет — значит мёртвая»)
    резало и то, чего в разметке не бывает вовсе: шестнадцатеричный цвет
    (`"#0b0f17"` подходит под селектор по id) и класс, который скрипт блока
    создаёт сам. У `v-code-diff` так пропала строка
    `return { scene: scene, code: code, gutter: scene.querySelector(".gutter") }`
    — `.gutter` рисует сам скрипт, — и блок падал в рантайме на `parts.code`
    (`page_error` у их `check --strict`, отчёт B4).
    """
    was = _markup_tokens(original)
    now = _markup_tokens(html)
    if was <= now:
        return html

    def parts_of(selector: str) -> list[str]:
        return selector.split()[0].split(":")[0].lstrip(".#").split(".")

    def target(selector: str) -> bool:
        """Строка целилась в этот элемент — он в разметке блока был."""
        return all(part in was for part in parts_of(selector))

    def gone(selector: str) -> bool:
        return not all(part in now for part in parts_of(selector))

    def prune(match: re.Match) -> str:
        kept = []
        for line in match.group(2).splitlines():
            targets = [one for one in _QUOTED_SELECTOR.findall(line)
                       if target(one)]
            if targets and all(gone(one) for one in targets):
                continue
            kept.append(line)
        return match.group(1) + "\n".join(kept) + match.group(3)

    return _SCRIPT_BODY.sub(prune, html)


def _drop(nodes: list[Node], index: int) -> list[dict]:
    """Убрать элемент. Строки таймлайна, целившиеся в него, снимает
    `prune_timeline` уже по сохранённому файлу."""
    return [remove_element(nodes[index].hfid)]


def fill_ops(nodes: list[Node], *, text: dict[str, str] | None = None,
             media: dict[str, dict] | None = None,
             decor: set[str] | frozenset[str] | None = None,
             contract: dict[str, str] | None = None) -> list[dict]:
    """Правки, подставляющие содержимое в слоты блока.

    `text` — имя слота → строка. `media` — имя слота → `{"file": …}` и, для
    видео, `{"start": …, "duration": …}`. `decor` — видимые тексты карточки
    (`reels.decor_texts`, читает их `hf_catalog.decor_texts`, тот же источник,
    что и гейт заглушек D22): слот с таким текстом никто не заполняет, и
    удалять его как незаполненную заглушку нельзя.
    """
    text = {k: (v or "").strip() for k, v in (text or {}).items()}
    media = media or {}
    slots = find_slots(nodes, decor, contract)
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
                if slot.kind == "media":
                    # Контентный слот полки держит рамку и маску сцены: убери
                    # его — и позиция останется без панели вовсе. Подавать
                    # нечего — позицию не берут для сцены, и говорит это гейт
                    # `D36_elements` ДО заказа ведущей
                    # (`hf_gates._element_problems`), а не сборка после.
                    continue
                # Пустая рамка со словом «slot» — тот же плейсхолдер на экране.
                ops += _drop(nodes, slot.index)
                continue
            if slot.kind == "media":
                if not is_slot_file(filled["file"]):
                    # Ролик в такой слот их линтер не пускает (`_media_child`);
                    # сцена узнаёт об этом до заказа (`hf_gates`), а сюда
                    # такой файл доходить не должен.
                    continue
                ops += [remove_element(nodes[child].hfid)
                        for child in node.children]
                ops.append(set_text(node.hfid, ""))
                ops.append(add_element(node.hfid, 0, _media_child(
                    f"slot-{slot.name}-{slot.index}", filled["file"])))
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
