"""Схема в кадре: то, что нельзя снять камерой.

Биролл показывает снятое — действие, предмет, руки. Величину, перечисление,
порядок и знак бренда камерой не снять, и на их месте стоит схема.

Форма идёт от **типа высказывания**, а не от того, какие слова короче. Это не
украшение: у каждого их блока свой смысл, записанный в его же карточке, и
подставить один вместо другого — соврать зрителю. `mk-progress-stat` в их
описании — «thin progress track filling to **value/max**» с дефолтной подписью
«Goals reached»: это величина против базы. Поставленный под «три вопроса», он
читается «три из ста», то есть недоделанной работой вместо оглавления.
Перечисление у них делает `grid-card-assemble` — «N capability cards…
stagger-assemble into a grid or vertical list», порядок — `hw-pipeline`
(«drawing on in sequence from a node list»).

Пять форм, каждую собирает их же блок:

- `metric` — одна величина против базы       (`mk-progress-stat`)
- `items`  — перечисление названных вещей    (`grid-card-assemble`)
- `pairs`  — свойство и его значение         (`mk-specs-list`)
- `steps`  — порядок или причинность         (`hw-pipeline`)
- `brand`  — знак бренда                     (`mk-placeholder-grid`)

**Почему блок правится текстом, а не параметрами.** У трёх из четырёх их
`CONFIG` живёт внутри IIFE, а рантайм заворачивает скрипт блока во вторую
(`packages/core/src/compiler/compositionScoping.ts:575-577`), поэтому снаружи
до него не дотянуться ни `window.CONFIG`, ни присваиванием после блока —
проверено кадром. Исключение — `grid-card-assemble`: он читает штатный канал
(`window.__hyperframes.getVariables()`, `grid-card-assemble.html:207-210`), и
содержимое ему уходит атрибутом `data-variable-values` на хосте.
"""
from __future__ import annotations

import json
import re

from reels_factory.config import OUT_H, OUT_W

#: Формы схемы и блок под каждую.
FORMS = {
    "metric": "mk-progress-stat",
    "items": "grid-card-assemble",
    "pairs": "mk-specs-list",
    "steps": "hw-pipeline",
    "brand": "mk-placeholder-grid",
}

#: Корень каждого блока — по нему прицеливается правило палитры и шрифта.
_ROOTS = {
    "mk-progress-stat": "mk-ps-root",
    "grid-card-assemble": "root",
    "mk-specs-list": "mk-sl-root",
    "hw-pipeline": "hw-pl-root",
    "mk-placeholder-grid": "mk-pg-root",
}

#: Сколько секунд блоку нужно, чтобы досказать свою анимацию. Числа сняты с их
#: же таймлайнов: у `hw-pipeline` узлы въезжают по 1,2 с каждый, у остальных
#: вход и выход занимают фиксированное время. У `grid-card-assemble` каскад
#: разложен по длительности его собственного корня (мы приводим её к сцене), а
#: последняя карточка садится к 60 % плюс 0,65 с осадки — отсюда пол в 3 с:
#: меньше, и кадр читается «ещё собирается» (проверено кадрами пробы).
#: Сцена короче — блок покажет себя недорисованным, и это хуже, чем не
#: показать вовсе.
_MIN_SECONDS = {
    "metric": lambda n: 2.6,
    "items": lambda n: 3.0,
    "pairs": lambda n: 0.3 + 0.18 * max(0, n - 1) + 1.45,
    "steps": lambda n: 0.3 + 1.2 * max(0, n - 1) + 1.3,
    "brand": lambda n: 1.4,
}

#: Сколько элементов форма выдерживает. Больше — блок не влезает в кадр, и его
#: же раскладка разъезжается (проверено: пять узлов дают ширину 1720 px при
#: кадре 1080; шесть карточек перечисления уходят под полосу титра).
LIMITS = {"metric": 1, "items": 4, "pairs": 4, "steps": 3, "brand": 3}

#: Сколько элементов форма требует минимум. Перечисление из одной-двух карточек
#: их блок рисует, но в вертикали это не сцена: одна карточка занимает 691x288,
#: девятую долю кадра, и 85 % высоты остаётся пустыми, а кегль подписи упирается
#: в потолок `min(2.6cqw, …)` (`grid-card-assemble.html:363`) и крупнее не
#: становится. Сценой блок делается с четырёх карточек (63 % высоты), читаемым —
#: с трёх. Их же карточка объявляет `items` как «Comma-separated cards (3 to 12)».
MINIMUM = {"metric": 1, "items": 3, "pairs": 2, "steps": 2, "brand": 1}

