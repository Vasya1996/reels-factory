# Golden Catalog — ТЗ (Stage 00 → Stage 02-golden)

Дата: 2026-08-02. Основано на: reference-board.md + свайп-сессия 49 приёмов.
Свайп-ответы: `swipe-results-20260802.md`.

## Подтверждённый taste profile

Из голосов свайпа (все «нет» на texture/grain/vignette/neon-glow/matrix/chromatic,
все «да» на чистую типографику и параллакс):

1. **Чистый флэт**: никаких плёночных фактур, зерна, виньеток, глитча, неона-свечения.
   Допустим точечный neon-accent на слове, без glow-ореола.
2. **Два цветовых языка**: светлый editorial (белый/кремовый, чёрная типографика,
   красный акцент) + тёмный (чёрный фон, белая типографика, красный/жёлтый акцент).
3. **Движение = типографика и смысл**, не камера: morph, weight-shift, накопление,
   зачёркивание, параллакс-зум внутри b-roll. Никакого мельтешения.
4. **Аватар**: fullscreen или editorial-рамка/пузырь. Сплит-раскладка — нет.
   Cutout без фона — кандидат (из витрины B6, в свайпе не участвовал).
5. **Переходы**: hard cut основной; blur / editorial push / white flash — только
   на смысловых поворотах.
6. **Динамика через плотность смысловых событий** (каждые 1,5–3 с событие),
   анимации триггерятся словами озвучки.
7. Запрещено: мемы, 3D-пропсы «в руках», сплит аватар+b-roll, шумовые фактуры.

## Состав каталога

### Группа 1 — готовые, перенос как есть (полировка контента, не механики)

| # | Блок | Источник |
|---|------|----------|
| G1 | avatar_editorial_bubble | approved, свайп «да» |
| G2 | avatar_fullscreen (+serif hook поверх, B1) | approved, «да» |
| G3 | broll_archival_collage | approved, «да» |
| G4 | broll_fullscreen (+ parallax-zoom/unzoom внутри) | approved, «да» |
| G5 | progressive_text_card (светлая и тёмная тема) | approved, «да» |
| G6 | sequence_flow (КТО → ЧТО → КАК) | local, «да» |
| G7 | stat_number | local, «да» |
| G8 | task_list (accumulate) | local, «да» |
| G9 | instagram-follow | upstream, «да» |

### Группа 2 — доработка по замечаниям Юлии («почти»)

| # | Блок | Что менять (слова Юлии) |
|---|------|------------------------|
| G10 | phone_case_overlay (бывш. avatar_object_overlay) | Без аватара: телефон на чистом фоне. Контент под реальные кейсы: скролл ленты, переписка, вопрос в чате |
| G11 | checklist_strike v2 | Механика ок, «покрасивее дизайн анимации»: полировка easing, стагger, дизайн пилюль как в витрине B3 |
| G12 | before_after v2 | Скучно статикой: больше анимации ИЛИ поверх fullscreen-аватара полупрозрачным слоем |
| G13 | complexity_cloud v2 | Использовать в перечислениях: слова всплывают с анимацией вокруг fullscreen-аватара, друг за другом по озвучке |

### Группа 3 — новые блоки из референсов (кода нет, строим по видео)

| # | Блок | Референс |
|---|------|----------|
| G14 | presenter_over_fullscreen_art — аватар мал внизу поверх fullscreen графики/арта, медленный zoom фона | C1 (QALAM BALAM) |
| G15 | big_ghost_number — гигантская полупрозрачная цифра вспыхивает на перечислении | C4 |
| G16 | app_price_cards — карточки-иконки с ценниками копятся у головы во время сравнения | D1 (alexeevweb) |
| G17 | pip_screencast — скринкаст/продукт fullscreen, аватар в скруглённом PiP снизу с градиент-подложкой | D2 |
| G18 | feature_typo_wall — стена названий крупной типографикой в ритме перечисления | D3 |
| G19 | text_selection_highlight — выделение строки как selection мышью, синхронно с фразой | D4 |
| G20 | cta_pill_word — финальный CTA: жёлтая пилюля со словом для комментария (замена social_outro, который «нет») | D5 |

Кандидат вне очереди: G21 avatar_cutout_pills (витрина B6) — cutout-аватар +
цветные пилюли-тезисы; в свайпе не участвовал, собрать превью и показать.

### Caption-система (не блоки, а слой)

Разрешены: editorial-emphasis, emoji-pop, gradient-fill, highlight, neon-accent,
particle-burst, pill-karaoke, weight-shift. Дефолт — bottom accumulate
(Unbounded, keyword #FFE500). Захардкодить в компилятор, LLM выбирает только
режим акцента из белого списка.

### Переходы

hard_cut (основной, ≥60% смен), transition_blur, transition_push_editorial,
transition_white_flash (кульминация). transition_chromatic — исключён.

## Отклонено свайпом (в каталог не берём)

avatar_broll_split, social_outro (заменён G20), concept_nodes, value_layers,
persona_card (skip), spotify-card, tiktok-follow, caption-blend-difference,
caption-clip-wipe, caption-glitch-rgb, caption-kinetic-slam, caption-matrix-decode,
caption-neon-glow, caption-parallax-layers, caption-texture, grain-overlay,
shimmer-sweep, texture-mask-text, vignette, transition_chromatic.

## Порядок сборки и приёмки

1. Партия 1: G10–G13 — СОБРАНА и ПРИНЯТА Юлией 2026-08-03
   (`golden-catalog/blocks/`, приёмка `review-batch-01.html`).
2. Партия 2: G14–G20 — СОБРАНА и ПРИНЯТА Юлией 2026-08-03
   (`review-batch-02.html`).
3. Партия 3: G1–G9 пересобраны в «Скетчбуке» 2026-08-03, на приёмке
   (`review-batch-03.html`). Каталог: 20/20 блоков реализовано.

Важно: стиль всех блоков — токены v2 «Скетчбук» (`design-tokens.md`),
общий код `golden-catalog/tokens.css` + `shared.js`.
4. Приёмка: каждый блок — рендер 3–5 с side-by-side с кадром референса,
   ответ «да / нет / правка». Блок в каталоге только после «да».
5. Механика движения каждого блока фиксируется в контракте (easing, стаггер,
   word-trigger), чтобы компилятор воспроизводил её детерминированно.
