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
#:
#: У `metric` недосказанность прежде считалась той же эстетикой — и это была
#: не причина, а следствие. Расследование rb0907-university (сцена `s-21`,
#: 07.09.2026: `value: "23 августа"`, в кадре «18 августа» на 67,0 с) нашло
#: настоящую причину не в поле, а в самом блоке: `mk-progress-stat.html`
#: считал ЛЮБУЮ величину твином GSAP с фиксированным стартом 0,5 с и
#: длительностью 1,6 с, независимо от длины сцены (счёт кончается РОВНО на
#: 2,1 с — гарантия самого твина, не зависящая от величины числа). Старый пол
#: 2,6 с не оставлял между этим мигом и угасанием (`DUR - 0,5`) ни одной
#: секунды, а `settle_schemas` вдобавок прощает недобор до 0,05 с — угасание
#: могло стартовать раньше, чем твин доедет до места. Первая правка (2,6 → 3,1
#: с) лечила симптом числом, не причину, и вдобавок путала два разных типа
#: высказывания: у количества («100 %», «250 000 $») отсчёт осмыслен, у даты
#: или номера («23 августа», «№ 42», «2026 год») — нет: дата не «доезжает» ни
#: от чего, а `Math.round` вдобавок ещё и портил дробную секунду до самого
#: конца твина у крупных чисел (тот же «250 000 $» из карточки формы,
#: `hf_montage_skill.py:566-572`).
#:
#: Первая правка лечила это в `build()`: `_is_dateline` отличала дату/номер
#: от количества и снимала твин патчем в `port_block`, оставляя счётчик
#: (`mk-progress-stat`) самим блоком. Расследование пошло дальше корня, а не
#: симптома (rb0908-university): счётчик — неверный блок для даты вообще,
#: не только его твин. Дата не отвечает «сколько» и не отсчитывается ни от
#: чего, поэтому дате нужен блок, который не считает, — `number-pop-in`
#: (`hf_compose`, схемная ветка `metric`+`_is_dateline`, ДО вызова `build()`
#: этого файла). `build()` теперь про количество целиком: дата до него не
#: доходит, и муть от «дата или количество» из этой функции ушла. Количеству
#: старт и длительность твина не фиксированы, а считаются `_count_timing` от
#: длительности сцены — тем же приёмом, что у их `count-up`
#: (`root.dataset.duration`, `count-up.html:222-232`), но без масштабирования
#: вверх: длинная сцена просто дольше держит готовое число. Пол `metric`
#: поэтому вернулся к 2,6 с — с масштабированием твин при любой длине сцены
#: успевает домотать до 40 % и оставить запас до угасания; инвариант держит
#: `test_счёт_величины_укладывается_в_долю_сцены` (test_hf_schema.py).
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


def overlay_css(root: str | None) -> str:
    """Правило, которым позиция вида `effect` перестаёт красить свою коробку.

    Позиция вида `effect` встаёт коробкой в свободную зону ЖИВОГО кадра —
    поверх вставки-биролла и подложки сцены (`hf_compose`, ветка
    `kind == "effect"`). Красить эту коробку ей нечем: их собственный контракт
    компонента говорит прямым текстом «Background should be `transparent` so it
    overlays cleanly»
    (`skills/hyperframes-registry/references/templates.md:416`).

    Половина их `effect`-позиций написана страницей-показом себя самой и
    контракт этот нарушает: у 41 позиции нашего каталога корень красится
    непрозрачно — `#000` у `chat-message` и `chat-thread`, `#fefefe` у
    `notes-typing`, `var(--bg, #0b0c0e)` у двух десятков остальных (а `--bg` мы
    не объявляем нарочно, см. `palette_css` выше, — работает их запасной цвет).
    В кадре это чёрная полоса поперёк биролла: прогон `exp-beat-direction-2`,
    вариант Б, 6,4 с — `chat-message` перерезал вставку полосой в треть кадра.

    Позиции вида `scene` правило не касается: та встаёт подложкой во весь кадр
    (`.ovl-back`) и держит его собой — прозрачной ей быть незачем.
    """
    if not root:
        return ""
    return f"\n      #{root} {{ background: transparent; }}"


#: Пара значений, которой позиции каталога объявляют полярность своих букв.
#: Смысл написан их же автором в самой позиции: «ink is near-black for light
#: frames, paper near-white for dark ones» (`typewriter.html:20-22`, и слово в
#: слово так же у остальных двенадцати позиций этой семьи). Пару берём целиком
#: — переменная, где есть только одно из двух слов, полярностью не считается и
#: не трогается.
_TONE_DARK_TEXT = "ink"
_TONE_LIGHT_TEXT = "paper"


