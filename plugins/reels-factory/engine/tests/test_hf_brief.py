"""Задание агенту: паспорт по контракту фреймворка, материал и границы.

Пооконной раскадровки здесь больше нет намеренно. Планирование битов —
работа агента через hyperframes-creative; когда мы отдавали ему готовые окна,
он переставал быть режиссёром и просто перекладывал наш чертёж в HTML.
"""
from reels_factory.hf_brief import FONTS, write_brief

SCENARIO = {
    "total": 41.5,
    "blocks": [
        {"role": "hook", "start": 0.0, "end": 12.22,
         "speech": "Все продажи на свете сводятся к трём вопросам"},
        {"role": "development", "start": 12.22, "end": 23.14,
         "speech": "Первый: кому продаём"},
        {"role": "payoff", "start": 23.14, "end": 34.62,
         "speech": "Третий: как продаём"},
        {"role": "cta", "start": 34.62, "end": 41.5,
         "speech": "Сохрани это видео"},
    ],
}

CLIPS = [{"file": "clips/avatar_0.mp4", "start": 0.0, "duration": 12.22}]


def _text(tmp_path, **kw):
    kw.setdefault("scenario", SCENARIO)
    kw.setdefault("clips", CLIPS)
    return write_brief(tmp_path, face={"cx": 540, "cy": 520, "h": 260},
                       duration=41.5, **kw).read_text(encoding="utf-8")


# ---------- паспорт задания ----------

def test_поля_которые_знает_движок_проставлены(tmp_path):
    text = _text(tmp_path)
    for field in ("flow", "storyboard", "mode", "aspect", "length",
                  "language", "narration", "destination"):
        assert field in text, f"нет поля {field}"
    assert "automation" in text
    assert "autonomous" in text
    assert "1080x1920" in text


def test_поля_контракта_агент_выводит_сам(tmp_path):
    """`message`, `audience`, `angle` — поля их контракта брифа
    (hyperframes-core/references/brief-contract.md:71-73). Клиента о них не
    спрашивают: глаголы контракта — infer, derive, recommend."""
    text = _text(tmp_path)
    for field in ("message", "audience", "angle"):
        assert f'"{field}"' in text, f"нет поля {field}"
    assert "выведи из материала сам" in text


def test_фразы_пронумерованы_в_задании(tmp_path):
    text = _text(tmp_path, phrases=[
        {"id": 0, "role": "hook", "text": "Все продажи.",
         "start": 0.0, "end": 2.4},
        {"id": 1, "role": "hook", "text": "Порядок решает.",
         "start": 2.4, "end": 5.0}])
    # длина нужна, чтобы агент не назначал сцену на фразу короче минимума
    assert "`0` **hook** 2.4 с — Все продажи." in text
    assert "есть фразы\n`0`–1" in text or "есть фразы `0`–1" in text


def test_маршрут_назван_в_шапке(tmp_path):
    """Роутер читает `workflow` из шапки BRIEF.md и дальше не переспрашивает
    (hyperframes/SKILL.md:28). Без шапки он выбирал маршрут сам и брал
    talking-head-recut — контракт упаковки чужого клипа, а не сборки с нуля."""
    text = _text(tmp_path)
    assert text.startswith("---\n"), "шапки нет — YAML должен идти первым"
    assert "workflow: general-video" in text
    assert "talking-head-recut" not in text


def test_язык_можно_задать(tmp_path):
    assert "kk" in _text(tmp_path, language="kk")


# ---------- вход ----------

def test_сценарий_по_блокам_передан(tmp_path):
    text = _text(tmp_path)
    for role in ("hook", "development", "payoff", "cta"):
        assert role in text
    assert "Все продажи на свете" in text


def test_расписание_клипов_секундами_не_передаётся(tmp_path):
    """Секунд агент не видит вовсе: где ведущей нет, ему говорят номерами фраз.
    Расписание клипов в секундах он всё равно ни с чем не мог бы сверить."""
    text = _text(tmp_path)
    assert "clips/avatar_0.mp4" not in text


