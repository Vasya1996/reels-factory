# Справочник визуальных и монтажных приёмов

## Оглавление по категориям

- бренд и outro: 6
- субтитры и типографика: 17
- код и терминал: 10
- сравнение и процесс: 7
- композиционная раскладка: 3
- данные и статистика: 4
- карты и диаграммы: 11
- обработка медиа: 1
- социальные и editorial overlay: 11
- пространственное движение: 1
- раскладка с ведущим: 4
- текстура и finishing: 5
- титры и lower third: 13
- переход: 55
- VFX и shader: 9

### Анимированный счётчик числа

- ID: `animated_stat_countup`
- Категория: данные и статистика
- Availability: ready
- Что видит зритель: Зритель видит крупную цифру, которая быстро растёт до целевого значения.
- Когда применять: Когда в сценарии есть проверяемые числа, сравнения или динамика показателей.
- Когда не применять: Когда данные отсутствуют или не подтверждают произносимый тезис.
- Реализации: `local:block:stat_number`
- Внутренние variants: нет
- Управляемые поля: поле контракта label_bottom, поле контракта label_top, поле контракта prefix, поле контракта suffix, поле контракта value
- Placement: полный экран
- Готовность к 9:16: ready
- Необходимая адаптация: не требуется для ready-реализаций
- Dependencies и risks: явных нет
- Source evidence: plugins/reels-factory/engine/src/reels_factory/hyperframes_blocks.py:214-215

### Кодовый приём: Code Snippet - Apple Terminal Basic

- ID: `apple_terminal_theme_card`
- Категория: код и терминал
- Availability: adapt
- Что видит зритель: Зритель видит: окно macOS Terminal посимвольно печатает командную сессию; двенадцать implementations отличаются цветовой темой терминала.
- Когда применять: Когда речь действительно относится к коду, разработке или работе в терминале.
- Когда не применять: Когда технический интерфейс не связан с содержанием фразы.
- Реализации: `upstream:block:code-snippet-apple-terminal-basic`, `upstream:block:code-snippet-apple-terminal-clear-dark`, `upstream:block:code-snippet-apple-terminal-clear-light`, `upstream:block:code-snippet-apple-terminal-grass`, `upstream:block:code-snippet-apple-terminal-homebrew`, `upstream:block:code-snippet-apple-terminal-man-page`, `upstream:block:code-snippet-apple-terminal-novel`, `upstream:block:code-snippet-apple-terminal-ocean`, `upstream:block:code-snippet-apple-terminal-pro`, `upstream:block:code-snippet-apple-terminal-red-sands`, `upstream:block:code-snippet-apple-terminal-silver-aerogel`, `upstream:block:code-snippet-apple-terminal-solid-colors`
- Внутренние variants: реализация «Code Snippet - Apple Terminal Basic»; реализация «Code Snippet - Apple Terminal Clear Dark»; реализация «Code Snippet - Apple Terminal Clear Light»; реализация «Code Snippet - Apple Terminal Grass»; реализация «Code Snippet - Apple Terminal Homebrew»; реализация «Code Snippet - Apple Terminal Man Page»; реализация «Code Snippet - Apple Terminal Novel»; реализация «Code Snippet - Apple Terminal Ocean»; реализация «Code Snippet - Apple Terminal Pro»; реализация «Code Snippet - Apple Terminal Red Sands»; реализация «Code Snippet - Apple Terminal Silver Aerogel»; реализация «Code Snippet - Apple Terminal Solid Colors»
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/code-snippet-apple-terminal-basic/registry-item.json:6-6, registry/blocks/code-snippet-apple-terminal-clear-dark/registry-item.json:6-6, registry/blocks/code-snippet-apple-terminal-clear-light/registry-item.json:6-6, registry/blocks/code-snippet-apple-terminal-grass/registry-item.json:6-6, registry/blocks/code-snippet-apple-terminal-homebrew/registry-item.json:6-6, registry/blocks/code-snippet-apple-terminal-man-page/registry-item.json:6-6, registry/blocks/code-snippet-apple-terminal-novel/registry-item.json:6-6, registry/blocks/code-snippet-apple-terminal-ocean/registry-item.json:6-6, registry/blocks/code-snippet-apple-terminal-pro/registry-item.json:6-6, registry/blocks/code-snippet-apple-terminal-red-sands/registry-item.json:6-6, registry/blocks/code-snippet-apple-terminal-silver-aerogel/registry-item.json:6-6, registry/blocks/code-snippet-apple-terminal-solid-colors/registry-item.json:6-6

### Editorial collage из B-roll

- ID: `archival_broll_collage`
- Категория: композиционная раскладка
- Availability: ready
- Что видит зритель: Зритель видит наклонённые карточки с видео, штамп и подпись.
- Когда применять: Когда два или несколько смысловых слоёв нужно показать одновременно.
- Когда не применять: Когда split или collage делает главный объект слишком мелким.
- Реализации: `approved:layout:broll_archival_collage`
- Внутренние variants: нет
- Управляемые поля: поле контракта brollVideo, поле контракта purpose, поле контракта text
- Placement: полный экран
- Готовность к 9:16: ready
- Необходимая адаптация: не требуется для ready-реализаций
- Dependencies и risks: явных нет
- Source evidence: assets/catalog.js:341-357, assets/catalog.js:525-541

### Split screen: аватар и B-roll

- ID: `avatar_broll_split`
- Категория: композиционная раскладка
- Availability: ready
- Что видит зритель: Зритель видит две заполненные вертикальные области.
- Когда применять: Когда два или несколько смысловых слоёв нужно показать одновременно.
- Когда не применять: Когда split или collage делает главный объект слишком мелким.
- Реализации: `approved:layout:avatar_broll_split`
- Внутренние variants: нет
- Управляемые поля: поле контракта baseVideo, поле контракта brollVideo, поле контракта start
- Placement: полный экран
- Готовность к 9:16: ready
- Необходимая адаптация: не требуется для ready-реализаций
- Dependencies и risks: явных нет
- Source evidence: assets/catalog.js:332-339, assets/catalog.js:513-523

### Аватар в editorial bubble

- ID: `avatar_editorial_bubble`
- Категория: раскладка с ведущим
- Availability: ready
- Что видит зритель: Зритель видит avatar video в нестандартной рамке и текстовую колонку.
- Когда применять: Когда важно сохранить лицо и прямой контакт ведущего со зрителем.
- Когда не применять: Когда доказательный материал должен занять весь экран.
- Реализации: `approved:layout:avatar_editorial_bubble`
- Внутренние variants: нет
- Управляемые поля: поле контракта baseVideo, поле контракта purpose, поле контракта text
- Placement: полный экран
- Готовность к 9:16: ready
- Необходимая адаптация: не требуется для ready-реализаций
- Dependencies и risks: явных нет
- Source evidence: assets/catalog.js:234-254, assets/catalog.js:467-477

### Полноэкранный аватар-якорь

- ID: `avatar_fullscreen_anchor`
- Категория: раскладка с ведущим
- Availability: ready
- Что видит зритель: Зритель видит avatar video на весь вертикальный кадр.
- Когда применять: Когда важно сохранить лицо и прямой контакт ведущего со зрителем.
- Когда не применять: Когда доказательный материал должен занять весь экран.
- Реализации: `approved:layout:avatar_fullscreen`
- Внутренние variants: нет
- Управляемые поля: поле контракта emphasis, поле контракта id, поле контракта role, поле контракта start
- Placement: полный экран
- Готовность к 9:16: ready
- Необходимая адаптация: не требуется для ready-реализаций
- Dependencies и risks: явных нет
- Source evidence: assets/catalog.js:218-232, assets/catalog.js:453-465

### Аватар с предметным overlay

- ID: `avatar_object_overlay`
- Категория: социальные и editorial overlay
- Availability: ready
- Что видит зритель: Зритель видит avatar video, телефон, bubbles и стрелку.
- Когда применять: Когда сценарий ссылается на профиль, публикацию, уведомление или медиакарточку.
- Когда не применять: Когда показанный сервис или контент не упоминается в речи.
- Реализации: `approved:layout:avatar_object_overlay`
- Внутренние variants: нет
- Управляемые поля: поле контракта baseVideo, поле контракта hits
- Placement: overlay поверх кадра
- Готовность к 9:16: ready
- Необходимая адаптация: не требуется для ready-реализаций
- Dependencies и risks: явных нет
- Source evidence: assets/catalog.js:392-429, assets/catalog.js:557-571

### Сравнение «было → стало»

- ID: `before_after_comparison`
- Категория: сравнение и процесс
- Availability: ready
- Что видит зритель: Зритель видит две карточки и направленную смену между ними.
- Когда применять: Когда нужно показать изменение, порядок шагов или причинно-следственную связь.
- Когда не применять: Когда элементы не образуют понятную последовательность или сравнение.
- Реализации: `local:block:before_after`
- Внутренние variants: нет
- Управляемые поля: поле контракта after_label, поле контракта after_value, поле контракта before_label, поле контракта before_value
- Placement: полный экран
- Готовность к 9:16: ready
- Необходимая адаптация: не требуется для ready-реализаций
- Dependencies и risks: явных нет
- Source evidence: plugins/reels-factory/engine/src/reels_factory/hyperframes_blocks.py:294-295

### Мягкий blur-переход

- ID: `blur_soft_transition`
- Категория: переход
- Availability: ready
- Что видит зритель: Зритель видит слой, который становится резким.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `approved:transition:transition_blur`
- Внутренние variants: нет
- Управляемые поля: поле контракта id, поле контракта start, поле контракта transition
- Placement: полный экран
- Готовность к 9:16: ready
- Необходимая адаптация: не требуется для ready-реализаций
- Dependencies и risks: явных нет
- Source evidence: assets/catalog.js:587-618

### Брендовый приём: App Showcase

- ID: `brand_showcase_app_showcase`
- Категория: бренд и outro
- Availability: adapt
- Что видит зритель: Зритель видит: три парящих экрана смартфона последовательно показывают интерфейс фитнес-приложения.
- Когда применять: Когда нужно представить продукт, автора, логотип или завершить ролик CTA.
- Когда не применять: Когда брендовый экран прерывает объяснение до завершения мысли.
- Реализации: `upstream:block:app-showcase`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/app-showcase/registry-item.json:6-6

### Data-приём: Apple Money Count

- ID: `brand_showcase_apple_money_count`
- Категория: данные и статистика
- Availability: adapt
- Что видит зритель: Зритель видит: счётчик в стилистике Apple растёт от нуля до 10 000 долларов, вспыхивает зелёным и выпускает иконки денег.
- Когда применять: Когда в сценарии есть проверяемые числа, сравнения или динамика показателей.
- Когда не применять: Когда данные отсутствуют или не подтверждают произносимый тезис.
- Реализации: `upstream:block:apple-money-count`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/apple-money-count/registry-item.json:6-6

### Брендовый приём: Blue Sweater Intro Video

- ID: `brand_showcase_blue_sweater_intro_video`
- Категория: бренд и outro
- Availability: adapt
- Что видит зритель: Зритель видит: тёплая заставка AI-креатора собирается из нескольких кадров и завершается карточкой подписки на профиль X.
- Когда применять: Когда нужно представить продукт, автора, логотип или завершить ролик CTA.
- Когда не применять: Когда брендовый экран прерывает объяснение до завершения мысли.
- Реализации: `upstream:block:blue-sweater-intro-video`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: overlay поверх кадра
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/blue-sweater-intro-video/registry-item.json:6-6

### Брендовый приём: Logo Outro

- ID: `brand_showcase_logo_outro`
- Категория: бренд и outro
- Availability: adapt
- Что видит зритель: Зритель видит: фрагменты логотипа собираются в знак, появляется свечение, затем слоган и плашка с адресом сайта.
- Когда применять: Когда нужно представить продукт, автора, логотип или завершить ролик CTA.
- Когда не применять: Когда брендовый экран прерывает объяснение до завершения мысли.
- Реализации: `upstream:block:logo-outro`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/logo-outro/registry-item.json:6-6

### Картографический приём: NYC Paris Flight

- ID: `brand_showcase_nyc_paris_flight`
- Категория: карты и диаграммы
- Availability: adapt
- Что видит зритель: Зритель видит: на реалистичной карте самолёт летит из Нью-Йорка в Париж, после посадки появляются маркер и подпись.
- Когда применять: Когда география, маршрут или структура связей являются частью аргумента.
- Когда не применять: Когда карта или схема служит только декоративным фоном.
- Реализации: `upstream:block:nyc-paris-flight`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/nyc-paris-flight/registry-item.json:6-6

### Брендовый приём: VPN YouTube Spot

- ID: `brand_showcase_vpn_youtube_spot`
- Категория: бренд и outro
- Availability: adapt
- Что видит зритель: Зритель видит: телефон показывает поиск и установку VPN-приложения как короткую рекламную вставку в стилистике Apple.
- Когда применять: Когда нужно представить продукт, автора, логотип или завершить ролик CTA.
- Когда не применять: Когда брендовый экран прерывает объяснение до завершения мысли.
- Реализации: `upstream:block:vpn-youtube-spot`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/vpn-youtube-spot/registry-item.json:6-6

### Полноэкранный B-roll

- ID: `broll_fullscreen`
- Категория: композиционная раскладка
- Availability: ready
- Что видит зритель: Зритель видит вертикальный B-roll с мягким движением.
- Когда применять: Когда два или несколько смысловых слоёв нужно показать одновременно.
- Когда не применять: Когда split или collage делает главный объект слишком мелким.
- Реализации: `approved:layout:broll_fullscreen`
- Внутренние variants: нет
- Управляемые поля: поле контракта brollVideo, поле контракта start
- Placement: полный экран
- Готовность к 9:16: ready
- Необходимая адаптация: не требуется для ready-реализаций
- Dependencies и risks: явных нет
- Source evidence: assets/catalog.js:325-330, assets/catalog.js:506-511

### Caption-приём: Blend Difference

- ID: `caption_blend_difference`
- Категория: субтитры и типографика
- Availability: adapt
- Что видит зритель: Зритель видит: текст автоматически переключается между белым и чёрным по яркости фона благодаря mix-blend-mode: difference.
- Когда применять: Когда нужно выделить конкретные слова синхронно с речью.
- Когда не применять: Когда на экране одновременно должен читаться длинный абзац.
- Реализации: `upstream:component:caption-blend-difference`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: overlay поверх кадра
- Готовность к 9:16: ready
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: явных нет
- Source evidence: registry/components/caption-blend-difference/registry-item.json:6-6

### Caption-приём: Clip Wipe

- ID: `caption_clip_wipe`
- Категория: субтитры и типографика
- Availability: adapt
- Что видит зритель: Зритель видит: каждое слово субтитра открывается слева направо отдельной clip-path шторкой.
- Когда применять: Когда нужно выделить конкретные слова синхронно с речью.
- Когда не применять: Когда на экране одновременно должен читаться длинный абзац.
- Реализации: `upstream:component:caption-clip-wipe`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: overlay поверх кадра
- Готовность к 9:16: ready
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/components/caption-clip-wipe/registry-item.json:6-6

### Caption-приём: Editorial Emphasis