def _is_dark(color: str) -> bool:
    """Тёмный ли цвет `#rrggbb` — по яркости WCAG, тем же порогом, что их
    проверка контраста делит светлый фон и тёмный."""
    raw = str(color or "").strip().lstrip("#")
    if len(raw) != 6:
        return True
    try:
        channels = [int(raw[index:index + 2], 16) / 255 for index in (0, 2, 4)]
    except ValueError:
        return True
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
              for c in channels]
    luminance = (0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2])
    return luminance < 0.18


def frame_variables(card: dict, colors: dict, chosen: dict | None = None) -> dict:
    """Значения переменных позиции, которые решает кадр, а не план.

    Позиция каталога приезжает нарисованной под СВОЙ кадр, и часть их прямо
    даёт выбрать, под какой: переменная `tone` со значениями `ink`/`paper`.
    Умолчание у всех тринадцати таких позиций — `ink`, «near-black for light
    frames», а наш кадр тёмный (`hf_frame.FRAME_DEFAULTS`, `bg #0b0b0c`), и
    буквы ложились чёрным по чёрному: живой `check --strict` 06.09.2026 дал
    `contrast_aa_failure` 1.02:1 с `fg rgb(24,24,27)` тринадцати позициям
    разом (`typewriter`, `top-down-letters`, `staggered-fade-up`,
    `shared-axis-y/z`, `text-state-swap`, `strikethrough-replace`,
    `slot-machine-roll`, `rgb-glitch-text`, `per-word-crossfade`,
    `number-pop-in`, `line-by-line-slide`, `focus-blur-resolve`,
    `blur-out-up`).

    Решает это код, а не агент: цвет кадра — наша арифметика (палитра
    `hf_frame`), в плане его нет, и просить агента подобрать значение под
    цвет, которого он не видит, значит просить догадку. Названное в плане
    значение сильнее: `chosen` не перекрываем никогда.
    """
    values = dict(chosen or {})
    out: dict = {}
    want = (_TONE_LIGHT_TEXT if _is_dark(colors.get("bg", "#0b0b0c"))
            else _TONE_DARK_TEXT)
    for key, rule in (card.get("variables") or {}).items():
        if key in values:
            continue
        options = {str(option) for option in (rule.get("options") or ())}
        if {_TONE_DARK_TEXT, _TONE_LIGHT_TEXT} <= options:
            out[key] = want
    return out


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

#: Доля кегля от ширины коробки узла и доля высоты коробки от кегля — их же
#: пропорции по умолчанию (`hw-pipeline.html:99-106`: `boxW: 320, boxH: 170,
#: fontSize: 56`), а не наша выдумка. До этой правки `build()` брал коробку от
#: ширины кадра, а кегль — литералом 46 в стороне: коробка росла, кегль нет,
#: и узел «Убеждает» на прогоне `rb0908-philosophers` (сцена `s-03`,
#: `pip-br`) читался пятипроцентной царапиной кадра. Кегль ниже читаемого пола
#: HyperFrames для видео не идёт: «If you're writing a font-size under 24px in
#: a video composition, justify it»
#: (`hyperframes-ref/skills/hyperframes-creative/references/
#: video-composition.md:47`).
_NODE_FONT_RATIO = 56 / 320
_NODE_BOXH_RATIO = 170 / 56
_NODE_MIN_FONT = 24

#: Внутренний отступ подписи от края коробки узла с обеих сторон вместе.
#: `_GLYPH_RATIO` — средняя ширина буквы по алфавиту; жирное узкое сочетание
#: («Выполняет» при кегле 60 в коробке 360, живой прогон правки) съедало
#: запас в 31,5 px на сторону почти целиком и читалось прижатым к обводке.
#: Запас взят вдвое шире прежнего (`+ 60` у старой формулы бокса, откуда
#: считался предел по тексту) — проверено тем же кадром после правки.
_NODE_TEXT_PADDING = 100


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