def test_материал_перечислен(tmp_path):
    text = _text(tmp_path)
    assert "voice.wav" in text and "words.json" in text


# ---------- то, чего в задании быть не должно ----------

def test_пооконной_раскадровки_нет(tmp_path):
    text = _text(tmp_path)
    assert "Что показывать по окнам" not in text
    assert "карточку не рисуй" not in text
    assert "window-000" not in text


def test_наших_блоков_агенту_больше_не_выдают(tmp_path):
    """Полноэкранная непрозрачная сцена выбивала ведущую из кадра, и вокруг неё
    была написана половина гейтов. Блоки остались на диске — их просто не
    предлагают."""
    text = _text(tmp_path)
    assert "g02-avatar-fullscreen-hook" not in text
    assert "Блоки каталога" not in text
    # «слот» в задании теперь законен: их накладки несут текстовые слоты,
    # а наши 25 полноэкранных по-прежнему не выдаются (строка выше).


def test_словарь_положений_ведущей_в_задании(tmp_path):
    """Позиции нет в списке — падаем внятно, а не додумываем."""
    text = _text(tmp_path)
    for position in ("full", "punch", "pip-tr", "stack", "none"):
        assert f"`{position}`" in text
    # `split` снят: лицо ведущей в нижней половине попадает в полосу титра
    assert "`split`" not in text


# ---------- границы ----------

def test_правила_числами(tmp_path):
    text = _text(tmp_path)
    assert "1080" in text and "1920" in text
    assert "41.5" in text or "41,5" in text


def test_гарнитуры_наши(tmp_path):
    """Гарнитуры держим сами: другие не несут кириллицу и казахские буквы."""
    assert FONTS in _text(tmp_path)


def test_вёрстку_у_агента_не_просят(tmp_path):
    """Изготовление ушло коду целиком: разметки в ответе агента больше нет."""
    text = _text(tmp_path)
    assert "public/cards/" not in text
    assert "data-anim" not in text
    assert "Композицию, разметку и субтитры собирает код" in text


def test_интервалы_без_ведущей_названы(tmp_path):
    # клип только на 0–12.22, значит 12.22–41.5 ведущей в кадре нет
    text = _text(tmp_path)
    assert "без ведущей" in text.lower() or "ведущей в кадре нет" in text.lower()


def test_причина_повтора_попадает_в_задание(tmp_path):
    assert "лицо перекрыто" in _text(tmp_path, retry_reason="лицо перекрыто")


def test_что_вернуть_названо(tmp_path):
    text = _text(tmp_path)
    assert "storyboard.json" in text
    # Композицию собирает код — просить её у агента больше нельзя.
    assert "public/index.html" not in text


def test_у_агента_просят_только_сцены(tmp_path):
    """Шапку схемы заполняет код: решений в ней нет, а разойтись есть где —
    на Sonnet агент отдал videoTrack списком и потерял попытку."""
    text = _text(tmp_path)
    assert '"scenes"' in text
    assert '"presenter"' in text and '"intent"' in text
    assert '"videoTrack"' not in text and '"schemaVersion": 3,' not in text
    # Поля, которые мы просили сверх схемы, противоречили videoTrack.bounds.
    assert "contentRect" not in text and "videoRect" not in text
    assert '"zone"' not in text


def test_поле_под_следующий_шаг_заложено(tmp_path):
    """Работа 8 переставит заказ островов после плана — читать он будет это."""
    assert "avatarNeeded" in _text(tmp_path)


def test_запрос_вставки_объяснён_без_квоты(tmp_path):
    """Квоты «не меньше N вставок» больше нет: она загоняла агента в бироллы
    там, где они не нужны. Отрицательного правила взамен тоже нет — агент
    руководствуется положительным смыслом (решение Васи 09.08.2026)."""
    text = _text(tmp_path)
    assert "не меньше чем в трёх сценах" not in text
    assert "`shots`" in text
    assert "ПО-АНГЛИЙСКИ" in text
    assert "brollContext" in text