- ID: `caption_editorial_emphasis`
- Категория: субтитры и типографика
- Availability: adapt
- Что видит зритель: Зритель видит: две гарнитуры и резкий контраст кегля отделяют ключевые слова от остальной фразы.
- Когда применять: Когда нужно выделить конкретные слова синхронно с речью.
- Когда не применять: Когда на экране одновременно должен читаться длинный абзац.
- Реализации: `upstream:component:caption-editorial-emphasis`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: overlay поверх кадра
- Готовность к 9:16: ready
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/components/caption-editorial-emphasis/registry-item.json:6-6

### Caption-приём: Emoji Pop

- ID: `caption_emoji_pop`
- Категория: субтитры и типографика
- Availability: adapt
- Что видит зритель: Зритель видит: emoji появляется рядом с обведённым текстом, а строка входит через короткое горизонтальное сжатие.
- Когда применять: Когда нужно выделить конкретные слова синхронно с речью.
- Когда не применять: Когда на экране одновременно должен читаться длинный абзац.
- Реализации: `upstream:component:caption-emoji-pop`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: overlay поверх кадра
- Готовность к 9:16: ready
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/components/caption-emoji-pop/registry-item.json:6-6

### Caption-приём: Glitch RGB

- ID: `caption_glitch_rgb`
- Категория: субтитры и типографика
- Availability: adapt
- Что видит зритель: Зритель видит: у букв расходятся RGB-копии, а поверх текста появляются CRT-линии цифрового экрана.
- Когда применять: Когда нужно выделить конкретные слова синхронно с речью.
- Когда не применять: Когда на экране одновременно должен читаться длинный абзац.
- Реализации: `upstream:component:caption-glitch-rgb`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: overlay поверх кадра
- Готовность к 9:16: ready
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/components/caption-glitch-rgb/registry-item.json:6-6

### Caption-приём: Gradient Fill

- ID: `caption_gradient_fill`
- Категория: субтитры и типографика
- Availability: adapt
- Что видит зритель: Зритель видит: буквы заполняются цветным градиентом и входят с упругим bounce-движением.
- Когда применять: Когда нужно выделить конкретные слова синхронно с речью.
- Когда не применять: Когда на экране одновременно должен читаться длинный абзац.
- Реализации: `upstream:component:caption-gradient-fill`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: overlay поверх кадра
- Готовность к 9:16: ready
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/components/caption-gradient-fill/registry-item.json:6-6

### Caption-приём: Highlight

- ID: `caption_highlight`
- Категория: субтитры и типографика
- Availability: adapt
- Что видит зритель: Зритель видит: красная плашка проходит за активным словом и последовательно подсвечивает субтитр в TikTok-стиле.
- Когда применять: Когда нужно выделить конкретные слова синхронно с речью.
- Когда не применять: Когда на экране одновременно должен читаться длинный абзац.
- Реализации: `upstream:component:caption-highlight`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: overlay поверх кадра
- Готовность к 9:16: ready
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/components/caption-highlight/registry-item.json:6-6

### Caption-приём: Kinetic Slam

- ID: `caption_kinetic_slam`
- Категория: субтитры и типографика
- Availability: adapt
- Что видит зритель: Зритель видит: слова показываются по одному на весь экран и поочерёдно влетают с разных направлений.
- Когда применять: Когда нужно выделить конкретные слова синхронно с речью.
- Когда не применять: Когда на экране одновременно должен читаться длинный абзац.
- Реализации: `upstream:component:caption-kinetic-slam`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: overlay поверх кадра
- Готовность к 9:16: ready
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/components/caption-kinetic-slam/registry-item.json:6-6

### Caption-приём: Matrix Decode

- ID: `caption_matrix_decode`
- Категория: субтитры и типографика
- Availability: adapt
- Что видит зритель: Зритель видит: перед появлением правильной фразы символы быстро перебираются как при цифровой расшифровке.
- Когда применять: Когда нужно выделить конкретные слова синхронно с речью.
- Когда не применять: Когда на экране одновременно должен читаться длинный абзац.
- Реализации: `upstream:component:caption-matrix-decode`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: overlay поверх кадра
- Готовность к 9:16: ready
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/components/caption-matrix-decode/registry-item.json:6-6

### Caption-приём: Neon Accent

- ID: `caption_neon_accent`
- Категория: субтитры и типографика
- Availability: adapt
- Что видит зритель: Зритель видит: ключевые слова получают разноцветное неоновое свечение и лёгкий плавающий wiggle.
- Когда применять: Когда нужно выделить конкретные слова синхронно с речью.
- Когда не применять: Когда на экране одновременно должен читаться длинный абзац.
- Реализации: `upstream:component:caption-neon-accent`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: overlay поверх кадра
- Готовность к 9:16: ready
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/components/caption-neon-accent/registry-item.json:6-6

### Caption-приём: Neon Glow

- ID: `caption_neon_glow`
- Категория: субтитры и типографика
- Availability: adapt
- Что видит зритель: Зритель видит: субтитр светится голубым и пурпурным неоном, отдельные слова выделяются дополнительными цветами.
- Когда применять: Когда нужно выделить конкретные слова синхронно с речью.
- Когда не применять: Когда на экране одновременно должен читаться длинный абзац.
- Реализации: `upstream:component:caption-neon-glow`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: overlay поверх кадра
- Готовность к 9:16: ready
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/components/caption-neon-glow/registry-item.json:6-6

### Caption-приём: Parallax Layers

- ID: `caption_parallax_layers`
- Категория: субтитры и типографика
- Availability: adapt
- Что видит зритель: Зритель видит: крупный текст раскладывается слоями по глубине, проходит за объектом и растягивается по вертикали.
- Когда применять: Когда нужно выделить конкретные слова синхронно с речью.
- Когда не применять: Когда на экране одновременно должен читаться длинный абзац.
- Реализации: `upstream:component:caption-parallax-layers`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: overlay поверх кадра
- Готовность к 9:16: ready
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/components/caption-parallax-layers/registry-item.json:6-6

### Caption-приём: Particle Burst

- ID: `caption_particle_burst`
- Категория: субтитры и типографика
- Availability: adapt
- Что видит зритель: Зритель видит: при появлении ключевого слова из него разлетаются цветные частицы.
- Когда применять: Когда нужно выделить конкретные слова синхронно с речью.
- Когда не применять: Когда на экране одновременно должен читаться длинный абзац.
- Реализации: `upstream:component:caption-particle-burst`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: overlay поверх кадра
- Готовность к 9:16: ready
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/components/caption-particle-burst/registry-item.json:6-6

### Caption-приём: Pill Karaoke

- ID: `caption_pill_karaoke`
- Категория: субтитры и типографика
- Availability: adapt
- Что видит зритель: Зритель видит: фраза находится внутри округлой плашки, а произносимое слово последовательно меняет цвет.
- Когда применять: Когда нужно выделить конкретные слова синхронно с речью.
- Когда не применять: Когда на экране одновременно должен читаться длинный абзац.
- Реализации: `upstream:component:caption-pill-karaoke`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: overlay поверх кадра
- Готовность к 9:16: ready
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/components/caption-pill-karaoke/registry-item.json:6-6

### Caption-приём: Texture

- ID: `caption_texture`
- Категория: субтитры и типографика
- Availability: reference_only
- Что видит зритель: Зритель видит: крупные прописные буквы заполняются движущейся текстурой; variable texture переключает шесть встроенных материалов.
- Когда применять: Когда нужно выделить конкретные слова синхронно с речью.
- Когда не применять: Когда на экране одновременно должен читаться длинный абзац.
- Реализации: `upstream:component:caption-texture`
- Внутренние variants: нет
- Управляемые поля: поле контракта texture
- Placement: overlay поверх кадра
- Готовность к 9:16: ready
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/components/caption-texture/registry-item.json:6-6, registry/components/caption-texture/caption-texture.html:98-98

### Caption-приём: Weight Shift

- ID: `caption_weight_shift`
- Категория: субтитры и типографика
- Availability: adapt
- Что видит зритель: Зритель видит: при смене строки толщина шрифта плавно переходит от лёгкого начертания к жирному или обратно.
- Когда применять: Когда нужно выделить конкретные слова синхронно с речью.
- Когда не применять: Когда на экране одновременно должен читаться длинный абзац.
- Реализации: `upstream:component:caption-weight-shift`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: overlay поверх кадра
- Готовность к 9:16: ready
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/components/caption-weight-shift/registry-item.json:6-6

### Data-приём: Data Chart

- ID: `catalog_reference_data_chart`
- Категория: данные и статистика
- Availability: adapt
- Что видит зритель: Зритель видит: столбцы и линия графика появляются каскадом, после них раскрываются подписи и числовые значения.
- Когда применять: Когда в сценарии есть проверяемые числа, сравнения или динамика показателей.
- Когда не применять: Когда данные отсутствуют или не подтверждают произносимый тезис.
- Реализации: `upstream:block:data-chart`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/data-chart/registry-item.json:6-6

### Социальный overlay: Editorial Flash Overlay

- ID: `catalog_reference_editorial_flash_overlay`
- Категория: социальные и editorial overlay
- Availability: adapt
- Что видит зритель: Зритель видит: несколько нейтрально-тёплых световых слоёв создают управляемую вспышку камеры поверх монтажного стыка.
- Когда применять: Когда сценарий ссылается на профиль, публикацию, уведомление или медиакарточку.
- Когда не применять: Когда показанный сервис или контент не упоминается в речи.
- Реализации: `upstream:block:editorial-flash-overlay`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: overlay поверх кадра
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/editorial-flash-overlay/registry-item.json:6-6

### Переход: Grid Pixelate Wipe

- ID: `catalog_reference_grid_pixelate_wipe`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит: экран распадается на сетку квадратов, которые исчезают с задержкой и открывают следующую сцену.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:component:grid-pixelate-wipe`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: overlay поверх кадра
- Готовность к 9:16: ready
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: явных нет
- Source evidence: registry/components/grid-pixelate-wipe/registry-item.json:6-6

### Приём процесса: Morph Text

- ID: `catalog_reference_morph_text`
- Категория: сравнение и процесс
- Availability: adapt
- Что видит зритель: Зритель видит: слова из редактируемого списка текуче превращаются друг в друга через SVG threshold и управляемое размытие.
- Когда применять: Когда нужно показать изменение, порядок шагов или причинно-следственную связь.
- Когда не применять: Когда элементы не образуют понятную последовательность или сравнение.
- Реализации: `upstream:component:morph-text`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: overlay поверх кадра
- Готовность к 9:16: ready
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/components/morph-text/registry-item.json:6-6

### Картографический приём: North Korea Locked Down

- ID: `catalog_reference_north_korea_locked_down`
- Категория: карты и диаграммы
- Availability: adapt
- Что видит зритель: Зритель видит: карта приближается к Северной Корее, область обводится красной линией и получает плашку Locked Down.
- Когда применять: Когда география, маршрут или структура связей являются частью аргумента.
- Когда не применять: Когда карта или схема служит только декоративным фоном.
- Реализации: `upstream:block:north-korea-locked-down`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/north-korea-locked-down/registry-item.json:6-6

### Переход: Ridged Burn

- ID: `catalog_reference_ridged_burn`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит: шумовой shader создаёт неровный фронт прожига, который разрушает старый кадр и раскрывает новый.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:ridged-burn`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/ridged-burn/registry-item.json:6-6

### Зачёркивание рутины

- ID: `checklist_strike_routine`
- Категория: сравнение и процесс
- Availability: ready
- Что видит зритель: Зритель видит строки списка и красные линии зачёркивания.
- Когда применять: Когда нужно показать изменение, порядок шагов или причинно-следственную связь.
- Когда не применять: Когда элементы не образуют понятную последовательность или сравнение.
- Реализации: `approved:layout:checklist_strike`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: ready
- Необходимая адаптация: не требуется для ready-реализаций
- Dependencies и risks: явных нет
- Source evidence: assets/catalog.js:264-297, assets/catalog.js:479-492

### Chromatic accent-переход

- ID: `chromatic_accent_transition`
- Категория: переход
- Availability: ready
- Что видит зритель: Зритель видит короткую цветовую рассинхронизацию каналов.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `approved:transition:transition_chromatic`
- Внутренние variants: нет
- Управляемые поля: поле контракта id, поле контракта start, поле контракта transition
- Placement: полный экран
- Готовность к 9:16: ready
- Необходимая адаптация: не требуется для ready-реализаций
- Dependencies и risks: явных нет
- Source evidence: assets/catalog.js:587-618

### Кодовый приём: Code 3D Extrude

- ID: `code_3d_extrude`
- Категория: код и терминал
- Availability: adapt
- Что видит зритель: Зритель видит: подсвеченный код лежит на объёмной плите с фасками, вращается в WebGL-пространстве и останавливается для чтения.
- Когда применять: Когда речь действительно относится к коду, разработке или работе в терминале.
- Когда не применять: Когда технический интерфейс не связан с содержанием фразы.
- Реализации: `upstream:block:code-3d-extrude`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/code-3d-extrude/registry-item.json:6-6

### Кодовый приём: Code Diff

- ID: `code_diff`
- Категория: код и терминал
- Availability: reference_only
- Что видит зритель: Зритель видит: удалённые строки кода схлопываются красным, а добавленные раскрываются зелёным.
- Когда применять: Когда речь действительно относится к коду, разработке или работе в терминале.
- Когда не применять: Когда технический интерфейс не связан с содержанием фразы.
- Реализации: `upstream:block:code-diff`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.; Пока доступно только как reference, не runtime-ready.
- Source evidence: registry/blocks/code-diff/registry-item.json:6-6

### Кодовый приём: Code Snippet - Dark 2026

- ID: `code_editor_theme_card`
- Категория: код и терминал
- Availability: adapt
- Что видит зритель: Зритель видит: полный интерфейс VS Code посимвольно печатает код; тринадцать implementations меняют тему редактора или способ сборки сниппета.
- Когда применять: Когда речь действительно относится к коду, разработке или работе в терминале.
- Когда не применять: Когда технический интерфейс не связан с содержанием фразы.
- Реализации: `upstream:block:code-snippet-dark-2026`, `upstream:block:code-snippet-dark-modern`, `upstream:block:code-snippet-dark-plus`, `upstream:block:code-snippet-flight`, `upstream:block:code-snippet-high-contrast`, `upstream:block:code-snippet-high-contrast-light`, `upstream:block:code-snippet-light-2026`, `upstream:block:code-snippet-light-modern`, `upstream:block:code-snippet-light-plus`, `upstream:block:code-snippet-monokai`, `upstream:block:code-snippet-solarized-light`, `upstream:block:code-snippet-visual-studio-dark`, `upstream:block:code-snippet-visual-studio-light`
- Внутренние variants: реализация «Code Snippet - Dark 2026»; реализация «Code Snippet - Dark Modern»; реализация «Code Snippet - Dark+»; реализация «Code Snippet - High Contrast Light»; реализация «Code Snippet - High Contrast»; реализация «Code Snippet - Light 2026»; реализация «Code Snippet - Light Modern»; реализация «Code Snippet - Light+»; реализация «Code Snippet - Monokai»; реализация «Code Snippet - Solarized Light»; реализация «Code Snippet - Visual Studio Dark»; реализация «Code Snippet - Visual Studio Light»; реализация «Code Snippet Flight»
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/code-snippet-dark-2026/registry-item.json:6-6, registry/blocks/code-snippet-dark-modern/registry-item.json:6-6, registry/blocks/code-snippet-dark-plus/registry-item.json:6-6, registry/blocks/code-snippet-flight/registry-item.json:6-6, registry/blocks/code-snippet-high-contrast/registry-item.json:6-6, registry/blocks/code-snippet-high-contrast-light/registry-item.json:6-6, registry/blocks/code-snippet-light-2026/registry-item.json:6-6, registry/blocks/code-snippet-light-modern/registry-item.json:6-6, registry/blocks/code-snippet-light-plus/registry-item.json:6-6, registry/blocks/code-snippet-monokai/registry-item.json:6-6, registry/blocks/code-snippet-solarized-light/registry-item.json:6-6, registry/blocks/code-snippet-visual-studio-dark/registry-item.json:6-6, registry/blocks/code-snippet-visual-studio-light/registry-item.json:6-6

