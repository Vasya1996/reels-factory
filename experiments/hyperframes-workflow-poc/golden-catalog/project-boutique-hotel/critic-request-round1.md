# Визуальный критик — круг 1 (C:\Users\Asus\Documents\personal_ai\projects\content_factory\reels-factory-hyperframes-workflow-poc\experiments\hyperframes-workflow-poc\golden-catalog\project-boutique-hotel)

Ты смотришь на кадры смонтированного вертикального ролика (1080×1920) и
проверяешь монтаж по фиксированному чек-листу. У тебя нет доступа к прошлым
обсуждениям этого проекта — суди только по тому, что видишь на кадрах, и по
тексту речи/плана ниже.

## Чек-лист

Фиксированный чек-лист (NEXT-SESSION.md, правила v3-v5). По КАЖДОЙ сцене
ответь да/нет на каждый пункт, разбирая переданные кадры (начало и середина):

1. Пустая композиция: раскладка отжала место под контент, а самого контента
   там нет. Проверяй КАЖДУЮ сцену без исключения, даже если она не выглядит
   "сломанной" на первый взгляд: мысленно оцени, какая доля кадра (на глаз,
   в процентах) не занята ни аватаром, ни текстом, ни графикой. Если пустует
   заметная часть кадра (примерно треть и больше) — это находка, даже если
   формально в раскладке "что-то есть" (например, только заголовок наверху,
   а весь остальной отведённый под контент блок — пустое поле/бумага).
   ОБЯЗАТЕЛЬНО (правило v6 №16): для этой находки fix_op обязан быть
   add_label(text, trigger_word_index), где text — ДОСЛОВНО слово/фраза из
   "Речь сцены" ниже; report_only для находки этого класса допустим ТОЛЬКО
   вместе с объяснением в поле evidence, почему ни одно слово речи сцены не
   подходит для label.
2. Текст в кадре без функции: для КАЖДОГО отдельного текстового элемента
   (заголовок, метка, тег — не субтитры) отдельно спроси: если стереть
   именно этот элемент прямо сейчас, зритель что-то теряет? Особый случай —
   одиночное слово-название в углу кадра, которое лишь называет то же самое,
   что через мгновение и так проговорят субтитры внизу: это находка, даже
   если по формальным правилам (длина, отсутствие цитаты) элемент "разрешён".
3. Мета-слова/абстрактные категории в кадре (не конкретная нумерация глав).
4. Заголовок дублирует субтитры/речь сцены (>60% слов).
5. Приём (визуальная метафора блока) противоречит смыслу речи сцены.
6. Мёртвый простой в начале сцены: на кадре "начало" (t=scene.start+0.4)
   уже видно готовое событие, но между стартом сцены и первым событием
   слишком большой воздух.
7. Fullscreen-аватар: минимум 2 сцены должны быть TRUE fullscreen (видео на
   весь кадр, без рамки/капсулы/бумаги вокруг), хук обязан быть таким.
8. Текст обрезан/вылезает за кадр/перекрыт другим элементом; субтитры легли
   на важный контент.
9. Хук (первая сцена): заголовок — суть первой фразы (или его вообще нет),
    не абстракция типа "ЗНАКОМО?".

Правило v6 №17: «графика опережает слово» НЕ проверяется — это
машинно-гарантировано компилятором (тайминги строятся из word.start,
опережение физически невозможно; 3 ложных срабатывания за 3 круга на
прошлом проекте). Чек-лист — только невычислимое: пустота кадра, функция
текста, семантика приёма, читаемость.

ВАЖНО, постоянное уточнение правила 2/4 (не путать приём с багом): если
текст label/пилюли/облака-стикера — это слово или фраза, взятая ДОСЛОВНО из
речи именно этой сцены, то появление того же слова чуть позже в субтитрах —
НЕ дубль-баг, а задуманное подтверждение сказанного (стикер стемпится, когда
слово прозвучало, субтитры донабирают его следом — это одна и та же
механика, не два независимых текста). Находка "дубль" — ТОЛЬКО когда
элемент декоративный и не несёт НИКАКОЙ второй функции (например, одиночный
заголовок-этикетка в углу, который просто называет то же самое и ничего не
добавляет). Не предлагай remove_label только потому, что слово label потом
встречается в субтитрах — это нормально для label, взятых из речи.

Выведи СТРОГИЙ JSON (без markdown, без пояснений вне JSON) — массив находок:
[{"scene_id":"sNN","rule":"<номер правила из списка выше>","evidence":"что именно видно на кадре(ах)","fix_op":"<ровно одна строка из меню>"}]

Меню fix_op (используй ТОЛЬКО эти формы, ничего своего не изобретай):
- set_block(name)
- set_headline(null|text)
- add_label(text, trigger_word_index) — текст ТОЛЬКО дословно из слов речи ИМЕННО этой сцены (см. блок "Речь сцены" ниже), trigger_word_index — индекс слова из этой же речи, откуда взят текст
- remove_label(idx)
- set_label_trigger(idx, word_index)
- move_boundary(scene, ±sec)
- set_captions(hidden|bottom)
- set_transition(name)
- report_only