#: Их кегли (46/40 px, `mk-specs-list.html:59,65`) сверстаны под landscape-
#: канвас 1920x1080 и в нашей вертикали не растут ни от чего: подмена канваса
#: (`port_block`) переписывает только буквальные 1920/1080, а других чисел не
#: трогает. На реальном прогоне (`rb0908-philosophers`, сцена `s-05`, none)
#: строка «да  объяснить честно» при кегле 46 занимала ~443 px из 840
#: `lineWidth` — меньше половины безопасной ширины, и сам кегль (2,4 % высоты
#: кадра) читался «мелким текстом». Растим кегль и разрыв между рядами одним
#: множителем от РЕАЛЬНОГО текста строки (не от потолка
#: `PAIRS_LABEL_CHARS`/`PAIRS_VALUE_CHARS` — то запас на редкий случай, а не
#: типичная длина), значит самая длинная пара доходит до `lineWidth`, а не
#: только до своей исходной доли. Потолок — их же канон читаемости для видео:
#: «Headlines … 64-120px»
#: (`hyperframes-ref/skills/hyperframes-creative/references/
#: video-composition.md:40`) — при кегле 46 множитель 2,5 даёт 115 px, у
#: верхней границы их «Headlines».
_PAIRS_LABEL_FONT = 46
_PAIRS_VALUE_FONT = 40
_PAIRS_ROW_GAP = 56
_PAIRS_TEXT_GAP = 18  # их `.mk-sl-text { gap: 18px }`, mk-specs-list.html:54
_PAIRS_ROW_EXTRA = 24  # margin-top подчёркивания (22) + волосяная линия (2)
_PAIRS_MAX_SCALE = 2.5

#: Их скрипт меряет высоту ряда своим же кеглем 46 (при `line-height: 1`)
#: плюс отступ подчёркивания и волосяную линию — и центрирует колонку по этой
#: высоте (`mk-specs-list.html:185-189`, та же арифметика, что чинит
#: `_SPECS_TOP` рядом). Кегль растёт вместе с текстом (`build()` ниже), и этот
#: литерал обязан расти вместе с ним — иначе колонка отцентруется по СТАРОЙ,
#: маленькой высоте ряда и разъедется с настоящей.
_PAIRS_ROW_HEIGHT = "(46 + 22 + (CONFIG.underline ? 2 : 0))"


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


#: Дата или порядковый номер против количества. Количество отвечает «сколько»
#: и отсчёт для него честен; дата и номер отвечают «когда» и «который» — им не
#: от чего отсчитывать, а от нуля до «23 августа» ничего не вело (расследование
#: rb0907-university, сцена `s-21`, 07.09.2026). Отличаем по хвосту при цифрах:
#: название месяца в любом падеже, «год/года/г.», «№», время «10:30», диапазон
#: «10–20». Список — не философия, а перечень форм даты, которые агент реально
#: пишет в `value` формы `metric` (`hf_montage_skill.py`, пример «дедлайн
#: приёма заявок»).
_MONTH_STEMS = ("январ", "феврал", "март", "апрел", "ма[йя]", "июн", "июл",
                "август", "сентябр", "октябр", "ноябр", "декабр")
_DATELIKE = re.compile(
    r"(?:" + "|".join(_MONTH_STEMS) + r")"
    r"|\bг\.?\b|\bгод[а-я]*\b"
    r"|№"
    r"|^\d{1,2}:\d{2}\b"
    r"|^\d+\s*[–—-]\s*\d+\b",
    re.IGNORECASE,
)


def _is_dateline(value: str) -> bool:
    """Величина формы `metric` — дата или номер, а не количество."""
    return bool(_DATELIKE.search(str(value or "")))


def date_variables(value: str) -> dict:
    """Дата/номер как переменные `number-pop-in`: `value` — цифры, `unit` —
    хвост при них.

    Один и тот же разбор, что уже режет счётчик на число и суффикс
    (`_metric_parts`) — дата отличается от количества не разбором, а тем, в
    какой компонент едут те же две части (`hf_compose`, схемная ветка
    `metric`+`_is_dateline`): счётчику суффикс приклеивается к числу
    («87 %»), а `number-pop-in` печатает его отдельным полем `unit` под
    числом («20» + «августа»).
    """
    number, tail = _metric_parts(value)
    return {"value": str(number), "unit": tail.strip()}


#: Их твин считает `CONFIG.value` со стартом 0,5 с и длительностью 1,6 с
#: (`mk-progress-stat.html:161-172`) — числа фиксированы и не знают длины
#: сцены. При коротких сценах (наш пол `metric` — 2,6 с) счёт кончается на
#: 2,1 с, оставляя до угасания (`DUR - 0,5`) считаные сотые доли секунды —
#: сама причина дефекта rb0907-university. Масштабируем оба числа так, чтобы
#: счёт не заканчивался позже `_COUNT_END_SHARE` длины сцены: тот же приём, что
#: у их `count-up` (`root.dataset.duration`, `count-up.html:222-232`), но без
#: масштабирования ВВЕРХ — длинная сцена держит готовое число дольше, а не
#: считает его дольше.
_COUNT_START_BASE = 0.5
_COUNT_DURATION_BASE = 1.6
_COUNT_END_BASE = _COUNT_START_BASE + _COUNT_DURATION_BASE
_COUNT_END_SHARE = 0.4