### Кодовый приём: Code Highlight Sweep

- ID: `code_highlight`
- Категория: код и терминал
- Availability: reference_only
- Что видит зритель: Зритель видит: светлая полоса проходит по выбранной строке кода, пока окружающий контекст затемняется.
- Когда применять: Когда речь действительно относится к коду, разработке или работе в терминале.
- Когда не применять: Когда технический интерфейс не связан с содержанием фразы.
- Реализации: `upstream:block:code-highlight`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.; Пока доступно только как reference, не runtime-ready.
- Source evidence: registry/blocks/code-highlight/registry-item.json:6-6

### Кодовый приём: Code Morph

- ID: `code_morph`
- Категория: код и терминал
- Availability: reference_only
- Что видит зритель: Зритель видит: токены первого сниппета перемещаются в позиции второго, исчезающие токены гаснут, новые проявляются.
- Когда применять: Когда речь действительно относится к коду, разработке или работе в терминале.
- Когда не применять: Когда технический интерфейс не связан с содержанием фразы.
- Реализации: `upstream:block:code-morph`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.; Пока доступно только как reference, не runtime-ready.
- Source evidence: registry/blocks/code-morph/registry-item.json:6-6

### Кодовый приём: Code Particle Assemble

- ID: `code_particle_assemble`
- Категория: код и терминал
- Availability: adapt
- Что видит зритель: Зритель видит: тысячи GPU-частиц слетаются к пикселям символов и собирают читаемый syntax-highlighted код.
- Когда применять: Когда речь действительно относится к коду, разработке или работе в терминале.
- Когда не применять: Когда технический интерфейс не связан с содержанием фразы.
- Реализации: `upstream:block:code-particle-assemble`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/code-particle-assemble/registry-item.json:6-6

### Кодовый приём: Code Scroll To Line

- ID: `code_scroll`
- Категория: код и терминал
- Availability: reference_only
- Что видит зритель: Зритель видит: камера прокручивает длинный файл до целевой строки, ставит её в центр и подсвечивает.
- Когда применять: Когда речь действительно относится к коду, разработке или работе в терминале.
- Когда не применять: Когда технический интерфейс не связан с содержанием фразы.
- Реализации: `upstream:block:code-scroll`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.; Пока доступно только как reference, не runtime-ready.
- Source evidence: registry/blocks/code-scroll/registry-item.json:6-6

### Кодовый приём: Code Shader Dissolve

- ID: `code_shader_dissolve`
- Категория: код и терминал
- Availability: adapt
- Что видит зритель: Зритель видит: код проявляется из seeded noise через цветной shader-фронт, затем остаётся резким и читаемым.
- Когда применять: Когда речь действительно относится к коду, разработке или работе в терминале.
- Когда не применять: Когда технический интерфейс не связан с содержанием фразы.
- Реализации: `upstream:block:code-shader-dissolve`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/code-shader-dissolve/registry-item.json:6-6

### Социальный overlay: VFX Text Cursor

- ID: `code_text_cursor`
- Категория: социальные и editorial overlay
- Availability: adapt
- Что видит зритель: Зритель видит: текст проявляется за светящимся курсором с хроматическими лучами и направленным освещением на чёрном фоне.
- Когда применять: Когда сценарий ссылается на профиль, публикацию, уведомление или медиакарточку.
- Когда не применять: Когда показанный сервис или контент не упоминается в речи.
- Реализации: `upstream:block:vfx-text-cursor`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: overlay поверх кадра
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/vfx-text-cursor/registry-item.json:6-6

### Кодовый приём: Code Typing

- ID: `code_typing`
- Категория: код и терминал
- Availability: reference_only
- Что видит зритель: Зритель видит: код печатается потоком токенов, а каретка точно следует за границей уже показанного текста.
- Когда применять: Когда речь действительно относится к коду, разработке или работе в терминале.
- Когда не применять: Когда технический интерфейс не связан с содержанием фразы.
- Реализации: `upstream:block:code-typing`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.; Пока доступно только как reference, не runtime-ready.
- Source evidence: registry/blocks/code-typing/registry-item.json:6-6

### Схлопывание сложности в решение

- ID: `complexity_to_resolution`
- Категория: сравнение и процесс
- Availability: ready
- Что видит зритель: Зритель видит россыпь карточек, которая сменяется центральной карточкой решения.
- Когда применять: Когда нужно показать изменение, порядок шагов или причинно-следственную связь.
- Когда не применять: Когда элементы не образуют понятную последовательность или сравнение.
- Реализации: `local:block:complexity_cloud`
- Внутренние variants: нет
- Управляемые поля: поле контракта items, поле контракта resolution, поле контракта title
- Placement: полный экран
- Готовность к 9:16: ready
- Необходимая адаптация: не требуется для ready-реализаций
- Dependencies и risks: явных нет
- Source evidence: plugins/reels-factory/engine/src/reels_factory/hyperframes_blocks.py:374-375

### Карта связанных понятий

- ID: `concept_node_map`
- Категория: карты и диаграммы
- Availability: ready
- Что видит зритель: Зритель видит hub в центре и карточки вокруг него.
- Когда применять: Когда география, маршрут или структура связей являются частью аргумента.
- Когда не применять: Когда карта или схема служит только декоративным фоном.
- Реализации: `local:block:concept_nodes`
- Внутренние variants: нет
- Управляемые поля: поле контракта items, поле контракта title
- Placement: полный экран
- Готовность к 9:16: ready
- Необходимая адаптация: не требуется для ready-реализаций
- Dependencies и risks: явных нет
- Source evidence: plugins/reels-factory/engine/src/reels_factory/hyperframes_blocks.py:496-497

### Editorial push-переход

- ID: `editorial_push_transition`
- Категория: переход
- Availability: ready
- Что видит зритель: Зритель видит горизонтальный push нового layout.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `approved:transition:transition_push_editorial`
- Внутренние variants: нет
- Управляемые поля: поле контракта id, поле контракта start, поле контракта transition
- Placement: полный экран
- Готовность к 9:16: ready
- Необходимая адаптация: не требуется для ready-реализаций
- Dependencies и risks: явных нет
- Source evidence: assets/catalog.js:587-618

### Запрещённый исторический cutout overlay

- ID: `forbidden_avatar_cutout_overlay`
- Категория: раскладка с ведущим
- Availability: forbidden
- Что видит зритель: Зритель видит статичный cutout человека поверх editorial карточек.
- Когда применять: Когда важно сохранить лицо и прямой контакт ведущего со зрителем.
- Когда не применять: Когда доказательный материал должен занять весь экран.
- Реализации: `approved:layout:avatar_cutout_overlay`
- Внутренние variants: нет
- Управляемые поля: поле контракта cutoutImage, поле контракта emphasis
- Placement: overlay поверх кадра
- Готовность к 9:16: ready
- Необходимая адаптация: не требуется для ready-реализаций
- Dependencies и risks: Историческая реализация запрещена актуальными решениями проекта.; Среди implementations есть запрещённая историческая реализация.
- Source evidence: assets/catalog.js:359-390, assets/catalog.js:543-555

### Жёсткий монтажный стык

- ID: `hard_cut_transition`
- Категория: переход
- Availability: ready
- Что видит зритель: Зритель видит чистую моментальную смену одного кадра другим.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `approved:transition:hard_cut`
- Внутренние variants: нет
- Управляемые поля: поле контракта id, поле контракта start, поле контракта transition
- Placement: полный экран
- Готовность к 9:16: ready
- Необходимая адаптация: не требуется для ready-реализаций
- Dependencies и risks: явных нет
- Source evidence: assets/catalog.js:587-618

### Титровый приём: Lower Third — Accent Underline

- ID: `lower_third_accent_underline`
- Категория: титры и lower third
- Availability: adapt
- Что видит зритель: Зритель видит: имя поднимается поверх видео, акцентная линия рисуется слева направо, затем проявляется должность.
- Когда применять: Когда нужно представить спикера, источник или постоянную рубрику.
- Когда не применять: Когда нижняя зона закрывает важную часть лица или демонстрации.
- Реализации: `upstream:block:lt-accent-underline`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: нижняя титровая зона
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/lt-accent-underline/registry-item.json:6-6

### Титровый приём: Lower Third — BILD Style

- ID: `lower_third_bild`
- Категория: титры и lower third
- Availability: adapt
- Что видит зритель: Зритель видит: новостной lower third использует белую плашку заголовка и красную строку с контрастными тенями в стиле BILD.
- Когда применять: Когда нужно представить спикера, источник или постоянную рубрику.
- Когда не применять: Когда нижняя зона закрывает важную часть лица или демонстрации.
- Реализации: `upstream:block:lower-third-bild`
- Внутренние variants: нет
- Управляемые поля: поле контракта TXT_MAIN_1_Line, поле контракта TXT_SUB
- Placement: нижняя титровая зона
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/lower-third-bild/registry-item.json:6-6, registry/blocks/lower-third-bild/lower-third-bild.html:97-97

### Титровый приём: Lower Third — Bold Block

- ID: `lower_third_bold_block`
- Категория: титры и lower third
- Availability: adapt
- Что видит зритель: Зритель видит: тёмный прямоугольник закрывает нижнюю часть кадра, имя резко входит снизу, акцентный тег подпрыгивает.
- Когда применять: Когда нужно представить спикера, источник или постоянную рубрику.
- Когда не применять: Когда нижняя зона закрывает важную часть лица или демонстрации.
- Реализации: `upstream:block:lt-bold-block`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: нижняя титровая зона
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/lt-bold-block/registry-item.json:6-6

### Титровый приём: Lower Third — Clean Bar

- ID: `lower_third_clean_bar`
- Категория: титры и lower third
- Availability: adapt
- Что видит зритель: Зритель видит: минималистичная белая карточка открывается clip-wipe, показывая цветной tab, имя и должность.
- Когда применять: Когда нужно представить спикера, источник или постоянную рубрику.
- Когда не применять: Когда нижняя зона закрывает важную часть лица или демонстрации.
- Реализации: `upstream:block:lt-clean-bar`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: нижняя титровая зона
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/lt-clean-bar/registry-item.json:6-6

### Титровый приём: Lower Third — Color Block

- ID: `lower_third_color_block`
- Категория: титры и lower third
- Availability: adapt
- Что видит зритель: Зритель видит: яркий цветной блок въезжает с overshoot и показывает крупное имя с моноширинной должностью.
- Когда применять: Когда нужно представить спикера, источник или постоянную рубрику.
- Когда не применять: Когда нижняя зона закрывает важную часть лица или демонстрации.
- Реализации: `upstream:block:lt-color-block`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: нижняя титровая зона
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/lt-color-block/registry-item.json:6-6

### Титровый приём: Lower Third — Dark Card

- ID: `lower_third_dark_card`
- Категория: титры и lower third
- Availability: adapt
- Что видит зритель: Зритель видит: тёмная карточка поднимается поверх светлого видео, после имени рисуется акцентная линия и появляется должность.
- Когда применять: Когда нужно представить спикера, источник или постоянную рубрику.
- Когда не применять: Когда нижняя зона закрывает важную часть лица или демонстрации.
- Реализации: `upstream:block:lt-dark-card`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: нижняя титровая зона
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/lt-dark-card/registry-item.json:6-6

### Титровый приём: Lower Third — Kicker Name

- ID: `lower_third_kicker_name`
- Категория: титры и lower third
- Availability: adapt
- Что видит зритель: Зритель видит: над крупным именем появляется небольшой цветной kicker, а снизу прорисовывается базовая линия.
- Когда применять: Когда нужно представить спикера, источник или постоянную рубрику.
- Когда не применять: Когда нижняя зона закрывает важную часть лица или демонстрации.
- Реализации: `upstream:block:lt-kicker-name`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: нижняя титровая зона
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/lt-kicker-name/registry-item.json:6-6

### Титровый приём: Lower Third — Mask Reveal

- ID: `lower_third_mask_reveal`
- Категория: титры и lower third
- Availability: adapt
- Что видит зритель: Зритель видит: цветная полоса проходит по нижней части кадра и через clip-path открывает имя, затем проявляется должность.
- Когда применять: Когда нужно представить спикера, источник или постоянную рубрику.
- Когда не применять: Когда нижняя зона закрывает важную часть лица или демонстрации.
- Реализации: `upstream:block:lt-mask-reveal`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: нижняя титровая зона
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/lt-mask-reveal/registry-item.json:6-6

### Титровый приём: News Ticker

- ID: `lower_third_news_ticker`
- Категория: титры и lower third
- Availability: adapt
- Что видит зритель: Зритель видит: эфирная плашка объединяет индикатор LIVE, основной заголовок и непрерывно движущуюся новостную строку.
- Когда применять: Когда нужно представить спикера, источник или постоянную рубрику.
- Когда не применять: Когда нижняя зона закрывает важную часть лица или демонстрации.
- Реализации: `upstream:block:news-ticker`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: нижняя титровая зона
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/news-ticker/registry-item.json:6-6

### Титровый приём: Lower Third — Side Rule

- ID: `lower_third_side_rule`
- Категория: титры и lower third
- Availability: adapt
- Что видит зритель: Зритель видит: вертикальная цветная линия закрепляет слева имя и моноширинную должность без фоновой карточки.
- Когда применять: Когда нужно представить спикера, источник или постоянную рубрику.
- Когда не применять: Когда нижняя зона закрывает важную часть лица или демонстрации.
- Реализации: `upstream:block:lt-side-rule`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: нижняя титровая зона
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/lt-side-rule/registry-item.json:6-6

### Титровый приём: Lower Third — Soft Pill

- ID: `lower_third_soft_pill`
- Категория: титры и lower third
- Availability: adapt
- Что видит зритель: Зритель видит: белая округлая плашка появляется через scale-pop и показывает status dot, имя и должность.
- Когда применять: Когда нужно представить спикера, источник или постоянную рубрику.
- Когда не применять: Когда нижняя зона закрывает важную часть лица или демонстрации.
- Реализации: `upstream:block:lt-soft-pill`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: нижняя титровая зона
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/lt-soft-pill/registry-item.json:6-6

### Титровый приём: Lower Third — Stack Bars