def test_серия_из_двух_планов_объяснена(tmp_path):
    """Одиночных вставок больше не бывает: агент называет два плана, а сколько
    серий доживёт до кадра — считает код."""
    text = _text(tmp_path)
    assert "серией из двух планов" in text
    assert "от пяти до восьми на ролик" in text


def test_оплаченная_ведущая_обязана_быть_в_кадре(tmp_path):
    """Клипы куплены до плана, поэтому задание требует обратного прежнему:
    прятать ведущую на оплаченной секунде — выбрасывать деньги заказчика.
    Прежнего потолка 60 % в этом тексте остаться не должно, иначе агент читает
    два взаимоисключающих требования."""
    text = _text(tmp_path)
    assert "## Где ведущая в кадре" in text
    assert "клип куплен и оплачен заказчиком" in text
    assert "зритель должен её увидеть" in text
    assert "не больше 60 %" not in text
    assert "65–70" not in text and "65-70" not in text


def test_до_заказа_аватара_потолок_остаётся(tmp_path):
    """План до заказа (работа 9) считает деньги ровно наоборот: там сцена без
    ведущей её и не закажет, и потолок аватарного времени осмыслен."""
    text = _text(tmp_path, avatar_ordered=False)
    assert "не больше 60 % хронометража" in text
    assert "заказанная секунда генерации" in text


def test_когда_аватар_остаётся_поверх_биролла(tmp_path):
    """Четыре случая названы явно: без них агент ставил уголок по вкусу."""
    text = _text(tmp_path)
    assert "Сцена со вставкой — `pip-*` (ведущая уголком поверх вставки)" in text
    assert "обращается к зрителю" in text
    assert "предмет, который диктор называет" in text


def test_субтитры_снимаются_с_агента(tmp_path):
    text = _text(tmp_path)
    assert "субтитры" in text.lower()
    assert "Композицию, разметку и субтитры собирает код" in text


def test_правило_смены_положения_совпадает_с_проверкой(tmp_path):
    """Проверка считает заметно разные ОКНА ведущей и сцены с `none` не
    засчитывает вовсе. Прежняя формулировка «сменилось не меньше трёх раз»
    разрешала план `full → none → full → none → full`: он выполняет написанное
    буквально и валит гейт, а попытка одна и аватар уже оплачен."""
    text = _text(tmp_path)
    assert "заметно разных окнах" in text
    assert "сцены с `none` в этот счёт не" in text
    assert "минимум три" in text
    assert "не меньше трёх раз" not in text


def test_смену_картинки_даёт_граница_сцен(tmp_path):
    """Зазора между сценами больше нет: кадр из слоёв, сцены выстилают ролик,
    и две одинаковые подряд детектор видит одним планом."""
    text = _text(tmp_path)
    assert "Соседние сцены обязаны отличаться картинкой" in text
    assert "свободные фразы" not in text


def test_секунд_в_ответе_не_бывает_но_длину_сцены_считать_можно(tmp_path):
    """Прогоны 9 и 10: арифметика времени стоила по полчаса и всё равно с
    ошибкой — границы сцен считает код. Но длину сцены агенту знать нужно:
    накладка и серия требуют минимума секунд. Способ назван один раз —
    сложение длительностей фраз из списка; прежде задание требовало секунд и
    тут же запрещало их считать, не назвав ни одного способа."""
    text = _text(tmp_path)
    sample = text.split("```json")[1].split("```")[0]
    assert "startSec" not in sample and "endSec" not in sample
    assert '"phrases": [1, 2]' in sample
    assert "Секунд в них\nбыть не должно" in text
    assert "сложением длительностей её фраз" in text
    assert text.count("Не считай секунды") == 0


