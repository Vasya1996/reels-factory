import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { execSync } from "node:child_process";

const ROOT = process.cwd();
const CONTENT_ROOT = path.resolve(ROOT, "..");
const STAGE = path.join(ROOT, "experiments/hyperframes-workflow-poc/stage-01-catalog");
const OUT = {
  inventory: path.join(STAGE, "inventory"),
  galleryAssets: path.join(STAGE, "gallery/assets"),
  posters: path.join(STAGE, "gallery/assets/posters"),
  galleryData: path.join(STAGE, "gallery/data"),
  shortlist: path.join(STAGE, "shortlist"),
  reports: path.join(STAGE, "reports"),
  scripts: path.join(STAGE, "scripts"),
};
const SOURCES = {
  upstreamRoot: path.join(CONTENT_ROOT, "reference-audit/hyperframes-main-20260801-complete/hyperframes-main"),
  upstreamZip: path.join(CONTENT_ROOT, "reference-audit/hyperframes-main-20260801.zip"),
  localBlocksPy: path.join(ROOT, "plugins/reels-factory/engine/src/reels_factory/hyperframes_blocks.py"),
  localHyperframesDir: path.join(ROOT, "plugins/reels-factory/engine/hyperframes"),
  approvedRoot: path.join(CONTENT_ROOT, "plan-previews/two-reel-catalog-proxy-20260729"),
  memory: path.join(CONTENT_ROOT, "REELS-FACTORY-MEMORY.md"),
  pipelineTz: path.join(CONTENT_ROOT, "TZ-HYPERFRAMES-CATALOG-PIPELINE.md"),
  agents: path.join(ROOT, "AGENTS.md"),
  editPlan: path.join(ROOT, "docs/EDIT-PLAN.md"),
  visualDirector: path.join(ROOT, "docs/VISUAL-DIRECTOR.md"),
};
const EXPECTED = {
  branch: "codex/hyperframes-workflow-poc",
  zipHash: "CCA9B08B39A4A5FA29E55D9260F49020B1B6D455C68A674B42D4C3661D185BE3",
  version: "0.7.87",
  upstreamBlocks: 113,
  upstreamComponents: 25,
  examples: 8,
  localBlocks: ["before_after", "complexity_cloud", "concept_nodes", "persona_card", "sequence_flow", "stat_number", "task_list", "value_layers"],
  approvedLayouts: 10,
  approvedTransitions: 5,
  total: 161,
};
const CATEGORIES = ["speaker_layout","composition_layout","caption_and_typography","title_and_lower_third","data_and_statistics","comparison_and_process","social_and_editorial_overlay","transition","texture_and_finishing","media_treatment","vfx_and_shader","spatial_motion","code_and_terminal","map_and_diagram","brand_and_outro","other"];
const PARAM_LEVELS = ["declarative","manifest_only","generated_python","approved_js_contract","none","unknown"];
const SCORE_ROLE_SET = new Set(["caption","lower_third","title","quote","data_visualization","stat","comparison","list","process","social_overlay","transition","layout"]);
const RU_CATEGORY = {
  speaker_layout: "раскладка с ведущим",
  composition_layout: "композиционная раскладка",
  caption_and_typography: "субтитры и типографика",
  title_and_lower_third: "титры и lower third",
  data_and_statistics: "данные и статистика",
  comparison_and_process: "сравнение и процесс",
  social_and_editorial_overlay: "социальные и editorial overlay",
  transition: "переход",
  texture_and_finishing: "текстура и finishing",
  media_treatment: "обработка медиа",
  vfx_and_shader: "VFX и shader",
  spatial_motion: "пространственное движение",
  code_and_terminal: "код и терминал",
  map_and_diagram: "карты и диаграммы",
  brand_and_outro: "бренд и outro",
  other: "прочее",
};