- ID: `lower_third_stack_bars`
- Категория: титры и lower third
- Availability: adapt
- Что видит зритель: Зритель видит: тёмная полоса имени входит слева, а цветная полоса должности — справа, образуя два уровня титра.
- Когда применять: Когда нужно представить спикера, источник или постоянную рубрику.
- Когда не применять: Когда нижняя зона закрывает важную часть лица или демонстрации.
- Реализации: `upstream:block:lt-stack-bars`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: нижняя титровая зона
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/lt-stack-bars/registry-item.json:6-6

### Титровый приём: YouTube Lower Third

- ID: `lower_third_yt_lower_third`
- Категория: титры и lower third
- Availability: adapt
- Что видит зритель: Зритель видит: карточка YouTube с аватаром, названием канала и кнопкой подписки анимированно входит в нижнюю часть кадра.
- Когда применять: Когда нужно представить спикера, источник или постоянную рубрику.
- Когда не применять: Когда нижняя зона закрывает важную часть лица или демонстрации.
- Реализации: `upstream:block:yt-lower-third`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: нижняя титровая зона
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/yt-lower-third/registry-item.json:6-6

### Картографический приём: Flowchart

- ID: `map_diagram_flowchart`
- Категория: карты и диаграммы
- Availability: reference_only
- Что видит зритель: Зритель видит: узлы decision tree появляются как стикеры, соединяются SVG-линиями, курсор исправляет набранный текст.
- Когда применять: Когда география, маршрут или структура связей являются частью аргумента.
- Когда не применять: Когда карта или схема служит только декоративным фоном.
- Реализации: `upstream:block:flowchart`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.; Пока доступно только как reference, не runtime-ready.
- Source evidence: registry/blocks/flowchart/registry-item.json:6-6

### Картографический приём: Flowchart Vertical

- ID: `map_diagram_flowchart_vertical`
- Категория: карты и диаграммы
- Availability: reference_only
- Что видит зритель: Зритель видит: вертикальное дерево решений для 9:16 раскрывает стикеры сверху вниз и соединяет их SVG-линиями.
- Когда применять: Когда география, маршрут или структура связей являются частью аргумента.
- Когда не применять: Когда карта или схема служит только декоративным фоном.
- Реализации: `upstream:block:flowchart-vertical`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: ready
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.; Пока доступно только как reference, не runtime-ready.
- Source evidence: registry/blocks/flowchart-vertical/registry-item.json:6-6

### Картографический приём: Spain Map

- ID: `map_diagram_spain_map`
- Категория: карты и диаграммы
- Availability: adapt
- Что видит зритель: Зритель видит: регионы Испании последовательно окрашиваются по значению, рядом появляется градиентная легенда.
- Когда применять: Когда география, маршрут или структура связей являются частью аргумента.
- Когда не применять: Когда карта или схема служит только декоративным фоном.
- Реализации: `upstream:block:spain-map`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/spain-map/registry-item.json:6-6

### Картографический приём: US Map

- ID: `map_diagram_us_map`
- Категория: карты и диаграммы
- Availability: adapt
- Что видит зритель: Зритель видит: штаты США каскадом получают цвет данных, числовые подписи и общую градиентную легенду.
- Когда применять: Когда география, маршрут или структура связей являются частью аргумента.
- Когда не применять: Когда карта или схема служит только декоративным фоном.
- Реализации: `upstream:block:us-map`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/us-map/registry-item.json:6-6

### Картографический приём: US Bubble Map

- ID: `map_diagram_us_map_bubble`
- Категория: карты и диаграммы
- Availability: adapt
- Что видит зритель: Зритель видит: на карте США вырастают круги пропорционального размера с подписями городов и значений.
- Когда применять: Когда география, маршрут или структура связей являются частью аргумента.
- Когда не применять: Когда карта или схема служит только декоративным фоном.
- Реализации: `upstream:block:us-map-bubble`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/us-map-bubble/registry-item.json:6-6

### Картографический приём: US Flow Map

- ID: `map_diagram_us_map_flow`
- Категория: карты и диаграммы
- Availability: adapt
- Что видит зритель: Зритель видит: между городами США прорисовываются дуги маршрутов, показывающие направление потоков.
- Когда применять: Когда география, маршрут или структура связей являются частью аргумента.
- Когда не применять: Когда карта или схема служит только декоративным фоном.
- Реализации: `upstream:block:us-map-flow`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/us-map-flow/registry-item.json:6-6

### Картографический приём: US Hex Grid Map

- ID: `map_diagram_us_map_hex`
- Категория: карты и диаграммы
- Availability: adapt
- Что видит зритель: Зритель видит: каждый штат показан равновесным шестиугольником с аббревиатурой и цветом значения.
- Когда применять: Когда география, маршрут или структура связей являются частью аргумента.
- Когда не применять: Когда карта или схема служит только декоративным фоном.
- Реализации: `upstream:block:us-map-hex`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/us-map-hex/registry-item.json:6-6

### Картографический приём: World Map

- ID: `map_diagram_world_map`
- Категория: карты и диаграммы
- Availability: adapt
- Что видит зритель: Зритель видит: страны мира последовательно окрашиваются по данным, появляются tooltip-подписи и небольшой вращающийся глобус.
- Когда применять: Когда география, маршрут или структура связей являются частью аргумента.
- Когда не применять: Когда карта или схема служит только декоративным фоном.
- Реализации: `upstream:block:world-map`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/world-map/registry-item.json:6-6

### Финишная текстура: Camcorder HUD

- ID: `media_treatment_camcorder_hud`
- Категория: текстура и finishing
- Availability: adapt
- Что видит зритель: Зритель видит: поверх видео появляются REC, батарея, дата и счётчик времени, имитирующие интерфейс любительской камеры.
- Когда применять: Когда всему кадру нужна единая фактура или дополнительный фокус.
- Когда не применять: Когда обработка ухудшает читаемость текста и деталей лица.
- Реализации: `upstream:block:camcorder-hud`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: overlay поверх кадра
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/camcorder-hud/registry-item.json:6-6

### Социальный overlay: Freeze-Frame Dressing

- ID: `media_treatment_freeze_frame_dressing`
- Категория: социальные и editorial overlay
- Availability: adapt
- Что видит зритель: Зритель видит: стоп-кадр или вырезанный объект оформляется слоями бумаги, скотча и короткими вспышками.
- Когда применять: Когда сценарий ссылается на профиль, публикацию, уведомление или медиакарточку.
- Когда не применять: Когда показанный сервис или контент не упоминается в речи.
- Реализации: `upstream:block:freeze-frame-dressing`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: overlay поверх кадра
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/freeze-frame-dressing/registry-item.json:6-6

### Финишная текстура: Grain Overlay

- ID: `media_treatment_grain_overlay`
- Категория: текстура и finishing
- Availability: adapt
- Что видит зритель: Зритель видит: поверх всей композиции движется мелкое плёночное зерно, добавляющее аналоговую фактуру.
- Когда применять: Когда всему кадру нужна единая фактура или дополнительный фокус.
- Когда не применять: Когда обработка ухудшает читаемость текста и деталей лица.
- Реализации: `upstream:component:grain-overlay`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: overlay поверх кадра
- Готовность к 9:16: ready
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: явных нет
- Source evidence: registry/components/grain-overlay/registry-item.json:6-6

### Финишная текстура: Shimmer Sweep

- ID: `media_treatment_shimmer_sweep`
- Категория: текстура и finishing
- Availability: adapt
- Что видит зритель: Зритель видит: узкая световая полоса проходит по тексту или объекту через градиентную маску.
- Когда применять: Когда всему кадру нужна единая фактура или дополнительный фокус.
- Когда не применять: Когда обработка ухудшает читаемость текста и деталей лица.
- Реализации: `upstream:component:shimmer-sweep`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: overlay поверх кадра
- Готовность к 9:16: ready
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: явных нет
- Source evidence: registry/components/shimmer-sweep/registry-item.json:6-6

### Финишная текстура: Texture Mask Text

- ID: `media_treatment_texture_mask_text`
- Категория: текстура и finishing
- Availability: adapt
- Что видит зритель: Зритель видит: шестьдесят шесть luminance-масок вырезают фактурные отверстия внутри букв.
- Когда применять: Когда всему кадру нужна единая фактура или дополнительный фокус.
- Когда не применять: Когда обработка ухудшает читаемость текста и деталей лица.
- Реализации: `upstream:component:texture-mask-text`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: overlay поверх кадра
- Готовность к 9:16: ready
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: явных нет
- Source evidence: registry/components/texture-mask-text/registry-item.json:6-6

### Финишная текстура: Vignette

- ID: `media_treatment_vignette`
- Категория: текстура и finishing
- Availability: adapt
- Что видит зритель: Зритель видит: радиальный CSS-градиент затемняет края изображения и удерживает внимание в центре.
- Когда применять: Когда всему кадру нужна единая фактура или дополнительный фокус.
- Когда не применять: Когда обработка ухудшает читаемость текста и деталей лица.
- Реализации: `upstream:component:vignette`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: overlay поверх кадра
- Готовность к 9:16: ready
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: явных нет
- Source evidence: registry/components/vignette/registry-item.json:6-6

### Карточка аудитории

- ID: `persona_context_card`
- Категория: раскладка с ведущим
- Availability: ready
- Что видит зритель: Зритель видит avatar-mark и строки с характеристиками ситуации.
- Когда применять: Когда важно сохранить лицо и прямой контакт ведущего со зрителем.
- Когда не применять: Когда доказательный материал должен занять весь экран.
- Реализации: `local:block:persona_card`
- Внутренние variants: нет
- Управляемые поля: поле контракта items, поле контракта title
- Placement: полный экран
- Готовность к 9:16: ready
- Необходимая адаптация: не требуется для ready-реализаций
- Dependencies и risks: явных нет
- Source evidence: plugins/reels-factory/engine/src/reels_factory/hyperframes_blocks.py:423-424

### Прогрессивная типографическая карточка

- ID: `progressive_text_card`
- Категория: субтитры и типографика
- Availability: ready
- Что видит зритель: Зритель видит большие слова, которые появляются по очереди.
- Когда применять: Когда нужно выделить конкретные слова синхронно с речью.
- Когда не применять: Когда на экране одновременно должен читаться длинный абзац.
- Реализации: `approved:layout:progressive_text_card`
- Внутренние variants: нет
- Управляемые поля: поле контракта emphasis, поле контракта hits, поле контракта purpose
- Placement: полный экран
- Готовность к 9:16: ready
- Необходимая адаптация: не требуется для ready-реализаций
- Dependencies и risks: явных нет
- Source evidence: assets/catalog.js:299-323, assets/catalog.js:494-504

### Вертикальный flow шагов

- ID: `sequence_step_flow`
- Категория: сравнение и процесс
- Availability: ready
- Что видит зритель: Зритель видит нумерованные карточки со стрелками между ними.
- Когда применять: Когда нужно показать изменение, порядок шагов или причинно-следственную связь.
- Когда не применять: Когда элементы не образуют понятную последовательность или сравнение.
- Реализации: `local:block:sequence_flow`
- Внутренние variants: нет
- Управляемые поля: поле контракта items, поле контракта title
- Placement: полный экран
- Готовность к 9:16: ready
- Необходимая адаптация: не требуется для ready-реализаций
- Dependencies и risks: явных нет
- Source evidence: plugins/reels-factory/engine/src/reels_factory/hyperframes_blocks.py:540-541

### Финальный social outro lockup

- ID: `social_outro_lockup`
- Категория: бренд и outro
- Availability: ready
- Что видит зритель: Зритель видит крупный призыв, handle и кнопку.
- Когда применять: Когда нужно представить продукт, автора, логотип или завершить ролик CTA.
- Когда не применять: Когда брендовый экран прерывает объяснение до завершения мысли.
- Реализации: `approved:layout:social_outro`
- Внутренние variants: нет
- Управляемые поля: поле контракта id
- Placement: overlay поверх кадра
- Готовность к 9:16: ready
- Необходимая адаптация: не требуется для ready-реализаций
- Dependencies и risks: явных нет
- Source evidence: assets/catalog.js:431-451, assets/catalog.js:573-585

### Социальный overlay: Instagram Follow

- ID: `social_overlay_instagram_follow`
- Категория: социальные и editorial overlay
- Availability: adapt
- Что видит зритель: Зритель видит: поверх видео появляется Instagram-профиль с аватаром и анимированной кнопкой Follow.
- Когда применять: Когда сценарий ссылается на профиль, публикацию, уведомление или медиакарточку.
- Когда не применять: Когда показанный сервис или контент не упоминается в речи.
- Реализации: `upstream:block:instagram-follow`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: overlay поверх кадра
- Готовность к 9:16: ready
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/instagram-follow/registry-item.json:6-6

### Социальный overlay: Liquid Glass Notification

- ID: `social_overlay_liquid_glass_notification`
- Категория: социальные и editorial overlay
- Availability: adapt
- Что видит зритель: Зритель видит: матовые стеклянные уведомления плавают над цветным aurora shader-фоном.
- Когда применять: Когда сценарий ссылается на профиль, публикацию, уведомление или медиакарточку.
- Когда не применять: Когда показанный сервис или контент не упоминается в речи.
- Реализации: `upstream:block:liquid-glass-notification`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: overlay поверх кадра
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/liquid-glass-notification/registry-item.json:6-6

### Социальный overlay: macOS Notification

- ID: `social_overlay_macos_notification`
- Категория: социальные и editorial overlay
- Availability: adapt
- Что видит зритель: Зритель видит: в верхней части кадра появляется системное уведомление macOS с иконкой приложения и текстом.
- Когда применять: Когда сценарий ссылается на профиль, публикацию, уведомление или медиакарточку.
- Когда не применять: Когда показанный сервис или контент не упоминается в речи.
- Реализации: `upstream:block:macos-notification`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: overlay поверх кадра
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/macos-notification/registry-item.json:6-6

### Социальный overlay: Reddit Post Card

- ID: `social_overlay_reddit_post`
- Категория: социальные и editorial overlay
- Availability: adapt
- Что видит зритель: Зритель видит: карточка Reddit показывает пост, рейтинг голосов и число комментариев поверх основного кадра.
- Когда применять: Когда сценарий ссылается на профиль, публикацию, уведомление или медиакарточку.
- Когда не применять: Когда показанный сервис или контент не упоминается в речи.
- Реализации: `upstream:block:reddit-post`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: overlay поверх кадра
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/reddit-post/registry-item.json:6-6

### Социальный overlay: Spotify Now Playing

- ID: `social_overlay_spotify_card`
- Категория: социальные и editorial overlay
- Availability: adapt
- Что видит зритель: Зритель видит: карточка Spotify показывает обложку, текущий трек и движущийся progress bar.
- Когда применять: Когда сценарий ссылается на профиль, публикацию, уведомление или медиакарточку.
- Когда не применять: Когда показанный сервис или контент не упоминается в речи.
- Реализации: `upstream:block:spotify-card`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: overlay поверх кадра
- Готовность к 9:16: ready
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/spotify-card/registry-item.json:6-6

### Социальный overlay: TikTok Follow