def _count_timing(duration: float) -> tuple[float, float]:
    """Старт и длительность твина счёта, подогнанные под длину сцены."""
    target_end = min(_COUNT_END_BASE, _COUNT_END_SHARE * float(duration))
    scale = target_end / _COUNT_END_BASE
    return _COUNT_START_BASE * scale, _COUNT_DURATION_BASE * scale


#: Ровно тот блок JS, что считает величину вверх твином — их же файл,
#: `mk-progress-stat.html:159-174`. Заменяем целиком, а не числом рядом:
#: разойдись needle с шаблоном, `port_block` сам поднимет ошибку
#: («в блоке нет места для правки»), а не промолчит устаревшим патчем.
_COUNT_TWEEN = (
    '        /* count-up + track fill on the same ease (the data-viz recipe) */\n'
    '        var st = { v: 0 };\n'
    '        tl.to(\n'
    '          st,\n'
    '          {\n'
    '            v: CONFIG.value,\n'
    '            duration: 1.6,\n'
    '            ease: "power2.out",\n'
    '            onUpdate: function () {\n'
    '              num.textContent = Math.round(st.v) + CONFIG.suffix;\n'
    '            },\n'
    '          },\n'
    '          0.5,\n'
    '        );\n'
    '        gsap.set(fill, { scaleX: 0 });\n'
    '        tl.to(fill, { scaleX: CONFIG.value / CONFIG.max, duration: 1.6,'
    ' ease: "power2.out" }, 0.5);'
)