_CONFIG_HEAD = re.compile(r"var CONFIG = \{")
#: Только собственный атрибут, не хвост `data-composition-duration`.
_DURATION_ATTR = re.compile(r'(?<![-\w])data-duration="[\d.]+"')
#: Высота на корне блока. Её обязан держать сам блок, а не только наш хост:
#: их загрузчик читает `data-height` у корня и переписывает ею и атрибут, и
#: инлайновую высоту хоста
#: (`packages/core/src/runtime/compositionLoader.ts:516-524`). Пока корень
#: говорил 1920, обрезанный до 980 хост распрямлялся обратно во весь кадр.
_ROOT_HEIGHT = re.compile(r'(?<![-\w])data-height="\d+"')
#: Сам тег корня — тот же признак, что различает корень в `hf_compose.
#: block_root` (`id="…"` и `data-composition-id="…"` в одном теге, в любом
#: порядке атрибутов). Дублируем здесь, а не импортируем: `hf_compose` сам
#: импортирует `hf_schema`, обратный импорт дал бы цикл.
#: Нужен, чтобы `_ROOT_HEIGHT` не ушёл дальше корня: у настоящего блока
#: (`registry/blocks/gallery-tunnel/gallery-tunnel.html:68`) тот же атрибут
#: стоит ещё раз в примере использования — внутри HTML-комментария, ДО
#: настоящего корня. Замена по всему файлу переписала бы оба вхождения;
#: замена только внутри найденного тега трогает исключительно корень.
_ROOT_TAG = re.compile(
    r'<[^>]*\bid="[^"]+"[^>]*\bdata-composition-id="[^"]+"[^>]*>'
    r'|<[^>]*\bdata-composition-id="[^"]+"[^>]*\bid="[^"]+"[^>]*>'
)
_COMPOSITION_DURATION = re.compile(r'data-composition-duration="[\d.]+"')
_DURATION_VAR = re.compile(r"\bDUR = [\d.]+")
_STYLE_END = re.compile(r"</style>")

#: Канвас подменяем сплошной заменой литералов: у трёх блоков каждое вхождение
#: 1920 и 1080 — это канвас (CSS, `data-width/height`, `viewBox` и арифметика
#: центрирования в скрипте), проверено грепом по файлам. Перечисление упругое
#: и меряет себя в единицах контейнера, ему замена не нужна и вредна.
_W_LITERAL = re.compile(r"(?<!\d)1920(?!\d)")
_H_LITERAL = re.compile(r"(?<!\d)1080(?!\d)")
_ELASTIC = ("grid-card-assemble",)

#: Ниже этой черты схеме места нет: там идут слова титра. Число то же, что у
#: накладок (`hf_compose.CAPTION_BAND_TOP` минус запас), и держать его обязана
#: каждая форма — их собственная проверка перекрытия ловит его через раз, а
#: `brand` и вовсе клала белую плашку прямо на первую строку титра.
SAFE_BOTTOM = 980


def is_elastic(block: str) -> bool:
    """Упругий ли блок: канвас ему не подменяют, содержимое идёт на хост.

    У упругого нет ни `data-width`, ни литерала `CONFIG`: он меряет себя в
    единицах контейнера и читает штатный канал переменных. Его «конфиг» — это
    значения для `data-variable-values`, а не довесок к литералу.
    """
    return block in _ELASTIC


def min_seconds(form: str, items: int) -> float:
    """Минимальная длина сцены под форму с таким числом элементов."""
    rule = _MIN_SECONDS.get(form)
    return rule(items) if rule else 0.0