def test_служебные_надписи_запрещены(tmp_path):
    """Запреты собраны в negative list — их же приём из visual-design.md:89."""
    text = _text(tmp_path)
    assert "Чего в кадре не бывает" in text
    assert "фото из каталога" in text
    assert "Стоковых клише" in text


def test_биты_объяснены_и_кульминация_одна(tmp_path):
    text = _text(tmp_path)
    assert "`climax`" in text
    assert "Ровно одна на ролик" in text
    assert "сцена-передышка" in text


def test_пол_сцен_дан_числом(tmp_path):
    """Пол только против дыр: ceil(41,5 / 8) = 6. Числовой планки смен в
    задании больше нет — темп задаёт их правило жанра (1,5–4 с на мысль),
    наш детектор остаётся замером по готовому файлу."""
    text = _text(tmp_path)
    assert "Сцен не меньше 6" in text
    assert "1,5–4 секунды" in text
    assert "заметных смен" not in text


def test_лишняя_работа_названа_разделением_работы(tmp_path):
    """16 минут на план — это чтение справочников и попытки собрать самому.
    Список остался, но говорит, что уже сделано, а не чего нельзя: их дока
    прямо советует позитивную форму («Tell Claude what to do instead of what
    not to do», prompt-engineering/claude-prompting-best-practices)."""
    text = _text(tmp_path)
    assert "## Что делает код после тебя" in text
    assert "hyperframes check" in text
    assert "HTML, CSS и JavaScript в этом\n  прогоне не пишутся вовсе" in text


def test_правило_наполнения_кадра_живёт_в_одном_месте(tmp_path):
    """Разбор задания: правило про значок стояло в трёх местах в трёх
    редакциях. Средства кадра описаны одним разделом — иначе агент читает
    два разных требования и выбирает одно из них."""
    text = _text(tmp_path)
    assert text.count("## Чем занять кадр") == 1
    assert "## Медиа-проход" not in text
    assert "## Иконка фоновой сцены" not in text
    assert "## Их накладки из каталога" not in text


def test_выбор_между_бироллом_и_схемой_дан_признаками(tmp_path):
    """Их дока про классификацию: качество выбора прямо пропорционально
    качеству определений, а не количеству запретов; варианты — закрытым
    списком, и ровно один применим."""
    text = _text(tmp_path)
    assert "У сцены\nровно одно средство" in text
    assert "когда мысль снимается камерой" in text
    assert "когда мысль камерой не снимается" in text
    assert "У сцены ровно одна форма" in text
    assert "Форма идёт от **типа высказывания**" in text


def test_у_каждой_формы_названо_и_назначение_и_граница(tmp_path):
    """Канон описания инструмента: что делает, когда брать, **когда не
    брать** и чего не выражает — иначе форму применяют не по адресу.
    Проверено на нас: метрика с полосой прогресса стояла под «три вопроса»."""
    text = _text(tmp_path)
    section = text.split("<forms>")[1].split("</forms>")[0]
    for form in ("metric", "items", "pairs", "steps", "brand"):
        assert f'<form name="{form}">' in section
    assert section.count("Бери") >= 5
    assert section.count("Не бери") >= 4
    assert "Не бери под счёт названных вещей" in section
    assert "три из ста" in section


def test_разбор_идёт_до_выбора_формы(tmp_path):
    """Их же приём из руководства по классификации: сначала рассуждение,
    потом метка. У нас рассуждение — строка `why` в самой схеме."""
    text = _text(tmp_path)
    assert "напиши в поле `why` одну строку разбора" in text
    assert "Разбор идёт до выбора, а не после" in text
    assert '"why"' in text


def test_спор_решается_названным_приоритетом(tmp_path):
    """Приём из их же руководства по классификации: когда подходят два
    признака, сказать вслух, какой весит больше, и почему."""
    text = _text(tmp_path)
    assert "есть и чувство, и величина" in text
    assert "чувство уже\nзвучит в голосе ведущей" in text