- ID: `social_overlay_tiktok_follow`
- Категория: социальные и editorial overlay
- Availability: adapt
- Что видит зритель: Зритель видит: поверх видео появляется TikTok-профиль с аватаром и анимированной кнопкой подписки.
- Когда применять: Когда сценарий ссылается на профиль, публикацию, уведомление или медиакарточку.
- Когда не применять: Когда показанный сервис или контент не упоминается в речи.
- Реализации: `upstream:block:tiktok-follow`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: overlay поверх кадра
- Готовность к 9:16: ready
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/tiktok-follow/registry-item.json:6-6

### Социальный overlay: X Post Card

- ID: `social_overlay_x_post`
- Категория: социальные и editorial overlay
- Availability: adapt
- Что видит зритель: Зритель видит: карточка поста X показывает текст публикации и счётчики реакций.
- Когда применять: Когда сценарий ссылается на профиль, публикацию, уведомление или медиакарточку.
- Когда не применять: Когда показанный сервис или контент не упоминается в речи.
- Реализации: `upstream:block:x-post`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: overlay поверх кадра
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/x-post/registry-item.json:6-6

### Шлейф от быстрого движения

- ID: `spatial_motion_blur`
- Категория: пространственное движение
- Availability: reference_only
- Что видит зритель: Зритель видит смазанный шлейф за движущимся объектом внутри сцены; это не переход между сценами.
- Когда применять: Когда движение объекта должно ощущаться быстрым, инерционным или объёмным.
- Когда не применять: Когда элемент почти неподвижен и эффект не будет заметен.
- Реализации: `upstream:component:motion-blur`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: overlay поверх кадра
- Готовность к 9:16: ready
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Пока доступно только как reference, не runtime-ready.
- Source evidence: registry/components/motion-blur/registry-item.json:6-6

### Пошаговый список с акцентом

- ID: `task_checklist_reveal`
- Категория: сравнение и процесс
- Availability: ready
- Что видит зритель: Зритель видит вертикальный список с номерами и акцентной финальной строкой.
- Когда применять: Когда нужно показать изменение, порядок шагов или причинно-следственную связь.
- Когда не применять: Когда элементы не образуют понятную последовательность или сравнение.
- Реализации: `local:block:task_list`
- Внутренние variants: нет
- Управляемые поля: поле контракта items, поле контракта title
- Placement: полный экран
- Готовность к 9:16: ready
- Необходимая адаптация: не требуется для ready-реализаций
- Dependencies и risks: явных нет
- Source evidence: plugins/reels-factory/engine/src/reels_factory/hyperframes_blocks.py:132-133

### 3D-переворот карточки

- ID: `transition_3d_card_flip`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит один перспективный переворот плоскости вокруг вертикальной оси.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:transitions-3d`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/transitions-3d/transitions-3d.html:274-276

### Blur crossfade с размытием

- ID: `transition_blur_crossfade`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит старую сцену, которая теряет резкость и смешивается с новой.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:transitions-dissolve`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/transitions-dissolve/transitions-dissolve.html:179-195

### Blur-through переход

- ID: `transition_blur_through`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит старый и новый кадр, соединённые blur-состоянием.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:transitions-blur`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/transitions-blur/transitions-blur.html:179-190

### Спокойный blur-through переход

- ID: `transition_calm_blur_through`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит ненавязчивый blur без резкого удара.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:transitions-blur`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/transitions-blur/transitions-blur.html:179-190

### Хроматическая аберрация

- ID: `transition_chromatic_aberration`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит цветные контуры и краткую рассинхронизацию изображения.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:transitions-distortion`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/transitions-distortion/transitions-distortion.html:210-218

### Переход: Chromatic Radial Split

- ID: `transition_chromatic_radial_split`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит: радиальный shader-разрез расходится от центра с цветным смещением RGB-каналов.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:chromatic-radial-split`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/chromatic-radial-split/registry-item.json:6-6

### Переход: Cinematic Zoom

- ID: `transition_cinematic_zoom`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит: резкий zoom blur втягивает старый кадр в точку и выводит новую сцену.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:cinematic-zoom`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/cinematic-zoom/registry-item.json:6-6

### Круглая диафрагма

- ID: `transition_circle_iris`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит классический круговой iris reveal.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:transitions-radial`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/transitions-radial/transitions-radial.html:273-321

### Круговая часовая шторка

- ID: `transition_clock_wipe`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит wipe, движущийся как стрелка часов.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:transitions-mechanical`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/transitions-mechanical/transitions-mechanical.html:205-210

### Переход: Cross Warp Morph

- ID: `transition_cross_warp_morph`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит: два кадра перекрёстно искривляются и плавно превращаются друг в друга.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:cross-warp-morph`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/cross-warp-morph/registry-item.json:6-6

### Классический crossfade

- ID: `transition_crossfade`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит плавное смешивание двух сцен.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:transitions-dissolve`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/transitions-dissolve/transitions-dissolve.html:179-195

### Диагональное раскрытие

- ID: `transition_diagonal_split`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит разрез кадра по диагонали.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:transitions-radial`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/transitions-radial/transitions-radial.html:273-321

### Ромбовидная диафрагма

- ID: `transition_diamond_iris`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит геометрический iris reveal в форме ромба.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:transitions-radial`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/transitions-radial/transitions-radial.html:273-321

### Dip to black через затемнение

- ID: `transition_dip_to_black`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит короткое затемнение между сценами.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:transitions-dissolve`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/transitions-dissolve/transitions-dissolve.html:179-195

### Направленное размытие при смене кадра

- ID: `transition_directional_blur`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит смазанный по направлению кадр, который уступает место следующему.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:transitions-blur`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/transitions-blur/transitions-blur.html:179-190

### Glitch-искажение

- ID: `transition_distortion_glitch`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит короткий цифровой сбой перед появлением новой сцены.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:transitions-distortion`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/transitions-distortion/transitions-distortion.html:210-218

### Переход: Domain Warp Dissolve

- ID: `transition_domain_warp_dissolve`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит: фрактальный шум деформирует границу растворения между старым и новым кадром.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:domain-warp-dissolve`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/domain-warp-dissolve/registry-item.json:6-6

### Эластичный push-переход

- ID: `transition_elastic_push`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит упругое движение с небольшим overshoot.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:transitions-push`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/transitions-push/transitions-push.html:179-195

### Film burn-переход

- ID: `transition_film_burn`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит органичный световой ожог по краю или центру.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:transitions-light`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/transitions-light/transitions-light.html:304-306

### Flash Cut со вспышкой

- ID: `transition_flash_cut`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит мгновенный световой удар и новый кадр.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:transitions-other`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/transitions-other/transitions-other.html:210-220

### Переход: Flash Through White

- ID: `transition_flash_through_white`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит: кадр быстро пересвечивается до белого и из вспышки возвращается новой сценой.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:flash-through-white`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/flash-through-white/registry-item.json:6-6

### Focus pull-переход

- ID: `transition_focus_pull`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит потерю резкости старого кадра и появление нового фокуса.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:transitions-dissolve`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/transitions-dissolve/transitions-dissolve.html:179-195

### Переход: Glitch

- ID: `transition_glitch`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит: цифровые полосы, сдвиги и артефакты shader-глитча скрывают смену кадров.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:glitch`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/glitch/registry-item.json:6-6

### Переход: Gravitational Lens

- ID: `transition_gravitational_lens`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит: изображение изгибается вокруг виртуального центра притяжения и переходит в следующий кадр.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:gravitational-lens`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/gravitational-lens/registry-item.json:6-6

### Падение под действием гравитации

- ID: `transition_gravity_drop`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит тяжёлое вертикальное падение всей сцены.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:transitions-other`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/transitions-other/transitions-other.html:210-220

### Растворение сеткой

- ID: `transition_grid_dissolve`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит единственный вариант Grid Dissolve с каскадом квадратных ячеек.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:transitions-grid`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/transitions-grid/transitions-grid.html:166-166

### Горизонтальные жалюзи

- ID: `transition_horizontal_blinds`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит горизонтальные створки, открывающие новый кадр.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:transitions-cover`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/transitions-cover/transitions-cover.html:286-288

### Light Leak-переход

- ID: `transition_light_leak`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит тёплую световую протечку поверх изображения.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:light-leak`, `upstream:block:transitions-light`
- Внутренние variants: реализация «Light Leak»; реализация «Light Transitions»
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/light-leak/registry-item.json:6-6, registry/blocks/transitions-light/transitions-light.html:304-306

### Механический затвор

- ID: `transition_mechanical_shutter`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит движение створок, похожее на затвор камеры.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:transitions-mechanical`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/transitions-mechanical/transitions-mechanical.html:205-210

### Круговой morph-переход

- ID: `transition_morph_circle`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит сцену, появляющуюся через трансформирующийся круг.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:transitions-other`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/transitions-other/transitions-other.html:210-220

### Переход: Organic Light Leak Overlay

- ID: `transition_organic_light_leak_overlay`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит: органичный световой засвет проходит поверх кадра и мотивирует смену сцены или воспоминание.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:organic-light-leak-overlay`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/organic-light-leak-overlay/registry-item.json:6-6

### Overexposure burn с пересветом

- ID: `transition_overexposure_burn`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит короткое белое выгорание изображения на монтажном стыке.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:transitions-light`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/transitions-light/transitions-light.html:304-306

### Прожиг страницы

- ID: `transition_page_burn`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит, как изображение выгорает подобно бумажной странице.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:transitions-destruction`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/transitions-destruction/transitions-destruction.html:187-187

### Переход: Parallax Unzoom

- ID: `transition_parallax_unzoom`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит: центральная карточка уменьшается от полного экрана, а соседние элементы входят параллаксом и образуют сетку.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:component:parallax-unzoom`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: overlay поверх кадра
- Готовность к 9:16: ready
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: явных нет
- Source evidence: registry/components/parallax-unzoom/registry-item.json:6-6

### Переход: Parallax Zoom

- ID: `transition_parallax_zoom`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит: центральная карточка увеличивается до полного экрана, а соседние элементы расходятся наружу параллаксом.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:component:parallax-zoom`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: overlay поверх кадра
- Готовность к 9:16: ready
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: явных нет
- Source evidence: registry/components/parallax-zoom/registry-item.json:6-6

### Push slide-переход

- ID: `transition_push_slide`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит боковой slide между сценами.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:transitions-push`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/transitions-push/transitions-push.html:179-195

### Волновое искажение

- ID: `transition_ripple_distortion`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит волну, которая искривляет стык между сценами.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:transitions-distortion`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/transitions-distortion/transitions-distortion.html:210-218

### Переход: Ripple Waves

- ID: `transition_ripple_waves`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит: концентрические волны деформируют изображение и переносят зрителя в следующий кадр.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:ripple-waves`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/ripple-waves/registry-item.json:6-6

### Переход: SDF Iris

- ID: `transition_sdf_iris`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит: sDF-маска открывает новую сцену через управляемую геометрическую диафрагму.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:sdf-iris`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/sdf-iris/registry-item.json:6-6

### Squeeze-переход

- ID: `transition_squeeze`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит сжатие плоскости кадра.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:transitions-push`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/transitions-push/transitions-push.html:179-195

### Переход ступенчатыми блоками

- ID: `transition_staggered_blocks`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит плитки, которые входят не одновременно.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:transitions-cover`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/transitions-cover/transitions-cover.html:286-288

### Переход: Swirl Vortex

- ID: `transition_swirl_vortex`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит: изображение закручивается в вихрь и раскручивается уже следующей сценой.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:swirl-vortex`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/swirl-vortex/registry-item.json:6-6

### Переход: Thermal Distortion

- ID: `transition_thermal_distortion`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит: тепловая рябь и heat-haze искажают стык между кадрами.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:thermal-distortion`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/thermal-distortion/registry-item.json:6-6

### Вертикальные жалюзи

- ID: `transition_vertical_blinds`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит вертикальные створки, открывающие новый кадр.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:transitions-cover`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/transitions-cover/transitions-cover.html:286-288

### Вертикальный push-переход

- ID: `transition_vertical_push`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит вертикальное смещение всей сцены.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:transitions-push`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/transitions-push/transitions-push.html:179-195

### Переход: Whip Pan

- ID: `transition_whip_pan`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит: сильный направленный смаз имитирует быстрый поворот камеры и скрывает монтажный стык.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:whip-pan`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/whip-pan/registry-item.json:6-6

### Отъезд камеры Zoom Out

