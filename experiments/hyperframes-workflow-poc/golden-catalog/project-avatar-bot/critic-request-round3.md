# Визуальный критик — круг 3 (C:\Users\Asus\Documents\personal_ai\projects\content_factory\reels-factory-hyperframes-workflow-poc\experiments\hyperframes-workflow-poc\golden-catalog\project-avatar-bot)

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
2. Текст в кадре без функции: для КАЖДОГО отдельного текстового элемента
   (заголовок, метка, тег — не субтитры) отдельно спроси: если стереть
   именно этот элемент прямо сейчас, зритель что-то теряет? Особый случай —
   одиночное слово-название в углу кадра, которое лишь называет то же самое,
   что через мгновение и так проговорят субтитры внизу: это находка, даже
   если по формальным правилам (длина, отсутствие цитаты) элемент "разрешён".
3. Мета-слова/абстрактные категории в кадре (не конкретная нумерация глав).
4. Заголовок дублирует субтитры/речь сцены (>60% слов).
5. Приём (визуальная метафора блока) противоречит смыслу речи сцены.
6. Графика опережает слова: сравни кадр "начало" и кадр "середина" — не
   появился ли текст/элемент ДО того, как соответствующее слово могло
   прозвучать.
7. Мёртвый простой в начале сцены: на кадре "начало" (t=scene.start+0.4)
   уже видно готовое событие, но между стартом сцены и первым событием
   слишком большой воздух.
8. Fullscreen-аватар: минимум 2 сцены должны быть TRUE fullscreen (видео на
   весь кадр, без рамки/капсулы/бумаги вокруг), хук обязан быть таким.
9. Текст обрезан/вылезает за кадр/перекрыт другим элементом; субтитры легли
   на важный контент.
10. Хук (первая сцена): заголовок — суть первой фразы (или его вообще нет),
    не абстракция типа "ЗНАКОМО?".

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
- Диапазон: 0.00s–3.38s (слова 0-9)
- Речь сцены: "Этот ролик записала не я. Да, ты смотришь на аватар."
- headline: null
- labels: []
- emphasis_words: ["аватар"]
- Кадры: start@0.4s → snapshots-round3/frame-00-at-0.4s.png; mid@1.69s → snapshots-round3/frame-01-at-1.69s.png

### s02 (purpose: contrast, block: avatarBubble, avatar_direction: editorial_bubble, captions: bottom, transition_in: hard_cut)
- Диапазон: 3.38s–5.49s (слова 10-16)
- Речь сцены: "И его не отличить от реального видео."
- headline: "КАК ЖИВОЙ"
- labels: []
- emphasis_words: ["видео"]
- Кадры: start@3.78s → snapshots-round3/frame-02-at-3.78s.png; mid@4.44s → snapshots-round3/frame-03-at-4.44s.png

### s03 (purpose: build, block: complexityCloud, avatar_direction: fullscreen, captions: bottom, transition_in: hard_cut)
- Диапазон: 5.49s–9.74s (слова 17-26)
- Речь сцены: "Пока строишь продукт, физически не успеваешь снимать контент каждый день."
- headline: "НЕТ ВРЕМЕНИ"
- labels: [{"text":"продукт","trigger_word_index":19},{"text":"контент","trigger_word_index":24},{"text":"каждый день","trigger_word_index":25}]
- emphasis_words: ["успеваешь"]
- Кадры: start@5.89s → snapshots-round3/frame-04-at-5.89s.png; mid@7.62s → snapshots-round3/frame-05-at-7.62s.png

### s04 (purpose: contrast, block: avatarBubble, avatar_direction: editorial_bubble, captions: bottom, transition_in: hard_cut)
- Диапазон: 9.74s–13.46s (слова 27-34)
- Речь сцены: "А в соцсетях находят тех, кого видят регулярно."
- headline: "КТО НА ВИДУ"
- labels: [{"text":"в соцсетях","trigger_word_index":29},{"text":"видят регулярно","trigger_word_index":33}]
- emphasis_words: ["регулярно"]
- Кадры: start@10.14s → snapshots-round3/frame-06-at-10.14s.png; mid@11.6s → snapshots-round3/frame-07-at-11.6s.png

### s05 (purpose: explain, block: avatarFullscreen, avatar_direction: fullscreen, captions: bottom, transition_in: white_flash)
- Диапазон: 13.46s–18.12s (слова 35-46)
- Речь сцены: "Поэтому мы сделали бота: он берёт одно фото и запись твоего голоса"
- headline: null
- labels: []
- emphasis_words: ["фото"]
- Кадры: start@13.86s → snapshots-round3/frame-08-at-13.86s.png; mid@15.79s → snapshots-round3/frame-09-at-15.79s.png

### s06 (purpose: payoff, block: phoneCase, avatar_direction: object_overlay, captions: bottom, transition_in: hard_cut)
- Диапазон: 18.12s–21.30s (слова 47-54)
- Речь сцены: "и превращает всё в готовое видео для соцсетей."
- headline: null
- labels: ["Видео готово 🎬","Уже в сторис 🔥"]
- emphasis_words: ["соцсетей"]
- Кадры: start@18.52s → snapshots-round3/frame-10-at-18.52s.png; mid@19.71s → snapshots-round3/frame-11-at-19.71s.png

### s07 (purpose: payoff, block: taskList, avatar_direction: object_overlay, captions: bottom, transition_in: hard_cut)
- Диапазон: 21.30s–25.72s (слова 55-61)
- Речь сцены: "Уже смонтированное, с субтитрами, анимациями и эффектами."
- headline: "ГОТОВО"
- labels: [{"text":"смонтированное","trigger_word_index":56},{"text":"субтитрами","trigger_word_index":58},{"text":"анимациями","trigger_word_index":59},{"text":"эффектами","trigger_word_index":61}]
- emphasis_words: ["анимациями"]
- Кадры: start@21.7s → snapshots-round3/frame-12-at-21.7s.png; mid@23.51s → snapshots-round3/frame-13-at-23.51s.png

### s08 (purpose: cta, block: avatarFullscreenCta, avatar_direction: fullscreen, captions: bottom, transition_in: white_flash)
- Диапазон: 25.72s–29.54s (слова 62-70)
- Речь сцены: "Если хочешь также - пиши "хочу", пришлю все детали!"
- headline: null
- labels: ["@julia.agents"]
- emphasis_words: ["хочу"]
- Кадры: start@26.12s → snapshots-round3/frame-14-at-26.12s.png; mid@27.63s → snapshots-round3/frame-15-at-27.63s.png

## Кадры

Открой файлы snapshots-round3/*.png (перечислены выше при каждой сцене)
через Read и посмотри на них лично, прежде чем отвечать.