const LOCAL_DESCRIPTIONS = {
  before_after: "Карточки сравнивают старое и новое состояние через движение «было → стало».",
  complexity_cloud: "Несколько шумных тезисов появляются каскадом и схлопываются в одно решение.",
  concept_nodes: "Центральный тезис соединяется линиями с опорными понятиями.",
  persona_card: "Карточка аудитории раскрывает человека, контекст и боль.",
  sequence_flow: "Нумерованные шаги раскрываются сверху вниз как обязательный порядок.",
  stat_number: "Крупная цифра досчитывается до значения и фиксирует измеримый тезис.",
  task_list: "Пункты списка появляются последовательно, последний может стать акцентом.",
  value_layers: "Формальный offer сменяется реальной ценностью, которую покупает клиент.",
};
const APPROVED_DESCRIPTIONS = {
  avatar_fullscreen: "Движущийся аватар занимает весь вертикальный кадр и держит eye contact.",
  avatar_editorial_bubble: "Движущийся аватар находится в крупном editorial bubble рядом с текстом.",
  avatar_broll_split: "Кадр разделён между аватаром и B-roll, обе области заполнены.",
  broll_fullscreen: "B-roll занимает весь экран и конкретизирует фразу без лица.",
  checklist_strike: "Пункты рутины появляются списком и по очереди зачёркиваются.",
  progressive_text_card: "Фраза собирается крупными типографическими строками.",
  broll_archival_collage: "Несколько B-roll слоёв раскладываются как editorial collage.",
  avatar_cutout_overlay: "Исторический cutout с прозрачным PNG ведущего поверх карточек; запрещён для runtime.",
  avatar_object_overlay: "Движущийся аватар сочетается с предметным overlay, например телефоном.",
  social_outro: "Финальный social lockup фиксирует CTA и handle.",
  hard_cut: "Мгновенная смена окна без графического перехода.",
  transition_push_editorial: "Новый кадр въезжает сбоку и вытесняет предыдущий.",
  transition_blur: "Следующий кадр появляется из размытия и лёгкого scale.",
  transition_chromatic: "RGB-полосы создают короткий технологичный акцент.",
  transition_white_flash: "Белая вспышка резко вводит следующий смысловой пик.",
};
const APPROVED_SYMBOLS = {
  avatar_fullscreen: ["renderAvatarFullscreen","animateAvatar"],
  avatar_editorial_bubble: ["renderEditorial","animateEditorial"],
  avatar_broll_split: ["renderSplit","animateSplit"],
  broll_fullscreen: ["renderBroll","animateBroll"],
  checklist_strike: ["renderChecklist","animateChecklist"],
  progressive_text_card: ["renderProgressive","animateProgressive"],
  broll_archival_collage: ["renderCollage","animateCollage"],
  avatar_cutout_overlay: ["renderCutout","animateCutout"],
  avatar_object_overlay: ["renderObject","animateObject"],
  social_outro: ["renderOutro","animateOutro"],
  hard_cut: ["addTransition"],
  transition_push_editorial: ["addTransition"],
  transition_blur: ["addTransition"],
  transition_chromatic: ["addTransition"],
  transition_white_flash: ["addTransition"],
};
const MULTI_VARIANTS = {
  "upstream:block:transitions-blur": ["transition_blur_through","transition_directional_blur","transition_calm_blur_through"],
  "upstream:block:transitions-cover": ["transition_staggered_blocks","transition_horizontal_blinds","transition_vertical_blinds"],
  "upstream:block:transitions-push": ["transition_push_slide","transition_vertical_push","transition_elastic_push","transition_squeeze"],
  "upstream:block:transitions-dissolve": ["transition_crossfade","transition_blur_crossfade","transition_focus_pull","transition_dip_to_black"],
  "upstream:block:transitions-light": ["transition_light_leak","transition_overexposure_burn","transition_film_burn"],
  "upstream:block:transitions-3d": ["transition_3d_card_flip"],
  "upstream:block:transitions-destruction": ["transition_page_burn"],
  "upstream:block:transitions-distortion": ["transition_distortion_glitch","transition_chromatic_aberration","transition_ripple_distortion"],
  "upstream:block:transitions-grid": ["transition_grid_dissolve"],
  "upstream:block:transitions-mechanical": ["transition_mechanical_shutter","transition_clock_wipe"],
  "upstream:block:transitions-other": ["transition_flash_cut","transition_gravity_drop","transition_morph_circle"],
  "upstream:block:transitions-radial": ["transition_circle_iris","transition_diamond_iris","transition_diagonal_split"],
  "upstream:block:transitions-scale": ["transition_zoom_through","transition_zoom_out"],
};
const MULTI_EVIDENCE = {
  "upstream:block:transitions-3d": [274, 276, "Исходник называет единственный вариант: 3D Card Flip."],
  "upstream:block:transitions-blur": [179, 190, "Исходник перечисляет Blur Through, Directional Blur и Calm Blur Through."],
  "upstream:block:transitions-cover": [286, 288, "Конфигурация перечисляет Staggered Blocks, Horizontal Blinds и Vertical Blinds."],
  "upstream:block:transitions-destruction": [187, 187, "Исходник называет единственный вариант: Page Burn."],
  "upstream:block:transitions-dissolve": [179, 195, "Исходник перечисляет Crossfade, Blur Crossfade, Focus Pull и Color Dip."],
  "upstream:block:transitions-distortion": [210, 218, "Исходник перечисляет Glitch, Chromatic Aberration и Ripple."],
  "upstream:block:transitions-grid": [166, 166, "Исходник называет единственный вариант: Grid Dissolve."],
  "upstream:block:transitions-light": [304, 306, "Конфигурация перечисляет Light Leak, Overexposure Burn и Film Burn."],
  "upstream:block:transitions-mechanical": [205, 210, "Исходник перечисляет Shutter и Clock Wipe."],
  "upstream:block:transitions-other": [210, 220, "Исходник перечисляет Flash Cut, Gravity Drop и Morph Circle."],
  "upstream:block:transitions-push": [179, 195, "Исходник перечисляет Push Slide, Vertical Push, Elastic Push и Squeeze."],
  "upstream:block:transitions-radial": [273, 321, "Timeline называет Circle Iris, Diamond Iris и Diagonal Split."],
  "upstream:block:transitions-scale": [179, 184, "Исходник перечисляет Zoom Through и Zoom Out."],
};
const SPECIAL_EVIDENCE = {
  "upstream:block:vfx-liquid-glass": [
    ["registry/blocks/vfx-liquid-glass/vfx-liquid-glass.html", 418, 441, "Код создаёт отдельные стеклянные фрагменты через Voronoi-разбиение."],
    ["registry/blocks/vfx-liquid-glass/vfx-liquid-glass.html", 660, 678, "Код связывает поворот стеклянного слоя с указателем и управляет разлётом фрагментов."],
  ],
  "upstream:block:vfx-magnetic": [
    ["registry/blocks/vfx-magnetic/vfx-magnetic.html", 180, 207, "Текст и shader-комментарий описывают притяжение пикселей к курсору, Gaussian warp и chromatic aberration."],
  ],
  "upstream:block:vfx-portal": [
    ["registry/blocks/vfx-portal/vfx-portal.html", 595, 614, "Fragment shader задаёт радиальное искажение, цветное расщепление, маску и светящееся кольцо портала."],
  ],
  "upstream:block:vfx-shatter": [
    ["registry/blocks/vfx-shatter/vfx-shatter.html", 737, 811, "Shader строит расходящийся Voronoi-рисунок трещин перед разрушением плоскости."],
  ],
};
const TECH_OVERRIDES = {
  "local:block:stat_number": ["animated_stat_countup"],
  "local:block:before_after": ["before_after_comparison"],
  "local:block:task_list": ["task_checklist_reveal"],
  "local:block:complexity_cloud": ["complexity_to_resolution"],
  "local:block:persona_card": ["persona_context_card"],
  "local:block:value_layers": ["value_layer_swap"],
  "local:block:concept_nodes": ["concept_node_map"],
  "local:block:sequence_flow": ["sequence_step_flow"],
  "approved:layout:avatar_fullscreen": ["avatar_fullscreen_anchor"],
  "approved:layout:avatar_editorial_bubble": ["avatar_editorial_bubble"],
  "approved:layout:avatar_broll_split": ["avatar_broll_split"],
  "approved:layout:broll_fullscreen": ["broll_fullscreen"],
  "approved:layout:checklist_strike": ["checklist_strike_routine"],
  "approved:layout:progressive_text_card": ["progressive_text_card"],
  "approved:layout:broll_archival_collage": ["archival_broll_collage"],
  "approved:layout:avatar_cutout_overlay": ["forbidden_avatar_cutout_overlay"],
  "approved:layout:avatar_object_overlay": ["avatar_object_overlay"],
  "approved:layout:social_outro": ["social_outro_lockup"],
  "approved:transition:hard_cut": ["hard_cut_transition"],
  "approved:transition:transition_push_editorial": ["editorial_push_transition"],
  "approved:transition:transition_blur": ["blur_soft_transition"],
  "approved:transition:transition_chromatic": ["chromatic_accent_transition"],
  "approved:transition:transition_white_flash": ["white_flash_transition"],
  "upstream:component:motion-blur": ["spatial_motion_blur"],
  ...MULTI_VARIANTS,
};
const TECH_BASE = {
  animated_stat_countup: ["Анимированный счётчик числа","data_and_statistics","Число досчитывается до ключевого значения и фиксирует измеримый тезис.","Зритель видит крупную цифру, которая быстро растёт до целевого значения."],
  before_after_comparison: ["Сравнение «было → стало»","comparison_and_process","Старое состояние уступает место новому, показывая контраст.","Зритель видит две карточки и направленную смену между ними."],
  task_checklist_reveal: ["Пошаговый список с акцентом","comparison_and_process","Пункты появляются по очереди и превращают перечисление в порядок действий.","Зритель видит вертикальный список с номерами и акцентной финальной строкой."],
  checklist_strike_routine: ["Зачёркивание рутины","comparison_and_process","Повторяющиеся задачи зачёркиваются, чтобы показать избавление от ручной работы.","Зритель видит строки списка и красные линии зачёркивания."],
  complexity_to_resolution: ["Схлопывание сложности в решение","comparison_and_process","Несколько шумных тезисов собираются в один ясный вывод.","Зритель видит россыпь карточек, которая сменяется центральной карточкой решения."],
  persona_context_card: ["Карточка аудитории","speaker_layout","Аудитория показана как человек с контекстом и болью.","Зритель видит avatar-mark и строки с характеристиками ситуации."],
  value_layer_swap: ["Замена продукта ценностью","comparison_and_process","Формальный продукт визуально сменяется настоящей покупаемой ценностью.","Зритель видит две смысловые карточки, где вторая занимает главный фокус."],
  concept_node_map: ["Карта связанных понятий","map_and_diagram","Центральный тезис соединяется с несколькими опорными понятиями.","Зритель видит hub в центре и карточки вокруг него."],
  sequence_step_flow: ["Вертикальный flow шагов","comparison_and_process","Шаги раскрываются сверху вниз и подчёркивают порядок.","Зритель видит нумерованные карточки со стрелками между ними."],
  avatar_fullscreen_anchor: ["Полноэкранный аватар-якорь","speaker_layout","Движущийся ведущий удерживает личный контакт.","Зритель видит avatar video на весь вертикальный кадр."],
  avatar_editorial_bubble: ["Аватар в editorial bubble","speaker_layout","Ведущий остаётся видимым внутри крупного bubble рядом с пояснением.","Зритель видит avatar video в нестандартной рамке и текстовую колонку."],
  avatar_broll_split: ["Split screen: аватар и B-roll","composition_layout","Лицо и доказательный материал показываются одновременно.","Зритель видит две заполненные вертикальные области."],
  broll_fullscreen: ["Полноэкранный B-roll","composition_layout","Материал занимает весь кадр и конкретизирует тезис.","Зритель видит вертикальный B-roll с мягким движением."],
  progressive_text_card: ["Прогрессивная типографическая карточка","caption_and_typography","Фраза собирается крупными смысловыми строками.","Зритель видит большие слова, которые появляются по очереди."],
  archival_broll_collage: ["Editorial collage из B-roll","composition_layout","Несколько медиа-слоёв показывают широту примеров.","Зритель видит наклонённые карточки с видео, штамп и подпись."],
  forbidden_avatar_cutout_overlay: ["Запрещённый исторический cutout overlay","speaker_layout","Историческая реализация сохранена только как reference.","Зритель видит статичный cutout человека поверх editorial карточек."],
  avatar_object_overlay: ["Аватар с предметным overlay","social_and_editorial_overlay","Предмет или интерфейс рядом с ведущим объясняет действие продукта.","Зритель видит avatar video, телефон, bubbles и стрелку."],
  social_outro_lockup: ["Финальный social outro lockup","brand_and_outro","Финальный кадр фиксирует CTA и handle.","Зритель видит крупный призыв, handle и кнопку."],
  hard_cut_transition: ["Жёсткий монтажный стык","transition","Сцена меняется мгновенно без промежуточного графического слоя или анимации.","Зритель видит чистую моментальную смену одного кадра другим."],
  editorial_push_transition: ["Editorial push-переход","transition","Следующий кадр въезжает сбоку и вытесняет предыдущий.","Зритель видит горизонтальный push нового layout."],
  blur_soft_transition: ["Мягкий blur-переход","transition","Кадр появляется из размытия и лёгкого scale.","Зритель видит слой, который становится резким."],
  chromatic_accent_transition: ["Chromatic accent-переход","transition","RGB-полосы подчёркивают технологичный смысловой удар.","Зритель видит короткую цветовую рассинхронизацию каналов."],
  white_flash_transition: ["Белая flash-смена","transition","Белая вспышка резко вводит новый смысловой пик.","Зритель видит полноэкранный белый слой, который быстро исчезает."],
};
const VARIANT_NAMES = {
  transition_blur_through: ["Blur-through переход","transition","Кадр проходит через общее размытие при смене.","Зритель видит старый и новый кадр, соединённые blur-состоянием."],
  transition_directional_blur: ["Направленное размытие при смене кадра","transition","Новый кадр входит через размытие, вытянутое по направлению движения.","Зритель видит смазанный по направлению кадр, который уступает место следующему."],
  transition_calm_blur_through: ["Спокойный blur-through переход","transition","Мягкое размытие связывает спокойную смену сцен.","Зритель видит ненавязчивый blur без резкого удара."],
  transition_staggered_blocks: ["Переход ступенчатыми блоками","transition","Кадр закрывается или открывается блоками с задержкой.","Зритель видит плитки, которые входят не одновременно."],
  transition_horizontal_blinds: ["Горизонтальные жалюзи","transition","Смена кадра идёт полосами по горизонтали.","Зритель видит горизонтальные створки, открывающие новый кадр."],
  transition_vertical_blinds: ["Вертикальные жалюзи","transition","Смена кадра идёт вертикальными полосами.","Зритель видит вертикальные створки, открывающие новый кадр."],
  transition_push_slide: ["Push slide-переход","transition","Новый кадр сдвигает старый как цельная плоскость.","Зритель видит боковой slide между сценами."],
  transition_vertical_push: ["Вертикальный push-переход","transition","Новый кадр вытесняет старый вверх или вниз.","Зритель видит вертикальное смещение всей сцены."],
  transition_elastic_push: ["Эластичный push-переход","transition","Смена кадра делает пружинящий push.","Зритель видит упругое движение с небольшим overshoot."],
  transition_squeeze: ["Squeeze-переход","transition","Старый кадр сжимается, освобождая место новому.","Зритель видит сжатие плоскости кадра."],
  transition_crossfade: ["Классический crossfade","transition","Один кадр растворяется в другом через opacity.","Зритель видит плавное смешивание двух сцен."],
  transition_blur_crossfade: ["Blur crossfade с размытием","transition","Плавное растворение двух кадров дополнено общей фазой мягкого размытия.","Зритель видит старую сцену, которая теряет резкость и смешивается с новой."],
  transition_focus_pull: ["Focus pull-переход","transition","Смена сцены имитирует перевод фокуса объектива с одного плана на другой.","Зритель видит потерю резкости старого кадра и появление нового фокуса."],
  transition_dip_to_black: ["Dip to black через затемнение","transition","Кадр уходит в чёрный и возвращается новым изображением.","Зритель видит короткое затемнение между сценами."],
  transition_light_leak: ["Light Leak-переход","transition","Световой засвет перекрывает стык кадров.","Зритель видит тёплую световую протечку поверх изображения."],
  transition_overexposure_burn: ["Overexposure burn с пересветом","transition","Яркость старого кадра резко растёт до полного пересвета и открывает новую сцену.","Зритель видит короткое белое выгорание изображения на монтажном стыке."],
  transition_film_burn: ["Film burn-переход","transition","Смена стилизована под плёночный прожог.","Зритель видит органичный световой ожог по краю или центру."],
  transition_3d_card_flip: ["3D-переворот карточки","transition","Один кадр разворачивается в пространстве как карточка и открывает следующий.","Зритель видит один перспективный переворот плоскости вокруг вертикальной оси."],
  transition_page_burn: ["Прожиг страницы","transition","Старый кадр разрушается по неровному огненному фронту и открывает новый.","Зритель видит, как изображение выгорает подобно бумажной странице."],
  transition_distortion_glitch: ["Glitch-искажение","transition","Стык кадров маскируется цифровыми разрывами и смещениями фрагментов.","Зритель видит короткий цифровой сбой перед появлением новой сцены."],
  transition_chromatic_aberration: ["Хроматическая аберрация","transition","Красный, зелёный и синий каналы расходятся во время смены кадров.","Зритель видит цветные контуры и краткую рассинхронизацию изображения."],
  transition_ripple_distortion: ["Волновое искажение","transition","Новый кадр проявляется через расходящуюся деформацию поверхности.","Зритель видит волну, которая искривляет стык между сценами."],
  transition_grid_dissolve: ["Растворение сеткой","transition","Кадр распадается на клетки сетки и последовательно открывает следующий.","Зритель видит единственный вариант Grid Dissolve с каскадом квадратных ячеек."],
  transition_mechanical_shutter: ["Механический затвор","transition","Сегменты затвора закрывают старый кадр и открывают новый.","Зритель видит движение створок, похожее на затвор камеры."],
  transition_clock_wipe: ["Круговая часовая шторка","transition","Радиальный сектор обходит кадр по кругу, заменяя изображение.","Зритель видит wipe, движущийся как стрелка часов."],
  transition_flash_cut: ["Flash Cut со вспышкой","transition","Короткая вспышка создаёт резкий акцент на монтажном стыке.","Зритель видит мгновенный световой удар и новый кадр."],
  transition_gravity_drop: ["Падение под действием гравитации","transition","Старый кадр падает вниз и освобождает место следующему.","Зритель видит тяжёлое вертикальное падение всей сцены."],
  transition_morph_circle: ["Круговой morph-переход","transition","Круглая маска меняет размер и форму, раскрывая новый кадр.","Зритель видит сцену, появляющуюся через трансформирующийся круг."],
  transition_circle_iris: ["Круглая диафрагма","transition","Круглая маска расширяется или сжимается вокруг точки фокуса.","Зритель видит классический круговой iris reveal."],
  transition_diamond_iris: ["Ромбовидная диафрагма","transition","Ромбовидная маска раскрывает новый кадр от центра.","Зритель видит геометрический iris reveal в форме ромба."],
  transition_diagonal_split: ["Диагональное раскрытие","transition","Две диагональные половины расходятся и показывают следующую сцену.","Зритель видит разрез кадра по диагонали."],
  transition_zoom_through: ["Проход через приближение Zoom Through","transition","Камера проходит сквозь увеличивающийся кадр в следующую сцену.","Зритель видит быстрое приближение, которое становится новым изображением."],
  transition_zoom_out: ["Отъезд камеры Zoom Out","transition","Старый кадр уменьшается и обнаруживает следующую сцену вокруг него.","Зритель видит отъезд камеры от предыдущего изображения."],
  spatial_motion_blur: ["Шлейф от быстрого движения","spatial_motion","Скорость элемента управляет односторонним SVG-размытием и создаёт призрачный след.","Зритель видит смазанный шлейф за движущимся объектом внутри сцены; это не переход между сценами."],
};