def _config_end(html: str, start: int) -> int:
    """Конец литерала `CONFIG` — по балансу скобок, а не по отступу."""
    depth = 0
    for index in range(start, len(html)):
        char = html[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index + 1
    raise RuntimeError("в блоке не закрылся литерал CONFIG")


def port_block(html: str, *, duration: float, config: dict,
               css: str = "", patches: tuple = (), elastic: bool = False,
               height: int | None = None) -> str:
    """Их блок в нашем кадре: вертикаль, длительность, содержимое, палитра.

    `config` дописывается ПОСЛЕ литерала одним `Object.assign` — так работают и
    числа, и списки, и пути к файлам. Цвета сюда класть нельзя: их подстановщик
    слотов вырезает строку с шестнадцатеричным кодом, приняв её за мёртвый
    селектор (`hf_slots._QUOTED_SELECTOR`), — поэтому палитра идёт правилом CSS.

    `elastic` — блок, который меряет себя в единицах контейнера и содержимое
    получает штатным каналом: канвас ему не подменяют, литерала `CONFIG` у него
    нет, зато длительность правится в трёх местах (его собственный корень задаёт
    ритм каскада, длительность хоста на него не влияет вовсе).

    `height` — высота коробки для упругого блока. Правится на его корне: их
    загрузчик читает `data-height` именно там и ею же переписывает инлайновую
    высоту хоста (`compositionLoader.ts:516-524`), поэтому обрезать один хост
    бесполезно — коробка распрямляется обратно во весь кадр.
    """
    if elastic and height:
        root_tag = _ROOT_TAG.search(html)
        if root_tag:
            patched = _ROOT_HEIGHT.sub(f'data-height="{int(height)}"',
                                       root_tag.group(0))
            html = html[:root_tag.start()] + patched + html[root_tag.end():]
    if not elastic:
        # Их ширина 1920 становится нашей 1080, их высота 1080 — нашей 1920.
        # Через метку, иначе вторая замена переписала бы результат первой.
        html = _W_LITERAL.sub("\x00", html)
        html = _H_LITERAL.sub(str(OUT_H), html)
        html = html.replace("\x00", str(OUT_W))

    html = _DURATION_ATTR.sub(f'data-duration="{duration:.4f}"', html)
    html = _COMPOSITION_DURATION.sub(
        f'data-composition-duration="{duration:.4f}"', html)
    html = _DURATION_VAR.sub(f"DUR = {duration:.4f}", html)

    if config:
        match = _CONFIG_HEAD.search(html)
        if not match:
            raise RuntimeError("в блоке нет литерала CONFIG — версия изменилась")
        end = _config_end(html, match.end() - 1)
        payload = json.dumps(config, ensure_ascii=False)
        html = (html[:end]
                + f"\n        CONFIG = Object.assign(CONFIG, {payload});"
                + html[end:])

    for needle, replacement in patches:
        if needle not in html:
            raise RuntimeError(f"в блоке нет места для правки: {needle!r}")
        html = html.replace(needle, replacement, 1)

    if css:
        html = _STYLE_END.sub(css + "\n    </style>", html, count=1)
    return html


#: Насколько плитка карточки светлее подложки кадра. Их собственное значение —
#: `var(--surface, #141a23)` против `var(--bg, …)`: плитка у них отличается от
#: фона всегда. У нас `--surface` равнялся `bg` знак в знак, и карточка
#: читалась одним контуром. Доля мала нарочно: сверху блок кладёт свою
#: световую полосу (`linear-gradient(180deg, rgba(255,255,255,0.055), …)` в
#: `.gca-card`, grid-card-assemble.html:127), и вместе они дают плоскость, а не
#: светлое пятно.
SURFACE_LIFT = 0.14


def _mix(base: str, toward: str, share: float) -> str:
    """Цвет `base`, сдвинутый к `toward` на долю `share`. Оба — `#rrggbb`.

    Считаем сами, а не через `color-mix`: правило палитры уезжает в блок
    строкой, а их подстановщик слотов вырезает строки с шестнадцатеричным
    кодом внутри функции, приняв их за мёртвый селектор (см. `port_block`).
    """
    def channels(value: str) -> list[int] | None:
        raw = str(value or "").strip().lstrip("#")
        if len(raw) != 6:
            return None
        try:
            return [int(raw[index:index + 2], 16) for index in (0, 2, 4)]
        except ValueError:
            return None

    left, right = channels(base), channels(toward)
    if left is None or right is None:
        return base
    return "#" + "".join(
        f"{round(a + (b - a) * share):02x}" for a, b in zip(left, right))


def palette_css(block: str, colors: dict, root: str | None = None) -> str:
    """Правило палитры и шрифта для корня блока.

    Гарнитуру объявляем ДВАЖДЫ — обычным `font-family` и их токеном. Их же
    врезка шрифтов собирает семейства только из объявлений `font-family`
    (`inject-fonts.cjs:93`), и имя, живущее лишь в переменной, она не увидит:
    тогда кириллица уедет в подменный шрифт, а казахские буквы не отрисуются
    вовсе.

    `root` — корень позиции, если она не из таблицы форм: у произвольной
    позиции каталога корневой id код читает из её же разметки
    (`hf_compose._root_id`). Правило целится в корень, а не в `:root`: их
    контракт тем прямо запрещает объявлять токены глобально — «those
    declarations escape composition scoping» (`themes/CONTRACT.md:3`).
    """
    root = root or _ROOTS.get(block)
    if not root:
        return ""
    ink = colors.get("ink", "#ffffff")
    accent = colors.get("accent", "#ff5a36")
    bg = colors.get("bg", "#0d0b10")
    return (
        f"\n      #{root} {{ font-family: 'Manrope', sans-serif;"
        f" --mk-font: 'Manrope', sans-serif;"
        # Типографские токены их же контракта тем (`themes/CONTRACT.md:9-14`):
        # позиции полки читают гарнитуру через `var(--font-display, …)`, а наш
        # `_FONT_FAMILY` стирает объявление, к которому этот `var` подставлен.
        # Без токена шрифт вернулся бы к их запасной Inter.
        f" --font-display: 'Unbounded', sans-serif;"
        f" --font-body: 'Manrope', sans-serif;"
        f" --font-mono: 'Manrope', sans-serif;"
        f" --hw-font-print: 'Manrope', sans-serif;"
        f" --hw-font-script: 'Unbounded', sans-serif;"
        f" --mk-ink: {ink}; --mk-ink-dim: {ink}b3; --mk-ink-dark: {ink};"
        f" --mk-ink-dim-dark: {ink}b3; --mk-accent: {accent};"
        # `--mk-paper` — заливка плитки, а не цвет букв: с цветом чернил она
        # давала белую плашку во весь прямоугольник знака.
        f" --mk-accent-dark: {accent}; --mk-paper: {bg};"
        f" --hw-ink: {ink}; --hw-accent: {accent};"
        # Токены карточек перечисления: их значения по умолчанию — тёмная
        # сине-серая тема их промо, поверх нашей палитры она читается чужой.
        f" --brand: {accent}; --accent: {accent}; --accent-2: {accent};"
        # `--surface` разведён с фоном: плитка светлее подложки на
        # `SURFACE_LIFT` в сторону чернил, иначе её видно только по контуру.
        # `--bg` не объявляем нарочно: корень их блока красится по нему, и
        # прямоугольник 1080x980 закрыл бы живой фон схемной сцены.
        f" --fg: {ink}; --muted: {ink}99;"
        f" --surface: {_mix(bg, ink, SURFACE_LIFT)}; --border: {ink}33; }}"
    )


def _fit_label(text: str, limit: int) -> str:
    """Строка, которая влезет в свою рамку.

    У их списка и у подписи узла стоит `white-space: nowrap`: длинная строка
    не переносится, а уезжает за край кадра, и ни один их гейт этого не видит —
    он меряет рамку элемента, а не текст внутри. Поэтому режем по словам.
    """
    words = str(text or "").split()
    out: list[str] = []
    for word in words:
        candidate = " ".join(out + [word])
        if len(candidate) > limit and out:
            break
        out.append(word)
    return " ".join(out) or str(text or "")[:limit]


#: Ширина буквы относительно кегля у Manrope — по ней считается, влезет ли
#: подпись в коробку узла. Мерить точнее незачем: числа идут в геометрию блока
#: с запасом.
_GLYPH_RATIO = 0.55


#: Сколько знаков держит коробка узла у `hw-pipeline`. Ширина коробки падает с
#: числом узлов (три коробки с зазорами занимают весь кадр), поэтому и предел
#: разный: на глаз он мерился по кадру, а не по формуле блока. Без подчёркивания
#: — заданию нужно называть агенту эти же числа, а не переписывать их литералом
#: рядом (`hf_montage_skill.py`).
NODE_CHARS = {1: 14, 2: 11, 3: 8}

#: Сколько знаков держат подписи остальных форм — те же числа, которыми режет
#: их `_fit_label` ниже. Заданию нужны они же, а не переписанные рядом литералы.
METRIC_LABEL_CHARS = 28
ITEMS_LABEL_CHARS = 20
PAIRS_LABEL_CHARS = 22
PAIRS_VALUE_CHARS = 26


#: Значки карточек перечисления — закрытый набор, из которого агент выбирает по
#: смыслу пункта. Свои, а не их шесть: их набор (щит, график, облако, молния,
#: слои, документ) прокручивается по номеру карточки, то есть значок ничего не
#: означает, — а именно за бессмысленный значок в кадре мы и получили отказ.
#: Пути нарисованы в их же координатной коробке 48×48 и обводятся их же стилем
#: (`.gca-icon path`), поэтому штрих дорисовывается на входе как у родных.
ICONS = {
    "вопрос": ["M18 18a6 6 0 1 1 6 6v6", "M24 37.5h.5"],
    "деньги": ["M24 8v32",
               "M32 16a7 5 0 0 0-8-4h-2a6 6 0 0 0 0 12h4a6 6 0 0 1 0 12h-2"
               "a7 5 0 0 1-8-4"],
    "время": ["M24 6a18 18 0 1 0 0 36a18 18 0 0 0 0-36", "M24 14v11l8 5"],
    "человек": ["M24 8a8 8 0 1 0 0 16a8 8 0 0 0 0-16",
                "M8 42c0-8 8-12 16-12s16 4 16 12"],
    "разговор": ["M8 10h32v22H20l-12 9z"],
    "рост": ["M8 40h32", "M14 40V26", "M24 40V12", "M34 40v-9"],
    "галочка": ["M10 26l10 10 18-22"],
    "тревога": ["M24 8L6 40h36z", "M24 20v9", "M24 34h.5"],
    "документ": ["M14 6h14l8 8v28H14z", "M28 6v8h8", "M20 26h12", "M20 33h8"],
    "энергия": ["M26 6L12 28h10l-2 14 14-22H24l2-14z"],
    "цель": ["M24 6a18 18 0 1 0 0 36a18 18 0 0 0 0-36",
             "M24 15a9 9 0 1 0 0 18a9 9 0 0 0 0-18", "M24 23.5h.5"],
    "поиск": ["M21 8a13 13 0 1 0 0 26a13 13 0 0 0 0-26", "M31 31l9 9"],
    "идея": ["M18 38h12", "M20 43h8",
             "M24 5a12 12 0 0 0-7 21c2 2 2 4 2 6h10c0-2 0-4 2-6a12 12 0 0 0-7-21"],
    "замок": ["M14 22h20v18H14z", "M19 22v-6a5 5 0 0 1 10 0v6"],
}


#: Их раскладчик плиток знает только ландшафтные наборы: `2up` это две колонки,
#: `3up` — три. В вертикали нужны строки, а под один знак — вообще одна ячейка;
#: своего набора у них нет, поэтому дописываем три ветки рядом с их же.
#: Пустых ячеек это заодно избегает: цикл у них идёт по прямоугольникам
#: раскладки, а не по картинкам, и лишний прямоугольник рисуется «лункой» с
#: номером — на прогоне это был бы пустой квадрат с цифрой 2.
_GRID_DISPATCH = ('if (layout === "3up") return grid(3, 1);',
                  'if (layout === "1up") return grid(1, 1);\n'
                  '          if (layout === "2down") return grid(1, 2);\n'
                  '          if (layout === "3down") return grid(1, 3);\n'
                  '          if (layout === "3up") return grid(3, 1);')

#: Их список центрирует колонку по всей высоте канваса. Литерал уже прошёл
#: подмену канваса (1080 → 1920), поэтому целимся в подменённое число.
_SPECS_TOP = (f'Math.round(({OUT_H} - colH) / 2)',
              f'Math.round(({SAFE_BOTTOM} - colH) / 2)')

#: Пустой слот их компонента: сюда уезжают наши карточки со своими значками.
_ITEMS_SLOT = '<div class="gca-stage" data-slot="items" role="list"></div>'

#: Их подгонка кегля считает ~0,75em на знак моноширинного латинского. У
#: кириллицы знак шире, и слово обрезалось прямо в кадре (проверено пробой:
#: «ПУБЛИКАЦИЯ» отрисовалась как «ПУБЛИКАL»), а их же `check --strict` этого не
#: видел — он меряет рамку элемента, а не текст внутри.
_LABEL_RATIO = ("textW / (maxChars * 0.75)", "textW / (maxChars * 0.95)")


def _metric_parts(value: str) -> tuple[int, str]:
    """Число и хвост при нём: «87 %» → (87, ' %'), «2x» → (2, 'x').

    Их счётчик печатает `Math.round(значение) + суффикс`
    (`mk-progress-stat.html:168`), поэтому величина обязана начинаться с цифр.
    «Десятки» и «∞» прежде превращались в ноль, и в кадре стояло «0».
    """
    text = str(value or "").strip()
    match = re.match(r"\d+", text)
    if not match:
        raise ValueError(
            f"величина {text!r} не начинается с цифры: их счётчик печатает "
            "округлённое число и хвост при нём, а не произвольную строку")
    return int(match.group()), text[match.end():]


def _cards_markup(items: list[dict]) -> str:
    """Наши карточки перечисления — своими значками, их же разметкой.

    Их компонент объявляет это прямо: «A fork that wants custom card content
    places its own children inside the [data-slot="items"] grid element; when
    that element already has children the script animates them as the cards»
    (`grid-card-assemble.html:45-51`).
    """
    cards = []
    for item in items:
        paths = "".join(f'<path d="{d}"/>' for d in ICONS[item["icon"]])
        cards.append(
            '<div class="gca-card" role="listitem">'
            f'<svg class="gca-icon" viewBox="0 0 48 48" aria-hidden="true">'
            f'{paths}</svg>'
            f'<div class="gca-text"><div class="gca-label">'
            f'{item["label"]}</div></div></div>')
    return ('<div class="gca-stage" data-slot="items" role="list">'
            + "".join(cards) + "</div>")


def build(form: str, content: dict, *, duration: float, colors: dict,
          files: dict | None = None) -> tuple[str, dict, str, tuple]:
    """Что подставить в блок под названную агентом форму.

    Возвращает `(имя блока, CONFIG-довесок, правило CSS, правки текста)`.
    Геометрия считается от кадра: у их блоков она задана числами под ландшафт,
    и в вертикали их раскладка разъезжается.
    """
    block = FORMS[form]
    files = files or {}
    css = palette_css(block, colors)

    if form == "metric":
        number, suffix = _metric_parts(content.get("value"))
        # База не названа — величине не с чем соотноситься, и полосу мы
        # убираем: залитая доверху, она обещает «столько из стольких» там, где
        # никакого «стольких» нет. Это и была та самая «3 из 100».
        base = content.get("base")
        base = int(base) if base not in (None, "") else 0
        config = {
            "scheme": "dark", "value": number, "suffix": suffix,
            "max": base or number or 1,
            "label": _fit_label(content.get("label"), METRIC_LABEL_CHARS),
            "caption": "",
            "trackWidth": 620,
            "x": 120, "y": round(OUT_H * 0.30),
        }
        # Число у них набрано 190 px с `line-height: 1`, а подпись отстоит от
        # него на 10 px. Коробка знака у Manrope шире кегля примерно на 37 % —
        # замер их же аудита: рамка `#mk-ps-num` начинается на 35 px выше
        # группы и на столько же ниже её строки, — и хвост цифры садится прямо
        # на подпись. Их `check` считает это ошибкой `content_overlap` на
        # `#mk-ps-num` (прогон 37), причём при ЛЮБОМ содержимом: геометрия
        # блока не зависит от наших чисел. Поэтому подписи даём просвет, а
        # группу поднимаем, чтобы она не уехала в полосу титра.
        css += "\n      #mk-ps-label { margin-top: 60px; }"
        if base <= number:
            css += "\n      #mk-ps-track { display: none; }"
        return block, config, css, ()

    if form == "items":
        # Двадцать знаков — последняя ступень, на которой кегль ещё
        # максимальный: с двадцать первого их подгонка начинает уменьшать
        # шрифт, ничего не выигрывая (проверено лестницей кадров).
        cards = [{"label": _fit_label(item.get("label"), ITEMS_LABEL_CHARS).upper(),
                  "icon": item["icon"]}
                 for item in (content.get("items") or [])[:LIMITS["items"]]]
        labels = ",".join(card["label"] for card in cards)
        # Содержимое уходит штатным каналом на хост, поэтому `CONFIG` пуст;
        # переменная `items` всё равно нужна — по ней их скрипт считает
        # раскладку и кегль, даже когда карточки пришли из слота. И она обязана
        # совпадать с подписями в слоте знак в знак: кегль считается по ней, и
        # разошедшиеся строки режутся посередине (проверено кадром — это и был
        # источник обрезанной «ПУБЛИКАL»).
        variables = {"items": labels, "layout": "list", "exit": "none"}
        # Разрядка их промо (0,16em) на кириллице разносит слово так, что оно
        # перестаёт читаться словом; половины хватает, чтобы подпись осталась
        # набранной их же манерой.
        css += "\n      .gca-label { letter-spacing: 0.08em; }"
        return block, variables, css, ((_ITEMS_SLOT, _cards_markup(cards)),
                                       _LABEL_RATIO)

    if form == "pairs":
        # Их блок — «Left-aligned specs/traits checklist», строка это пара
        # «свойство → значение». Половину пары мы прежде оставляли пустой, и в
        # кадре тянулись пустые линии: незаполненная анкета вместо смысла.
        # Поэтому значение обязательно, и его отсутствие — ошибка плана.
        rows = []
        for row in (content.get("rows") or [])[:LIMITS["pairs"]]:
            label = _fit_label(row.get("label"), PAIRS_LABEL_CHARS)
            value = _fit_label(row.get("value"), PAIRS_VALUE_CHARS)
            if not value.strip():
                raise ValueError(
                    f"строка «{label}» без значения: их список рисует пару "
                    "«свойство → значение», и половина пары оставляет в кадре "
                    "пустую линию")
            rows.append({"label": label, "value": value})
        config = {"scheme": "dark", "rows": rows, "underline": True,
                  "lineWidth": OUT_W - 240, "scrim": 0,
                  "x": 120, "rowGap": 56}
        # Их блок центрирует колонку по всей высоте канваса, и после подмены
        # канваса три строки садились на 799…1121 — нижнее подчёркивание уже в
        # полосе титра. Центрируем по безопасной высоте.
        return block, config, css, (_SPECS_TOP,)

    if form == "steps":
        nodes = list((content.get("nodes") or [])[:LIMITS["steps"]])
        limit = NODE_CHARS.get(len(nodes), 8)
        nodes = [_fit_label(node, limit) for node in nodes]
        count = max(1, len(nodes))
        font = 46
        longest = max((len(node) for node in nodes), default=8)
        box = min(360, max(220, round(longest * font * _GLYPH_RATIO) + 60))
        gap = 70
        while count * box + (count - 1) * gap > OUT_W - 80 and box > 180:
            box -= 20
        config = {
            "nodes": [{"label": node} for node in nodes],
            "boxW": box, "boxH": 150, "gap": gap,
            "y": round(OUT_H * 0.42), "fontSize": font,
        }
        return block, config, css, ()

    # brand — знак бренда крупно, несколько знаков столбиком
    cells = [{"src": src, "insideScale": 0.62}
             for src in (content.get("files") or [])[:LIMITS["brand"]]]
    layout = {1: "1up", 2: "2down", 3: "3down"}.get(len(cells), "1up")
    config = {"layout": layout, "cells": cells, "margin": 120, "gap": 40,
              "radius": 40, "kenBurns": False}
    # Их раскладчик считает сетку по своим W/H, а не по корню, поэтому полосу
    # ставим сами: знак бренда живёт в середине кадра, а не во весь рост.
    # Полоса живёт в безопасной высоте, а не по центру кадра: центрированная по
    # 1920 она кончалась на 1382 и клала свою плашку прямо на первую строку
    # титра — белым по белому, и их проверка контраста этого не увидела.
    band = min(round(OUT_H * (0.30 + 0.14 * len(cells))), SAFE_BOTTOM - 120)
    css += (f"\n      #mk-pg-grid {{ position: absolute; left: 0;"
            f" top: {round((SAFE_BOTTOM - band) / 2)}px; width: {OUT_W}px;"
            f" height: {band}px; }}"
            f"\n      .mk-pg-media {{ object-fit: contain; padding: 48px; }}")
    # Раскладчик считает прямоугольники по своим W/H — это не размер кадра, а
    # размер полосы, в которой стоят плитки. Подмена канваса делает их равными
    # кадру, поэтому высоту возвращаем к полосе.
    return block, config, css, (_GRID_DISPATCH, (f"H = {OUT_H},",
                                                 f"H = {band},"))