def test_формы_схемы_даны_закрытым_списком_с_примерами(tmp_path):
    """Их рекомендация — 3–5 примеров, разнородных, в `<example>`, и один
    спорный с объяснением выбора."""
    text = _text(tmp_path)
    assert "<fillings>" in text
    for form in ("metric", "items", "pairs", "steps", "brand"):
        assert f'"form": "{form}"' in text
    section = text.split("## Чем занять кадр")[1].split("### Паспорта")[0]
    assert 3 <= section.count("<example>") <= 5
    assert "Метрика запрещена" in section


def test_запасная_схема_той_же_формы(tmp_path):
    """Схему выбирает агент по смыслу; `fallback` — та же форма на случай,
    когда сток не ответил, а не отдельный вид."""
    text = _text(tmp_path)
    assert "**`fallback` — та же схема на случай" in text
    assert "Заполняй у\nкаждой сцены с бироллом" in text


def test_имена_слотов_накладки_берутся_дословно(tmp_path):
    """Три способа уронить сборку накладкой не были названы ни разу."""
    text = _text(tmp_path)
    assert "имя блока — из паспортов дословно" in text
    assert "имена слотов из паспорта этого блока дословно" in text
    assert "поля `text` быть не должно" in text


def test_настроение_титра_больше_не_спрашивают(tmp_path):
    """Код его не читает, и просить у агента решение, которое ни на что не
    влияет, — тратить его внимание впустую."""
    text = _text(tmp_path)
    assert "captionTone" not in text


def test_бриф_до_заказа_аватара_отдаёт_решение_агенту(tmp_path):
    """Работа 9: дыры не навязаны, агент решает avatarNeeded, и по нему
    закажут острова."""
    from reels_factory.hf_brief import write_brief

    path = write_brief(
        tmp_path, scenario={"blocks": [{"role": "hook", "speech": "Привет"}]},
        face=None, duration=41.5, clips=[], avatar_ordered=False,
        phrases=[{"id": 0, "role": "hook", "start": 0.0, "end": 2.0,
                  "text": "Привет"}])
    text = path.read_text(encoding="utf-8")
    assert "не заказан" in text and "avatarNeeded: true" in text
    assert "дешевле" in text
    assert "ведущей тут нет" not in text


def test_схема_не_берёт_чужую_реплику_и_не_повторяет_титр(tmp_path):
    """Обе находки веера из шести сценариев: агент дорисовывал перечисление
    указателю («Первый: кому продаём»), взяв пункты из следующей фразы, и
    ставил на карточку два слова подряд из самой реплики — титр печатает их в
    тот же момент. Правило их же: «never a sentence from the narration… the
    root caption track already shows the spoken words»."""
    text = _text(tmp_path)
    assert "Объявлен набор целиком" in text
    assert "Названа одна позиция" in text
    assert "Слова схемы говорят своё" in text
    assert "Проверь каждую подпись, и" in text
    assert "живёт по тем же правилам" in text


def test_шаг_пожеланий_можно_пропустить(tmp_path):
    """Их слой намерения спрашивает один раз и держит сказанное отдельно от
    выведенного (`intent-interview.md`, шаг 8). Пропущенный шаг ничего не
    меняет: поля без ответа агент выводит, как выводил."""
    assert "Это сказал заказчик" not in _text(tmp_path)


def test_сказанное_заказчиком_идёт_дословно_и_отдельно(tmp_path):
    text = _text(tmp_path, wishes={
        "message": "заговорить можно с телефона",
        "notes": "спокойный тон, тёплая палитра"})
    assert "### Это сказал заказчик — бери как есть" in text
    assert "заговорить можно с телефона" in text
    assert "спокойный тон, тёплая палитра" in text
    # Незаполненное поле не превращается в пустую строку в брифе — оно
    # остаётся на выведение агентом, и об этом сказано вслух.
    assert "Остальное (audience, angle, destination) выведи сам." in text