const RU_DESCRIPTION = {
  apple_terminal_theme_card: "Окно macOS Terminal посимвольно печатает командную сессию; двенадцать implementations отличаются цветовой темой терминала.",
  brand_showcase_app_showcase: "Три парящих экрана смартфона последовательно показывают интерфейс фитнес-приложения.",
  brand_showcase_apple_money_count: "Счётчик в стилистике Apple растёт от нуля до 10 000 долларов, вспыхивает зелёным и выпускает иконки денег.",
  brand_showcase_blue_sweater_intro_video: "Тёплая заставка AI-креатора собирается из нескольких кадров и завершается карточкой подписки на профиль X.",
  brand_showcase_logo_outro: "Фрагменты логотипа собираются в знак, появляется свечение, затем слоган и плашка с адресом сайта.",
  brand_showcase_nyc_paris_flight: "На реалистичной карте самолёт летит из Нью-Йорка в Париж, после посадки появляются маркер и подпись.",
  brand_showcase_vpn_youtube_spot: "Телефон показывает поиск и установку VPN-приложения как короткую рекламную вставку в стилистике Apple.",
  caption_blend_difference: "Текст автоматически переключается между белым и чёрным по яркости фона благодаря mix-blend-mode: difference.",
  caption_clip_wipe: "Каждое слово субтитра открывается слева направо отдельной clip-path шторкой.",
  caption_editorial_emphasis: "Две гарнитуры и резкий контраст кегля отделяют ключевые слова от остальной фразы.",
  caption_emoji_pop: "Emoji появляется рядом с обведённым текстом, а строка входит через короткое горизонтальное сжатие.",
  caption_glitch_rgb: "У букв расходятся RGB-копии, а поверх текста появляются CRT-линии цифрового экрана.",
  caption_gradient_fill: "Буквы заполняются цветным градиентом и входят с упругим bounce-движением.",
  caption_highlight: "Красная плашка проходит за активным словом и последовательно подсвечивает субтитр в TikTok-стиле.",
  caption_kinetic_slam: "Слова показываются по одному на весь экран и поочерёдно влетают с разных направлений.",
  caption_matrix_decode: "Перед появлением правильной фразы символы быстро перебираются как при цифровой расшифровке.",
  caption_neon_accent: "Ключевые слова получают разноцветное неоновое свечение и лёгкий плавающий wiggle.",
  caption_neon_glow: "Субтитр светится голубым и пурпурным неоном, отдельные слова выделяются дополнительными цветами.",
  caption_parallax_layers: "Крупный текст раскладывается слоями по глубине, проходит за объектом и растягивается по вертикали.",
  caption_particle_burst: "При появлении ключевого слова из него разлетаются цветные частицы.",
  caption_pill_karaoke: "Фраза находится внутри округлой плашки, а произносимое слово последовательно меняет цвет.",
  caption_texture: "Крупные прописные буквы заполняются движущейся текстурой; variable texture переключает шесть встроенных материалов.",
  caption_weight_shift: "При смене строки толщина шрифта плавно переходит от лёгкого начертания к жирному или обратно.",
  catalog_reference_data_chart: "Столбцы и линия графика появляются каскадом, после них раскрываются подписи и числовые значения.",
  catalog_reference_editorial_flash_overlay: "Несколько нейтрально-тёплых световых слоёв создают управляемую вспышку камеры поверх монтажного стыка.",
  catalog_reference_grid_pixelate_wipe: "Экран распадается на сетку квадратов, которые исчезают с задержкой и открывают следующую сцену.",
  catalog_reference_morph_text: "Слова из редактируемого списка текуче превращаются друг в друга через SVG threshold и управляемое размытие.",
  catalog_reference_north_korea_locked_down: "Карта приближается к Северной Корее, область обводится красной линией и получает плашку Locked Down.",
  catalog_reference_ridged_burn: "Шумовой shader создаёт неровный фронт прожига, который разрушает старый кадр и раскрывает новый.",
  code_3d_extrude: "Подсвеченный код лежит на объёмной плите с фасками, вращается в WebGL-пространстве и останавливается для чтения.",
  code_diff: "Удалённые строки кода схлопываются красным, а добавленные раскрываются зелёным.",
  code_editor_theme_card: "Полный интерфейс VS Code посимвольно печатает код; тринадцать implementations меняют тему редактора или способ сборки сниппета.",
  code_highlight: "Светлая полоса проходит по выбранной строке кода, пока окружающий контекст затемняется.",
  code_morph: "Токены первого сниппета перемещаются в позиции второго, исчезающие токены гаснут, новые проявляются.",
  code_particle_assemble: "Тысячи GPU-частиц слетаются к пикселям символов и собирают читаемый syntax-highlighted код.",
  code_scroll: "Камера прокручивает длинный файл до целевой строки, ставит её в центр и подсвечивает.",
  code_shader_dissolve: "Код проявляется из seeded noise через цветной shader-фронт, затем остаётся резким и читаемым.",
  code_text_cursor: "Текст проявляется за светящимся курсором с хроматическими лучами и направленным освещением на чёрном фоне.",
  code_typing: "Код печатается потоком токенов, а каретка точно следует за границей уже показанного текста.",
  lower_third_accent_underline: "Имя поднимается поверх видео, акцентная линия рисуется слева направо, затем проявляется должность.",
  lower_third_bild: "Новостной lower third использует белую плашку заголовка и красную строку с контрастными тенями в стиле BILD.",
  lower_third_bold_block: "Тёмный прямоугольник закрывает нижнюю часть кадра, имя резко входит снизу, акцентный тег подпрыгивает.",
  lower_third_clean_bar: "Минималистичная белая карточка открывается clip-wipe, показывая цветной tab, имя и должность.",
  lower_third_color_block: "Яркий цветной блок въезжает с overshoot и показывает крупное имя с моноширинной должностью.",
  lower_third_dark_card: "Тёмная карточка поднимается поверх светлого видео, после имени рисуется акцентная линия и появляется должность.",
  lower_third_kicker_name: "Над крупным именем появляется небольшой цветной kicker, а снизу прорисовывается базовая линия.",
  lower_third_mask_reveal: "Цветная полоса проходит по нижней части кадра и через clip-path открывает имя, затем проявляется должность.",
  lower_third_news_ticker: "Эфирная плашка объединяет индикатор LIVE, основной заголовок и непрерывно движущуюся новостную строку.",
  lower_third_side_rule: "Вертикальная цветная линия закрепляет слева имя и моноширинную должность без фоновой карточки.",
  lower_third_soft_pill: "Белая округлая плашка появляется через scale-pop и показывает status dot, имя и должность.",
  lower_third_stack_bars: "Тёмная полоса имени входит слева, а цветная полоса должности — справа, образуя два уровня титра.",
  lower_third_yt_lower_third: "Карточка YouTube с аватаром, названием канала и кнопкой подписки анимированно входит в нижнюю часть кадра.",
  map_diagram_flowchart: "Узлы decision tree появляются как стикеры, соединяются SVG-линиями, курсор исправляет набранный текст.",
  map_diagram_flowchart_vertical: "Вертикальное дерево решений для 9:16 раскрывает стикеры сверху вниз и соединяет их SVG-линиями.",
  map_diagram_spain_map: "Регионы Испании последовательно окрашиваются по значению, рядом появляется градиентная легенда.",
  map_diagram_us_map: "Штаты США каскадом получают цвет данных, числовые подписи и общую градиентную легенду.",
  map_diagram_us_map_bubble: "На карте США вырастают круги пропорционального размера с подписями городов и значений.",
  map_diagram_us_map_flow: "Между городами США прорисовываются дуги маршрутов, показывающие направление потоков.",
  map_diagram_us_map_hex: "Каждый штат показан равновесным шестиугольником с аббревиатурой и цветом значения.",
  map_diagram_world_map: "Страны мира последовательно окрашиваются по данным, появляются tooltip-подписи и небольшой вращающийся глобус.",
  media_treatment_camcorder_hud: "Поверх видео появляются REC, батарея, дата и счётчик времени, имитирующие интерфейс любительской камеры.",
  media_treatment_freeze_frame_dressing: "Стоп-кадр или вырезанный объект оформляется слоями бумаги, скотча и короткими вспышками.",
  media_treatment_grain_overlay: "Поверх всей композиции движется мелкое плёночное зерно, добавляющее аналоговую фактуру.",
  media_treatment_shimmer_sweep: "Узкая световая полоса проходит по тексту или объекту через градиентную маску.",
  media_treatment_texture_mask_text: "Шестьдесят шесть luminance-масок вырезают фактурные отверстия внутри букв.",
  media_treatment_vignette: "Радиальный CSS-градиент затемняет края изображения и удерживает внимание в центре.",
  social_overlay_instagram_follow: "Поверх видео появляется Instagram-профиль с аватаром и анимированной кнопкой Follow.",
  social_overlay_liquid_glass_notification: "Матовые стеклянные уведомления плавают над цветным aurora shader-фоном.",
  social_overlay_macos_notification: "В верхней части кадра появляется системное уведомление macOS с иконкой приложения и текстом.",
  social_overlay_reddit_post: "Карточка Reddit показывает пост, рейтинг голосов и число комментариев поверх основного кадра.",
  social_overlay_spotify_card: "Карточка Spotify показывает обложку, текущий трек и движущийся progress bar.",
  social_overlay_tiktok_follow: "Поверх видео появляется TikTok-профиль с аватаром и анимированной кнопкой подписки.",
  social_overlay_x_post: "Карточка поста X показывает текст публикации и счётчики реакций.",
  transition_chromatic_radial_split: "Радиальный shader-разрез расходится от центра с цветным смещением RGB-каналов.",
  transition_cinematic_zoom: "Резкий zoom blur втягивает старый кадр в точку и выводит новую сцену.",
  transition_cross_warp_morph: "Два кадра перекрёстно искривляются и плавно превращаются друг в друга.",
  transition_domain_warp_dissolve: "Фрактальный шум деформирует границу растворения между старым и новым кадром.",
  transition_flash_through_white: "Кадр быстро пересвечивается до белого и из вспышки возвращается новой сценой.",
  transition_glitch: "Цифровые полосы, сдвиги и артефакты shader-глитча скрывают смену кадров.",
  transition_gravitational_lens: "Изображение изгибается вокруг виртуального центра притяжения и переходит в следующий кадр.",
  transition_organic_light_leak_overlay: "Органичный световой засвет проходит поверх кадра и мотивирует смену сцены или воспоминание.",
  transition_parallax_unzoom: "Центральная карточка уменьшается от полного экрана, а соседние элементы входят параллаксом и образуют сетку.",
  transition_parallax_zoom: "Центральная карточка увеличивается до полного экрана, а соседние элементы расходятся наружу параллаксом.",
  transition_ripple_waves: "Концентрические волны деформируют изображение и переносят зрителя в следующий кадр.",
  transition_sdf_iris: "SDF-маска открывает новую сцену через управляемую геометрическую диафрагму.",
  transition_swirl_vortex: "Изображение закручивается в вихрь и раскручивается уже следующей сценой.",
  transition_thermal_distortion: "Тепловая рябь и heat-haze искажают стык между кадрами.",
  transition_whip_pan: "Сильный направленный смаз имитирует быстрый поворот камеры и скрывает монтажный стык.",
  vfx_ios26_liquid_glass: "Трёхмерный iPhone показывает домашний экран iOS 26 со стеклянными иконками, shader-обоями, dock и уведомлениями.",
  vfx_iphone_device: "GLTF-модели iPhone и MacBook вращаются в продуктовой камере, а их экраны содержат живой HTML-контент.",
  vfx_liquid_background: "Под HTML-контентом колышется subdivided plane с жидкой vertex-деформацией и динамическими волнами.",
  vfx_liquid_glass: "Стеклянная плоскость разбивается на Voronoi-фрагменты, реагирует параллаксом на указатель и частично разлетается в глубину.",
  vfx_liquid_glass_context_menu: "Матовое стеклянное контекстное меню дрейфует над цветным aurora shader-фоном.",
  vfx_liquid_glass_media_controls: "Стеклянные панели медиаплеера раскрываются и располагаются поверх aurora shader-фона.",
  vfx_liquid_glass_widgets: "Стеклянные карточки статистики, showcase-панель и pill-элементы собираются над aurora-фоном.",
  vfx_macos_tahoe_liquid_glass: "Трёхмерный MacBook показывает desktop macOS Tahoe со стеклянным menu bar, Finder, dock и кинематографическим движением камеры.",
  vfx_magnetic: "Fragment shader притягивает пиксели изображения к курсору через Gaussian warp и добавляет цветное расщепление по краям деформации.",
  vfx_portal: "Светящийся портал открывается в пространстве кадра и создаёт глубинный проход к другому слою.",
  vfx_shatter: "Плоскость или объект раскалывается на фрагменты, которые разлетаются в глубину и стороны.",
  vfx_ui_3d_reveal: "UI-элементы входят как отдельные перспективные слои, выстраиваются по глубине и поворачиваются к камере.",
};