#: Количество: тот же твин, но старт/длительность из `_count_timing` вместо их
#: фиксированных 0,5/1,6 — подставлены числом, без формулы в JS: `duration`
#: сцены уже известна в Python на момент сборки.
_COUNT_TWEEN_SCALED = (
    '        /* count-up + track fill, старт/длительность масштабированы под\n'
    '           сцену — reels-factory hf_schema._count_timing,\n'
    '           rb0907-university s-21, 07.09.2026 */\n'
    '        var st = { v: 0 };\n'
    '        tl.to(\n'
    '          st,\n'
    '          {\n'
    '            v: CONFIG.value,\n'
    '            duration: __COUNT_DURATION__,\n'
    '            ease: "power2.out",\n'
    '            onUpdate: function () {\n'
    '              num.textContent = Math.round(st.v) + CONFIG.suffix;\n'
    '            },\n'
    '          },\n'
    '          __COUNT_START__,\n'
    '        );\n'
    '        gsap.set(fill, { scaleX: 0 });\n'
    '        tl.to(fill, { scaleX: CONFIG.value / CONFIG.max, duration:'
    ' __COUNT_DURATION__, ease: "power2.out" }, __COUNT_START__);'
)

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
        # никакого «стольких» нет. Это и была та самая «3 из 100». Дата и
        # номер сюда больше не доходят вовсе — их перехватывает схемная ветка
        # `hf_compose` (`_is_dateline` + `date_variables`) ДО вызова `build()`
        # и монтирует компонентом `number-pop-in`, а не этим блоком.
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
        # Тот же твин их блока, но старт и длительность подогнаны под длину
        # сцены, а не фиксированы их числом — `_count_timing` (там же разбор
        # причины).
        start, count_duration = _count_timing(duration)
        patch = (_COUNT_TWEEN_SCALED
                .replace("__COUNT_DURATION__", f"{count_duration:.4f}")
                .replace("__COUNT_START__", f"{start:.4f}"))
        return block, config, css, ((_COUNT_TWEEN, patch),)

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
        # Кегль растим множителем от САМОЙ ДЛИННОЙ реальной строки — так
        # текст доходит до `lineWidth`, а не остаётся на исходной доле, какой
        # бы ни была фактическая длина (см. `_PAIRS_LABEL_FONT` выше). Множитель
        # держат двумя потолками разом: по ширине строки (не вылезти за
        # `lineWidth`) и по высоте колонки (не вылезти за `SAFE_BOTTOM` — та
        # же черта, что и `_SPECS_TOP` ниже), и общим потолком читаемости.
        line_width = OUT_W - 240
        widest = max(
            (len(row["label"]) * _PAIRS_LABEL_FONT
             + len(row["value"]) * _PAIRS_VALUE_FONT) * _GLYPH_RATIO
            for row in rows)
        scale_width = (line_width - _PAIRS_TEXT_GAP) / widest
        rows_n = len(rows)
        native_column = (rows_n * (_PAIRS_LABEL_FONT + _PAIRS_ROW_EXTRA)
                         + (rows_n - 1) * _PAIRS_ROW_GAP)
        scale_height = SAFE_BOTTOM / native_column
        scale = max(1.0, min(scale_width, scale_height, _PAIRS_MAX_SCALE))
        label_font = round(_PAIRS_LABEL_FONT * scale)
        value_font = round(_PAIRS_VALUE_FONT * scale)
        row_gap = round(_PAIRS_ROW_GAP * scale)
        config = {"scheme": "dark", "rows": rows, "underline": True,
                  "lineWidth": line_width, "scrim": 0,
                  "x": 120, "rowGap": row_gap}
        css += (f"\n      .mk-sl-label {{ font-size: {label_font}px; }}"
                f"\n      .mk-sl-value {{ font-size: {value_font}px; }}")
        # Их блок центрирует колонку по всей высоте канваса, и после подмены
        # канваса три строки садились на 799…1121 — нижнее подчёркивание уже в
        # полосе титра. Центрируем по безопасной высоте, а высоту ряда в их
        # же формуле поднимаем до нашего нового кегля (`_PAIRS_ROW_HEIGHT`) —
        # иначе центровка считала бы по кеглю 46, которого в кадре уже нет.
        return block, config, css, (
            _SPECS_TOP,
            (_PAIRS_ROW_HEIGHT,
             f"({label_font} + 22 + (CONFIG.underline ? 2 : 0))"))

    if form == "steps":
        nodes = list((content.get("nodes") or [])[:LIMITS["steps"]])
        limit = NODE_CHARS.get(len(nodes), 8)
        nodes = [_fit_label(node, limit) for node in nodes]
        count = max(1, len(nodes))
        gap = 70
        margin = 80
        # Коробка — от ширины кадра, а не от текста: `count` узлов в ряд
        # заполняют безопасную ширину целиком (пол 220 и потолок 360 держат
        # её в их собственных пропорциях при малом/большом счёте). До этой
        # правки коробка уже считалась от кадра, а кегль — нет: литерал 46 не
        # рос вместе с коробкой, и узел читался в разы мельче их дизайна
        # (`hw-pipeline.html:99-106`, коробка 320x170 при кегле 56).
        box = min(360, max(220, (OUT_W - margin - (count - 1) * gap) // count))
        # Досужка box'а — ДО кегля и высоты коробки: иначе при более тесных
        # `LIMITS`/`gap`/`margin`, чем сегодняшние, цикл сузил бы `box` уже
        # ПОСЛЕ того, как кегль и высота были бы подобраны под старое, большее
        # значение — подпись вылезла бы за новый, узкий край коробки без
        # единого упавшего теста (при нынешних константах цикл не срабатывает
        # ни разу — держит это мёртвым тест `test_hf_schema.py`).
        while count * box + (count - 1) * gap > OUT_W - margin and box > 180:
            box -= 20
        longest = max((len(node) for node in nodes), default=8)
        # Кегль — МЕНЬШИЙ из двух потолков: их же пропорция от коробки
        # (`_NODE_FONT_RATIO`) и гарантия, что самая длинная подпись при этом
        # кегле не вылезет из коробки (`_NODE_TEXT_PADDING` — запас на отступ
        # с обеих сторон). Не ниже читаемого пола HyperFrames для видео
        # (`_NODE_MIN_FONT`, 24 px).
        font_by_box = round(box * _NODE_FONT_RATIO)
        font_by_text = (int((box - _NODE_TEXT_PADDING) / (longest * _GLYPH_RATIO))
                       if longest else font_by_box)
        font = max(_NODE_MIN_FONT, min(font_by_box, font_by_text))
        y = round(OUT_H * 0.42)
        # Высота коробки — их же пропорция от кегля, урезанная безопасной
        # чертой: расти вместе с кеглем без верхнего предела значило бы
        # заехать на слова титра при малом счёте узлов (коробка шире —
        # кегль и высота больше).
        box_h = min(round(font * _NODE_BOXH_RATIO), SAFE_BOTTOM - y)
        config = {
            "nodes": [{"label": node} for node in nodes],
            "boxW": box, "boxH": box_h, "gap": gap,
            "y": y, "fontSize": font,
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