- ID: `transition_zoom_out`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит отъезд камеры от предыдущего изображения.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:transitions-scale`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/transitions-scale/transitions-scale.html:179-184

### Проход через приближение Zoom Through

- ID: `transition_zoom_through`
- Категория: переход
- Availability: adapt
- Что видит зритель: Зритель видит быстрое приближение, которое становится новым изображением.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `upstream:block:transitions-scale`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/transitions-scale/transitions-scale.html:179-184

### Замена продукта ценностью

- ID: `value_layer_swap`
- Категория: сравнение и процесс
- Availability: ready
- Что видит зритель: Зритель видит две смысловые карточки, где вторая занимает главный фокус.
- Когда применять: Когда нужно показать изменение, порядок шагов или причинно-следственную связь.
- Когда не применять: Когда элементы не образуют понятную последовательность или сравнение.
- Реализации: `local:block:value_layers`
- Внутренние variants: нет
- Управляемые поля: поле контракта actual, поле контракта offer, поле контракта title
- Placement: полный экран
- Готовность к 9:16: ready
- Необходимая адаптация: не требуется для ready-реализаций
- Dependencies и risks: явных нет
- Source evidence: plugins/reels-factory/engine/src/reels_factory/hyperframes_blocks.py:460-461

### VFX-приём: iOS 26 Liquid Glass Home Screen

- ID: `vfx_ios26_liquid_glass`
- Категория: VFX и shader
- Availability: adapt
- Что видит зритель: Зритель видит: трёхмерный iPhone показывает домашний экран iOS 26 со стеклянными иконками, shader-обоями, dock и уведомлениями.
- Когда применять: Когда нужен редкий визуальный пик, продуктовый hero-shot или технологический акцент.
- Когда не применять: Когда тяжёлый эффект отвлекает от основной мысли или не оправдан сценарием.
- Реализации: `upstream:block:ios26-liquid-glass`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/ios26-liquid-glass/registry-item.json:6-6

### VFX-приём: iPhone & MacBook 3D Showcase

- ID: `vfx_iphone_device`
- Категория: VFX и shader
- Availability: adapt
- Что видит зритель: Зритель видит: gLTF-модели iPhone и MacBook вращаются в продуктовой камере, а их экраны содержат живой HTML-контент.
- Когда применять: Когда нужен редкий визуальный пик, продуктовый hero-shot или технологический акцент.
- Когда не применять: Когда тяжёлый эффект отвлекает от основной мысли или не оправдан сценарием.
- Реализации: `upstream:block:vfx-iphone-device`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/vfx-iphone-device/registry-item.json:6-6

### VFX-приём: Liquid Background

- ID: `vfx_liquid_background`
- Категория: VFX и shader
- Availability: adapt
- Что видит зритель: Зритель видит: под HTML-контентом колышется subdivided plane с жидкой vertex-деформацией и динамическими волнами.
- Когда применять: Когда нужен редкий визуальный пик, продуктовый hero-shot или технологический акцент.
- Когда не применять: Когда тяжёлый эффект отвлекает от основной мысли или не оправдан сценарием.
- Реализации: `upstream:block:vfx-liquid-background`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/vfx-liquid-background/registry-item.json:6-6

### VFX-приём: Liquid Glass

- ID: `vfx_liquid_glass`
- Категория: VFX и shader
- Availability: adapt
- Что видит зритель: Зритель видит: стеклянная плоскость разбивается на Voronoi-фрагменты, реагирует параллаксом на указатель и частично разлетается в глубину.
- Когда применять: Когда нужен редкий визуальный пик, продуктовый hero-shot или технологический акцент.
- Когда не применять: Когда тяжёлый эффект отвлекает от основной мысли или не оправдан сценарием.
- Реализации: `upstream:block:vfx-liquid-glass`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/vfx-liquid-glass/registry-item.json:6-6, registry/blocks/vfx-liquid-glass/vfx-liquid-glass.html:418-441, registry/blocks/vfx-liquid-glass/vfx-liquid-glass.html:660-678

### VFX-приём: Liquid Glass Context Menu

- ID: `vfx_liquid_glass_context_menu`
- Категория: VFX и shader
- Availability: adapt
- Что видит зритель: Зритель видит: матовое стеклянное контекстное меню дрейфует над цветным aurora shader-фоном.
- Когда применять: Когда нужен редкий визуальный пик, продуктовый hero-shot или технологический акцент.
- Когда не применять: Когда тяжёлый эффект отвлекает от основной мысли или не оправдан сценарием.
- Реализации: `upstream:block:liquid-glass-context-menu`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/liquid-glass-context-menu/registry-item.json:6-6

### Обработка медиа: Liquid Glass Media Controls

- ID: `vfx_liquid_glass_media_controls`
- Категория: обработка медиа
- Availability: adapt
- Что видит зритель: Зритель видит: стеклянные панели медиаплеера раскрываются и располагаются поверх aurora shader-фона.
- Когда применять: Когда исходный кадр нужно оформить как конкретный носитель или редакционный объект.
- Когда не применять: Когда оформление не поддерживает смысл сцены.
- Реализации: `upstream:block:liquid-glass-media-controls`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: overlay поверх кадра
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/liquid-glass-media-controls/registry-item.json:6-6

### Data-приём: Liquid Glass Widgets

- ID: `vfx_liquid_glass_widgets`
- Категория: данные и статистика
- Availability: adapt
- Что видит зритель: Зритель видит: стеклянные карточки статистики, showcase-панель и pill-элементы собираются над aurora-фоном.
- Когда применять: Когда в сценарии есть проверяемые числа, сравнения или динамика показателей.
- Когда не применять: Когда данные отсутствуют или не подтверждают произносимый тезис.
- Реализации: `upstream:block:liquid-glass-widgets`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/liquid-glass-widgets/registry-item.json:6-6

### VFX-приём: macOS Tahoe Liquid Glass Desktop

- ID: `vfx_macos_tahoe_liquid_glass`
- Категория: VFX и shader
- Availability: adapt
- Что видит зритель: Зритель видит: трёхмерный MacBook показывает desktop macOS Tahoe со стеклянным menu bar, Finder, dock и кинематографическим движением камеры.
- Когда применять: Когда нужен редкий визуальный пик, продуктовый hero-shot или технологический акцент.
- Когда не применять: Когда тяжёлый эффект отвлекает от основной мысли или не оправдан сценарием.
- Реализации: `upstream:block:macos-tahoe-liquid-glass`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/macos-tahoe-liquid-glass/registry-item.json:6-6

### VFX-приём: Magnetic

- ID: `vfx_magnetic`
- Категория: VFX и shader
- Availability: adapt
- Что видит зритель: Зритель видит: fragment shader притягивает пиксели изображения к курсору через Gaussian warp и добавляет цветное расщепление по краям деформации.
- Когда применять: Когда нужен редкий визуальный пик, продуктовый hero-shot или технологический акцент.
- Когда не применять: Когда тяжёлый эффект отвлекает от основной мысли или не оправдан сценарием.
- Реализации: `upstream:block:vfx-magnetic`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/vfx-magnetic/registry-item.json:6-6, registry/blocks/vfx-magnetic/vfx-magnetic.html:180-207

### VFX-приём: Portal

- ID: `vfx_portal`
- Категория: VFX и shader
- Availability: adapt
- Что видит зритель: Зритель видит: светящийся портал открывается в пространстве кадра и создаёт глубинный проход к другому слою.
- Когда применять: Когда нужен редкий визуальный пик, продуктовый hero-shot или технологический акцент.
- Когда не применять: Когда тяжёлый эффект отвлекает от основной мысли или не оправдан сценарием.
- Реализации: `upstream:block:vfx-portal`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/vfx-portal/registry-item.json:6-6, registry/blocks/vfx-portal/vfx-portal.html:595-614

### VFX-приём: Shatter

- ID: `vfx_shatter`
- Категория: VFX и shader
- Availability: adapt
- Что видит зритель: Зритель видит: плоскость или объект раскалывается на фрагменты, которые разлетаются в глубину и стороны.
- Когда применять: Когда нужен редкий визуальный пик, продуктовый hero-shot или технологический акцент.
- Когда не применять: Когда тяжёлый эффект отвлекает от основной мысли или не оправдан сценарием.
- Реализации: `upstream:block:vfx-shatter`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/vfx-shatter/registry-item.json:6-6, registry/blocks/vfx-shatter/vfx-shatter.html:737-811

### Брендовый приём: 3D UI Reveal

- ID: `vfx_ui_3d_reveal`
- Категория: бренд и outro
- Availability: adapt
- Что видит зритель: Зритель видит: uI-элементы входят как отдельные перспективные слои, выстраиваются по глубине и поворачиваются к камере.
- Когда применять: Когда нужно представить продукт, автора, логотип или завершить ролик CTA.
- Когда не применять: Когда брендовый экран прерывает объяснение до завершения мысли.
- Реализации: `upstream:block:ui-3d-reveal`
- Внутренние variants: нет
- Управляемые поля: нет доказанных controls
- Placement: полный экран
- Готовность к 9:16: adapt
- Необходимая адаптация: Проверить и при необходимости адаптировать под 1080x1920.; Контент запечён, нужна параметризация.
- Dependencies и risks: Есть внешняя runtime-зависимость, зафиксированная по строке source evidence.
- Source evidence: registry/blocks/ui-3d-reveal/registry-item.json:6-6

### Белая flash-смена

- ID: `white_flash_transition`
- Категория: переход
- Availability: ready
- Что видит зритель: Зритель видит полноэкранный белый слой, который быстро исчезает.
- Когда применять: Когда смена смыслового блока требует заметного визуального стыка.
- Когда не применять: Когда эффект повторялся недавно или обычный hard cut читается лучше.
- Реализации: `approved:transition:transition_white_flash`
- Внутренние variants: нет
- Управляемые поля: поле контракта id, поле контракта start, поле контракта transition
- Placement: полный экран
- Готовность к 9:16: ready
- Необходимая адаптация: не требуется для ready-реализаций
- Dependencies и risks: явных нет
- Source evidence: assets/catalog.js:587-618

## Матрица `item → techniques`

- `approved:layout:avatar_broll_split` → `avatar_broll_split`
- `approved:layout:avatar_cutout_overlay` → `forbidden_avatar_cutout_overlay`
- `approved:layout:avatar_editorial_bubble` → `avatar_editorial_bubble`
- `approved:layout:avatar_fullscreen` → `avatar_fullscreen_anchor`
- `approved:layout:avatar_object_overlay` → `avatar_object_overlay`
- `approved:layout:broll_archival_collage` → `archival_broll_collage`
- `approved:layout:broll_fullscreen` → `broll_fullscreen`
- `approved:layout:checklist_strike` → `checklist_strike_routine`
- `approved:layout:progressive_text_card` → `progressive_text_card`
- `approved:layout:social_outro` → `social_outro_lockup`
- `approved:transition:hard_cut` → `hard_cut_transition`
- `approved:transition:transition_blur` → `blur_soft_transition`
- `approved:transition:transition_chromatic` → `chromatic_accent_transition`
- `approved:transition:transition_push_editorial` → `editorial_push_transition`
- `approved:transition:transition_white_flash` → `white_flash_transition`
- `local:block:before_after` → `before_after_comparison`
- `local:block:complexity_cloud` → `complexity_to_resolution`
- `local:block:concept_nodes` → `concept_node_map`
- `local:block:persona_card` → `persona_context_card`
- `local:block:sequence_flow` → `sequence_step_flow`
- `local:block:stat_number` → `animated_stat_countup`
- `local:block:task_list` → `task_checklist_reveal`
- `local:block:value_layers` → `value_layer_swap`
- `upstream:block:app-showcase` → `brand_showcase_app_showcase`
- `upstream:block:apple-money-count` → `brand_showcase_apple_money_count`
- `upstream:block:blue-sweater-intro-video` → `brand_showcase_blue_sweater_intro_video`
- `upstream:block:camcorder-hud` → `media_treatment_camcorder_hud`
- `upstream:block:chromatic-radial-split` → `transition_chromatic_radial_split`
- `upstream:block:cinematic-zoom` → `transition_cinematic_zoom`
- `upstream:block:code-3d-extrude` → `code_3d_extrude`
- `upstream:block:code-diff` → `code_diff`
- `upstream:block:code-highlight` → `code_highlight`
- `upstream:block:code-morph` → `code_morph`
- `upstream:block:code-particle-assemble` → `code_particle_assemble`
- `upstream:block:code-scroll` → `code_scroll`
- `upstream:block:code-shader-dissolve` → `code_shader_dissolve`
- `upstream:block:code-snippet-apple-terminal-basic` → `apple_terminal_theme_card`
- `upstream:block:code-snippet-apple-terminal-clear-dark` → `apple_terminal_theme_card`
- `upstream:block:code-snippet-apple-terminal-clear-light` → `apple_terminal_theme_card`
- `upstream:block:code-snippet-apple-terminal-grass` → `apple_terminal_theme_card`
- `upstream:block:code-snippet-apple-terminal-homebrew` → `apple_terminal_theme_card`
- `upstream:block:code-snippet-apple-terminal-man-page` → `apple_terminal_theme_card`
- `upstream:block:code-snippet-apple-terminal-novel` → `apple_terminal_theme_card`
- `upstream:block:code-snippet-apple-terminal-ocean` → `apple_terminal_theme_card`
- `upstream:block:code-snippet-apple-terminal-pro` → `apple_terminal_theme_card`
- `upstream:block:code-snippet-apple-terminal-red-sands` → `apple_terminal_theme_card`
- `upstream:block:code-snippet-apple-terminal-silver-aerogel` → `apple_terminal_theme_card`
- `upstream:block:code-snippet-apple-terminal-solid-colors` → `apple_terminal_theme_card`
- `upstream:block:code-snippet-dark-2026` → `code_editor_theme_card`
- `upstream:block:code-snippet-dark-modern` → `code_editor_theme_card`
- `upstream:block:code-snippet-dark-plus` → `code_editor_theme_card`
- `upstream:block:code-snippet-flight` → `code_editor_theme_card`
- `upstream:block:code-snippet-high-contrast` → `code_editor_theme_card`
- `upstream:block:code-snippet-high-contrast-light` → `code_editor_theme_card`
- `upstream:block:code-snippet-light-2026` → `code_editor_theme_card`
- `upstream:block:code-snippet-light-modern` → `code_editor_theme_card`
- `upstream:block:code-snippet-light-plus` → `code_editor_theme_card`
- `upstream:block:code-snippet-monokai` → `code_editor_theme_card`
- `upstream:block:code-snippet-solarized-light` → `code_editor_theme_card`
- `upstream:block:code-snippet-visual-studio-dark` → `code_editor_theme_card`
- `upstream:block:code-snippet-visual-studio-light` → `code_editor_theme_card`
- `upstream:block:code-typing` → `code_typing`
- `upstream:block:cross-warp-morph` → `transition_cross_warp_morph`
- `upstream:block:data-chart` → `catalog_reference_data_chart`
- `upstream:block:domain-warp-dissolve` → `transition_domain_warp_dissolve`
- `upstream:block:editorial-flash-overlay` → `catalog_reference_editorial_flash_overlay`
- `upstream:block:flash-through-white` → `transition_flash_through_white`
- `upstream:block:flowchart` → `map_diagram_flowchart`
- `upstream:block:flowchart-vertical` → `map_diagram_flowchart_vertical`
- `upstream:block:freeze-frame-dressing` → `media_treatment_freeze_frame_dressing`
- `upstream:block:glitch` → `transition_glitch`
- `upstream:block:gravitational-lens` → `transition_gravitational_lens`
- `upstream:block:instagram-follow` → `social_overlay_instagram_follow`
- `upstream:block:ios26-liquid-glass` → `vfx_ios26_liquid_glass`
- `upstream:block:light-leak` → `transition_light_leak`
- `upstream:block:liquid-glass-context-menu` → `vfx_liquid_glass_context_menu`
- `upstream:block:liquid-glass-media-controls` → `vfx_liquid_glass_media_controls`
- `upstream:block:liquid-glass-notification` → `social_overlay_liquid_glass_notification`
- `upstream:block:liquid-glass-widgets` → `vfx_liquid_glass_widgets`
- `upstream:block:logo-outro` → `brand_showcase_logo_outro`
- `upstream:block:lower-third-bild` → `lower_third_bild`
- `upstream:block:lt-accent-underline` → `lower_third_accent_underline`
- `upstream:block:lt-bold-block` → `lower_third_bold_block`
- `upstream:block:lt-clean-bar` → `lower_third_clean_bar`
- `upstream:block:lt-color-block` → `lower_third_color_block`
- `upstream:block:lt-dark-card` → `lower_third_dark_card`
- `upstream:block:lt-kicker-name` → `lower_third_kicker_name`
- `upstream:block:lt-mask-reveal` → `lower_third_mask_reveal`
- `upstream:block:lt-side-rule` → `lower_third_side_rule`
- `upstream:block:lt-soft-pill` → `lower_third_soft_pill`
- `upstream:block:lt-stack-bars` → `lower_third_stack_bars`
- `upstream:block:macos-notification` → `social_overlay_macos_notification`
- `upstream:block:macos-tahoe-liquid-glass` → `vfx_macos_tahoe_liquid_glass`
- `upstream:block:news-ticker` → `lower_third_news_ticker`
- `upstream:block:north-korea-locked-down` → `catalog_reference_north_korea_locked_down`
- `upstream:block:nyc-paris-flight` → `brand_showcase_nyc_paris_flight`
- `upstream:block:organic-light-leak-overlay` → `transition_organic_light_leak_overlay`
- `upstream:block:reddit-post` → `social_overlay_reddit_post`
- `upstream:block:ridged-burn` → `catalog_reference_ridged_burn`
- `upstream:block:ripple-waves` → `transition_ripple_waves`
- `upstream:block:sdf-iris` → `transition_sdf_iris`
- `upstream:block:spain-map` → `map_diagram_spain_map`
- `upstream:block:spotify-card` → `social_overlay_spotify_card`
- `upstream:block:swirl-vortex` → `transition_swirl_vortex`
- `upstream:block:thermal-distortion` → `transition_thermal_distortion`
- `upstream:block:tiktok-follow` → `social_overlay_tiktok_follow`
- `upstream:block:transitions-3d` → `transition_3d_card_flip`
- `upstream:block:transitions-blur` → `transition_blur_through`, `transition_directional_blur`, `transition_calm_blur_through`
- `upstream:block:transitions-cover` → `transition_staggered_blocks`, `transition_horizontal_blinds`, `transition_vertical_blinds`
- `upstream:block:transitions-destruction` → `transition_page_burn`
- `upstream:block:transitions-dissolve` → `transition_crossfade`, `transition_blur_crossfade`, `transition_focus_pull`, `transition_dip_to_black`
- `upstream:block:transitions-distortion` → `transition_distortion_glitch`, `transition_chromatic_aberration`, `transition_ripple_distortion`
- `upstream:block:transitions-grid` → `transition_grid_dissolve`
- `upstream:block:transitions-light` → `transition_light_leak`, `transition_overexposure_burn`, `transition_film_burn`
- `upstream:block:transitions-mechanical` → `transition_mechanical_shutter`, `transition_clock_wipe`
- `upstream:block:transitions-other` → `transition_flash_cut`, `transition_gravity_drop`, `transition_morph_circle`
- `upstream:block:transitions-push` → `transition_push_slide`, `transition_vertical_push`, `transition_elastic_push`, `transition_squeeze`
- `upstream:block:transitions-radial` → `transition_circle_iris`, `transition_diamond_iris`, `transition_diagonal_split`
- `upstream:block:transitions-scale` → `transition_zoom_through`, `transition_zoom_out`
- `upstream:block:ui-3d-reveal` → `vfx_ui_3d_reveal`
- `upstream:block:us-map` → `map_diagram_us_map`
- `upstream:block:us-map-bubble` → `map_diagram_us_map_bubble`
- `upstream:block:us-map-flow` → `map_diagram_us_map_flow`
- `upstream:block:us-map-hex` → `map_diagram_us_map_hex`
- `upstream:block:vfx-iphone-device` → `vfx_iphone_device`
- `upstream:block:vfx-liquid-background` → `vfx_liquid_background`
- `upstream:block:vfx-liquid-glass` → `vfx_liquid_glass`
- `upstream:block:vfx-magnetic` → `vfx_magnetic`
- `upstream:block:vfx-portal` → `vfx_portal`
- `upstream:block:vfx-shatter` → `vfx_shatter`
- `upstream:block:vfx-text-cursor` → `code_text_cursor`
- `upstream:block:vpn-youtube-spot` → `brand_showcase_vpn_youtube_spot`
- `upstream:block:whip-pan` → `transition_whip_pan`
- `upstream:block:world-map` → `map_diagram_world_map`
- `upstream:block:x-post` → `social_overlay_x_post`
- `upstream:block:yt-lower-third` → `lower_third_yt_lower_third`
- `upstream:component:caption-blend-difference` → `caption_blend_difference`
- `upstream:component:caption-clip-wipe` → `caption_clip_wipe`
- `upstream:component:caption-editorial-emphasis` → `caption_editorial_emphasis`
- `upstream:component:caption-emoji-pop` → `caption_emoji_pop`
- `upstream:component:caption-glitch-rgb` → `caption_glitch_rgb`
- `upstream:component:caption-gradient-fill` → `caption_gradient_fill`
- `upstream:component:caption-highlight` → `caption_highlight`
- `upstream:component:caption-kinetic-slam` → `caption_kinetic_slam`
- `upstream:component:caption-matrix-decode` → `caption_matrix_decode`
- `upstream:component:caption-neon-accent` → `caption_neon_accent`
- `upstream:component:caption-neon-glow` → `caption_neon_glow`
- `upstream:component:caption-parallax-layers` → `caption_parallax_layers`
- `upstream:component:caption-particle-burst` → `caption_particle_burst`
- `upstream:component:caption-pill-karaoke` → `caption_pill_karaoke`
- `upstream:component:caption-texture` → `caption_texture`
- `upstream:component:caption-weight-shift` → `caption_weight_shift`
- `upstream:component:grain-overlay` → `media_treatment_grain_overlay`
- `upstream:component:grid-pixelate-wipe` → `catalog_reference_grid_pixelate_wipe`
- `upstream:component:morph-text` → `catalog_reference_morph_text`
- `upstream:component:motion-blur` → `spatial_motion_blur`
- `upstream:component:parallax-unzoom` → `transition_parallax_unzoom`
- `upstream:component:parallax-zoom` → `transition_parallax_zoom`
- `upstream:component:shimmer-sweep` → `media_treatment_shimmer_sweep`
- `upstream:component:texture-mask-text` → `media_treatment_texture_mask_text`
- `upstream:component:vignette` → `media_treatment_vignette`

## Матрица `technique → implementations`

- `animated_stat_countup` → `local:block:stat_number`
- `apple_terminal_theme_card` → `upstream:block:code-snippet-apple-terminal-basic`, `upstream:block:code-snippet-apple-terminal-clear-dark`, `upstream:block:code-snippet-apple-terminal-clear-light`, `upstream:block:code-snippet-apple-terminal-grass`, `upstream:block:code-snippet-apple-terminal-homebrew`, `upstream:block:code-snippet-apple-terminal-man-page`, `upstream:block:code-snippet-apple-terminal-novel`, `upstream:block:code-snippet-apple-terminal-ocean`, `upstream:block:code-snippet-apple-terminal-pro`, `upstream:block:code-snippet-apple-terminal-red-sands`, `upstream:block:code-snippet-apple-terminal-silver-aerogel`, `upstream:block:code-snippet-apple-terminal-solid-colors`
- `archival_broll_collage` → `approved:layout:broll_archival_collage`
- `avatar_broll_split` → `approved:layout:avatar_broll_split`
- `avatar_editorial_bubble` → `approved:layout:avatar_editorial_bubble`
- `avatar_fullscreen_anchor` → `approved:layout:avatar_fullscreen`
- `avatar_object_overlay` → `approved:layout:avatar_object_overlay`
- `before_after_comparison` → `local:block:before_after`
- `blur_soft_transition` → `approved:transition:transition_blur`
- `brand_showcase_app_showcase` → `upstream:block:app-showcase`
- `brand_showcase_apple_money_count` → `upstream:block:apple-money-count`
- `brand_showcase_blue_sweater_intro_video` → `upstream:block:blue-sweater-intro-video`
- `brand_showcase_logo_outro` → `upstream:block:logo-outro`
- `brand_showcase_nyc_paris_flight` → `upstream:block:nyc-paris-flight`
- `brand_showcase_vpn_youtube_spot` → `upstream:block:vpn-youtube-spot`
- `broll_fullscreen` → `approved:layout:broll_fullscreen`
- `caption_blend_difference` → `upstream:component:caption-blend-difference`
- `caption_clip_wipe` → `upstream:component:caption-clip-wipe`
- `caption_editorial_emphasis` → `upstream:component:caption-editorial-emphasis`
- `caption_emoji_pop` → `upstream:component:caption-emoji-pop`
- `caption_glitch_rgb` → `upstream:component:caption-glitch-rgb`
- `caption_gradient_fill` → `upstream:component:caption-gradient-fill`
- `caption_highlight` → `upstream:component:caption-highlight`
- `caption_kinetic_slam` → `upstream:component:caption-kinetic-slam`
- `caption_matrix_decode` → `upstream:component:caption-matrix-decode`
- `caption_neon_accent` → `upstream:component:caption-neon-accent`
- `caption_neon_glow` → `upstream:component:caption-neon-glow`
- `caption_parallax_layers` → `upstream:component:caption-parallax-layers`
- `caption_particle_burst` → `upstream:component:caption-particle-burst`
- `caption_pill_karaoke` → `upstream:component:caption-pill-karaoke`
- `caption_texture` → `upstream:component:caption-texture`
- `caption_weight_shift` → `upstream:component:caption-weight-shift`
- `catalog_reference_data_chart` → `upstream:block:data-chart`
- `catalog_reference_editorial_flash_overlay` → `upstream:block:editorial-flash-overlay`
- `catalog_reference_grid_pixelate_wipe` → `upstream:component:grid-pixelate-wipe`
- `catalog_reference_morph_text` → `upstream:component:morph-text`
- `catalog_reference_north_korea_locked_down` → `upstream:block:north-korea-locked-down`
- `catalog_reference_ridged_burn` → `upstream:block:ridged-burn`
- `checklist_strike_routine` → `approved:layout:checklist_strike`
- `chromatic_accent_transition` → `approved:transition:transition_chromatic`
- `code_3d_extrude` → `upstream:block:code-3d-extrude`
- `code_diff` → `upstream:block:code-diff`
- `code_editor_theme_card` → `upstream:block:code-snippet-dark-2026`, `upstream:block:code-snippet-dark-modern`, `upstream:block:code-snippet-dark-plus`, `upstream:block:code-snippet-flight`, `upstream:block:code-snippet-high-contrast`, `upstream:block:code-snippet-high-contrast-light`, `upstream:block:code-snippet-light-2026`, `upstream:block:code-snippet-light-modern`, `upstream:block:code-snippet-light-plus`, `upstream:block:code-snippet-monokai`, `upstream:block:code-snippet-solarized-light`, `upstream:block:code-snippet-visual-studio-dark`, `upstream:block:code-snippet-visual-studio-light`
- `code_highlight` → `upstream:block:code-highlight`
- `code_morph` → `upstream:block:code-morph`
- `code_particle_assemble` → `upstream:block:code-particle-assemble`
- `code_scroll` → `upstream:block:code-scroll`
- `code_shader_dissolve` → `upstream:block:code-shader-dissolve`
- `code_text_cursor` → `upstream:block:vfx-text-cursor`
- `code_typing` → `upstream:block:code-typing`
- `complexity_to_resolution` → `local:block:complexity_cloud`
- `concept_node_map` → `local:block:concept_nodes`
- `editorial_push_transition` → `approved:transition:transition_push_editorial`
- `forbidden_avatar_cutout_overlay` → `approved:layout:avatar_cutout_overlay`
- `hard_cut_transition` → `approved:transition:hard_cut`
- `lower_third_accent_underline` → `upstream:block:lt-accent-underline`
- `lower_third_bild` → `upstream:block:lower-third-bild`
- `lower_third_bold_block` → `upstream:block:lt-bold-block`
- `lower_third_clean_bar` → `upstream:block:lt-clean-bar`
- `lower_third_color_block` → `upstream:block:lt-color-block`
- `lower_third_dark_card` → `upstream:block:lt-dark-card`
- `lower_third_kicker_name` → `upstream:block:lt-kicker-name`
- `lower_third_mask_reveal` → `upstream:block:lt-mask-reveal`
- `lower_third_news_ticker` → `upstream:block:news-ticker`
- `lower_third_side_rule` → `upstream:block:lt-side-rule`
- `lower_third_soft_pill` → `upstream:block:lt-soft-pill`
- `lower_third_stack_bars` → `upstream:block:lt-stack-bars`
- `lower_third_yt_lower_third` → `upstream:block:yt-lower-third`
- `map_diagram_flowchart` → `upstream:block:flowchart`
- `map_diagram_flowchart_vertical` → `upstream:block:flowchart-vertical`
- `map_diagram_spain_map` → `upstream:block:spain-map`
- `map_diagram_us_map` → `upstream:block:us-map`
- `map_diagram_us_map_bubble` → `upstream:block:us-map-bubble`
- `map_diagram_us_map_flow` → `upstream:block:us-map-flow`
- `map_diagram_us_map_hex` → `upstream:block:us-map-hex`
- `map_diagram_world_map` → `upstream:block:world-map`
- `media_treatment_camcorder_hud` → `upstream:block:camcorder-hud`
- `media_treatment_freeze_frame_dressing` → `upstream:block:freeze-frame-dressing`
- `media_treatment_grain_overlay` → `upstream:component:grain-overlay`
- `media_treatment_shimmer_sweep` → `upstream:component:shimmer-sweep`
- `media_treatment_texture_mask_text` → `upstream:component:texture-mask-text`
- `media_treatment_vignette` → `upstream:component:vignette`
- `persona_context_card` → `local:block:persona_card`
- `progressive_text_card` → `approved:layout:progressive_text_card`
- `sequence_step_flow` → `local:block:sequence_flow`
- `social_outro_lockup` → `approved:layout:social_outro`
- `social_overlay_instagram_follow` → `upstream:block:instagram-follow`
- `social_overlay_liquid_glass_notification` → `upstream:block:liquid-glass-notification`
- `social_overlay_macos_notification` → `upstream:block:macos-notification`
- `social_overlay_reddit_post` → `upstream:block:reddit-post`
- `social_overlay_spotify_card` → `upstream:block:spotify-card`
- `social_overlay_tiktok_follow` → `upstream:block:tiktok-follow`
- `social_overlay_x_post` → `upstream:block:x-post`
- `spatial_motion_blur` → `upstream:component:motion-blur`
- `task_checklist_reveal` → `local:block:task_list`
- `transition_3d_card_flip` → `upstream:block:transitions-3d`
- `transition_blur_crossfade` → `upstream:block:transitions-dissolve`
- `transition_blur_through` → `upstream:block:transitions-blur`
- `transition_calm_blur_through` → `upstream:block:transitions-blur`
- `transition_chromatic_aberration` → `upstream:block:transitions-distortion`
- `transition_chromatic_radial_split` → `upstream:block:chromatic-radial-split`
- `transition_cinematic_zoom` → `upstream:block:cinematic-zoom`
- `transition_circle_iris` → `upstream:block:transitions-radial`
- `transition_clock_wipe` → `upstream:block:transitions-mechanical`
- `transition_cross_warp_morph` → `upstream:block:cross-warp-morph`
- `transition_crossfade` → `upstream:block:transitions-dissolve`
- `transition_diagonal_split` → `upstream:block:transitions-radial`
- `transition_diamond_iris` → `upstream:block:transitions-radial`
- `transition_dip_to_black` → `upstream:block:transitions-dissolve`
- `transition_directional_blur` → `upstream:block:transitions-blur`
- `transition_distortion_glitch` → `upstream:block:transitions-distortion`
- `transition_domain_warp_dissolve` → `upstream:block:domain-warp-dissolve`
- `transition_elastic_push` → `upstream:block:transitions-push`
- `transition_film_burn` → `upstream:block:transitions-light`
- `transition_flash_cut` → `upstream:block:transitions-other`
- `transition_flash_through_white` → `upstream:block:flash-through-white`
- `transition_focus_pull` → `upstream:block:transitions-dissolve`
- `transition_glitch` → `upstream:block:glitch`
- `transition_gravitational_lens` → `upstream:block:gravitational-lens`
- `transition_gravity_drop` → `upstream:block:transitions-other`
- `transition_grid_dissolve` → `upstream:block:transitions-grid`
- `transition_horizontal_blinds` → `upstream:block:transitions-cover`
- `transition_light_leak` → `upstream:block:light-leak`, `upstream:block:transitions-light`
- `transition_mechanical_shutter` → `upstream:block:transitions-mechanical`
- `transition_morph_circle` → `upstream:block:transitions-other`
- `transition_organic_light_leak_overlay` → `upstream:block:organic-light-leak-overlay`
- `transition_overexposure_burn` → `upstream:block:transitions-light`
- `transition_page_burn` → `upstream:block:transitions-destruction`
- `transition_parallax_unzoom` → `upstream:component:parallax-unzoom`
- `transition_parallax_zoom` → `upstream:component:parallax-zoom`
- `transition_push_slide` → `upstream:block:transitions-push`
- `transition_ripple_distortion` → `upstream:block:transitions-distortion`
- `transition_ripple_waves` → `upstream:block:ripple-waves`
- `transition_sdf_iris` → `upstream:block:sdf-iris`
- `transition_squeeze` → `upstream:block:transitions-push`
- `transition_staggered_blocks` → `upstream:block:transitions-cover`
- `transition_swirl_vortex` → `upstream:block:swirl-vortex`
- `transition_thermal_distortion` → `upstream:block:thermal-distortion`
- `transition_vertical_blinds` → `upstream:block:transitions-cover`
- `transition_vertical_push` → `upstream:block:transitions-push`
- `transition_whip_pan` → `upstream:block:whip-pan`
- `transition_zoom_out` → `upstream:block:transitions-scale`
- `transition_zoom_through` → `upstream:block:transitions-scale`
- `value_layer_swap` → `local:block:value_layers`
- `vfx_ios26_liquid_glass` → `upstream:block:ios26-liquid-glass`
- `vfx_iphone_device` → `upstream:block:vfx-iphone-device`
- `vfx_liquid_background` → `upstream:block:vfx-liquid-background`
- `vfx_liquid_glass` → `upstream:block:vfx-liquid-glass`
- `vfx_liquid_glass_context_menu` → `upstream:block:liquid-glass-context-menu`
- `vfx_liquid_glass_media_controls` → `upstream:block:liquid-glass-media-controls`
- `vfx_liquid_glass_widgets` → `upstream:block:liquid-glass-widgets`
- `vfx_macos_tahoe_liquid_glass` → `upstream:block:macos-tahoe-liquid-glass`
- `vfx_magnetic` → `upstream:block:vfx-magnetic`
- `vfx_portal` → `upstream:block:vfx-portal`
- `vfx_shatter` → `upstream:block:vfx-shatter`
- `vfx_ui_3d_reveal` → `upstream:block:ui-3d-reveal`
- `white_flash_transition` → `approved:transition:transition_white_flash`

## Доступно сразу

- `animated_stat_countup` — Анимированный счётчик числа
- `archival_broll_collage` — Editorial collage из B-roll
- `avatar_broll_split` — Split screen: аватар и B-roll
- `avatar_editorial_bubble` — Аватар в editorial bubble
- `avatar_fullscreen_anchor` — Полноэкранный аватар-якорь
- `avatar_object_overlay` — Аватар с предметным overlay
- `before_after_comparison` — Сравнение «было → стало»
- `blur_soft_transition` — Мягкий blur-переход
- `broll_fullscreen` — Полноэкранный B-roll
- `checklist_strike_routine` — Зачёркивание рутины
- `chromatic_accent_transition` — Chromatic accent-переход
- `complexity_to_resolution` — Схлопывание сложности в решение
- `concept_node_map` — Карта связанных понятий
- `editorial_push_transition` — Editorial push-переход
- `hard_cut_transition` — Жёсткий монтажный стык
- `persona_context_card` — Карточка аудитории
- `progressive_text_card` — Прогрессивная типографическая карточка
- `sequence_step_flow` — Вертикальный flow шагов
- `social_outro_lockup` — Финальный social outro lockup
- `task_checklist_reveal` — Пошаговый список с акцентом
- `value_layer_swap` — Замена продукта ценностью
- `white_flash_transition` — Белая flash-смена

## Станет доступно после адаптации

- `apple_terminal_theme_card` — Кодовый приём: Code Snippet - Apple Terminal Basic
- `brand_showcase_app_showcase` — Брендовый приём: App Showcase
- `brand_showcase_apple_money_count` — Data-приём: Apple Money Count
- `brand_showcase_blue_sweater_intro_video` — Брендовый приём: Blue Sweater Intro Video
- `brand_showcase_logo_outro` — Брендовый приём: Logo Outro
- `brand_showcase_nyc_paris_flight` — Картографический приём: NYC Paris Flight
- `brand_showcase_vpn_youtube_spot` — Брендовый приём: VPN YouTube Spot
- `caption_blend_difference` — Caption-приём: Blend Difference
- `caption_clip_wipe` — Caption-приём: Clip Wipe
- `caption_editorial_emphasis` — Caption-приём: Editorial Emphasis
- `caption_emoji_pop` — Caption-приём: Emoji Pop
- `caption_glitch_rgb` — Caption-приём: Glitch RGB
- `caption_gradient_fill` — Caption-приём: Gradient Fill
- `caption_highlight` — Caption-приём: Highlight
- `caption_kinetic_slam` — Caption-приём: Kinetic Slam
- `caption_matrix_decode` — Caption-приём: Matrix Decode
- `caption_neon_accent` — Caption-приём: Neon Accent
- `caption_neon_glow` — Caption-приём: Neon Glow
- `caption_parallax_layers` — Caption-приём: Parallax Layers
- `caption_particle_burst` — Caption-приём: Particle Burst
- `caption_pill_karaoke` — Caption-приём: Pill Karaoke
- `caption_weight_shift` — Caption-приём: Weight Shift
- `catalog_reference_data_chart` — Data-приём: Data Chart
- `catalog_reference_editorial_flash_overlay` — Социальный overlay: Editorial Flash Overlay
- `catalog_reference_grid_pixelate_wipe` — Переход: Grid Pixelate Wipe
- `catalog_reference_morph_text` — Приём процесса: Morph Text
- `catalog_reference_north_korea_locked_down` — Картографический приём: North Korea Locked Down
- `catalog_reference_ridged_burn` — Переход: Ridged Burn
- `code_3d_extrude` — Кодовый приём: Code 3D Extrude
- `code_editor_theme_card` — Кодовый приём: Code Snippet - Dark 2026
- `code_particle_assemble` — Кодовый приём: Code Particle Assemble
- `code_shader_dissolve` — Кодовый приём: Code Shader Dissolve
- `code_text_cursor` — Социальный overlay: VFX Text Cursor
- `lower_third_accent_underline` — Титровый приём: Lower Third — Accent Underline
- `lower_third_bild` — Титровый приём: Lower Third — BILD Style
- `lower_third_bold_block` — Титровый приём: Lower Third — Bold Block
- `lower_third_clean_bar` — Титровый приём: Lower Third — Clean Bar
- `lower_third_color_block` — Титровый приём: Lower Third — Color Block
- `lower_third_dark_card` — Титровый приём: Lower Third — Dark Card
- `lower_third_kicker_name` — Титровый приём: Lower Third — Kicker Name
- `lower_third_mask_reveal` — Титровый приём: Lower Third — Mask Reveal
- `lower_third_news_ticker` — Титровый приём: News Ticker
- `lower_third_side_rule` — Титровый приём: Lower Third — Side Rule
- `lower_third_soft_pill` — Титровый приём: Lower Third — Soft Pill
- `lower_third_stack_bars` — Титровый приём: Lower Third — Stack Bars
- `lower_third_yt_lower_third` — Титровый приём: YouTube Lower Third
- `map_diagram_spain_map` — Картографический приём: Spain Map
- `map_diagram_us_map` — Картографический приём: US Map
- `map_diagram_us_map_bubble` — Картографический приём: US Bubble Map
- `map_diagram_us_map_flow` — Картографический приём: US Flow Map
- `map_diagram_us_map_hex` — Картографический приём: US Hex Grid Map
- `map_diagram_world_map` — Картографический приём: World Map
- `media_treatment_camcorder_hud` — Финишная текстура: Camcorder HUD
- `media_treatment_freeze_frame_dressing` — Социальный overlay: Freeze-Frame Dressing
- `media_treatment_grain_overlay` — Финишная текстура: Grain Overlay
- `media_treatment_shimmer_sweep` — Финишная текстура: Shimmer Sweep
- `media_treatment_texture_mask_text` — Финишная текстура: Texture Mask Text
- `media_treatment_vignette` — Финишная текстура: Vignette
- `social_overlay_instagram_follow` — Социальный overlay: Instagram Follow
- `social_overlay_liquid_glass_notification` — Социальный overlay: Liquid Glass Notification
- `social_overlay_macos_notification` — Социальный overlay: macOS Notification
- `social_overlay_reddit_post` — Социальный overlay: Reddit Post Card
- `social_overlay_spotify_card` — Социальный overlay: Spotify Now Playing
- `social_overlay_tiktok_follow` — Социальный overlay: TikTok Follow
- `social_overlay_x_post` — Социальный overlay: X Post Card
- `transition_3d_card_flip` — 3D-переворот карточки
- `transition_blur_crossfade` — Blur crossfade с размытием
- `transition_blur_through` — Blur-through переход
- `transition_calm_blur_through` — Спокойный blur-through переход
- `transition_chromatic_aberration` — Хроматическая аберрация
- `transition_chromatic_radial_split` — Переход: Chromatic Radial Split
- `transition_cinematic_zoom` — Переход: Cinematic Zoom
- `transition_circle_iris` — Круглая диафрагма
- `transition_clock_wipe` — Круговая часовая шторка
- `transition_cross_warp_morph` — Переход: Cross Warp Morph
- `transition_crossfade` — Классический crossfade
- `transition_diagonal_split` — Диагональное раскрытие
- `transition_diamond_iris` — Ромбовидная диафрагма
- `transition_dip_to_black` — Dip to black через затемнение
- `transition_directional_blur` — Направленное размытие при смене кадра
- `transition_distortion_glitch` — Glitch-искажение
- `transition_domain_warp_dissolve` — Переход: Domain Warp Dissolve
- `transition_elastic_push` — Эластичный push-переход
- `transition_film_burn` — Film burn-переход
- `transition_flash_cut` — Flash Cut со вспышкой
- `transition_flash_through_white` — Переход: Flash Through White
- `transition_focus_pull` — Focus pull-переход
- `transition_glitch` — Переход: Glitch
- `transition_gravitational_lens` — Переход: Gravitational Lens
- `transition_gravity_drop` — Падение под действием гравитации
- `transition_grid_dissolve` — Растворение сеткой
- `transition_horizontal_blinds` — Горизонтальные жалюзи
- `transition_light_leak` — Light Leak-переход
- `transition_mechanical_shutter` — Механический затвор
- `transition_morph_circle` — Круговой morph-переход
- `transition_organic_light_leak_overlay` — Переход: Organic Light Leak Overlay
- `transition_overexposure_burn` — Overexposure burn с пересветом
- `transition_page_burn` — Прожиг страницы
- `transition_parallax_unzoom` — Переход: Parallax Unzoom
- `transition_parallax_zoom` — Переход: Parallax Zoom
- `transition_push_slide` — Push slide-переход
- `transition_ripple_distortion` — Волновое искажение
- `transition_ripple_waves` — Переход: Ripple Waves
- `transition_sdf_iris` — Переход: SDF Iris
- `transition_squeeze` — Squeeze-переход
- `transition_staggered_blocks` — Переход ступенчатыми блоками
- `transition_swirl_vortex` — Переход: Swirl Vortex
- `transition_thermal_distortion` — Переход: Thermal Distortion
- `transition_vertical_blinds` — Вертикальные жалюзи
- `transition_vertical_push` — Вертикальный push-переход
- `transition_whip_pan` — Переход: Whip Pan
- `transition_zoom_out` — Отъезд камеры Zoom Out
- `transition_zoom_through` — Проход через приближение Zoom Through
- `vfx_ios26_liquid_glass` — VFX-приём: iOS 26 Liquid Glass Home Screen
- `vfx_iphone_device` — VFX-приём: iPhone & MacBook 3D Showcase
- `vfx_liquid_background` — VFX-приём: Liquid Background
- `vfx_liquid_glass` — VFX-приём: Liquid Glass
- `vfx_liquid_glass_context_menu` — VFX-приём: Liquid Glass Context Menu
- `vfx_liquid_glass_media_controls` — Обработка медиа: Liquid Glass Media Controls
- `vfx_liquid_glass_widgets` — Data-приём: Liquid Glass Widgets
- `vfx_macos_tahoe_liquid_glass` — VFX-приём: macOS Tahoe Liquid Glass Desktop
- `vfx_magnetic` — VFX-приём: Magnetic
- `vfx_portal` — VFX-приём: Portal
- `vfx_shatter` — VFX-приём: Shatter
- `vfx_ui_3d_reveal` — Брендовый приём: 3D UI Reveal

## Только референсы

- `caption_texture` — Caption-приём: Texture
- `code_diff` — Кодовый приём: Code Diff
- `code_highlight` — Кодовый приём: Code Highlight Sweep
- `code_morph` — Кодовый приём: Code Morph
- `code_scroll` — Кодовый приём: Code Scroll To Line
- `code_typing` — Кодовый приём: Code Typing
- `map_diagram_flowchart` — Картографический приём: Flowchart
- `map_diagram_flowchart_vertical` — Картографический приём: Flowchart Vertical
- `spatial_motion_blur` — Шлейф от быстрого движения

## Запрещённые исторические решения

- `forbidden_avatar_cutout_overlay` — Запрещённый исторический cutout overlay

## Пробелы каталога

- Нет готового face-safe reposition для произвольного HeyGen-видео; evidence: items содержат визуальные реализации, но не содержат detector contract.
- Нет production asset resolver для лицензированного B-roll; evidence: catalog хранит media slots и examples, но не правообладательский pipeline.
- Большинство upstream landscape blocks требует отдельной 1080x1920 адаптации; evidence: orientation distribution фиксируется в inventory.

## Counts по категориям

- brand_and_outro: 6
- caption_and_typography: 17
- code_and_terminal: 10
- comparison_and_process: 7
- composition_layout: 3
- data_and_statistics: 4
- map_and_diagram: 11
- media_treatment: 1
- social_and_editorial_overlay: 11
- spatial_motion: 1
- speaker_layout: 4
- texture_and_finishing: 5
- title_and_lower_third: 13
- transition: 55
- vfx_and_shader: 9

## Counts `ready/adapt/reference_only/forbidden`

- adapt: 125
- forbidden: 1
- ready: 22
- reference_only: 9

## Multi-technique items

- `upstream:block:transitions-blur`: 3
- `upstream:block:transitions-cover`: 3
- `upstream:block:transitions-dissolve`: 4
- `upstream:block:transitions-distortion`: 3
- `upstream:block:transitions-light`: 3
- `upstream:block:transitions-mechanical`: 2
- `upstream:block:transitions-other`: 3
- `upstream:block:transitions-push`: 4
- `upstream:block:transitions-radial`: 3
- `upstream:block:transitions-scale`: 2