const TECH_CATEGORY_OVERRIDES = {
  brand_showcase_blue_sweater_intro_video: "brand_and_outro",
  spatial_motion_blur: "spatial_motion",
};

const USE_AVOID_RU = {
  caption_and_typography: [["Когда нужно выделить конкретные слова синхронно с речью."], ["Когда на экране одновременно должен читаться длинный абзац."]],
  title_and_lower_third: [["Когда нужно представить спикера, источник или постоянную рубрику."], ["Когда нижняя зона закрывает важную часть лица или демонстрации."]],
  data_and_statistics: [["Когда в сценарии есть проверяемые числа, сравнения или динамика показателей."], ["Когда данные отсутствуют или не подтверждают произносимый тезис."]],
  comparison_and_process: [["Когда нужно показать изменение, порядок шагов или причинно-следственную связь."], ["Когда элементы не образуют понятную последовательность или сравнение."]],
  code_and_terminal: [["Когда речь действительно относится к коду, разработке или работе в терминале."], ["Когда технический интерфейс не связан с содержанием фразы."]],
  map_and_diagram: [["Когда география, маршрут или структура связей являются частью аргумента."], ["Когда карта или схема служит только декоративным фоном."]],
  transition: [["Когда смена смыслового блока требует заметного визуального стыка."], ["Когда эффект повторялся недавно или обычный hard cut читается лучше."]],
  texture_and_finishing: [["Когда всему кадру нужна единая фактура или дополнительный фокус."], ["Когда обработка ухудшает читаемость текста и деталей лица."]],
  media_treatment: [["Когда исходный кадр нужно оформить как конкретный носитель или редакционный объект."], ["Когда оформление не поддерживает смысл сцены."]],
  vfx_and_shader: [["Когда нужен редкий визуальный пик, продуктовый hero-shot или технологический акцент."], ["Когда тяжёлый эффект отвлекает от основной мысли или не оправдан сценарием."]],
  spatial_motion: [["Когда движение объекта должно ощущаться быстрым, инерционным или объёмным."], ["Когда элемент почти неподвижен и эффект не будет заметен."]],
  social_and_editorial_overlay: [["Когда сценарий ссылается на профиль, публикацию, уведомление или медиакарточку."], ["Когда показанный сервис или контент не упоминается в речи."]],
  brand_and_outro: [["Когда нужно представить продукт, автора, логотип или завершить ролик CTA."], ["Когда брендовый экран прерывает объяснение до завершения мысли."]],
  speaker_layout: [["Когда важно сохранить лицо и прямой контакт ведущего со зрителем."], ["Когда доказательный материал должен занять весь экран."]],
  composition_layout: [["Когда два или несколько смысловых слоёв нужно показать одновременно."], ["Когда split или collage делает главный объект слишком мелким."]],
  other: [["Когда назначение реализации точно совпадает с содержанием сцены."], ["Когда связь с тезисом не доказана."]],
};