Если находку нельзя починить ни одним из этих fix_op — используй "report_only".
Если находок нет вообще — верни пустой массив [].

## Сцены

### s01 (purpose: hook, block: avatarFullscreen, avatar_direction: fullscreen, captions: bottom, transition_in: hard_cut)
- Диапазон: 0.00s–4.97s (слова 0-8)
- Речь сцены: "Обычная гостиница окупается за пятнадцать лет Бутик-отель вдвое быстрее"
- headline: null
- labels: []
- emphasis_words: ["вдвое"]
- Кадры: start@0.4s → snapshots-round1/frame-00-at-0.4s.png; mid@2.48s → snapshots-round1/frame-01-at-2.48s.png

### s02 (purpose: build, block: avatarBubble, avatar_direction: editorial_bubble, captions: bottom, transition_in: hard_cut)
- Диапазон: 4.97s–8.88s (слова 9-16)
- Речь сцены: "Многие вкладывают в отели И ждут прибыль десятилетиями"
- headline: "ДОЛГО ЖДУТ"
- labels: [{"text":"вкладывают","trigger_word_index":10},{"text":"десятилетиями","trigger_word_index":16}]
- emphasis_words: ["десятилетиями"]
- Кадры: start@5.37s → snapshots-round1/frame-02-at-5.37s.png; mid@6.93s → snapshots-round1/frame-03-at-6.93s.png

### s03 (purpose: contrast, block: avatarFullscreen, avatar_direction: fullscreen, captions: bottom, transition_in: white_flash)
- Диапазон: 8.88s–11.23s (слова 17-24)
- Речь сцены: "Но дело не в отелях а в формате"
- headline: "ФОРМАТ РЕШАЕТ"
- labels: []
- emphasis_words: ["формате"]
- Кадры: start@9.28s → snapshots-round1/frame-04-at-9.28s.png; mid@10.05s → snapshots-round1/frame-05-at-10.05s.png

### s04 (purpose: explain, block: complexityCloud, avatar_direction: fullscreen, captions: bottom, transition_in: hard_cut)
- Диапазон: 11.23s–16.15s (слова 25-34)
- Речь сцены: "Бутик-отели санатории и медикал спа окупаются всего за девять лет"
- headline: null
- labels: [{"text":"бутик-отели","trigger_word_index":25},{"text":"санатории","trigger_word_index":26},{"text":"медикал спа","trigger_word_index":28},{"text":"девять лет","trigger_word_index":33}]
- emphasis_words: ["девять"]
- Кадры: start@11.63s → snapshots-round1/frame-06-at-11.63s.png; mid@13.69s → snapshots-round1/frame-07-at-13.69s.png

### s05 (purpose: contrast, block: avatarBubble, avatar_direction: editorial_bubble, captions: bottom, transition_in: hard_cut)
- Диапазон: 16.15s–23.00s (слова 35-47)
- Речь сцены: "Это почти вдвое быстрее обычной гостиницы Там ждут пятнадцать лет Рентабельность обычной гостиницы"
- headline: null
- labels: [{"text":"почти вдвое","trigger_word_index":36},{"text":"пятнадцать лет","trigger_word_index":43}]
- emphasis_words: ["пятнадцать"]
- Кадры: start@16.55s → snapshots-round1/frame-08-at-16.55s.png; mid@19.57s → snapshots-round1/frame-09-at-19.57s.png

### s06 (purpose: payoff, block: beforeAfter, avatar_direction: object_overlay, captions: bottom, transition_in: hard_cut)
- Диапазон: 23.00s–27.02s (слова 48-56)
- Речь сцены: "двадцать пять процентов У бутик-отеля и спа тридцать пять"
- headline: null
- labels: [{"text":"двадцать пять","trigger_word_index":48},{"text":"тридцать пять","trigger_word_index":55}]
- emphasis_words: ["процентов"]
- Кадры: start@23.4s → snapshots-round1/frame-10-at-23.4s.png; mid@25.01s → snapshots-round1/frame-11-at-25.01s.png

### s07 (purpose: payoff, block: statNumber, avatar_direction: hidden, captions: bottom, transition_in: hard_cut)
- Диапазон: 27.02s–29.98s (слова 57-65)
- Речь сцены: "Вот и вся разница в доходе на вложенный рубль"
- headline: null
- labels: [{"text":"разница","trigger_word_index":60}]
- emphasis_words: ["рубль"]
- Кадры: start@27.42s → snapshots-round1/frame-12-at-27.42s.png; mid@28.5s → snapshots-round1/frame-13-at-28.5s.png

### s08 (purpose: cta, block: avatarFullscreen, avatar_direction: fullscreen, captions: bottom, transition_in: white_flash)
- Диапазон: 29.98s–33.06s (слова 66-72)
- Речь сцены: "Сохрани если задумываешься об инвестициях в отели"
- headline: null
- labels: []
- emphasis_words: ["Сохрани"]
- Кадры: start@30.38s → snapshots-round1/frame-14-at-30.38s.png; mid@31.52s → snapshots-round1/frame-15-at-31.52s.png

## Кадры

Открой файлы snapshots-round1/*.png (перечислены выше при каждой сцене)
через Read и посмотри на них лично, прежде чем отвечать.