function ensureDirs() { for (const d of Object.values(OUT)) fs.mkdirSync(d, { recursive: true }); }
function readText(file) { return fs.readFileSync(file, "utf8"); }
function readJson(file) { return JSON.parse(readText(file)); }
function writeText(file, text) { fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, text.endsWith("\n") ? text : `${text}\n`, "utf8"); }
function writeJson(file, data) { writeText(file, JSON.stringify(data, null, 2)); }
function exists(file) { return fs.existsSync(file); }
function posix(p) { return p.split(path.sep).join("/"); }
function rel(from, file) { return posix(path.relative(from, file)); }
function sourceRel(file) {
  if (file.startsWith(SOURCES.upstreamRoot)) return rel(SOURCES.upstreamRoot, file);
  if (file.startsWith(SOURCES.approvedRoot)) return rel(SOURCES.approvedRoot, file);
  return rel(ROOT, file);
}
function slug(s) { return String(s || "").toLowerCase().replace(/[^a-z0-9_]+/g, "_").replace(/^_+|_+$/g, "").replace(/_{2,}/g, "_"); }
function titleCase(s) { return String(s || "").replace(/[-_]+/g, " ").replace(/\b\w/g, (x) => x.toUpperCase()); }
function hashFile(file) { return crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex").toUpperCase(); }
function listDirs(dir) { return fs.readdirSync(dir, { withFileTypes: true }).filter((e) => e.isDirectory()).map((e) => path.join(dir, e.name)).sort(); }
function listFiles(dir) {
  const out = [];
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const f = path.join(dir, e.name);
    if (e.isDirectory()) out.push(...listFiles(f)); else out.push(f);
  }
  return out.sort();
}
function lineCount(file) { return readText(file).split(/\r?\n/).length; }
function findLine(file, re, start = 1) {
  const lines = readText(file).split(/\r?\n/);
  for (let i = Math.max(0, start - 1); i < lines.length; i++) if (re.test(lines[i])) return i + 1;
  return 1;
}
function findFunctionRange(file, symbol) {
  const lines = readText(file).split(/\r?\n/);
  const start = lines.findIndex((l) => new RegExp(`function\\s+${symbol}\\b`).test(l));
  if (start < 0) return { line_start: 1, line_end: Math.min(10, lines.length) };
  let depth = 0, seen = false;
  for (let i = start; i < lines.length; i++) {
    for (const ch of lines[i]) {
      if (ch === "{") { depth++; seen = true; }
      if (ch === "}") depth--;
    }
    if (seen && depth <= 0) return { line_start: start + 1, line_end: i + 1 };
  }
  return { line_start: start + 1, line_end: Math.min(lines.length, start + 20) };
}
function orientation(dim, kind, text = "") {
  if (kind === "component" && !/data-width\s*=|width:\s*\d+px|width="\d+/.test(text)) return "adaptive";
  const w = Number(dim?.width), h = Number(dim?.height);
  if (!w || !h) return kind === "component" ? "adaptive" : "unknown";
  if (h > w * 1.1) return "portrait";
  if (w > h * 1.1) return "landscape";
  return "square";
}
function uniq(arr) { return [...new Set(arr.filter(Boolean))].sort(); }
function manifestParams(m) { return Array.isArray(m.params) ? m.params.map((p) => typeof p === "string" ? p : p.name || p.id || "").filter(Boolean).sort() : []; }
function parseVariablesPayload(raw) {
  if (!raw) return [];
  const cleaned = raw.replace(/&quot;/g, "\"").replace(/&#39;/g, "'");
  try { const parsed = JSON.parse(cleaned); if (parsed && typeof parsed === "object") return Object.keys(parsed).sort(); } catch {}
  return uniq([...cleaned.matchAll(/["']?([A-Za-z_][\w-]*)["']?\s*:/g)].map((m) => m[1]));
}
function visibleTextDetected(text) {
  const stripped = text.replace(/<script[\s\S]*?<\/script>/gi, " ").replace(/<style[\s\S]*?<\/style>/gi, " ").replace(/<!--[\s\S]*?-->/g, " ").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
  return /[A-Za-zА-Яа-я]{3,}/.test(stripped);
}
function runtimeFiles(files) { return files.filter((f) => /\.(html|js|mjs|css)$/i.test(f)); }
function lineUsage(line) {
  const checks = [
    ["script_src", /<script\b[^>]*\bsrc\s*=\s*["'](https?:\/\/[^"']+)["']/gi],
    ["stylesheet_href", /<link\b[^>]*rel\s*=\s*["']stylesheet["'][^>]*href\s*=\s*["'](https?:\/\/[^"']+)["']/gi],
    ["media_src", /<(?:img|video|audio|source)\b[^>]*\bsrc\s*=\s*["'](https?:\/\/[^"']+)["']/gi],
    ["css_url", /url\(\s*["']?(https?:\/\/[^"')]+)["']?\s*\)/gi],
    ["css_import", /@import\s+(?:url\()?["'](https?:\/\/[^"')]+)["']/gi],
    ["js_fetch", /\bfetch\s*\(\s*["'](https?:\/\/[^"']+)["']/gi],
    ["js_import", /\bimport\s*\(\s*["'](https?:\/\/[^"']+)["']/gi],
    ["js_new_url", /new\s+URL\s*\(\s*["'](https?:\/\/[^"']+)["']/gi],
  ];
  const out = [];
  for (const [usage, re] of checks) for (const m of line.matchAll(re)) out.push({ usage, url: m[1] });
  return out;
}
function analyzeImplementation(itemId, files, sourceRoot) {
  const impl = runtimeFiles(files);
  const text = impl.map((f) => readText(f)).join("\n");
  const deps = [];
  for (const file of impl) {
    const lines = readText(file).split(/\r?\n/);
    lines.forEach((line, idx) => {
      for (const hit of lineUsage(line)) {
        if (/static\.heygen\.ai\/hyperframes-oss\/docs\/images\/catalog/.test(hit.url)) continue;
        if (/w3\.org\/(2000\/svg|1999\/xhtml)/.test(hit.url)) continue;
        deps.push({ item_id: itemId, url: hit.url, usage: hit.usage, path: sourceRel(file), line: idx + 1 });
      }
    });
  }
  const declared = [];
  for (const m of text.matchAll(/data-composition-variables\s*=\s*(['"])([\s\S]*?)\1/g)) declared.push(...parseVariablesPayload(m[2]));
  const engines = [];
  if (/\bgsap\b|GSAP/.test(text)) engines.push("gsap");
  if (/\blottie\b/i.test(text)) engines.push("lottie");
  if (/\bTHREE\b|three\.js|WebGL|webgl/i.test(text)) engines.push("three_or_webgl");
  if (/HyperShader|\bshader\b|fragmentShader|vertexShader/i.test(text)) engines.push("shader");
  if (/@keyframes/.test(text)) engines.push("css_keyframes");
  if (/\.animate\s*\(/.test(text)) engines.push("waapi");
  const media = [];
  if (/<video\b/i.test(text)) media.push("video");
  if (/<audio\b/i.test(text)) media.push("audio");
  if (/<img\b/i.test(text)) media.push("image");
  if (/<svg\b/i.test(text)) media.push("svg");
  void sourceRoot;
  return {
    text,
    declared_variables: uniq(declared),
    uses_variable_values: /data-variable-values\s*=/.test(text),
    uses_data_var_bindings: /data-var-[a-z0-9_-]+/i.test(text),
    hardcoded_content_detected: visibleTextDetected(text),
    animation_engines: uniq(engines),
    media_types: uniq(media),
    remote_dependencies: uniq(deps.map((d) => d.url)),
    dependency_entries: deps,
    uses_sub_compositions: /data-composition-src\s*=/.test(text),
    uses_shader_or_webgl: /HyperShader|\bshader\b|fragmentShader|vertexShader|\bTHREE\b|three\.js|WebGL|webgl/i.test(text),
  };
}
function roleFrom(item, analysis) {
  const tags = new Set((item.tags || []).map((t) => String(t).toLowerCase()));
  const tokens = new Set(String(item.name || "").toLowerCase().split(/[-_]+/).filter(Boolean));
  const desc = String(item.description || "").toLowerCase();
  const roles = new Set();
  const has = (...xs) => xs.some((x) => tags.has(x) || tokens.has(x) || new RegExp(`\\b${x}\\b`).test(desc));
  if (has("caption","subtitle","karaoke")) roles.add("caption");
  if (has("lower","third") || item.name.startsWith("lt-") || /lower-third/.test(item.name)) roles.add("lower_third");
  if (has("title","headline","kicker")) roles.add("title");
  if (has("quote")) roles.add("quote");
  if (has("chart","data")) roles.add("data_visualization");
  if (has("stat","count","finance","money")) roles.add("stat");
  if (has("comparison","before","after")) roles.add("comparison");
  if (has("list","checklist")) roles.add("list");
  if (has("process","flow","sequence")) roles.add("process");
  if (has("code","terminal","developer","diff")) roles.add("code");
  if (has("map","flowchart","diagram")) roles.add("map");
  if (has("instagram","tiktok","reddit","post","social","notification","spotify","follow","ticker")) roles.add("social_overlay");
  if (tags.has("transition") || tokens.has("transition") || item.name.startsWith("transitions-") || /shader transition/.test(desc)) roles.add("transition");
  if (has("texture","grain","vignette","hud","camcorder","mask","shimmer")) roles.add("texture");
  if (has("vfx","shader","webgl","particle","portal","magnetic","shatter","liquid","glass")) roles.add("vfx");
  if (has("overlay","media","freeze","light") && !roles.has("transition")) roles.add("media_treatment");
  if (item.source === "approved" && item.kind === "layout") roles.add("layout");
  if (item.source === "approved" && item.kind === "transition") roles.add("transition");
  if (has("logo","outro","brand","showcase","app","product","youtube","vpn","flight","creator")) roles.add("brand");
  if (analysis?.uses_shader_or_webgl) roles.add("vfx");
  if (!roles.size) roles.add("other");
  return [...roles].sort();
}
function capabilitiesFor(item) {
  const roles = item.capabilities_roles || [];
  const overlay = roles.some((r) => ["caption","lower_third","quote","social_overlay","texture","media_treatment"].includes(r)) || item.kind === "component";
  let placement = ["fullscreen"];
  if (roles.includes("lower_third")) placement = ["lower_third"];
  else if (overlay) placement = ["overlay"];
  else if (roles.includes("transition")) placement = ["fullscreen"];
  return {
    roles,
    placement,
    supports_portrait_as_is: ["portrait","adaptive"].includes(item.dimensions.orientation),
    supports_overlay: overlay,
    supports_text_content: roles.some((r) => ["caption","lower_third","title","quote","data_visualization","stat","comparison","list","process","code","map","social_overlay","brand"].includes(r)),
    supports_media_content: roles.some((r) => ["layout","social_overlay","texture","vfx","transition","media_treatment","brand","map"].includes(r)) || item.runtime?.media_types?.length > 0,
  };
}
function scoreItem(item) {
  let score = 0;
  const b = [];
  const add = (n, s) => { score += n; b.push(`${n > 0 ? "+" : ""}${n}: ${s}`); };
  if (item.source === "approved" && item.name !== "avatar_cutout_overlay") add(5, "source approved и item не запрещён");
  if (item.source === "local") add(4, "source local");
  if ((item.capabilities.roles || []).some((r) => SCORE_ROLE_SET.has(r))) add(3, "роль подходит для Reels/talking-head каталога");
  if (["portrait","adaptive"].includes(item.dimensions.orientation)) add(2, "orientation portrait/adaptive");
  if (["declarative","generated_python"].includes(item.parameterization.level)) add(2, "parameterization declarative/generated_python");
  if (item.parameterization.manifest_params.length) add(1, "есть manifest params");
  if (item.preview.poster_remote) add(1, "есть official poster URL в frozen manifest");
  if (item.kind === "block" && item.dimensions.orientation === "landscape" && !/responsive|portrait/i.test(`${item.description} ${(item.tags || []).join(" ")}`)) add(-2, "landscape block без доказанного responsive/portrait режима");
  if (item.runtime.remote_dependencies.length) add(-2, "есть настоящая runtime remote dependency");
  if (item.runtime.uses_shader_or_webgl) add(-2, "shader/WebGL/Three.js обязателен для приёма");
  if ((item.capabilities.roles || []).some((r) => ["code","map"].includes(r))) add(-3, "роль code или map без связи с generic talking-head use case");
  if (item.name === "avatar_cutout_overlay") add(-100, "item запрещён актуальными решениями проекта");
  return { score, score_breakdown: b };
}
function reviewFor(item) {
  if (item.name === "avatar_cutout_overlay") return { review_status: "forbidden", runtime_allowed: false, reason: "Запрещён актуальными решениями проекта; сохранён только для истории.", adaptation_needed: ["Не возвращать в shortlist без отдельного явного одобрения."], risks: ["Статичный PNG подменяет движущийся avatar video."] };
  if (item.source === "approved") return { review_status: "ready", runtime_allowed: true, reason: "Ранее одобренный Reels Factory pattern с доказанной JS-хореографией.", adaptation_needed: [], risks: [] };
  if (item.source === "local") return { review_status: "ready", runtime_allowed: true, reason: "Локальный generated_python block с проверенным builder-контрактом.", adaptation_needed: [], risks: item.runtime.remote_dependencies.length ? ["Перед production freeze CDN нужно заменить локальным asset."] : [] };
  const suitable = (item.capabilities.roles || []).some((r) => SCORE_ROLE_SET.has(r) || ["texture","media_treatment","vfx","brand"].includes(r));
  const paramOk = item.parameterization.level === "declarative";
  const portraitOk = ["portrait","adaptive"].includes(item.dimensions.orientation);
  if (suitable && portraitOk && paramOk) return { review_status: "ready", runtime_allowed: false, reason: "Upstream item имеет подходящую роль, совместимую orientation и доказанные declarative variables; runtime ждёт human approval.", adaptation_needed: [], risks: [] };
  if (suitable) return { review_status: "adapt", runtime_allowed: false, reason: "Подходит по роли, но требует адаптации canvas, content variables или runtime contracts.", adaptation_needed: [portraitOk ? null : "portrait layout", paramOk ? null : "content variables"].filter(Boolean), risks: [] };
  return { review_status: "reference_only", runtime_allowed: false, reason: "Узкоспециализированный или недоказанный для generic talking-head use case reference.", adaptation_needed: ["Нужна отдельная product/story fit проверка."], risks: ["Прямое применение к Reels не доказано источником."] };
}
function itemBase(input) {
  const assessment = { ...reviewFor(input), ...scoreItem(input) };
  return { ...input, assessment, human_review: { decision: "undecided", notes: "" } };
}
function posterPathFor(id, report) {
  const entry = report?.entries?.find((e) => e.id === id);
  if (entry && ["downloaded","cached"].includes(entry.status) && entry.local_path) return entry.local_path.replace(/^gallery\//, "");
  return "assets/placeholder.svg";
}
function loadPreviewReport() {
  const p = path.join(OUT.reports, "preview-downloads.json");
  return exists(p) ? readJson(p) : null;
}
function extractUpstream(kind, dirName, previewReport, allRuntimeDeps) {
  const base = path.join(SOURCES.upstreamRoot, "registry", dirName);
  return listDirs(base).map((dir) => {
    const name = path.basename(dir);
    const manifestPath = path.join(dir, "registry-item.json");
    const manifest = readJson(manifestPath);
    if (manifest.name !== name) throw new Error(`manifest name mismatch: ${sourceRel(manifestPath)}`);
    const files = (manifest.files || []).map((f) => path.join(dir, f.path));
    for (const f of files) if (!exists(f)) throw new Error(`missing implementation: ${sourceRel(f)}`);
    const id = `upstream:${kind}:${name}`;
    const analysis = analyzeImplementation(id, files, SOURCES.upstreamRoot);
    allRuntimeDeps.push(...analysis.dependency_entries);
    const params = manifestParams(manifest);
    const level = analysis.declared_variables.length ? "declarative" : params.length ? "manifest_only" : "none";
    const dimensions = { width: manifest.dimensions?.width ?? null, height: manifest.dimensions?.height ?? null, orientation: orientation(manifest.dimensions, kind, analysis.text) };
    const implRel = files.map(sourceRel);
    const manifestLine = findLine(manifestPath, /^\s*"description"\s*:/);
    const evidenceRefs = [{
      path: sourceRel(manifestPath),
      symbol: null,
      line_start: manifestLine,
      line_end: manifestLine,
      reason_ru: "Manifest прямо описывает назначение и видимое поведение registry item.",
    }];
    if (analysis.declared_variables.length) {
      const variableFile = runtimeFiles(files).find((file) => /data-composition-variables/.test(readText(file)));
      if (variableFile) {
        const variableLine = findLine(variableFile, /data-composition-variables/);
        evidenceRefs.push({ path: sourceRel(variableFile), symbol: null, line_start: variableLine, line_end: variableLine, reason_ru: "Строка содержит реальное объявление data-composition-variables." });
      }
    }
    const draft = {
      id, source: "upstream", kind, name,
      title: manifest.title || titleCase(name),
      description: manifest.description || "",
      tags: (manifest.tags || []).sort(),
      source_ref: { manifest: sourceRel(manifestPath), implementation: implRel },
      evidence_refs: evidenceRefs,
      dimensions,
      duration_seconds: manifest.duration ?? null,
      preview: { poster_remote: manifest.preview?.poster || null, poster_local: manifest.preview?.poster ? posterPathFor(id, previewReport) : "assets/placeholder.svg", video_remote: manifest.preview?.video || null, available: Boolean(manifest.preview?.poster || manifest.preview?.video), error: null },
      parameterization: { manifest_params: params, declared_variables: analysis.declared_variables, contract_fields: analysis.declared_variables.length ? analysis.declared_variables : params, uses_variable_values: analysis.uses_variable_values, uses_data_var_bindings: analysis.uses_data_var_bindings, hardcoded_content_detected: analysis.hardcoded_content_detected, level },
      runtime: { animation_engines: analysis.animation_engines, media_types: analysis.media_types, remote_dependencies: analysis.remote_dependencies, uses_sub_compositions: analysis.uses_sub_compositions, uses_shader_or_webgl: analysis.uses_shader_or_webgl, determinism_risk: analysis.remote_dependencies.length || analysis.uses_shader_or_webgl ? "medium" : "low" },
    };
    draft.capabilities_roles = roleFrom(draft, analysis);
    draft.capabilities = capabilitiesFor(draft);
    delete draft.capabilities_roles;
    return itemBase(draft);
  });
}
function splitParams(sig) {
  const out = []; let cur = "", depth = 0;
  for (const ch of sig) {
    if (ch === "," && depth === 0) { out.push(cur.trim()); cur = ""; continue; }
    if ("([{".includes(ch)) depth++;
    if (")]}".includes(ch)) depth--;
    cur += ch;
  }
  if (cur.trim()) out.push(cur.trim());
  return out;
}
function extractLocal() {
  const py = readText(SOURCES.localBlocksPy);
  const lines = py.split(/\r?\n/);
  const block = py.match(/BLOCKS\s*=\s*\{([\s\S]*?)\n\}/);
  if (!block) throw new Error("local BLOCKS dictionary not found");
  const entries = [...block[1].matchAll(/"([^"]+)"\s*:\s*\("([^"]+)"\s*,\s*([A-Za-z_][A-Za-z0-9_]*)\)/g)].map((m) => ({ name: m[1], subdir: m[2], builder: m[3] }));
  const keys = entries.map((e) => e.name).sort();
  if (JSON.stringify(keys) !== JSON.stringify(EXPECTED.localBlocks)) throw new Error(`local BLOCKS mismatch: ${keys.join(",")}`);
  return entries.map((entry) => {
    const def = py.match(new RegExp(`def\\s+${entry.builder}\\s*\\(([^)]*)\\)\\s*->`, "s"));
    if (!def) throw new Error(`builder signature not found: ${entry.builder}`);
    const lineNo = lines.findIndex((l) => l.includes(`def ${entry.builder}`)) + 1;
    const fields = [], defaults = {};
    for (const p of splitParams(def[1].replace(/\s+/g, " "))) {
      if (!p || p.startsWith("*")) continue;
      const [left, d] = p.split("=").map((x) => x.trim());
      const n = left.split(":")[0].trim();
      if (n && n !== "duration") { fields.push(n); if (d !== undefined) defaults[n] = d; }
    }
    const id = `local:block:${entry.name}`;
    const draft = {
      id, source: "local", kind: "block", name: entry.name, title: titleCase(entry.name), description: LOCAL_DESCRIPTIONS[entry.name], tags: ["reels-factory","generated-python",entry.name.replace(/_/g,"-")].sort(),
      source_ref: { manifest: "plugins/reels-factory/engine/src/reels_factory/hyperframes_blocks.py", implementation: [`plugins/reels-factory/engine/src/reels_factory/hyperframes_blocks.py`, `plugins/reels-factory/engine/hyperframes/${entry.subdir}`] },
      evidence_refs: [{ path: "plugins/reels-factory/engine/src/reels_factory/hyperframes_blocks.py", symbol: entry.builder, line_start: lineNo, line_end: lineNo + 1, reason_ru: "Сигнатура builder-функции задаёт доказанный контракт переменных локального блока." }],
      dimensions: { width: 1080, height: 1920, orientation: "portrait" },
      duration_seconds: null,
      preview: { poster_remote: null, poster_local: "assets/placeholder.svg", video_remote: null, available: false, error: null },
      parameterization: { manifest_params: [], declared_variables: fields.sort(), contract_fields: fields.sort(), defaults, uses_variable_values: false, uses_data_var_bindings: false, hardcoded_content_detected: false, level: "generated_python" },
      runtime: { animation_engines: ["gsap"], media_types: [], remote_dependencies: ["https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"], uses_sub_compositions: false, uses_shader_or_webgl: false, determinism_risk: "medium" },
    };
    draft.runtime.remote_dependencies = [];
    draft.capabilities_roles = roleFrom(draft, {});
    draft.capabilities = capabilitiesFor(draft);
    delete draft.capabilities_roles;
    return itemBase(draft);
  });
}
function approvedContract(symbols) {
  const jsFile = path.join(SOURCES.approvedRoot, "assets/catalog.js");
  const text = readText(jsFile);
  const fields = new Set(), refs = [];
  for (const symbol of symbols) {
    const r = findFunctionRange(jsFile, symbol);
    const body = text.split(/\r?\n/).slice(r.line_start - 1, r.line_end).join("\n");
    for (const m of body.matchAll(/\b(?:windowSpec|spec)\.([A-Za-z_$][\w$]*)/g)) fields.add(m[1]);
    refs.push({ path: "assets/catalog.js", symbol, line_start: r.line_start, line_end: r.line_end, reason_ru: `Функция ${symbol} содержит доказанный JS-контракт и хореографию approved pattern.` });
  }
  return { fields: [...fields].sort(), refs };
}
function extractApproved() {
  const catalog = readJson(path.join(SOURCES.approvedRoot, "catalog/catalog.json"));
  const poster = "assets/posters/approved-contact-sheet.jpg";
  fs.copyFileSync(path.join(SOURCES.approvedRoot, "snapshots/contact-sheet.jpg"), path.join(OUT.posters, "approved-contact-sheet.jpg"));
  const items = [];
  for (const name of catalog.layouts) {
    const c = approvedContract(APPROVED_SYMBOLS[name]);
    const draft = {
      id: `approved:layout:${name}`, source: "approved", kind: "layout", name, title: titleCase(name), description: APPROVED_DESCRIPTIONS[name], tags: ["approved-montage","layout",...name.split("_")].sort(),
      source_ref: { manifest: "catalog/catalog.json", implementation: ["assets/catalog.js","assets/catalog.css"] },
      evidence_refs: c.refs,
      dimensions: { width: 1080, height: 1920, orientation: "portrait" },
      duration_seconds: null,
      preview: { poster_remote: null, poster_local: poster, video_remote: null, available: true, error: null },
      parameterization: { manifest_params: [], declared_variables: [], contract_fields: c.fields, uses_variable_values: false, uses_data_var_bindings: false, hardcoded_content_detected: false, level: "approved_js_contract" },
      runtime: { animation_engines: ["gsap"], media_types: ["video"], remote_dependencies: [], uses_sub_compositions: false, uses_shader_or_webgl: false, determinism_risk: "low" },
    };
    draft.capabilities_roles = roleFrom(draft, {});
    draft.capabilities = capabilitiesFor(draft);
    delete draft.capabilities_roles;
    items.push(itemBase(draft));
  }
  for (const name of catalog.transitions) {
    const c = approvedContract(APPROVED_SYMBOLS[name]);
    const draft = {
      id: `approved:transition:${name}`, source: "approved", kind: "transition", name, title: titleCase(name), description: APPROVED_DESCRIPTIONS[name], tags: ["approved-montage","transition",...name.split("_")].sort(),
      source_ref: { manifest: "catalog/catalog.json", implementation: ["assets/catalog.js","assets/catalog.css"] },
      evidence_refs: c.refs,
      dimensions: { width: 1080, height: 1920, orientation: "portrait" },
      duration_seconds: null,
      preview: { poster_remote: null, poster_local: poster, video_remote: null, available: true, error: null },
      parameterization: { manifest_params: [], declared_variables: [], contract_fields: c.fields, uses_variable_values: false, uses_data_var_bindings: false, hardcoded_content_detected: false, level: "approved_js_contract" },
      runtime: { animation_engines: ["gsap"], media_types: [], remote_dependencies: [], uses_sub_compositions: false, uses_shader_or_webgl: name === "transition_chromatic", determinism_risk: "low" },
    };
    draft.capabilities_roles = roleFrom(draft, {});
    draft.capabilities = capabilitiesFor(draft);
    delete draft.capabilities_roles;
    items.push(itemBase(draft));
  }
  return items;
}
function categoryFromItem(item) {
  const r = new Set(item.capabilities.roles || []);
  if (r.has("caption")) return "caption_and_typography";
  if (r.has("lower_third") || r.has("title") || r.has("quote")) return "title_and_lower_third";
  if (r.has("map")) return "map_and_diagram";
  if (r.has("social_overlay")) return "social_and_editorial_overlay";
  if (r.has("data_visualization") || r.has("stat")) return "data_and_statistics";
  if (r.has("comparison") || r.has("list") || r.has("process")) return "comparison_and_process";
  if (r.has("code")) return "code_and_terminal";
  if (r.has("transition")) return "transition";
  if (r.has("texture")) return "texture_and_finishing";
  if (r.has("media_treatment")) return "media_treatment";
  if (r.has("vfx")) return item.runtime.uses_shader_or_webgl ? "vfx_and_shader" : "spatial_motion";
  if (r.has("layout")) return item.id.includes("avatar") ? "speaker_layout" : "composition_layout";
  if (r.has("brand")) return "brand_and_outro";
  return "other";
}
function techniqueIdFor(item) {
  if (TECH_OVERRIDES[item.id]) return TECH_OVERRIDES[item.id];
  const n = item.name;
  if (/^caption-/.test(n)) return [`caption_${slug(n.replace(/^caption-/, ""))}`];
  if (/^lt-|lower-third|ticker|yt-lower/.test(n)) return [`lower_third_${slug(n.replace(/^lt-/, "").replace(/^lower-third-/, ""))}`];
  if (/^code-snippet-apple-terminal/.test(n)) return ["apple_terminal_theme_card"];
  if (/^code-snippet-/.test(n)) return ["code_editor_theme_card"];
  if (/^code-/.test(n) || n === "vfx-text-cursor") return [`code_${slug(n.replace(/^code-/, "").replace(/^vfx-text-/, "text_"))}`];
  if (/map|flowchart/.test(n)) return [`map_diagram_${slug(n)}`];
  if (/transition|dissolve|warp|whip|iris|zoom|glitch|swirl|ripple|lens|thermal|blur|push|radial|light-leak|flash-through/.test(n)) return [`transition_${slug(n.replace(/^transitions-/, ""))}`];
  if (/grain|vignette|texture|mask|hud|camcorder|freeze|motion-blur|shimmer/.test(n)) return [`media_treatment_${slug(n)}`];
  if (/instagram|tiktok|reddit|x-post|spotify|notification|post|follow/.test(n)) return [`social_overlay_${slug(n)}`];
  if (/logo|outro|showcase|app|youtube|vpn|flight|creator|intro/.test(n)) return [`brand_showcase_${slug(n)}`];
  if (/vfx|shader|liquid|glass|portal|magnetic|shatter|particle|3d/.test(n)) return [`vfx_${slug(n.replace(/^vfx-/, ""))}`];
  return [`catalog_reference_${slug(n)}`];
}
function techniqueDefinition(id, sample) {
  const base = TECH_BASE[id] || VARIANT_NAMES[id];
  if (base) return base;
  const category = TECH_CATEGORY_OVERRIDES[id] || categoryFromItem(sample);
  const title = sample.title || titleCase(sample.name);
  const namePrefix = {
    caption_and_typography: "Caption-приём",
    title_and_lower_third: "Титровый приём",
    data_and_statistics: "Data-приём",
    comparison_and_process: "Приём процесса",
    code_and_terminal: "Кодовый приём",
    map_and_diagram: "Картографический приём",
    transition: "Переход",
    texture_and_finishing: "Финишная текстура",
    media_treatment: "Обработка медиа",
    vfx_and_shader: "VFX-приём",
    spatial_motion: "Пространственный приём",
    social_and_editorial_overlay: "Социальный overlay",
    brand_and_outro: "Брендовый приём",
    speaker_layout: "Раскладка с ведущим",
    composition_layout: "Композиционная раскладка",
    other: "Reference-приём",
  }[category];
  const semantic = RU_DESCRIPTION[id];
  if (!semantic) throw new Error(`Нет доказательного русского описания technique ${id}`);
  return [
    `${namePrefix}: ${title}`,
    category,
    semantic,
    `Зритель видит: ${semantic[0].toLowerCase()}${semantic.slice(1)}`,
  ];
}
function makeTechnique(id, sample) {
  const [name_ru, category, description_ru, viewer_sees_ru] = techniqueDefinition(id, sample);
  const [use_when_ru, avoid_when_ru] = USE_AVOID_RU[category];
  return {
    id, name_ru, category,
    description_ru,
    viewer_sees_ru,
    use_when_ru,
    avoid_when_ru,
    implementation_ids: [],
    variants_ru: [],
    controllable_fields_ru: [],
    placement_ru: sample.capabilities.placement.map((p) => p === "fullscreen" ? "полный экран" : p === "overlay" ? "overlay поверх кадра" : p === "lower_third" ? "нижняя титровая зона" : p === "side_panel" ? "боковая панель" : p === "picture_in_picture" ? "картинка в картинке" : p === "background" ? "фон кадра" : p === "inline_effect" ? "встроенный эффект" : "неизвестное размещение"),
    portrait_support: ["portrait","adaptive"].includes(sample.dimensions.orientation) ? "ready" : "adapt",
    adaptation_notes_ru: sample.source === "upstream" ? ["Проверить и при необходимости адаптировать под 1080x1920.", sample.parameterization.level === "none" ? "Контент запечён, нужна параметризация." : null].filter(Boolean) : [],
    dependencies_ru: sample.runtime.remote_dependencies.length ? ["Есть внешняя runtime-зависимость, зафиксированная по строке source evidence."] : [],
    risks_ru: sample.assessment.review_status === "forbidden" ? ["Историческая реализация запрещена актуальными решениями проекта."] : sample.assessment.review_status === "reference_only" ? ["Пока доступно только как reference, не runtime-ready."] : [],
    evidence: [],
    evidence_refs: [],
    availability: "reference_only",
  };
}
function buildCuration(items) {
  const current = { catalog_version: 1, techniques: [], items: [] };
  const techniqueIds = new Set();
  for (const item of items) {
    const ids = techniqueIdFor(item).map(slug);
    ids.forEach((id) => techniqueIds.add(id));
    let evidenceRefs = item.evidence_refs;
    if (MULTI_EVIDENCE[item.id]) {
      const [line_start, line_end, reason_ru] = MULTI_EVIDENCE[item.id];
      evidenceRefs = [{ path: item.source_ref.implementation.find((p) => p.endsWith(".html")), symbol: null, line_start, line_end, reason_ru }];
    }
    if (SPECIAL_EVIDENCE[item.id]) {
      evidenceRefs = [
        ...evidenceRefs,
        ...SPECIAL_EVIDENCE[item.id].map(([path, line_start, line_end, reason_ru]) => ({ path, symbol: null, line_start, line_end, reason_ru })),
      ];
    }
    current.items.push({ item_id: item.id, reviewed: true, technique_ids: ids, evidence_refs: evidenceRefs });
  }
  const byId = new Map(items.map((i) => [i.id, i]));
  for (const id of [...techniqueIds].sort()) {
    const sampleItem = current.items.find((m) => m.technique_ids.includes(id));
    current.techniques.push(makeTechnique(id, byId.get(sampleItem.item_id)));
  }
  current.items.sort((a, b) => a.item_id.localeCompare(b.item_id));
  current.techniques.sort((a, b) => a.id.localeCompare(b.id));
  writeJson(path.join(OUT.scripts, "technique-curation.json"), current);
  return current;
}
function buildTechniques(items, curation) {
  const byItem = new Map(items.map((i) => [i.id, i]));
  const techs = new Map(curation.techniques.map((t) => [t.id, { ...t, implementation_ids: [], evidence: [], evidence_refs: [] }]));
  for (const map of curation.items) {
    const item = byItem.get(map.item_id);
    for (const id of map.technique_ids) {
      const t = techs.get(id);
      t.implementation_ids.push(item.id);
      t.evidence.push(item.id, item.source_ref.manifest, ...item.source_ref.implementation);
      t.evidence_refs.push(...map.evidence_refs);
    }
  }
  for (const t of techs.values()) {
    t.implementation_ids = uniq(t.implementation_ids);
    t.evidence = uniq(t.evidence);
    const impls = t.implementation_ids.map((id) => byItem.get(id));
    const fields = uniq(impls.flatMap((i) => i.parameterization.contract_fields || []));
    t.controllable_fields_ru = fields.length ? fields.map((f) => `поле контракта ${f}`) : [];
    if (impls.length > 1) t.variants_ru = impls.map((i) => `реализация «${i.title}»`).sort();
    if (impls.some((i) => i.assessment.review_status === "ready" && ["approved","local"].includes(i.source))) t.availability = "ready";
    else if (impls.some((i) => i.assessment.review_status === "adapt")) t.availability = "adapt";
    else if (impls.every((i) => i.assessment.review_status === "forbidden")) t.availability = "forbidden";
    else t.availability = "reference_only";
    if (impls.some((i) => i.assessment.review_status === "forbidden")) t.risks_ru = uniq([...t.risks_ru, "Среди implementations есть запрещённая историческая реализация."]);
  }
  return { catalog_version: 1, techniques: [...techs.values()].sort((a, b) => a.id.localeCompare(b.id)), item_to_techniques: curation.items.map((i) => ({ item_id: i.item_id, technique_ids: i.technique_ids })).sort((a, b) => a.item_id.localeCompare(b.item_id)) };
}
function buildSchemas() {
  writeJson(path.join(OUT.inventory, "catalog.schema.json"), {
    $schema: "https://json-schema.org/draft/2020-12/schema",
    type: "object",
    required: ["id","source","kind","name","title","description","tags","source_ref","evidence_refs","dimensions","preview","parameterization","runtime","capabilities","assessment","human_review"],
    properties: {
      id: { type: "string", pattern: "^[a-z0-9_:-]+$" },
      source: { enum: ["upstream","local","approved"] },
      kind: { enum: ["block","component","layout","transition"] },
      evidence_refs: { type: "array", minItems: 1 },
      parameterization: { type: "object", required: ["manifest_params","declared_variables","contract_fields","uses_variable_values","uses_data_var_bindings","hardcoded_content_detected","level"], properties: { level: { enum: PARAM_LEVELS } } },
      assessment: { type: "object", required: ["score","score_breakdown","review_status","runtime_allowed","adaptation_needed","risks","reason"] },
    },
  });
  writeJson(path.join(OUT.inventory, "techniques.schema.json"), {
    $schema: "https://json-schema.org/draft/2020-12/schema",
    type: "object",
    required: ["catalog_version","techniques","item_to_techniques"],
    properties: {
      catalog_version: { const: 1 },
      techniques: { type: "array", items: { type: "object", required: ["id","name_ru","category","description_ru","viewer_sees_ru","use_when_ru","avoid_when_ru","implementation_ids","availability","evidence_refs"], properties: { id: { pattern: "^[a-z0-9_]+$" }, category: { enum: CATEGORIES }, availability: { enum: ["ready","adapt","reference_only","forbidden"] } } } },
    },
  });
}
function makePlaceholder() {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1920" viewBox="0 0 1080 1920"><rect width="1080" height="1920" fill="#151515"/><rect x="72" y="72" width="936" height="1776" fill="none" stroke="#3a3a3a" stroke-width="4"/><text x="540" y="900" text-anchor="middle" fill="#f5f0e8" font-family="Arial" font-size="64" font-weight="700">Preview</text><text x="540" y="982" text-anchor="middle" fill="#b9b1a6" font-family="Arial" font-size="42">not available</text></svg>`;
}
function counts(items) {
  const c = (p) => items.filter(p).length;
  return { upstream_blocks: c((i) => i.source === "upstream" && i.kind === "block"), upstream_components: c((i) => i.source === "upstream" && i.kind === "component"), local_blocks: c((i) => i.source === "local" && i.kind === "block"), approved_layouts: c((i) => i.source === "approved" && i.kind === "layout"), approved_transitions: c((i) => i.source === "approved" && i.kind === "transition"), total_items: items.length };
}
function sourceManifest(pre, c) {
  return { generated_at: new Date().toISOString(), branch: pre.branch, preflight: pre.preflight, sources: { upstream_snapshot: SOURCES.upstreamRoot, upstream_zip: SOURCES.upstreamZip, local_blocks_py: SOURCES.localBlocksPy, local_hyperframes_dir: SOURCES.localHyperframesDir, approved_catalog: SOURCES.approvedRoot }, upstream_zip_sha256: pre.hash, package_versions: pre.packages, expected_counts: { upstream_blocks: EXPECTED.upstreamBlocks, upstream_components: EXPECTED.upstreamComponents, upstream_examples: EXPECTED.examples, local_blocks: EXPECTED.localBlocks.length, approved_layouts: EXPECTED.approvedLayouts, approved_transitions: EXPECTED.approvedTransitions, total_items: EXPECTED.total }, actual_counts: { ...c, upstream_examples: pre.examples }, network_registry_update: false, project_decision_documents_read: [SOURCES.memory,SOURCES.pipelineTz,SOURCES.agents,SOURCES.editPlan,SOURCES.visualDirector] };
}
function by(items, f) {
  return Object.fromEntries(Object.entries(items.reduce((a, x) => (a[f(x)] = (a[f(x)] || 0) + 1, a), {})).sort(([a], [b]) => a.localeCompare(b)));
}
function makeShortlist(items) {
  const rows = items.filter((i) => i.assessment.review_status !== "forbidden").filter((i) => i.assessment.review_status === "ready" || (i.assessment.review_status === "adapt" && i.assessment.score >= 3)).map((i) => ({ id: i.id, title: i.title, kind: i.kind, score: i.assessment.score, reason: i.assessment.reason, adaptation_needed: i.assessment.adaptation_needed, risks: i.assessment.risks })).sort((a, b) => b.score - a.score || a.id.localeCompare(b.id));
  writeJson(path.join(OUT.shortlist, "auto-shortlist.json"), { catalog_version: 1, items: rows });
  writeJson(path.join(OUT.shortlist, "human-review.template.json"), { catalog_version: 1, decisions: items.map((i) => ({ id: i.id, decision: "undecided", notes: "" })) });
}
function makeGalleryData(items, techniques) {
  const techById = new Map(techniques.techniques.map((t) => [t.id, t]));
  const mapByItem = new Map(techniques.item_to_techniques.map((m) => [m.item_id, m.technique_ids]));
  return { catalog_version: 1, counts: { total: items.length, sources: by(items, (i) => i.source), kinds: by(items, (i) => i.kind), statuses: by(items, (i) => i.assessment.review_status), orientations: by(items, (i) => i.dimensions.orientation) }, techniques: techniques.techniques.map((t) => ({ id: t.id, name_ru: t.name_ru, category: t.category, description_ru: t.description_ru, availability: t.availability })), items: items.map((i) => ({ ...i, techniques: (mapByItem.get(i.id) || []).map((id) => ({ id, name_ru: techById.get(id).name_ru, category: techById.get(id).category, description_ru: techById.get(id).description_ru, availability: techById.get(id).availability })) })) };
}
function makeTechMd(items, data) {
  const lines = ["# Справочник визуальных и монтажных приёмов\n", "## Оглавление по категориям\n"];
  for (const [k, v] of Object.entries(by(data.techniques, (t) => t.category))) lines.push(`- ${RU_CATEGORY[k]}: ${v}`);
  lines.push("");
  for (const t of data.techniques) {
    lines.push(`### ${t.name_ru}\n`);
    lines.push(`- ID: \`${t.id}\``);
    lines.push(`- Категория: ${RU_CATEGORY[t.category]}`);
    lines.push(`- Availability: ${t.availability}`);
    lines.push(`- Что видит зритель: ${t.viewer_sees_ru}`);
    lines.push(`- Когда применять: ${t.use_when_ru.join(" ")}`);
    lines.push(`- Когда не применять: ${t.avoid_when_ru.join(" ")}`);
    lines.push(`- Реализации: ${t.implementation_ids.map((id) => `\`${id}\``).join(", ")}`);
    lines.push(`- Внутренние variants: ${t.variants_ru.join("; ") || "нет"}`);
    lines.push(`- Управляемые поля: ${t.controllable_fields_ru.join(", ") || "нет доказанных controls"}`);
    lines.push(`- Placement: ${t.placement_ru.join(", ")}`);
    lines.push(`- Готовность к 9:16: ${t.portrait_support}`);
    lines.push(`- Необходимая адаптация: ${t.adaptation_notes_ru.join("; ") || "не требуется для ready-реализаций"}`);
    lines.push(`- Dependencies и risks: ${[...t.dependencies_ru, ...t.risks_ru].join("; ") || "явных нет"}`);
    lines.push(`- Source evidence: ${t.evidence_refs.map((e) => `${e.path}:${e.line_start}-${e.line_end}`).join(", ")}`);
    lines.push("");
  }
  lines.push("## Матрица `item → techniques`\n");
  for (const m of data.item_to_techniques) lines.push(`- \`${m.item_id}\` → ${m.technique_ids.map((id) => `\`${id}\``).join(", ")}`);
  lines.push("\n## Матрица `technique → implementations`\n");
  for (const t of data.techniques) lines.push(`- \`${t.id}\` → ${t.implementation_ids.map((id) => `\`${id}\``).join(", ")}`);
  const section = (title, pred) => { lines.push(`\n## ${title}\n`); const rows = data.techniques.filter(pred); lines.push(rows.length ? rows.map((t) => `- \`${t.id}\` — ${t.name_ru}`).join("\n") : "- нет"); };
  section("Доступно сразу", (t) => t.availability === "ready");
  section("Станет доступно после адаптации", (t) => t.availability === "adapt");
  section("Только референсы", (t) => t.availability === "reference_only");
  section("Запрещённые исторические решения", (t) => t.availability === "forbidden" || t.implementation_ids.some((id) => id.includes("avatar_cutout_overlay")));
  lines.push("\n## Пробелы каталога\n");
  lines.push("- Нет готового face-safe reposition для произвольного HeyGen-видео; evidence: items содержат визуальные реализации, но не содержат detector contract.");
  lines.push("- Нет production asset resolver для лицензированного B-roll; evidence: catalog хранит media slots и examples, но не правообладательский pipeline.");
  lines.push("- Большинство upstream landscape blocks требует отдельной 1080x1920 адаптации; evidence: orientation distribution фиксируется в inventory.");
  lines.push("\n## Counts по категориям\n");
  for (const [k, v] of Object.entries(by(data.techniques, (t) => t.category))) lines.push(`- ${k}: ${v}`);
  lines.push("\n## Counts `ready/adapt/reference_only/forbidden`\n");
  for (const [k, v] of Object.entries(by(data.techniques, (t) => t.availability))) lines.push(`- ${k}: ${v}`);
  lines.push("\n## Multi-technique items\n");
  for (const m of data.item_to_techniques.filter((m) => m.technique_ids.length > 1)) lines.push(`- \`${m.item_id}\`: ${m.technique_ids.length}`);
  return lines.join("\n");
}
function makeAudit(items, techniques, pre, runtimeDeps) {
  return `# Catalog audit

## Preflight

- Branch: \`${pre.preflight.branch}\`
- Node: \`${pre.preflight.node}\`
- Baseline items: ${pre.preflight.baseline_items}
- Baseline techniques: ${pre.preflight.baseline_techniques}

## Sources

- Upstream snapshot: \`${SOURCES.upstreamRoot}\`
- Upstream ZIP: \`${SOURCES.upstreamZip}\`
- Local blocks: \`${SOURCES.localBlocksPy}\`
- Approved catalog: \`${SOURCES.approvedRoot}\`

## Versions and SHA-256

- ZIP SHA-256: \`${pre.hash}\`
- packages: ${Object.entries(pre.packages).map(([k,v]) => `${k} ${v}`).join(", ")}
- Network registry update: no

## Counts

${Object.entries(counts(items)).map(([k,v]) => `- ${k}: ${v}`).join("\n")}
- upstream_examples_reported_not_cards: ${pre.examples}
- techniques: ${techniques.techniques.length}

## Parameterization

${Object.entries(by(items, (i) => i.parameterization.level)).map(([k,v]) => `- ${k}: ${v}`).join("\n")}

## Orientation

${Object.entries(by(items, (i) => i.dimensions.orientation)).map(([k,v]) => `- ${k}: ${v}`).join("\n")}

## Review status

${Object.entries(by(items, (i) => i.assessment.review_status)).map(([k,v]) => `- ${k}: ${v}`).join("\n")}

## Runtime dependencies

- dependency entries: ${runtimeDeps.length}
- unique URLs: ${new Set(runtimeDeps.map((d) => d.url)).size}

## Missing/broken previews

See \`reports/preview-downloads.json\`.

## Top-30 auto-shortlist

${readJson(path.join(OUT.shortlist, "auto-shortlist.json")).items.slice(0,30).map((i, n) => `${n + 1}. \`${i.id}\` — score ${i.score}: ${i.reason}`).join("\n")}

## Local blocks

${items.filter((i) => i.source === "local").map((i) => `- \`${i.id}\`: ${i.parameterization.contract_fields.join(", ")}`).join("\n")}

## Approved patterns

${items.filter((i) => i.source === "approved").map((i) => `- \`${i.id}\`: ${i.parameterization.level}; fields ${i.parameterization.contract_fields.join(", ")}`).join("\n")}

## Forbidden confirmation

\`approved:layout:avatar_cutout_overlay\` remains \`forbidden\` and \`runtime_allowed: false\`.

## Not done

- No edit_plan, render, Stage 02, LLM, ElevenLabs, HeyGen or provider calls.

## Commands

\`\`\`powershell
node experiments/hyperframes-workflow-poc/stage-01-catalog/scripts/extract-catalog.mjs
node experiments/hyperframes-workflow-poc/stage-01-catalog/scripts/download-posters.mjs
node experiments/hyperframes-workflow-poc/stage-01-catalog/scripts/build-gallery.mjs
node experiments/hyperframes-workflow-poc/stage-01-catalog/scripts/validate-catalog.mjs
\`\`\`
`;
}
function preflight() {
  ensureDirs();
  const errs = [];
  for (const [k, p] of Object.entries(SOURCES)) if (!exists(p)) errs.push(`missing source ${k}: ${p}`);
  const branch = execSync("git branch --show-current", { cwd: ROOT, encoding: "utf8" }).trim();
  const status = execSync("git status --short", { cwd: ROOT, encoding: "utf8" });
  const node = execSync("node --version", { cwd: ROOT, encoding: "utf8" }).trim();
  if (branch !== EXPECTED.branch) errs.push(`branch mismatch: ${branch}`);
  const hash = exists(SOURCES.upstreamZip) ? hashFile(SOURCES.upstreamZip) : "";
  if (hash !== EXPECTED.zipHash) errs.push(`zip SHA mismatch: ${hash}`);
  const packages = {};
  for (const name of ["cli","core","producer","sdk"]) {
    const f = path.join(SOURCES.upstreamRoot, `packages/${name}/package.json`);
    packages[name] = exists(f) ? readJson(f).version : "missing";
    if (packages[name] !== EXPECTED.version) errs.push(`package ${name} version ${packages[name]}`);
  }
  const registry = readJson(path.join(SOURCES.upstreamRoot, "registry/registry.json"));
  const examples = registry.items.filter((i) => i.type === "hyperframes:example").length;
  if (examples !== EXPECTED.examples) errs.push(`examples count ${examples}`);
  const oldItems = exists(path.join(OUT.inventory, "items.json")) ? readJson(path.join(OUT.inventory, "items.json")).length : 0;
  const oldTech = exists(path.join(OUT.inventory, "techniques.json")) ? readJson(path.join(OUT.inventory, "techniques.json")).techniques.length : 0;
  if (errs.length) {
    writeText(path.join(OUT.reports, "blockers.md"), `# Blockers\n\n${errs.map((e) => `- ${e}`).join("\n")}\n`);
    throw new Error(errs.join("\n"));
  }
  return { branch, hash, packages, examples, preflight: { branch, status, node, baseline_items: oldItems, baseline_techniques: oldTech } };
}
function main() {
  ensureDirs();
  const pre = preflight();
  buildSchemas();
  writeText(path.join(OUT.galleryAssets, "placeholder.svg"), makePlaceholder());
  const runtimeDeps = [];
  const previewReport = loadPreviewReport();
  const items = [
    ...extractUpstream("block", "blocks", previewReport, runtimeDeps),
    ...extractUpstream("component", "components", previewReport, runtimeDeps),
    ...extractLocal(),
    ...extractApproved(),
  ].sort((a, b) => a.id.localeCompare(b.id));
  const c = counts(items);
  if (JSON.stringify(c) !== JSON.stringify({ upstream_blocks: 113, upstream_components: 25, local_blocks: 8, approved_layouts: 10, approved_transitions: 5, total_items: 161 })) {
    writeText(path.join(OUT.reports, "blockers.md"), `# Blockers\n\n- count mismatch: ${JSON.stringify(c)}\n`);
    throw new Error("count mismatch");
  }
  const curation = buildCuration(items);
  const techniques = buildTechniques(items, curation);
  writeJson(path.join(STAGE, "source-manifest.json"), sourceManifest(pre, c));
  writeJson(path.join(OUT.inventory, "items.json"), items);
  writeJson(path.join(OUT.inventory, "techniques.json"), techniques);
  writeJson(path.join(OUT.galleryData, "catalog.json"), makeGalleryData(items, techniques));
  writeJson(path.join(OUT.reports, "runtime-dependencies.json"), { catalog_version: 1, dependencies: runtimeDeps.sort((a, b) => a.item_id.localeCompare(b.item_id) || a.url.localeCompare(b.url)), unique_urls: uniq(runtimeDeps.map((d) => d.url)) });
  writeJson(path.join(OUT.reports, "technique-extraction-audit.json"), {
    catalog_version: 1,
    source_text_files_inspected: items
      .flatMap((i) => [i.source_ref.manifest, ...i.source_ref.implementation])
      .filter((file) => /\.(json|html|js|mjs|css)$/i.test(file))
      .filter((value, index, all) => all.indexOf(value) === index)
      .sort(),
    item_mappings: curation.items,
  });
  writeJson(path.join(OUT.inventory, "upstream-summary.json"), { blocks: c.upstream_blocks, components: c.upstream_components, examples_reported_not_catalog_items: pre.examples, parameterization: by(items.filter((i) => i.source === "upstream"), (i) => i.parameterization.level) });
  writeJson(path.join(OUT.inventory, "local-summary.json"), { blocks: c.local_blocks, ids: items.filter((i) => i.source === "local").map((i) => i.name).sort(), parameterization_level: "generated_python" });
  writeJson(path.join(OUT.inventory, "approved-summary.json"), { layouts: c.approved_layouts, transitions: c.approved_transitions, parameterization_level: "approved_js_contract", forbidden: ["approved:layout:avatar_cutout_overlay"] });
  makeShortlist(items);
  if (!exists(path.join(OUT.reports, "preview-downloads.json"))) writeJson(path.join(OUT.reports, "preview-downloads.json"), { attempted: false, entries: [], counts: { downloaded: 0, cached: 0, failed: 0, not_applicable: 0 } });
  writeText(path.join(OUT.reports, "catalog-audit.md"), makeAudit(items, techniques, pre, runtimeDeps));
  writeText(path.join(OUT.reports, "techniques-catalog.md"), makeTechMd(items, techniques));
  writeText(path.join(OUT.reports, "blockers.md"), "# Blockers\n\nNo blockers recorded for current extraction.\n");
  writeText(path.join(STAGE, "README.md"), `# Stage 01 HyperFrames catalog\n\nОткройте \`gallery/index.html\` двойным кликом. Каталог содержит 161 карточку, фильтры, поиск, shortlist, decisions, notes и export \`human-review.json\`. Экспорт нужно положить в \`experiments/hyperframes-workflow-poc/stage-01-catalog/shortlist/human-review.json\`. Stage 02 нельзя начинать до утверждения этого файла человеком.\n`);
  console.log(`extracted ${items.length} items, ${techniques.techniques.length} techniques, ${runtimeDeps.length} runtime dependency entries`);
}
main();
