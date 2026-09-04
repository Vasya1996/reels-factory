"""Задание агенту: паспорт по контракту фреймворка, материал и границы.

Пооконной раскадровки здесь больше нет намеренно. Планирование битов —
работа агента через hyperframes-creative; когда мы отдавали ему готовые окна,
он переставал быть режиссёром и просто перекладывал наш чертёж в HTML.
"""
import json
import math
import re

import pytest

from reels_factory.avatar_islands import DEFAULTS as ISLAND_DEFAULTS
from reels_factory.editplan import MAX_FACE_ABSENCE_S, MIN_FULLSCREEN_S
from reels_factory.hf_brief import FONTS, write_brief
from reels_factory.hf_gates import min_scenes as _min_scenes
from reels_factory.hf_montage import SERIES_MAX, SERIES_MIN, face_gap, inserts_wanted
from reels_factory.hf_phrases import MIN_SCENE
from reels_factory.hf_rhythm import MAX_STATIC_SPAN
from reels_factory.hf_schema import LIMITS, MINIMUM, min_seconds
# Написание секунд одно на оба текста, и тесты обязаны искать ровно его:
# «29,05 с» печатается как «29 с», и поиск по `f"{x:.1f}"` находил бы пустоту.
from reels_factory.hf_montage_skill import number as _число, seconds as _секунды

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


def _цели(duration: float, islands: dict | None = None) -> tuple[float, float]:
    """Цель и граница бюджета ведущей — из той же функции, что и задание.

    Числа считает `avatar_budget_targets` (avatar_islands.py), и по ней же
    судит гейт бюджета `D29_avatar_budget`. Повторять её формулу в тесте
    нельзя: правка долей (решение заказчика — ориентир 60 % и граница отказа
    70 % порознь) развела бы тест с кодом, и зелёный тест означал бы прежнее
    число.

    Возвращаются два числа из трёх: цель — то, в которое агент целится своим
    счётом (ориентир минус ручки заказа), и граница — та, выше которой план
    заворачивают. Сам ориентир берётся из `ceiling_seconds` там, где он нужен.
    """
    from reels_factory.avatar_islands import (
        avatar_budget_targets, avatar_islands_settings,
    )

    settings = avatar_islands_settings({"avatar_islands": islands or {}})
    budget = avatar_budget_targets(duration, settings)
    return budget["target_seconds"], budget["hard_ceiling_seconds"]


def _text(tmp_path, **kw):
    kw.setdefault("scenario", SCENARIO)
    kw.setdefault("clips", CLIPS)
    kw.setdefault("duration", 41.5)
    return write_brief(tmp_path, face={"cx": 540, "cy": 520, "h": 260},
                       **kw).read_text(encoding="utf-8")


def _skill(tmp_path, **kw):
    """Монтажная доктрина: живёт скиллом рядом с заданием, а не в нём."""
    _text(tmp_path, **kw)
    return (tmp_path / ".claude" / "skills" / "reels-montage"
            / "SKILL.md").read_text(encoding="utf-8")


#: Фразы, часть которых приходится на пропуск между островами аватара: клип из
#: `CLIPS` кончается на 12.22, ролик длится 41.5, значит фразы `2`–`4` идут без
#: ведущей. Нужны там, где проверяется ветка «аватар уже заказан».
GAP_PHRASES = [
    {"id": 0, "role": "hook", "text": "Все продажи.", "start": 0.0,
     "end": 6.0},
    {"id": 1, "role": "hook", "text": "Порядок решает.", "start": 6.0,
     "end": 12.0},
    {"id": 2, "role": "development", "text": "Кому продаём.", "start": 12.4,
     "end": 20.0},
    {"id": 3, "role": "payoff", "text": "Как продаём.", "start": 20.0,
     "end": 30.0},
    {"id": 4, "role": "cta", "text": "Сохрани это видео.", "start": 30.0,
     "end": 41.5},
]

#: Клип на весь ролик: дыр между островами нет вовсе.
FULL_CLIPS = [{"file": "clips/avatar_0.mp4", "start": 0.0, "duration": 41.5}]

def _фразы(count: int, length: float = 2.0) -> list[dict]:
    """Ровные фразы с правдоподобными ролями: хук открывает, призыв закрывает.

    Роли нужны материалу для правдоподобия — реальный сценарий их несёт, — а
    не потому, что роль сама решает, какой сцене годится отказ от ведущей:
    единственное, что теперь его решает, — длина сцены и края ролика
    (`D28_avatar_bookends`).
    """
    return [{"id": index,
             "role": "hook" if index < 2 else
                     "cta" if index >= count - 2 else "development",
             "text": f"фраза {index}",
             "start": index * length, "end": index * length + length}
            for index in range(count)]


#: Восемь ровных фраз — на них собирается образец плана: он показывает первые
#: четыре сцены, а короче списка сцен в образце меньше.
EVEN_PHRASES = _фразы(8)

#: Быстрая речь: фразы около 2,4 с, то есть каждая короче `MIN_FULLSCREEN_S`.
#: Ревизия круга 3 перебрала на таком материале все 1024 плана и не нашла ни
#: одного проходящего: порог мерялся каждой фразой. После склейки соседних окон
#: (`apply_agent_coverage`) сцена из двух таких фраз пол проходит, и тексты
#: обязаны звать именно туда.
FAST_PHRASES = _фразы(17, 2.4)

#: Речь, где короткие фразы стоят в середине показанных образцом сцен, а
#: длинные — раньше. Выбор сцены под отказ «по номеру» попадал ровно в
#: короткую пару и печатал сцену, которую гейт заворачивает.
UNEVEN_PHRASES = [
    {"id": 0, "role": "hook", "text": "фраза 0", "start": 0.0, "end": 2.0},
    {"id": 1, "role": "hook", "text": "фраза 1", "start": 2.0, "end": 4.0},
    {"id": 2, "role": "development", "text": "фраза 2", "start": 4.0,
     "end": 7.0},
    {"id": 3, "role": "development", "text": "фраза 3", "start": 7.0,
     "end": 10.0},
    {"id": 4, "role": "development", "text": "фраза 4", "start": 10.0,
     "end": 11.0},
    {"id": 5, "role": "development", "text": "фраза 5", "start": 11.0,
     "end": 12.0},
    {"id": 6, "role": "cta", "text": "фраза 6", "start": 12.0, "end": 14.0},
    {"id": 7, "role": "cta", "text": "фраза 7", "start": 14.0, "end": 16.0},
]

#: Речь, где короче порога выходит любая сцена образца: фразы по 1,2 с, и пара
#: соседних даёт 2,4 с. Отказ показать не на чем — образец обязан обойтись без
#: него и сказать, почему.
TINY_PHRASES = _фразы(34, 1.2)

#: Как код может напечатать три секунды. Число одно, а имён у него в текстах
#: три (пол схемы `items`, минимальный кусок заказа, минимум сцены БЕЗ
#: ведущей), и тесты ниже требуют, чтобы каждое стояло рядом со своим именем.
THREE_SECONDS = ("3 с", "3,0 с", "3.0 с")


def _абзац(text: str, at: int) -> str:
    """Абзац или пункт списка, внутри которого стоит позиция `at`.

    Проверять число «рядом со своим именем» окном в N знаков нельзя: соседний
    пункт списка попадает в окно и подсовывает своё имя чужому числу.
    """
    head = max(text.rfind(mark, 0, at) for mark in ("\n- ", "\n\n"))
    head = head + 1 if head > 0 else 0
    ends = [end for end in (text.find(mark, at) for mark in ("\n- ", "\n\n"))
            if end != -1]
    return text[head:min(ends)] if ends else text[head:]


def _абзацы(text: str, mark: str) -> list[str]:
    """Все абзацы, в которых встречается `mark`."""
    found, at = [], text.find(mark)
    while at != -1:
        found.append(_абзац(text, at))
        at = text.find(mark, at + 1)
    return found


def _с_числом(text: str, renderings: tuple[str, ...]) -> list[str]:
    """Абзацы, где число названо в любом из написаний."""
    return [part for mark in renderings for part in _абзацы(text, mark)]


def _минимум_без_ведущей(skill: str) -> list[str]:
    """Куски свода правил, где три секунды названы минимумом сцены БЕЗ ведущей.

    Именно это меряет `MIN_FULLSCREEN_S` (editplan.py:2543): окно с покрытием
    `full_broll`/`hyperframes`, то есть кадр, из которого ведущая убрана.
    """
    return [part for part in _с_числом(skill, THREE_SECONDS)
            if "без ведущей" in part and "не меньше" in part]


def _board(text: str) -> dict:
    """Образец плана из задания, разобранный как JSON.

    Хвост образца подписан многоточием — закрываем список сцен сами.
    """
    sample = text.split("```json")[1].split("```")[0]
    body = "\n".join(line for line in sample.splitlines()
                     if "остальные сцены" not in line)
    body = body.rstrip().rstrip("}").rstrip().rstrip("]").rstrip().rstrip(",")
    return json.loads(body + "\n ]\n}")


# ---------- паспорт задания ----------

def test_поля_которые_знает_движок_проставлены(tmp_path):
    text = _text(tmp_path)
    for field in ("flow", "storyboard", "mode", "aspect", "length",
                  "language", "narration", "destination"):
        assert field in text, f"нет поля {field}"
    assert "automation" in text
    assert "autonomous" in text
    assert "1080x1920" in text


def test_мёртвых_полей_у_агента_не_просят(tmp_path):
    """`message`, `audience`, `angle`, `arc` не читает ни одна строка движка, а
    их собственный формат держит эти поля во frontmatter брифа, а не в выходе
    плана («message, audience, length, angle live in the frontmatter only»,
    hyperframes-core/references/brief-format.md). Решение, которое никуда не
    идёт, тратит внимание агента впустую."""
    sample = _text(tmp_path).split("```json")[1].split("```")[0]
    for field in ("message", "audience", "angle", "arc"):
        assert f'"{field}"' not in sample, f"поле {field} снова в образце"


def test_фразы_пронумерованы_в_задании(tmp_path):
    text = _text(tmp_path, phrases=[
        {"id": 0, "role": "hook", "text": "Все продажи.",
         "start": 0.0, "end": 2.4},
        {"id": 1, "role": "hook", "text": "Порядок решает.",
         "start": 2.4, "end": 5.0}])
    # длина нужна, чтобы агент не назначал сцену на фразу короче минимума;
    # написание секунд одно на оба файла (`seconds` в hf_montage_skill.py)
    assert "`0` **hook** 2,4 с — Все продажи." in text
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
    """Времени в секундах агент не получает нигде, кроме длины ролика во
    frontmatter и длительностей фраз: где ведущей нет, ему говорят номерами
    фраз. Расписание клипов в секундах он ни с чем не мог бы сверить."""
    text = _text(tmp_path)
    assert "clips/avatar_0.mp4" not in text


def test_материал_перечислен(tmp_path):
    text = _text(tmp_path)
    assert "voice.wav" in text and "words.json" in text
    assert "Материал (лежит в `public/`)" in text, (
        "после заказа материал уже на диске, и заголовок обязан это говорить")


def test_до_заказа_материала_в_public_ещё_нет(tmp_path):
    """Дефект 5, половина в задании. Раздел «Материал (лежит в `public/`)»
    печатался всегда, а на плане ДО заказа папка пуста: клипы и звук кладёт
    `prepare()` уже в сборке, после того как HeyGen снимет ведущую по этому
    плану. Обещание готового материала стоит сессии ходов — она уходит искать
    файлы, которых на диске нет.

    Первый ход сессии на этом шаге говорит ровно то же (`MATERIAL_LATER` в
    hf_agent.py), и задание не вправе утверждать обратное.
    """
    early = _text(tmp_path / "early", phrases=GAP_PHRASES, clips=[],
                  avatar_ordered=False)
    assert "Материал (лежит в `public/`)" not in early, (
        "до заказа задание объявляет материал лежащим на диске")
    section = early.split("## Материал")[1].split("\n## ")[0]
    assert "пока пуста" in section, "не сказано, что `public/` пуста"
    assert "по списку фраз выше" in section, (
        "не сказано, по чему планировать, раз материала нет")
    assert "После заказа" in section, (
        "не сказано, когда материал появится и по чьему решению")


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
    text = _skill(tmp_path)
    for position in ("full", "punch", "pip-tr", "stack", "none"):
        assert f"`{position}`" in text
    # `split` снят: лицо ведущей в нижней половине попадает в полосу титра
    assert "`split`" not in text


def test_уголок_держится_вставкой_или_схемой(tmp_path):
    """Правило, которого агент не знал: допустимые положения выбирает не вкус,
    а то, что он кладёт в ту же сцену (`positions_for`, hf_montage.py:323). На
    проде он получил отказ D14 и поставил s-06 `pip-tl` при `insert: null` —
    сборка встала на `D20_frame_filled`. Названо и следствие: запрет читается
    вкусовым советом, а чёрный кадр — цена, которую видно."""
    text = _skill(tmp_path)
    assert "уголок без них оставляет остальной кадр чёрным" in text
    assert "нет ни вставки, ни схемы, ставь `full` или `punch`" in text
    assert "D20_frame_filled" in text
    # Схема держит верхнюю треть, и с ней остаются только нижние уголки.
    assert "со схемой годятся только нижние уголки" in text


def test_главная_ошибка_не_зовёт_уголок_туда_где_кадр_пуст(tmp_path):
    """Прежде «Главная ошибка» велела ставить уголок «везде, где ведущая в
    кадре есть» — то есть и на сцене без вставки, где остальной кадр выходит
    чёрным. Своя половина правила осталась: не прятать оплаченную ведущую."""
    text = _text(tmp_path, phrases=GAP_PHRASES)
    блок = text.split("## Главная ошибка")[1].split("\n## ")[0]
    # Переносы строк в блоке произвольные — сравниваем по словам.
    блок = " ".join(блок.split())
    assert "везде, где ведущая в кадре есть" not in блок
    assert "Сцене со вставкой ставь ведущую уголком" in блок
    assert "нет ни вставки, ни схемы, остаётся полный кадр" in блок


# ---------- границы ----------

def test_правила_числами(tmp_path):
    text = _text(tmp_path)
    assert "1080" in text and "1920" in text
    assert "41.5" in text or "41,5" in text


def test_гарнитуры_наши(tmp_path):
    """Гарнитуры держим сами: другие не несут кириллицу и казахские буквы."""
    assert FONTS in _text(tmp_path)


def test_вёрстку_у_агента_не_просят(tmp_path):
    """Изготовление ушло коду целиком: разметки в ответе агента больше нет.

    Круг 5: граница ответственности стала разделом со списком, и у каждой
    строки своя причина — форма их `## You do NOT decide`
    (hyperframes-core/references/frame-worker-core.md:33-43). Прежде это была
    одна фраза без причин.
    """
    text = _text(tmp_path)
    assert "public/cards/" not in text
    assert "data-anim" not in text
    assert "## Что решаешь не ты" in text
    assert "**Геометрия кадра и разметка**" in text


def test_интервалы_без_ведущей_названы(tmp_path):
    """Клип только на 0–12.22, значит на 12.22–41.5 ведущей в кадре нет.

    Фразы теперь обязательны: разметку дыр код считает по ним, а не по одному
    расписанию клипов, и без списка фраз этот текст проверял пустое место —
    он проходил на абзаце, который печатался всегда (дефект 5).
    """
    text = _text(tmp_path, phrases=GAP_PHRASES)
    assert "без ведущей" in text.lower() or "ведущей в кадре нет" in text.lower()
    for pid in (2, 3, 4):
        assert f"- фраза `{pid}`" in text, f"фраза {pid} не названа дырой"


def test_причина_повтора_попадает_в_задание(tmp_path):
    assert "лицо перекрыто" in _text(tmp_path, retry_reason="лицо перекрыто")


def test_пересдача_просит_положить_план_заново(tmp_path):
    """Дефект 7, половина в задании. `plan_with_agent` снимает
    `storyboard.json` перед КАЖДЫМ запуском агента (hf_agent.py), иначе файл
    прошлой попытки прошёл бы проверку как новый ответ. После этого «исправь
    именно это» указывает на файл, которого на диске нет, — агент уходит его
    искать. Дословная копия прошлого ответа лежит в `plan.json`, и раздел
    пересдачи называет её.

    Факт на диске один на оба шага (снимает и пишет один и тот же код),
    поэтому и текст один — ветки по `avatar_ordered` тут быть не должно.
    """
    for ordered in (True, False):
        text = _text(tmp_path / f"o{ordered}", phrases=GAP_PHRASES,
                     clips=CLIPS if ordered else [], avatar_ordered=ordered,
                     retry_reason="D28_avatar_bookends: FAIL: s-04 — финал")
        section = (text.split("# Задание на монтаж рилса")[1]
                   .split("## Порядок работы")[0])
        assert "D28_avatar_bookends" in section, "причина не доехала до агента"
        assert "`plan.json`" in section, (
            "не сказано, где лежит план, который не прошёл проверку")
        assert "storyboard.json" in section, (
            "не сказано, куда класть исправленный план")
        assert "снят" in section, (
            "не сказано, что прошлого `storyboard.json` на диске уже нет")
        assert "Исправь именно это" not in section, (
            "задание просит поправить файл, которого на диске нет")


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
    assert "avatarNeeded" not in _text(tmp_path)
    assert "avatarNeeded" in _text(tmp_path, avatar_ordered=False)


def test_запрос_вставки_объяснён_без_квоты(tmp_path):
    """Квоты «не меньше N вставок» больше нет: она загоняла агента в бироллы
    там, где они не нужны. Отрицательного правила взамен тоже нет — агент
    руководствуется положительным смыслом (решение Васи 09.08.2026)."""
    text = _skill(tmp_path)
    assert "не меньше чем в трёх сценах" not in text
    assert "`shots`" in text
    assert "ПО-АНГЛИЙСКИ" in text
    # `brollContext` — часть контракта ответа, он в задании.
    assert "brollContext" in _text(tmp_path)


def test_серия_из_двух_планов_объяснена(tmp_path):
    """Одиночных вставок больше не бывает: агент называет два плана, а сколько
    серий доживёт до кадра — считает код."""
    text = _skill(tmp_path)
    assert "серией из двух планов" in text
    assert "Назови не меньше" in text
    assert "`inserts_wanted`" in text
    assert "2,1 с лица" in text or "с лица" in text


def test_оплаченная_ведущая_обязана_быть_в_кадре(tmp_path):
    """Клипы куплены до плана, поэтому задание требует обратного прежнему:
    прятать ведущую на оплаченной секунде — выбрасывать деньги заказчика.
    Прежнего потолка 60 % в этом тексте остаться не должно, иначе агент читает
    два взаимоисключающих требования."""
    text = _skill(tmp_path)
    assert "клип куплен и оплачен" in text
    assert "зритель должен её увидеть" in text
    assert "не больше 60 %" not in text
    assert "65–70" not in text and "65-70" not in text


def test_до_заказа_аватара_бюджет_назван_секундами(tmp_path):
    """План до заказа (работа 9) считает деньги ровно наоборот: там сцена без
    ведущей её и не закажет, и бюджет аватарного времени осмыслен.

    Секунды остаются рабочей единицей: свои сцены агент меряет сложением
    длительностей фраз, и пересчёт процента во фразы — арифметика, на которой
    прогоны 9 и 10 ошибались. Круг 5 добавил рядом долю: решение заказчика про
    допуск сформулировано долями — ориентир одна, граница отказа другая, — и
    агент обязан видеть, что чисел два и значат они разное. Оба считает
    `avatar_budget_targets`, доля выводится из тех же секунд.
    """
    from reels_factory.avatar_islands import (
        avatar_budget_targets, avatar_islands_settings,
    )

    text = _text(tmp_path, avatar_ordered=False, phrases=GAP_PHRASES)
    section = _где_ведущей_нет(text)
    цель, граница = _цели(41.5)
    for имя, число in (("цель", цель), ("граница", граница)):
        named = [f"{число:.1f}", f"{число:.0f}",
                 f"{число:.1f}".replace(".", ",")]
        assert any(mark in section for mark in named), (
            f"{имя} по ведущей в секундах не названа, ждали одно из {named}")
    # Доли названы обе: ориентир по ролику и граница отказа. Обе выводятся из
    # тех же секунд, что вернул `avatar_budget_targets`.
    budget = avatar_budget_targets(41.5, avatar_islands_settings({}))
    for имя, число in (("ориентир", budget["ceiling_seconds"]),
                       ("граница", граница)):
        доля = f"{round(100 * число / 41.5)} %"
        assert доля in section, f"{имя} не назван долей хронометража ({доля})"
    assert "это главные деньги ролика" in section


def test_бюджет_ведущей_это_бюджет_заказа_а_не_показа(tmp_path):
    """Число меряется на ЗАКАЗЕ у HeyGen, а не на показе: внутри купленного
    куска платятся все секунды, даже спрятанные под непрозрачной вставкой
    (`AVATAR_ON_SCREEN_MAX`, hf_montage.py). Агент, прочитавший его как
    «сколько ведущей видно», начнёт экономить прятанием — а это уже оплаченные
    секунды.
    """
    text = _text(tmp_path, avatar_ordered=False, phrases=GAP_PHRASES)
    section = _где_ведущей_нет(text)
    потолок = _цели(41.5)[1]
    budget = _с_числом(section, (f"{потолок:.0f}", f"{потолок:.1f}",
                                 f"{потолок:.1f}".replace(".", ",")))
    assert budget, "бюджет не назван числом"
    assert any("заказ" in part for part in budget), (
        "рядом с бюджетом не сказано, что это бюджет заказа")
    assert any("avatarNeeded" in part for part in budget), (
        "не сказано, чем набирается бюджет — сценами с `avatarNeeded: true`")


def test_когда_аватар_остаётся_поверх_биролла(tmp_path):
    """Случаи названы явно: без них агент ставил уголок по вкусу."""
    text = _skill(tmp_path)
    assert "Сцена со вставкой — любой уголок (`pip-*`)" in text
    assert "обращается к зрителю" in text
    assert "предмет, который диктор называет" in text


def test_субтитры_снимаются_с_агента(tmp_path):
    text = _text(tmp_path)
    assert "**Субтитры**" in text
    assert "Изготовление за кодом" in text


def test_три_окна_ведущей_названы_как_решение_агента(tmp_path):
    """Три разных окна — то, что агент действительно выбирает полем
    `presenter`. Про саму проверку в задании не говорим: она меряет
    отрендеренный ролик, а положение сцены после агента переписывает код —
    обещать её исход он не может."""
    text = _skill(tmp_path)
    assert "в трёх разных окнах, не считая `none`" in text
    assert "не меньше трёх раз" not in text
    assert "Проверка считает по" not in text
    # Само задание доктрину не пересказывает — только ссылается.
    assert "в трёх разных окнах" not in _text(tmp_path)


def test_смену_картинки_даёт_граница_сцен(tmp_path):
    """Зазора между сценами больше нет: кадр из слоёв, сцены выстилают ролик,
    и две одинаковые подряд детектор видит одним планом. Формулировка —
    указанием, что делать: пару близнецов, которую создаёт уже сам код,
    разводит `dedupe_neighbours`, а не агент."""
    text = _skill(tmp_path)
    assert "Меняй картинку между соседними сценами" in text
    assert "обязаны отличаться" not in text
    assert "свободные фразы" not in text


def test_секунд_в_ответе_не_бывает_но_длину_сцены_считать_можно(tmp_path):
    """Прогоны 9 и 10: арифметика времени стоила по полчаса и всё равно с
    ошибкой — границы сцен считает код. Но длину сцены агенту знать нужно:
    накладка и серия требуют минимума секунд. Способ назван один раз —
    сложение длительностей фраз из списка; прежде задание требовало секунд и
    тут же запрещало их считать, не назвав ни одного способа.

    Требование сказано положительно, чем заменять секунды («Время в плане
    называй номерами фраз»), а не перечнем запрещённых полей: их канон —
    «Tell Claude what to do instead of what not to do». Строгость та же —
    образец по-прежнему обязан обойтись без секундных полей, а перечня
    запретов в тексте быть не должно.
    """
    text = _text(tmp_path)
    sample = text.split("```json")[1].split("```")[0]
    assert "startSec" not in sample and "endSec" not in sample
    assert '"phrases": [0, 0]' in sample
    assert "Время в плане называй номерами фраз" in text
    assert "границы сцен код считает сам по звуку" in text
    assert "сложением длительностей" in text
    for banned in ("Секунд в плане быть не должно", "Не считай секунды",
                   "ни `startSec`"):
        assert banned not in text, f"запрет вместо указания: {banned}"


def test_служебные_надписи_запрещены(tmp_path):
    """Раздел говорит, из чего кадр складывается, и уже отсюда — чего в нём не
    ставят: их же совет писать, что делать, а не чего не делать."""
    text = _skill(tmp_path)
    assert "## Что зритель читает" in text
    assert "фото из каталога" in text
    assert "Стоковые клише" in text


def test_биты_объяснены_и_кульминация_одна(tmp_path):
    text = _skill(tmp_path)
    assert "`climax`" in text
    assert "одна на ролик и не в первой сцене" in text
    assert "сцена-передышка" in text


def test_пол_сцен_дан_числом(tmp_path):
    """Пол только против дыр: ceil(41,5 / 8) = 6. Числовой планки смен в
    задании больше нет — темп задаёт пол сцены с ведущей, подставленный из
    `MIN_SCENE`, а не переписанный литералом рядом; наш детектор остаётся
    замером по готовому файлу."""
    text = _text(tmp_path)
    assert "меньше 6" in text
    assert "Сцена с ведущей живёт не короче" in _skill(tmp_path)
    assert "заметных смен" not in text


def test_лишняя_работа_названа_разделением_работы(tmp_path):
    """16 минут на план — это чтение справочников и попытки собрать самому.
    Список остался, но говорит, что уже сделано, а не чего нельзя: их дока
    прямо советует позитивную форму («Tell Claude what to do instead of what
    not to do», prompt-engineering/claude-prompting-best-practices)."""
    text = _text(tmp_path)
    # Раздел говорит, что уже сделано за агента, и почему это не его дело;
    # перечисления запретов («не пиши разметку») их дока не одобряет.
    assert "## Что решаешь не ты" in text
    assert "**Файл вставки**" in text and "судья" in text
    assert "## Что делает код после тебя" not in text
    for banned in ("не пиши", "не считай", "запрещено"):
        assert banned not in text.split("## Что решаешь не ты")[1].split(
            "\n## ")[0], f"запрет вместо указания: {banned}"


def test_правило_наполнения_кадра_живёт_в_одном_месте(tmp_path):
    """Разбор задания: правило про значок стояло в трёх местах в трёх
    редакциях. Средства кадра описаны одним разделом — иначе агент читает
    два разных требования и выбирает одно из них."""
    text = _skill(tmp_path)
    # Разделов «Чем занять кадр» два — схема и позиция каталога, — но каждое
    # средство описано ровно в своём: два раздела про одно и то же и есть
    # диагноз, от которого этот тест сторожит.
    assert text.count("## Чем занять кадр: схема") == 1
    assert text.count("## Чем занять кадр: позиция каталога") == 1
    assert text.count("## Чем занять кадр") == 2
    assert _text(tmp_path).count("## Чем занять кадр") == 0
    assert "## Медиа-проход" not in text
    assert "## Иконка фоновой сцены" not in text
    assert "## Их накладки из каталога" not in text


def test_выбор_между_бироллом_и_схемой_дан_признаками(tmp_path):
    """Их дока про классификацию: качество выбора прямо пропорционально
    качеству определений, а не количеству запретов; варианты — закрытым
    списком, и ровно один применим."""
    text = _skill(tmp_path)
    # Кто держит кадр — отдельный тест (`test_кадр_держат_те_же_средства_что_
    # считает_код`): держат его шестеро, и вставка со схемой лишь двое из них.
    assert "Кадр держит первое из этого" in text
    assert "когда мысль снимается камерой" in text
    assert "когда мысль камерой не снимается" in text
    assert "У сцены одна форма" in text
    assert "Форма идёт от типа высказывания" in text


def test_у_каждой_формы_названо_и_назначение_и_граница(tmp_path):
    """Канон описания инструмента: что делает, когда брать, **когда не
    брать** и чего не выражает — иначе форму применяют не по адресу.
    Проверено на нас: метрика с полосой прогресса стояла под «три вопроса»."""
    text = _skill(tmp_path)
    section = text.split("<forms>")[1].split("</forms>")[0]
    for form in ("metric", "items", "pairs", "steps", "brand"):
        assert f'<form name="{form}">' in section
    assert section.count("Бери") >= 5
    # Каждая форма называет и своё назначение, и поля, которыми задаётся.
    assert section.count("Поля:") >= 4
    assert "Счёт названных вещей" in section
    assert "три из ста" in section


def test_разбор_идёт_до_выбора_формы(tmp_path):
    """Их же приём из руководства по классификации: сначала рассуждение,
    потом метка. У нас рассуждение — строка `why` в самой схеме."""
    text = _skill(tmp_path)
    # Их дока для нынешнего поколения прямо не советует просить агента
    # излагать ход мысли в ответе; `why` остаётся данными — типом
    # высказывания, к которому отнесена сцена.
    assert "назови тип" in text and "высказывания" in text
    assert "Разбор идёт до выбора" not in text
    assert '"why"' in text


def test_спор_решается_названным_приоритетом(tmp_path):
    """Приём из их же руководства по классификации: когда подходят два
    признака, сказать вслух, какой весит больше, и почему."""
    text = _skill(tmp_path)
    assert "есть и чувство, и величина" in text
    assert "чувство уже звучит в голосе" in text


def test_формы_схемы_даны_закрытым_списком_с_примерами(tmp_path):
    """Их рекомендация — 3–5 примеров, разнородных, в `<example>`, и в каждом
    разбор выбора: не только взятая форма, но и отброшенная. Блок `<fillings>`
    снят — он показывал тот же синтаксис третьим заходом после `<forms>` и
    образца ответа."""
    text = _skill(tmp_path)
    assert "<fillings>" not in text
    for form in ("metric", "items", "pairs", "steps", "brand"):
        assert f'<form name="{form}">' in text
    # Раздел кончается там, где начинается следующий: примеры запаса (круг 6)
    # стоят ниже своим разделом и в эту вилку не входят.
    section = text.split("## Чем занять кадр: схема")[1].split("\n## ")[0]
    assert 3 <= section.count("<example>") <= 5
    # Разбор в примере называет и отброшенную форму: перенос на непохожую
    # реплику даёт именно он, а не сам ответ.
    assert "`metric` отпадает" in section
    assert "навязал бы порядок" in section
    # Синтаксис поля показан на примерах, а не отдельным блоком-каталогом.
    for form in ("items", "steps", "pairs", "metric"):
        assert f'"form": "{form}"' in section


def test_запасная_схема_той_же_формы(tmp_path):
    """Схему выбирает агент по смыслу; `fallback` — та же форма на случай,
    когда сток не ответил, а не отдельный вид."""
    text = _skill(tmp_path)
    assert "**`fallback` — та же схема на случай" in text
    # Область правила круг 6 снял с условия «где ведущей нет» и повесил на саму
    # вставку: исход заказа и сборки агент проверить не может, а сцены со
    # вставкой — может (`test_запас_требуется_у_каждой_сцены_со_вставкой`).
    assert "Живёт по тем же правилам, что и основная" in text


def test_позицию_каталога_ищут_по_смыслу_методом_фреймворка(tmp_path):
    """Закрытого списка приёмов больше нет: агент называет любую подходящую
    позицию, а ищет её так, как велит их же скилл реестра, — по смыслу, а не
    глазами по именам (`hyperframes-registry/SKILL.md:88`)."""
    text = _skill(tmp_path)
    assert "`catalog.index.md`" in text, "индекс каталога агенту не назван"
    assert "Search by intent before browsing" in text, (
        "правило поиска не названо словами фреймворка")
    assert "`catalog-map.md`" in text and "`CATALOG.md`" in text, (
        "справочники фреймворка агенту не названы")
    assert "пиши дословно из найденной строки" in text
    assert "не больше, чем слотов" in text
    # Зону агент не называет: её считает код из вида позиции, положения
    # ведущей и полосы титра.
    assert "Зону не называй" in text


def test_индекс_каталога_лежит_отдельным_файлом(tmp_path):
    """Ссылка одна и ведёт из задания прямо в файл: глубже одного уровня их же
    дока ходить не советует. Сами позиции в задание не переписываются."""
    _text(tmp_path)
    index = (tmp_path / "catalog.index.md").read_text(encoding="utf-8")
    assert "```json" in index, "индекс не в формате `catalog --json`"
    assert '"name"' in index and '"description"' in index
    # Справочники фреймворка едут рядом как есть.
    assert (tmp_path / "CATALOG.md").exists()
    assert (tmp_path / "catalog-map.md").exists()
    # В самом задании остаётся ссылка, а не список позиций.
    brief = (tmp_path / "BRIEF.md").read_text(encoding="utf-8")
    assert "catalog.index.md" in brief
    assert '"tags"' not in brief


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
    # Бюджет ведущей называется и секундами, и долей хронометража — проверка
    # живёт в `test_до_заказа_аватара_бюджет_назван_секундами`.
    assert "ведущей тут нет" not in text


def test_схема_не_берёт_чужую_реплику_и_не_повторяет_титр(tmp_path):
    """Обе находки веера из шести сценариев: агент дорисовывал перечисление
    указателю («Первый: кому продаём»), взяв пункты из следующей фразы, и
    ставил на карточку два слова подряд из самой реплики — титр печатает их в
    тот же момент. Правило их же: «never a sentence from the narration… the
    root caption track already shows the spoken words»."""
    text = _skill(tmp_path)
    assert "Объявлен набор целиком" in text
    assert "Названа одна позиция" in text
    assert "Слова схемы говорят своё" in text
    # «Проверь каждую подпись» снято: их дока велит убирать инструкции
    # самопроверки, а не переписывать их.
    assert "Проверь каждую" not in text
    assert "Живёт по тем же правилам" in text


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


def test_образец_плана_проходит_наши_же_проверки(tmp_path):
    """Образец сильнее правила, стоящего рядом с ним, поэтому он собирается из
    фраз этого ролика и обязан проходить те же гейты, что мы требуем от агента.
    Прежний образец был написан руками: сцен меньше минимума, ни одного
    `climax`, две последние сцены с одинаковым кадром и плашка со слотом,
    которого нет в её паспорте."""
    import json

    from reels_factory.hf_compose import complete_storyboard
    from reels_factory.hf_gates import check_montage, check_storyboard
    from reels_factory.hf_phrases import lay_out_scenes

    phrases = [{"id": index, "role": "hook", "text": f"фраза {index}",
                "start": index * 2.0, "end": index * 2.0 + 2.0}
               for index in range(8)]
    clips = [{"file": "clips/clip-00.mp4", "start": 0.0, "duration": 16.0}]
    text = _text(tmp_path, phrases=phrases, clips=clips)
    sample = text.split("```json")[1].split("```")[0]
    # Хвост образца подписан многоточием — для проверки берём показанные сцены
    # и дотягиваем последнюю до конца озвучки.
    body = "\n".join(line for line in sample.splitlines()
                     if "остальные сцены" not in line)
    body = body.rstrip().rstrip("}").rstrip().rstrip("]").rstrip().rstrip(",")
    board = json.loads(body + "\n ]\n}")
    shown = board["scenes"]
    shown[-1]["phrases"] = [shown[-1]["phrases"][0], 7]

    board["scenes"] = lay_out_scenes(shown, phrases, duration=16.0)
    board = complete_storyboard(board, clips=clips, duration=16.0)
    verdicts = check_storyboard(board, clips=clips, duration=16.0)
    verdicts.update(check_montage(board, clips=clips, duration=16.0))
    failed = [f"{name}: {value}" for name, value in verdicts.items()
              if value.startswith("FAIL")]
    assert not failed, failed


def test_правило_не_живёт_в_двух_местах(tmp_path):
    """Одно правило — одно место. Их канон: «Choose one term and use it
    throughout the Skill» и «the minimal set of information that fully outlines
    your expected behavior». Разбор задания находил по четыре редакции одного и
    того же — «верни два файла», «разметку не пиши», «сложи длительности».

    Проверяем механически: ключевые темы не должны встречаться и в задании, и
    в скиле, а внутри каждого файла — дважды.
    """
    brief = _text(tmp_path)
    skill = _skill(tmp_path)
    # (тема, где ей место, как её узнать)
    topics = [
        ("контракт ответа", brief, skill, "storyboard.json` и `frame.md`"),
        ("серия из двух планов", skill, brief, "серией из двух планов"),
        ("формы схемы", skill, brief, "<forms>"),
        ("положения ведущей", skill, brief, "Выбор положения:"),
        ("биты рассказа", skill, brief, "`hook` — первая сцена"),
    ]
    for name, home, foreign, mark in topics:
        assert mark in home, f"{name}: правило пропало из своего файла"
        assert mark not in foreign, f"{name}: правило сказано дважды"


def test_в_задании_нет_требований_к_чужому_результату(tmp_path):
    """Требовать от агента исход, который после него правит код, — источник
    провала 462a1c62. Пять функций переписывают `presenter`, пару близнецов
    разводит `dedupe_neighbours`, вставки снимает `pick_series`."""
    text = _text(tmp_path) + _skill(tmp_path)
    for banned in ("Проверка считает", "проверка заворачивает",
                   "сборка не пройдёт проверку", "детектор их не разделит",
                   "каждое роняет сборку"):
        assert banned not in text, f"обещание за код: {banned}"


# ---------- план до заказа аватара (работа 9) ----------

def test_минимальный_кусок_заказа_назван_числом_из_кода(tmp_path):
    """Кусок короче `min_request_seconds` код не отбрасывает, а дорастает за
    счёт соседнего звука и платит за него, — в ролик доплаченное не попадает
    (`_request_timing`, avatar_islands.py). Агент про это правило не знает
    ниоткуда: острова считаются после него. Число берётся из кода, чтобы текст
    не разошёлся с `DEFAULTS`, а вывод для агента сказан прямо — сцены с
    ведущей ставить подряд (работа B).
    """
    text = _text(tmp_path, avatar_ordered=False, phrases=GAP_PHRASES)
    section = _где_ведущей_нет(text)
    least = float(ISLAND_DEFAULTS["min_request_seconds"])
    named = _с_числом(section, (f"{least:g} с", f"{least:.1f} с",
                                f"{least:.1f} с".replace(".", ",")))
    assert named, f"минимальный кусок заказа ({least:g} с) агенту не назван"
    assert any("заказ" in part for part in named), (
        "число стоит без своего имени: не сказано, что это минимум заказа")
    assert "подряд" in section, (
        "не сказано главного вывода — сцены с ведущей ставить подряд")


def test_сцены_без_ведущей_требуют_запасную_схему(tmp_path):
    """Дефект 3. До работы 9 ветка «аватар не заказан» про `fallback` молчала:
    считалось, что пустой кадр всегда закроет ведущая. После работы 9 закрывать
    его нечем — на сцене с `avatarNeeded: false` ведущей не существует, и гейт
    D25 (`_empty_frame_problems`) заворачивает такой план.
    """
    text = _text(tmp_path, avatar_ordered=False, phrases=GAP_PHRASES)
    section = _где_ведущей_нет(text)
    assert "`fallback`" in section, (
        "у сцен без ведущей не потребована запасная схема")
    assert "сток" in section, (
        "не названа причина: сток отвечает не всегда, а закрыть кадр нечем")


def test_образец_плана_показывает_avatarNeeded_в_обоих_значениях(tmp_path):
    """Дефект 4. Образец сильнее правила, стоящего рядом с ним: поле, которое
    в нём не показано, агент не заполняет. Заказ островов читает ровно его,
    поэтому образец обязан показать и `true`, и `false` — и краевой случай
    целиком: сцена без ведущей стоит с `presenter: "none"` и своим `fallback`.
    """
    text = _text(tmp_path, avatar_ordered=False, phrases=EVEN_PHRASES,
                 clips=[])
    scenes = _board(text)["scenes"]
    missing = [scene["id"] for scene in scenes if "avatarNeeded" not in scene]
    assert not missing, f"сцены образца без `avatarNeeded`: {missing}"
    assert {scene["avatarNeeded"] for scene in scenes} == {True, False}, (
        "образец показывает только одно значение `avatarNeeded`")
    blind = [scene for scene in scenes if not scene["avatarNeeded"]]
    for scene in blind:
        assert scene["presenter"] == "none", (
            f'{scene["id"]}: ведущей не заказано, а `presenter` не `none`')
        assert scene.get("fallback"), (
            f'{scene["id"]}: сцена без ведущей показана без `fallback`')


def _длина_сцены(scene: dict, phrases: list[dict]) -> float:
    """Длина сцены образца — сумма длительностей её фраз.

    Ровно этим меряет сцену без ведущей гейт до заказа (D31, hf_render.py)
    после того, как соседние окна такой сцены склеиваются
    (`apply_agent_coverage`).
    """
    first, last = scene["phrases"][0], scene["phrases"][-1]
    return sum(float(p["end"]) - float(p["start"]) for p in phrases
               if first <= p["id"] <= last)


def test_образец_отдаёт_отказ_сцене_которая_набирает_пол(tmp_path):
    """Круг 4, дефект 4. Сцену под `avatarNeeded: false` образец выбирал по
    номеру — серединой показанных, — и на длительности не смотрел вовсе. На
    быстрой речи это печатало сцену, которую гейт до заказа заворачивает, а
    образец сильнее правила, стоящего рядом с ним.

    Смотрим на два материала: быструю речь (фразы по 2,4 с — пара таких фраз
    пол проходит) и речь, где короткие фразы стоят ровно в середине показанных
    сцен, а длинные раньше.
    """
    for name, phrases in (("fast", FAST_PHRASES), ("uneven", UNEVEN_PHRASES)):
        scenes = _board(_text(tmp_path / name, phrases=phrases, clips=[],
                              avatar_ordered=False))["scenes"]
        отказы = [scene for scene in scenes
                  if scene.get("avatarNeeded") is False]
        assert отказы, f"{name}: образец не показывает отказа от ведущей"
        for scene in отказы:
            длина = _длина_сцены(scene, phrases)
            assert длина >= MIN_FULLSCREEN_S, (
                f'{name}: образец отдаёт под отказ сцену {scene["id"]} длиной '
                f"{длина:g} с — короче минимума сцены без ведущей "
                f"({MIN_FULLSCREEN_S:g} с)")


def test_образец_молчит_про_отказ_когда_отдать_его_некому(tmp_path):
    """Круг 4, дефект 4, вторая половина. Когда ни одна сцена образца пола не
    набирает, отказ в нём не показывается вовсе: образец, который учит плану,
    заворачиваемому гейтом, дороже отсутствующего примера. Рядом с образцом
    сказано, почему его там нет и по какому признаку выбирать сцену под отказ
    самому.
    """
    text = _text(tmp_path / "tiny", phrases=TINY_PHRASES, clips=[],
                 avatar_ordered=False)
    scenes = _board(text)["scenes"]
    assert all(scene.get("avatarNeeded") is True for scene in scenes), (
        "фразы короче половины пола, а образец всё равно показывает отказ")
    оговорка = [" ".join(part.split())
                for part in _абзацы(text, "avatarNeeded: true`, и отказа")]
    assert оговорка, "образец молчит про отказ и не объясняет, почему"
    assert any("минимум сцены без ведущей" in part for part in оговорка), (
        "не названо, чем сцена под отказ отличается от прочих")
    assert any("суммой её фраз" in part or "целиком" in part
               for part in оговорка), (
        "не сказано, чем меряется минимум сцены без ведущей")
    assert any("собирай под отказ" in part for part in оговорка), (
        "не сказано, что делать вместо этого — собирать короткие фразы в одну "
        "сцену")

    с_отказом = _text(tmp_path / "fast", phrases=FAST_PHRASES, clips=[],
                      avatar_ordered=False)
    assert not _абзацы(с_отказом, "avatarNeeded: true`, и отказа"), (
        "оговорка печатается и тогда, когда отказ в образце показан")


def test_пометка_без_ведущей_только_в_ветке_с_заказом(tmp_path):
    """Дефект 5. Абзац «Фразы с пометкой „без ведущей“ держи в отдельных
    сценах» печатался всегда, а сама пометка ставится в `_phrase_line` только
    для дыр между островами. До заказа аватара дыр нет по построению — абзац
    описывает разметку, которой в списке фраз нет, и агент ищет её впустую.
    """
    ordered = _text(tmp_path / "ordered", phrases=GAP_PHRASES)
    assert "ведущей тут нет" in ordered, "пометка на фразах пропала"
    assert "с пометкой" in ordered, (
        "в ветке с заказанным аватаром правило про пометку обязано остаться")

    early = _text(tmp_path / "early", phrases=GAP_PHRASES,
                  avatar_ordered=False)
    assert "с пометкой" not in early, (
        "до заказа аватара задание ссылается на несуществующую пометку")

    whole = _text(tmp_path / "whole", phrases=GAP_PHRASES, clips=FULL_CLIPS)
    assert "с пометкой" not in whole, (
        "ведущая в кадре весь ролик, а правило про пометку всё ещё печатается")


def test_свод_правил_до_заказа_не_объявляет_клипы_купленными(tmp_path):
    """Дефект 6. «Ведущая уже снята… её клип куплен и оплачен заказчиком» —
    после работы 9 это ложь и прямой запрет на `avatarNeeded: false`: агент
    обобщает именно объяснение. До заказа клипов ещё нет, и `none` ставится не
    по пометке в задании, а по решению самого агента.
    """
    early = _skill(tmp_path / "early", avatar_ordered=False,
                   phrases=GAP_PHRASES)
    # Запрещено само утверждение, а не слово: «эти секунды не будут оплачены»
    # — законная причина ставить `avatarNeeded: false`.
    for lie in ("клип куплен", "оплачен заказчиком", "уже снята"):
        assert lie not in early, f"до заказа сказано неправду: «{lie}»"
    assert "avatarNeeded" in early, (
        "доктрина не называет поле, которым агент отказывается от ведущей")
    assert "`avatarNeeded: false`" in early, (
        "не сказано прямо, что отказаться от ведущей можно")
    assert "помеченных в задании" not in early, (
        "`none` привязан к пометке, которой до заказа нет")

    ordered = _skill(tmp_path / "ordered", phrases=GAP_PHRASES)
    assert "клип куплен" in ordered, (
        "после заказа правило обратное и должно остаться")


# ---------- финал ролика и числа проверок ----------

def test_финал_ролика_назван_сценой_а_не_секундами(tmp_path):
    """Работа C. Про открытие правило есть, про финал не было: ролик кончался
    вставкой, и лицо зрителя не провожало. Секундами это правило агенту не
    сформулировать — секунд в его плане нет, есть сцены и номера фраз.
    """
    text = _skill(tmp_path)
    assert "Открывай ролик ведущей во весь кадр" in text, (
        "правило про открытие пропало")
    assert "последняя сцена" in text, "правила про финал нет"
    item = _абзац(text, text.index("последняя сцена"))
    assert "`full`" in item and "`punch`" in item, (
        "финал не назван положениями ведущей во весь кадр")
    named_in_seconds = re.search(r"\d[\d,.]*\s*(с\b|секунд)", item)
    assert not named_in_seconds, (
        f"финал назван секундами («{item.strip()}»), которых у агента нет")


def test_числа_проверки_плана_названы_в_своде_правил(tmp_path):
    """Дефект 13. `MIN_FULLSCREEN_S` и `MAX_FACE_ABSENCE_S` (editplan.py) судят
    план агента, а самому агенту не названы нигде: он узнаёт о них отказом.
    Числа подставляются из кода — как уже сделано с `face_gap` и `max_static`.
    """
    text = _skill(tmp_path)
    точно = f"{MAX_FACE_ABSENCE_S:.1f} с"
    absence = _с_числом(text, (f"{MAX_FACE_ABSENCE_S:g} с", точно,
                               точно.replace(".", ",")))
    assert absence, f"предел без лица ({MAX_FACE_ABSENCE_S:g} с) не назван"
    assert any("лиц" in part.lower() or "ведущ" in part.lower()
               for part in absence), "число стоит без своего имени"

    assert _минимум_без_ведущей(text), (
        f"минимум сцены без ведущей ({MIN_FULLSCREEN_S:g} с) не назван")


def test_минимум_трёх_секунд_меряется_на_сцене_без_ведущей(tmp_path):
    """Ломает прод 1. `MIN_FULLSCREEN_S` судит окно, где ведущей НЕТ
    (`coverage in {full_broll, hyperframes}`, editplan.py:2543), а свод правил
    называл им минимум сцены с `full` или `punch`. Рядом стояло «обычная сцена
    живёт 1,5–4 с», и агент штатно отдавал вставке сцену в 2 с — окно без
    ведущей выходило короче минимума, и `build_avatar_render_plan` падал
    ValueError на всей сборке.

    Проверяем обе стороны: правило стоит у сцены без ведущей и не стоит у
    полнокадровой. Чем именно меряется минимум — сценой или каждой её фразой —
    судит `test_порог_без_ведущей_меряется_каждой_фразой`: пофразно его меряет
    только ранний шаг, где по плану и заказывают.
    """
    for kw in ({}, {"avatar_ordered": False, "phrases": GAP_PHRASES}):
        text = _skill(tmp_path / f"skill{len(kw)}", **kw)
        item = _минимум_без_ведущей(text)
        assert item, "минимум сцены без ведущей не назван"
        assert any("собери" in part or "собирай" in part for part in item), (
            "не сказано, что делать с фразами, из которых выходит сцена "
            "короче минимума")
        обратное = [part for part in _с_числом(text, THREE_SECONDS)
                    if "полнокадров" in part.lower()
                    or "`full` или `punch`" in part]
        assert not обратное, (
            f"минимум трёх секунд снова приписан ведущей: {обратное}")


def test_порог_без_ведущей_меряется_сценой_целиком(tmp_path):
    """Круг 4, дефект 2. Соседние окна, которые лишил ведущей сам агент, код
    теперь склеивает в одно (`apply_agent_coverage`), и порог `MIN_FULLSCREEN_S`
    меряет сцену — сумму длительностей её фраз, а не каждую фразу порознь. Тем
    же меряет и гейт до заказа (D31, hf_render.py), и правило обязано говорить
    то же самое.

    Прежний текст требовал обратного — «меряется это каждой её фразой». На
    быстрой речи (фразы около 2,4 с) такое требование не оставляет ни одного
    проходящего плана: сплошной перебор круга 3 принял единственный — ведущая
    весь ролик.

    В ветке с заказанным аватаром склейки нет: там окна навязаны материалом, а
    общий путь `editplan` не менялся ни поведением, ни числами.
    """
    early = _skill(tmp_path / "early", avatar_ordered=False,
                   phrases=FAST_PHRASES)
    правило = _минимум_без_ведущей(early)
    assert правило, "минимум сцены без ведущей не назван"
    assert all("целиком" in part or "сложением" in part for part in правило), (
        f"не сказано, что порог меряется сценой целиком: {правило}")
    пофразно = [part for part in правило
                if re.search(r"кажд\w+ (её )?фраз", part)]
    assert not пофразно, (
        f"порог всё ещё меряется каждой фразой: {пофразно}")
    assert any("собирай" in part or "собери" in part for part in правило), (
        "не сказано, что делать с короткими фразами — собирать их в одну сцену")

    примеры = early.split("<examples>")[1].split("</examples>")[0]
    склейка = [line for line in примеры.splitlines()
               if "avatarNeeded: false" in line
               and ("собери" in line or "собирай" in line)]
    assert склейка, (
        "краевой случай не показан примером: две короткие соседние фразы "
        "собираются в одну сцену без ведущей")


def test_три_разных_числа_три_секунды_названы_каждое_своим_именем(tmp_path):
    """Дефект 8. Три несвязанных величины по 3.0 с — пол схемы `items`
    (hf_schema.py), минимальный кусок заказа ведущей (avatar_islands.py) и
    минимум сцены без ведущей (editplan.py) — читаются как одно правило.
    У каждой в тексте своё имя, и ни одна не написана литералом.
    """
    brief = _text(tmp_path, avatar_ordered=False, phrases=GAP_PHRASES)
    skill = _skill(tmp_path)

    order = [part for part in _с_числом(brief, THREE_SECONDS)
             if "заказ" in part]
    assert order, "минимальный кусок заказа не назван своим именем"

    floors = [part for part in _с_числом(skill, THREE_SECONDS)
              if "`items`" in part]
    assert floors, "пол схемы `items` не назван своим именем"

    blind = _минимум_без_ведущей(skill)
    assert blind, "минимум сцены без ведущей не назван своим именем"
    assert set(floors).isdisjoint(blind), (
        "пол схемы и минимум сцены без ведущей стоят одним абзацем и "
        "читаются одним правилом")


def test_бюджет_и_финал_живут_каждый_в_своём_файле(tmp_path):
    """Одно правило — одно место (проверка выше делает это для прежних тем).
    Бюджет ведущей — данные этого ролика, его место в задании; правило про
    финал — доктрина, её место в скиле.
    """
    brief = _text(tmp_path, avatar_ordered=False, phrases=GAP_PHRASES)
    skill = _skill(tmp_path, avatar_ordered=False, phrases=GAP_PHRASES)
    assert "последняя сцена" not in brief, (
        "правило про финал сказано и в задании, и в скиле")
    assert "avatarNeeded" in brief
    потолок = _цели(41.5)[1]
    for mark in (f"{потолок:.0f} с", f"{потолок:.1f} с"):
        assert mark not in skill, (
            "бюджет этого ролика попал в доктрину, общую для всех роликов")


# ---------- круг ревизии: дефекты, найденные на собранных текстах ----------

def _где_ведущей_нет(text: str) -> str:
    """Секция про ведущую целиком.

    До заказа она называется бюджетом — решение о ведущей там и принимается, а
    после заказа дыры между островами навязаны материалом, и заголовок остаётся
    прежним.
    """
    for title in ("## Бюджет ведущей", "## Где ведущей нет"):
        if title in text:
            return text.split(title)[1].split("\n## ")[0]
    raise AssertionError("секции про ведущую в задании нет")


def _куски(duration: float) -> int:
    """Сколько кусков заказа выйдет в ролике такой длины.

    Число навязано нашим же правилом «лицо не пропадает дольше
    `MAX_FACE_ABSENCE_S` подряд»: между сценами без ведущей обязана стоять
    сцена с ведущей, и остров режется на столько кусков, сколько таких
    промежутков помещается в ролик, плюс один.
    """
    return math.ceil(duration / MAX_FACE_ABSENCE_S) + 1


def test_цель_по_ведущей_ниже_ориентира_на_ручки_заказа(tmp_path):
    """Ломает прод 3. Названная агенту цель равнялась линии отказа: гейт судит
    секунды ПОСТРОЕННОГО ЗАКАЗА (`order_facts`, hf_render.py), а к заказу код
    прикладывает `handle_seconds` с каждого края каждого куска. Агент,
    сложивший длительности фраз ровно до линии, промахивался на эти ручки.

    Круг 3, дефект 3(а): ручки считались по трём кускам, а гейт считает их по
    фактическому числу. На пяти-шести островах — а столько их навязывает наше
    же правило про десять секунд без лица — агент, уложившийся в названную
    цель, получал FAIL и жёг пересдачу.
    """
    section = _где_ведущей_нет(
        _text(tmp_path, avatar_ordered=False, phrases=GAP_PHRASES))
    target, hard = _цели(41.5)
    цель, граница = _секунды(target), _секунды(hard)
    assert цель != граница, "тест бессмыслен: цель совпала с границей"

    цели = [part for part in _абзацы(section, цель) if "цел" in part.lower()]
    assert цели, f"цель по ведущей ({цель}) не названа"
    assert any("складывай длительности фраз" in part for part in цели), (
        "не сказано, чем набирать цель — длительностями фраз своих сцен")
    assert any("ручек" in part or "ручки" in part for part in цели), (
        "не сказано, почему цель ниже ориентира по ролику")

    границы = [part for part in _абзацы(section, граница)
               if "граница" in part.lower()]
    assert границы, f"граница заказа ({граница}) не названа отдельным числом"
    assert any("заказ" in part for part in границы), (
        "не сказано, что граница меряется на заказе")


def test_кусок_длиннее_предела_режет_код_а_не_агент(tmp_path):
    """Ломает прод 3, вторая половина. Длинный остров код режет на несколько
    заказов (`max_shot_seconds`, avatar_islands.py), и каждый кусок добирает
    свою пару ручек. Агент, который об этом не знает, читает «один длинный
    кусок дешевле трёх коротких» как обещание одной пары ручек на весь ролик.
    """
    section = _где_ведущей_нет(
        _text(tmp_path, avatar_ordered=False, phrases=GAP_PHRASES))
    предел = f'{float(ISLAND_DEFAULTS["max_shot_seconds"]):g} с'
    названо = [part for part in _абзацы(section, предел) if "реж" in part]
    assert названо, f"не сказано, что кусок длиннее {предел} код режет сам"


def test_контракт_поля_avatarNeeded_объявлен(tmp_path):
    """Круг 4, дефект 3. Прежний текст обещал: «Сцену без этого поля код
    считает заказанной». Обещание неверно — гейты такую сцену и правда считали
    заказанной, а `apply_agent_coverage` её не трогал вовсе, и
    `build_avatar_render_plan` падал «лицо отсутствует дольше 10 с» уже после
    оплаты. Полноту решений судит отдельный гейт до заказа
    (`D33_avatar_decisions`), поэтому задание требует поле у каждой сцены и
    называет цену пропуска — пересдачу.
    """
    section = _где_ведущей_нет(
        _text(tmp_path, avatar_ordered=False, phrases=GAP_PHRASES))
    assert "каждой сцене" in section, (
        "не сказано, что поле ставится каждой сцене")
    assert "без этого поля код считает заказанной" not in section, (
        "задание всё ещё обещает, что сцена без поля идёт с ведущей")
    пересдача = [part for part in _абзацы(section, "avatarNeeded")
                 if "пересдач" in part]
    assert пересдача, (
        "не сказано, чем оборачивается сцена без поля — пересдачей плана")
    assert any("платит заказчик" in part or "платит заказчику" in part
               or "платит" in part for part in пересдача), (
        "не названа причина, по которой поле обязательно, — это деньги")


def test_запасная_схема_нужна_там_где_кадр_держит_вставка(tmp_path):
    """Жжёт ходы 8. Задание требовало `fallback` у каждой сцены без ведущей, а
    свод правил — только у сцены со вставкой. У сцены со схемой запасная
    бессмысленна: схему рисует код, и она в кадре уже стоит.
    """
    for name, kw in (("ordered", {"clips": CLIPS, "phrases": GAP_PHRASES}),
                     ("early", {"avatar_ordered": False,
                                "phrases": GAP_PHRASES})):
        section = _где_ведущей_нет(_text(tmp_path / name, **kw))
        assert "вставка" in section and "`fallback`" in section
        assert "У каждой сцены с `insert`" in section, (
            f"{name}: запас потребован без привязки к самой вставке")
        assert "Сцене со схемой запасная не нужна" in section, (
            f"{name}: не сказано, что сцене со схемой `fallback` не нужен")
        assert "у каждой такой сцены заполни `fallback`" not in section


def test_форма_запасной_схемы_выбирается_по_длине_сцены(tmp_path):
    """Канон 14. Совет назвать моменты под вставку с запасом после работы 9
    неполон: на сцене без ведущей снятая серия оставляет кадр на `fallback`, и
    форма, которой не хватило пола, снимается тоже — кадр пустеет, и это ловит
    D25 (`_empty_frame_problems`).
    """
    text = _skill(tmp_path)
    assert "Назови не меньше" in text, "совет про моменты под вставку пропал"
    assert "снятая серия оставляет кадр на `fallback`" in text, (
        "не сказано, что при снятой серии кадр остаётся на запасной схеме")
    assert "выбирай по длине этой сцены" in text, (
        "не сказано, чем выбирать форму запасной схемы")


def test_решение_про_ведущую_показано_примерами(tmp_path):
    """Канон 11. На выбор уголка в своде правил четыре примера, а на
    `avatarNeeded: false` — решение, которое после работы 9 стоит денег, — не
    было ни одного. Их канон требует примеров и на краевые случаи.
    """
    early = _skill(tmp_path / "early", avatar_ordered=False,
                   phrases=GAP_PHRASES)
    block = early.split("<examples>")[1].split("</examples>")[0]
    lines = block.splitlines()
    отказы = [line for line in lines if "avatarNeeded: false" in line]
    assert отказы, "примера на отказ от ведущей нет"
    assert [line for line in lines if "avatarNeeded: true" in line], (
        "примера на обязательную ведущую нет")
    # Краевой случай — фраза короче порога сцены без ведущей. После склейки
    # соседних окон (круг 4, дефект 1) выходов из него два, и оба стоят
    # примером: две короткие соседние фразы собираются в одну сцену без
    # ведущей, а короткая фраза, оставшаяся в сцене одна, идёт с ведущей.
    короткие = [line for line in lines
                if "короч" in line and any(mark in line
                                           for mark in THREE_SECONDS)]
    assert короткие, "краевой случай — фраза короче порога — примером не показан"
    assert [line for line in короткие
            if "avatarNeeded: false" in line
            and ("собери" in line or "собирай" in line)], (
        f"нет примера на склейку двух коротких фраз в сцену без ведущей: "
        f"{короткие}")
    assert [line for line in короткие if "avatarNeeded: true" in line], (
        f"нет примера на короткую фразу, оставшуюся в сцене одну: {короткие}")

    ordered = _skill(tmp_path / "ordered", phrases=GAP_PHRASES)
    assert "avatarNeeded" not in ordered.split("<examples>")[1], (
        "после заказа аватара примеры зовут решать поле, которого нет")


def test_образец_плана_помечен_примером(tmp_path):
    """Канон 11. Образец — пример, и их канон держит примеры в `<example>`:
    так видна граница между «вот форма ответа» и «вот твой ответ».
    """
    text = _text(tmp_path, phrases=EVEN_PHRASES)
    голова = text.split("```json")[0]
    assert голова.rstrip().endswith("<example>"), (
        "образец плана стоит вне `<example>`")
    assert "</example>" in text.split("```json")[1]


def test_хвост_образца_печатается_только_когда_есть_что_дописывать(tmp_path):
    """Жжёт ходы 6. «остальные сцены до фразы N тем же порядком» печаталось и
    тогда, когда образец дошёл до последней фразы сам, — агент дописывал сцены
    на фразы, уже накрытые выше.
    """
    целиком = _text(tmp_path / "whole", phrases=GAP_PHRASES, clips=[],
                    avatar_ordered=False)
    assert "остальные сцены" not in целиком, (
        "образец покрыл все фразы, а хвост всё равно обещает продолжение")
    json.loads(целиком.split("```json")[1].split("```")[0])

    # Фраз берём столько, чтобы групп вышло больше, чем образец показывает
    # даже растянутым под бюджет (`SAMPLE_MAX_SCENES`): по две фразы на сцену
    # это больше двенадцати.
    длинный = [{"id": index, "role": "hook", "text": f"фраза {index}",
                "start": index * 2.0, "end": index * 2.0 + 2.0}
               for index in range(20)]
    кусок = _text(tmp_path / "part", phrases=длинный, clips=[],
                  avatar_ordered=False)
    assert "остальные сцены до фразы 19" in кусок, (
        "образец обрывается молча, и агент не знает про остальные сцены")


def test_образец_не_спорит_с_числом_сцен(tmp_path):
    """Жжёт ходы 6, вторая половина. Образец из четырёх сцен стоял рядом с
    «сцен не меньше 6», и образец сильнее правила: агент отдавал четыре сцены.
    Оговорка снимает спор — образец учит форме, а число сцен названо рядом.
    """
    text = _text(tmp_path, phrases=EVEN_PHRASES, clips=[])
    оговорка = _абзац(text, text.index("Образец ниже показывает форму ответа"))
    assert "не меньше" in оговорка, "число сцен рядом с образцом не названо"
    assert "покрывают фразы" in оговорка, (
        "не сказано, что план целиком покрывает фразы")


def test_образец_не_отдаёт_финал_сцене_без_ведущей(tmp_path):
    """Ломает прод 4. `blind_at = min(2, len(shown) - 1)` попадал в последнюю
    показанную сцену, когда их меньше четырёх, — образец закрывал ролик сценой
    без ведущей и учил против правила финала и против роли `cta`.
    """
    for count in (4, 5, 6, 8):
        phrases = _фразы(count)
        scenes = _board(_text(tmp_path / f"n{count}", phrases=phrases,
                              clips=[], avatar_ordered=False))["scenes"]
        последняя = scenes[-1]
        assert последняя.get("avatarNeeded") is True, (
            f"{count} фраз: образец закрывает ролик сценой без ведущей")
        assert последняя["presenter"] != "none", (
            f"{count} фраз: в финале образца ведущей нет в кадре")
        assert scenes[0].get("avatarNeeded") is True, (
            f"{count} фраз: образец открывает ролик сценой без ведущей")
        отказы = [scene for scene in scenes
                  if scene.get("avatarNeeded") is False]
        assert not отказы or отказы[-1] is not scenes[-1]


def test_пример_одиночной_сцены_ссылается_на_существующую_фразу(tmp_path):
    """Пояснение к `phrases` показывало сцену из одной фразы как `[7, 7]` —
    номер взят из воздуха. На коротком ролике (фразы `0`–4) он указывает на
    фразу, которой нет, а образец в задании сильнее правила рядом с ним.
    """
    text = _text(tmp_path, phrases=GAP_PHRASES, clips=[], avatar_ordered=False)
    последняя = GAP_PHRASES[-1]["id"]
    пояснение = _абзац(text, text.index("Сцена из одной фразы"))
    номера = {int(n) for n in re.findall(r"`\[(\d+), \d+\]`", пояснение)}
    assert номера, "пример сцены из одной фразы пропал"
    assert all(n <= последняя for n in номера), (
        f"пример ссылается на фразу вне `0`–{последняя}: {sorted(номера)}")


def test_образец_не_закрывает_ролик_уголком_под_схему(tmp_path):
    """Тот же класс, что и «ломает прод 4», вторая его половина. Сцена со
    схемой стоит с `presenter: "pip-br"`, и на коротком ролике (две группы
    фраз) она оказывалась последней показанной — то есть финалом: образец учил
    закрывать ролик уголком, а свод правил и гейт до заказа
    (`D28_avatar_bookends`, hf_render.py) требуют `full` или `punch`.
    """
    закрывают = {"full", "punch"}
    for count in (2, 3, 4, 5, 6, 8, 9):
        phrases = _фразы(count)
        рано = _board(_text(tmp_path / f"early{count}", phrases=phrases,
                            clips=[], avatar_ordered=False))["scenes"]
        после = _board(_text(tmp_path / f"done{count}", phrases=phrases,
                             clips=FULL_CLIPS))["scenes"]
        # Образец идёт до конца ролика ровно тогда, когда фраз хватило на
        # четыре сцены и меньше: по две фразы на сцену. С хвостом-многоточием
        # последняя показанная сцена финалом не является, и судить по ней
        # нечего.
        весь_ролик = count <= 8
        for scenes, шаг in ((рано, "до заказа"), (после, "после заказа")):
            assert scenes[0]["presenter"] in закрывают, (
                f'{count} фраз, {шаг}: образец открывает ролик '
                f'`{scenes[0]["presenter"]}`')
            if not весь_ролик:
                continue
            assert scenes[-1]["presenter"] in закрывают, (
                f'{count} фраз, {шаг}: образец закрывает ролик '
                f'`{scenes[-1]["presenter"]}`')


def test_секунды_пишутся_одним_способом(tmp_path):
    """Канон 12. Одна и та же величина печаталась тремя способами — «1,5–4
    секунды», «2.2 с», «4.0 с». Три написания читаются как три единицы;
    формат один на оба файла (`seconds` в hf_montage_skill.py).
    """
    for text in (_text(tmp_path, avatar_ordered=False, phrases=GAP_PHRASES),
                 _skill(tmp_path)):
        тело = text.split("---\n", 2)[-1]
        точкой = re.findall(r"\d+\.\d+\s*с\b", тело)
        assert not точкой, f"секунды через точку: {точкой}"
        словом = re.findall(r"\d[\d,.]*\s*секунд\w*", тело)
        assert not словом, f"секунды словом вместо «с»: {словом}"
        нулём = re.findall(r"\d+,0\s*с\b", тело)
        assert not нулём, f"нулевая десятая доля: {нулём}"


def test_контракт_ответа_и_шрифты_сказаны_указанием(tmp_path):
    """Канон 10. «Два файла, и никаких других» и «Гарнитуры не выбирай» —
    запреты; их канон требует говорить, что делать, и называть причину.
    """
    text = _text(tmp_path)
    assert "Верни ровно два файла" in text
    assert "читает он только их" in text, "причина не названа"
    assert "Гарнитуры уже выбраны и стоят в проекте" in text
    assert "называй цвета и настроение" in text, (
        "не сказано, что писать во `frame.md` вместо шрифта")
    for banned in ("и никаких других", "Гарнитуры не выбирай"):
        assert banned not in text, f"запрет вместо указания: {banned}"


def test_число_кусков_названо_и_выведено_из_предела_без_лица(tmp_path):
    """Круг 3, дефект 3(а), вторая половина. Цель и потолок разошлись на число,
    которое агент не может проверить, а канон требует называть причину. Кусков
    столько, сколько их навязывает правило про десять секунд без лица, и оценка
    названа рядом с числом.
    """
    section = _где_ведущей_нет(
        _text(tmp_path, avatar_ordered=False, phrases=GAP_PHRASES))
    куски = str(_куски(41.5))
    названо = [part for part in _абзацы(section, куски) if "куск" in part]
    assert названо, f"число кусков ({куски}) агенту не названо"
    предел = f"{MAX_FACE_ABSENCE_S:g} с"
    assert any(предел in part for part in названо), (
        f"не сказано, откуда берётся число кусков — предел {предел} без лица")
    assert not [part for part in названо
                if "в самом экономном плане три" in part], (
        "в тексте осталась прежняя оценка в три куска")


def test_настройки_островов_доезжают_до_задания(tmp_path):
    """Круг 3, дефект 3(в), половина в задании. Числа печатались по `DEFAULTS`,
    а заказ идёт по настройкам клиента: правка настроек разводила задание, гейт
    и счёт HeyGen. Вызов без параметра обязан работать по-прежнему — его делает
    и сборка, и все прежние вызовы.
    """
    свои = {"handle_seconds": 0.5, "min_request_seconds": 4.0,
            "max_shot_seconds": 12.0}
    section = _где_ведущей_нет(
        _text(tmp_path / "custom", avatar_ordered=False, phrases=GAP_PHRASES,
              islands=свои))
    assert "0,5 с" in section, "ручка куска напечатана не по настройкам"
    assert "4 с" in section, "минимальный кусок заказа напечатан не по настройкам"
    assert "12 с" in section, "предел куска напечатан не по настройкам"
    цель = _цели(41.5, свои)[0]
    assert f"{цель:.1f} с".replace(".", ",") in section, (
        "цель по ведущей посчитана не по настройкам этого прогона")

    умолчания = _где_ведущей_нет(
        _text(tmp_path / "default", avatar_ordered=False, phrases=GAP_PHRASES))
    handle = float(ISLAND_DEFAULTS["handle_seconds"])
    assert f'{handle:g} с'.replace(".", ",") in умолчания, (
        "вызов без настроек перестал печатать умолчания")


def test_пол_серии_и_пол_сцены_без_ведущей_не_спорят(tmp_path):
    """Круг 3, дефект 5. «Сцена под серию живёт 2,4–6 с» против «сцена без
    ведущей живёт не меньше 3 с»: в зазоре 2,4–3 с правила зовут в разные
    стороны, и проигрывает то, которое роняет сборку. Абзац про серию обязан
    назвать, кому какой пол.
    """
    for kw in ({}, {"avatar_ordered": False, "phrases": GAP_PHRASES}):
        skill = _skill(tmp_path / f"s{len(kw)}", **kw)
        абзац = _абзац(skill, skill.index("Сцена под серию живёт"))
        assert f"{SERIES_MIN:g}".replace(".", ",") in абзац, (
            "пол серии из абзаца пропал")
        assert any(mark in абзац for mark in THREE_SECONDS), (
            "в абзаце про серию не назван пол сцены без ведущей")
        assert "с ведущей" in абзац and "без ведущей" in абзац, (
            "не сказано, кому какой пол принадлежит")


def test_оговорка_про_образец_печатается_когда_сцен_меньше_пола(tmp_path):
    """Круг 3, дефект 6. Оговорка печаталась только у образца с хвостом, а на
    восьми фразах хвоста нет: образец из четырёх сцен читался законченным
    планом рядом с требованием «сцен не меньше шести», и образец сильнее
    правила.
    """
    text = _text(tmp_path, phrases=EVEN_PHRASES, clips=[])
    оговорка = _абзац(text, text.index("Образец ниже показывает форму ответа"))
    сцен = text.count('"id": "s-')
    assert "остальные сцены" not in text, (
        "тест бессмыслен: у образца есть хвост, и оговорка печаталась и раньше")
    assert сцен < 6, "тест бессмыслен: сцен в образце не меньше пола"
    assert str(сцен) in оговорка, (
        "не сказано, сколько сцен в образце, — он читается готовым планом")
    assert "не меньше 6" in оговорка, "пол числа сцен рядом с образцом пропал"


def test_пол_числа_сцен_не_требует_больше_сцен_чем_есть_фраз(tmp_path):
    """Круг 3, дефект 6, вторая половина. `min_scenes` считает пол по длине
    ролика и о фразах не знает: на трёх фразах он требовал шести сцен, а сцена
    называет номера фраз — шести сцен там не собрать вовсе.
    """
    коротко = _text(tmp_path / "three", phrases=GAP_PHRASES[:3], clips=[],
                    avatar_ordered=False)
    assert "Сцен не\n   меньше 3" in коротко or "меньше 3:" in коротко, (
        "пол числа сцен больше числа фраз")
    assert "меньше 6" not in коротко, "прежний пол остался в тексте"

    длинно = _text(tmp_path / "eight", phrases=EVEN_PHRASES, clips=[],
                   avatar_ordered=False)
    assert "меньше 6" in длинно, (
        "фраз хватает, а пол числа сцен всё равно срезан")


def test_докстринг_образца_совпадает_с_поведением(tmp_path):
    """Круг 3, дефект 7. Докстринг `_sample_plan` обещал, что образец покажет
    оба значения `avatarNeeded`, а на коротком ролике отказа в нём нет вовсе:
    открытие и финал ведёт лицо, и середины, свободной от краёв, там не
    остаётся. Поведение верное — врал докстринг.
    """
    from reels_factory.hf_brief import _sample_plan

    короткий = _board(_text(tmp_path / "short", phrases=GAP_PHRASES[:4],
                            clips=[], avatar_ordered=False))["scenes"]
    assert {scene["avatarNeeded"] for scene in короткий} == {True}, (
        "поведение образца изменилось — докстринг надо перечитать заново")
    doc = _sample_plan.__doc__
    assert "обязан показать оба его значения" not in doc, (
        "докстринг обещает то, чего образец на коротком ролике не делает")
    assert "трёх" in doc, (
        "докстринг не называет условие, при котором отказ в образце есть")


def test_правило_финала_оговорено_материалом(tmp_path):
    """Круг 3, дефект 8. В ветке «аватар заказан» образец закрывает ролик
    сценой `presenter: "none"`, когда последние фразы попали в дыру между
    островами: ведущей там нет физически, и D12 требует именно `none`. Свод
    правил при этом требовал закрывать ролик лицом — два требования на один
    случай, и агент выбирает одно.

    До заказа оговорки быть не должно: там ведущую заказывают ровно по плану,
    и финал за лицом всегда (`D28_avatar_bookends`, hf_render.py).
    """
    ordered = _skill(tmp_path / "ordered", phrases=GAP_PHRASES)
    правило = _абзац(ordered, ordered.index("последняя сцена"))
    assert "без ведущей" in правило, (
        "правило финала не оговорено материалом: на дыре между островами лица "
        "нет физически")
    последняя = _board(_text(tmp_path / "ordered",
                             phrases=GAP_PHRASES))["scenes"][-1]
    assert последняя["presenter"] == "none", (
        "тест бессмыслен: образец больше не закрывает ролик сценой без ведущей")

    early = _skill(tmp_path / "early", avatar_ordered=False,
                   phrases=GAP_PHRASES)
    рано = _абзац(early, early.index("последняя сцена"))
    assert "помеч" not in рано, (
        "до заказа правило финала ссылается на пометку, которой там нет")


def test_титр_и_кадр_разведены_указанием(tmp_path):
    """Канон 10. «в кадр их не ставь» переписано положительно: сказано, что в
    кадр ставить, и почему рубрика туда не годится.
    """
    text = _skill(tmp_path)
    assert "в кадр ставь то, чего голос не сказал" in text
    assert "«вопрос первый», «фото из каталога»" in text
    assert "в кадр их не ставь" not in text


# ---------- круг 5: попадание с первой-второй попытки ----------

#: Два материала круга: обычная речь (фразы 3,5 с) и быстрая (2,4 с). На второй
#: сплошной перебор круга 3 не находил ни одного плана, проходящего гейты,
#: поэтому каждое требование этого круга проверяется на обеих.
МАТЕРИАЛЫ = (("обычная речь", _фразы(16, 3.5), 56.0),
             ("быстрая речь", _фразы(16, 2.42), 38.7))


def _гейты(scenes: list[dict], phrases: list[dict], duration: float) -> dict:
    """Приговор гейтов до заказа — тех самых, что судят план агента.

    Сценам проставляем секунды. Гейты разбирают план по времени (`_scene_at` в
    avatar_islands.py: фраза достаётся сцене, внутрь `startSec`–`endSec`
    которой попала её середина), а агент называет сцену номерами фраз, и
    секунды ей ставит код после сдачи плана (`lay_out_scenes` в hf_phrases.py).
    Без них КАЖДАЯ сцена остаётся без фраз, и всё, что меряется фразами —
    пол сцены без ведущей, промежуток без лица, — говорит PASS на любом плане:
    проверка была пустой и зелёной.

    Приговор — только FAIL. Бюджет судит построенный заказ (`order_facts` в
    hf_render.py), а плана монтажа у задания на этом шаге нет вовсе, и без него
    вердикт — `SKIP: судить нечем`. Считать SKIP приговором значило бы валить
    образец за то, что в тесте нечего заказывать; считать его проходом —
    прятать промах. Бюджет проверяют там, где заказ есть: `test_hf_render.py`,
    `test_бюджет_судит_построенный_заказ_а_не_оценку`.
    """
    from reels_factory.avatar_islands import avatar_islands_settings
    from reels_factory.hf_render import _early_plan_gates

    длина = {p["id"]: (float(p["start"]), float(p["end"])) for p in phrases}
    размеченные = []
    for scene in scenes:
        scene = dict(scene)
        first, last = scene["phrases"][0], scene["phrases"][-1]
        scene.setdefault("startSec", длина[first][0])
        scene.setdefault("endSec", длина[last][1])
        размеченные.append(scene)
    verdicts = _early_plan_gates(размеченные, duration, phrases,
                                 avatar_islands_settings({}))
    return {name: value for name, value in verdicts.items()
            if value.startswith("FAIL")}


def _план_из_образца(text: str, phrases: list[dict]) -> list[dict]:
    """Образец задания как план: показанные сцены плюс хвост, дописанный так,
    как хвост подписан в самом образце.

    Подпись хвоста говорит «та же длина, то же чередование сцен с ведущей и без
    неё, финал за лицом» — этим и продолжаем: сцены той же длины, отказ через
    одну, последняя сцена ролика с ведущей. Гейты судят план целиком, и хвост,
    отданный целиком ведущей, валил бы бюджет — но такому плану образец и не
    учит.
    """
    scenes = [dict(scene) for scene in _board(text)["scenes"]]
    last = phrases[-1]["id"]
    размер = max(1, len(range(scenes[0]["phrases"][0],
                             scenes[0]["phrases"][-1] + 1)))
    следующая = scenes[-1]["phrases"][-1] + 1
    ведущая = bool(scenes[-1].get("avatarNeeded", True))
    длина = {p["id"]: float(p["end"]) - float(p["start"]) for p in phrases}

    def _длина_сцены(первая, край):
        return sum(длина[pid] for pid in range(первая, край + 1))

    хвост = []
    while следующая <= last:
        ведущая = not ведущая
        # Момент под вставку несёт и сцена с ведущей: моментов план обязан
        # набрать столько, сколько требует `D34_inserts`, а счёт кредитует
        # теперь только те, что доживут до кадра — влезут в окно серии или
        # лягут на дыру аватара (`hf_montage.survives_series`). Слепых сцен на
        # это не хватает: они идут через одну, а края ролика ведёт лицо.
        # Сцену под серию режем по окну: пара фраз обычной речи даёт 7,0 с,
        # серия живёт до 6,0 с.
        размер_сцены = размер
        if ведущая and _длина_сцены(
                следующая, min(следующая + размер - 1, last)) > SERIES_MAX:
            размер_сцены = 1
        край = min(следующая + размер_сцены - 1, last)
        сцена = {"id": f"s-tail{len(хвост)}", "beat": "point",
                 "phrases": [следующая, край],
                 "presenter": "full" if ведущая else "none",
                 "avatarNeeded": ведущая}
        if not ведущая:
            # Сцена без ведущей обязана нести вставку: кадр там больше нечем
            # закрыть, и ровно так её показывает сам образец. Без этого хвост
            # получался беднее образца, и план не набирал моментов под вставку
            # (`D34_inserts`).
            сцена["insert"] = {"shots": ["hands sorting papers on a desk"],
                               "kind": "video"}
            сцена["fallback"] = {"form": "items", "why": "набор равноправных",
                                 "items": [{"label": "кому", "icon": "человек"},
                                           {"label": "что", "icon": "документ"},
                                           {"label": "как", "icon": "поиск"}]}
        elif _длина_сцены(следующая, край) <= SERIES_MAX + 0.001:
            сцена["presenter"] = "stack"
            сцена["insert"] = {"shots": ["hands sorting papers on a desk"],
                               "kind": "video"}
        хвост.append(сцена)
        следующая = край + 1
    if хвост:
        # Финал ведёт лицо во весь кадр — так подписан хвост образца. Серию он
        # не несёт: сцену, отданную ведущей, вставка покидает (`refill_scene`).
        хвост[-1].update(avatarNeeded=True, presenter="punch", beat="climax")
        хвост[-1].pop("insert", None)
        хвост[-1].pop("fallback", None)
        for scene in scenes:
            if scene.get("beat") == "climax":
                scene["beat"] = "point"
    return scenes + хвост


def _счёт_из_задания(text: str) -> list[tuple[int, int]]:
    """Сцены без ведущей из «сильной» половины счёта-примера в задании."""
    block = text.split("<example>\n")[1].split("</example>")[0]
    strong = [line for line in block.splitlines() if "проходит" in line][0]
    spans = re.search(r"на фразах ([^—]+)—", strong).group(1)
    found = []
    for part in spans.split(","):
        part = part.strip()
        if not part:
            continue
        first, _, last = part.partition("–")
        found.append((int(first), int(last or first)))
    return found


def test_образец_плана_проходит_гейты_до_заказа(tmp_path):
    """Требование круга: образец не спорит ни с одним правилом, по которому
    план судят. Прежний образец спорил с самым дорогим из них — с бюджетом.

    Судим не глазами, а теми же гейтами (`_early_plan_gates`, hf_render.py):
    образец сильнее любого правила рядом с ним, поэтому план, собранный по
    образцу, обязан проходить.
    """
    for имя, phrases, duration in МАТЕРИАЛЫ:
        text = _text(tmp_path / f"s{имя}", phrases=phrases, clips=[],
                     duration=duration, avatar_ordered=False)
        плохо = _гейты(_план_из_образца(text, phrases), phrases, duration)
        assert not плохо, (
            f"{имя}: образец учит плану, который заворачивают: {плохо}")


def test_доля_ведущей_в_образце_не_выше_потолка(tmp_path):
    """Круг 5, дефект 1. В образце было четыре сцены и ведущая на трёх — 75 %
    показанного при потолке 60 %. Образец сильнее правила, стоящего рядом, и
    агент воспроизводил именно эту пропорцию.
    """
    for имя, phrases, duration in МАТЕРИАЛЫ:
        text = _text(tmp_path / f"b{имя}", phrases=phrases, clips=[],
                     duration=duration, avatar_ordered=False)
        scenes = _board(text)["scenes"]
        длина = {p["id"]: float(p["end"]) - float(p["start"]) for p in phrases}

        def _длина(scene):
            first, last = scene["phrases"][0], scene["phrases"][-1]
            return sum(длина[pid] for pid in range(first, last + 1))

        всего = sum(_длина(scene) for scene in scenes)
        с_ведущей = sum(_длина(scene) for scene in scenes
                        if scene.get("avatarNeeded") is not False)
        # Мерка та же, какой меряется сам образец: сложение длительностей фраз.
        # Граница заказа тех же секунд не значит — заказ добирает ручки, — и
        # доля от неё разрешала бы образцу расстановку, которую гейт валит.
        потолок = _граница_в_счёте_агента(duration) / duration
        assert с_ведущей / всего <= потолок + 1e-6, (
            f"{имя}: в образце ведущая на {с_ведущей / всего:.0%} показанного "
            f"при потолке {потолок:.0%}")
        assert any(scene.get("avatarNeeded") is False for scene in scenes), (
            f"{имя}: образец не показывает отказа от ведущей вовсе")


def test_счёт_бюджета_показан_примером_и_проходит_гейты(tmp_path):
    """Канон: «Multishot examples work with thinking… show Claude the reasoning
    pattern». Ревизия круга 4 замерила, что арифметика агента верна, а
    промахивается он на квантовании — мерка плана целая сцена. Поэтому пример
    показывает сам счёт, обе его стороны (слабую и сильную), и назван на
    настоящих номерах фраз этого ролика.
    """
    for имя, phrases, duration in МАТЕРИАЛЫ:
        text = _text(tmp_path / f"c{имя}", phrases=phrases, clips=[],
                     duration=duration, avatar_ordered=False)
        section = _где_ведущей_нет(text)
        assert "<example>" in section, f"{имя}: счёта-примера в бюджете нет"
        assert "вернётся на пересдачу" in section, (
            f"{имя}: слабая половина пары не показана")
        # Сильная половина — план, который гейты действительно принимают.
        blind = _счёт_из_задания(text)
        assert len(blind) >= 2, f"{имя}: сильный вариант не назвал сцен"
        куски, at = [], 0
        for first, last in blind:
            if at < first:
                куски.append((at, first - 1, True))
            куски.append((first, last, False))
            at = last + 1
        if at <= phrases[-1]["id"]:
            куски.append((at, phrases[-1]["id"], True))
        план = [{"id": f"s-{i + 1:02d}", "phrases": [first, last],
                 "avatarNeeded": avatar,
                 "presenter": ("punch" if avatar and i == len(куски) - 1
                               else "full" if avatar else "none"),
                 "beat": "hook" if i == 0 else "point",
                 # Сцену без ведущей держит вставка — иначе кадр пуст, и этого
                 # же числа моментов требует `D34_inserts`.
                 "insert": None if avatar else {
                     "shots": ["hands sorting papers on a desk"],
                     "kind": "video"}}
                for i, (first, last, avatar) in enumerate(куски)]
        плохо = _гейты(план, phrases, duration)
        assert not плохо, (
            f"{имя}: счёт-пример учит плану, который валят: {плохо}")


def test_цель_и_граница_названы_порознь_и_допуск_объяснён(tmp_path):
    """Решение заказчика этого круга: ориентир доли ведущей — одно число,
    граница отказа — другое, и между ними план годен.

    Sonnet читает буквально и не обобщает одно указание на другое
    (prompting-claude-sonnet-5), поэтому глаголы у чисел разные: в цель целятся,
    выше границы заворачивают. Без явной оговорки «между ними план годен»
    буквальный читатель принял бы цель за единственно допустимое число.
    """
    text = _text(tmp_path, avatar_ordered=False, phrases=GAP_PHRASES)
    section = _где_ведущей_нет(text)
    target, hard = _цели(41.5)
    цель = _абзацы(section, _секунды(target))
    граница = _абзацы(section, _секунды(hard))
    assert any("Ориентир по ролику" in part for part in цель), (
        "цель не названа ориентиром — читается линией отказа")
    assert any("не линия отказа" in part for part in цель), (
        "не сказано, что цель отказом не является")
    assert any("ручек" in part or "ручки" in part for part in цель), (
        "не названа первая причина допуска: заказ длиннее показа на ручки")
    годен = [part for part in граница if "план годен" in part]
    assert годен, "не сказано, что между целью и границей план годен"
    assert any("целая сцена" in part for part in годен), (
        "не названа вторая причина допуска: мерка агента — целая сцена")


def test_требование_бюджета_сказано_действием(tmp_path):
    """Канон: «Tell Claude what to do instead of what not to do». «Не выходи за
    потолок» действием не является, а «отдай вставке не меньше N секунд, это от
    A до B сцен» — является, и мерка тут та же, какой считает агент.
    """
    for имя, phrases, duration in МАТЕРИАЛЫ:
        section = _где_ведущей_нет(
            _text(tmp_path / f"d{имя}", phrases=phrases, clips=[],
                  duration=duration, avatar_ordered=False))
        отдай = _абзацы(section, "отдай не меньше")
        assert отдай, f"{имя}: требование бюджета не повёрнуто в действие"
        target = _цели(duration)[0]
        assert any(f"{duration - target:.1f} с".replace(".", ",") in part
                   or f"{duration - target:.0f} с" in part
                   for part in отдай), (
            f"{имя}: не названо, сколько секунд уходит вставке и схеме")
        assert any("сцен с `avatarNeeded: false`" in part for part in отдай), (
            f"{имя}: не названа вилка числа сцен без ведущей")


def test_все_гейты_названы_в_сверке_перед_сдачей(tmp_path):
    """Приём взят у фреймворка: «## Self-check before finishing… the codes in
    parens are `hyperframes lint`'s and what the orchestrator may cite back»
    (hyperframes-core/references/frame-worker-core.md:63-80). Имена гейтов агент
    всё равно видит в причине пересдачи, а до отказа не знал, по чему его судят.

    Anthropic советует то же самое: «Ask Claude to self-check… This catches
    errors reliably», и от приёма освобождён только Opus 5 — наш планировщик
    Sonnet 5.
    """
    text = _text(tmp_path, avatar_ordered=False, phrases=GAP_PHRASES)
    сверка = text.split("## Сверка перед сдачей")[1]
    for гейт in ("D28_avatar_bookends", "D29_avatar_budget",
                 "D31_faceless_scenes", "D32_face_absence",
                 "D33_avatar_decisions", "D35_frame_filled"):
        assert гейт in сверка, f"{гейт} в сверке не назван"
    assert "почини план и только потом записывай файлы" in сверка, (
        "не сказано, что делать с найденным расхождением")
    # Мерка каждого пункта — та же, какой меряет гейт: сложение длительностей
    # фраз сцены. Иначе агент сверяется не тем, чем его судят.
    assert сверка.count("длительност") >= 3, (
        "пункты сверки не называют, чем мерить")


def test_сверка_стоит_последней_а_данные_выше_инструкций(tmp_path):
    """Канон про порядок: «Put longform data at the top… Queries at the end can
    improve response quality». Длинные данные у нас одни — список фраз; контракт
    ответа, образец и сверка стоят в конце.
    """
    text = _text(tmp_path, avatar_ordered=False, phrases=EVEN_PHRASES)
    порядок = [text.index(mark) for mark in
               ("## Сценарий", "## Фразы озвучки", "## Порядок работы",
                "## Что вернуть", "## Сверка перед сдачей")]
    assert порядок == sorted(порядок), f"разделы идут не по канону: {порядок}"
    assert text.rstrip().endswith(
        "почини план и только потом записывай файлы."), (
        "последним агент читает не сверку")


def test_пересдача_названа_жёстким_ограничением(tmp_path):
    """Их формулировка: «if your context carries `lint` / `check` feedback from
    a prior pass, read it first and re-author so none of those findings recur;
    treat each as a hard constraint» (frame-worker-core.md:25). Раздел не
    только просит не повторять замечания, но и честно называет цену: попыток
    ограниченное число (`MAX_PLAN_ATTEMPTS`/`MAX_COMPOSE_ATTEMPTS`,
    hf_render.py), и это последняя.
    """
    text = _text(tmp_path, avatar_ordered=False, phrases=GAP_PHRASES,
                 retry_reason="D29_avatar_budget: FAIL: 40 с при потолке 25 с",
                 attempt=1, max_attempts=2)
    section = text.split("# Задание на монтаж рилса")[1].split(
        "\n## Что решаешь не ты")[0]
    assert "ни одно из них не должно повториться" in section
    assert "Пересдач на этот шаг всего 2, это последняя" in section, (
        "число попыток и то, что это последняя, не названы")
    assert "план всё равно уйдёт в заказ ведущей" in section, (
        "не сказано, что после последней попытки план уходит в заказ как есть")


def test_главная_ошибка_названа_отдельным_блоком(tmp_path):
    """Форма их: «## Core rule… **The single most common failure is…**»
    (faceless-explainer/references/story-design.md:29-31). Наша самая частая
    ошибка измерена сплошным перебором: план валится на бюджете заказа, пройдя
    все прочие правила, — и до этого круга нигде не была названа ошибкой №1.
    """
    рано = _text(tmp_path / "early", avatar_ordered=False, phrases=GAP_PHRASES)
    assert "## Главная ошибка" in рано
    блок = рано.split("## Главная ошибка")[1].split("\n## ")[0]
    assert "границу заказа" in блок, "не названа цена ошибки"
    assert "ДО того как распишешь сцены" in блок, (
        "не сказано, что делать вместо этого")
    # Ошибка у шагов разная: после заказа клипы уже куплены, и дорого обратное
    # — прятать оплаченную ведущую.
    после = _text(tmp_path / "done", phrases=GAP_PHRASES)
    assert "Оплаченная ведущая спрятана" in после


def test_решение_про_ведущую_дано_таблицей_случаев(tmp_path):
    """Форма их: дорогое решение выносится нулевым шагом и оформляется строкой
    на случай («0. **Decide first…**» и таблица «Category | Pick when…»,
    motion-graphics/agents/director.md:9-11). Прежде решение выводилось из
    четырёх примеров подряд.
    """
    skill = _skill(tmp_path, avatar_ordered=False, phrases=GAP_PHRASES)
    таблица = skill.split("| Случай | `avatarNeeded` |")[1].split("\n\n")[0]
    for случай in ("открывает или закрывает ролик",
                   "Предыдущая сцена уже идёт без ведущей"):
        assert случай in таблица, f"в таблице решения нет случая: {случай}"
    assert "Ни одна строка не подошла" in skill, (
        "не сказано, что делать, когда ни один случай не подошёл")
    после = _skill(tmp_path / "done", phrases=GAP_PHRASES)
    assert "| Случай |" not in после, (
        "после заказа таблица зовёт решать поле, которого нет")


def test_края_ролика_судятся_двумя_мерками_и_названы_обеими(tmp_path):
    """Круг 4, дефект 5. `D28_avatar_bookends` требует ОДНОВРЕМЕННО
    полнокадрового положения и `avatarNeeded: true`, а правило называло только
    положение: связь подана в другом разделе и в одну сторону, и буквальный
    читатель обратную не выводит.
    """
    skill = _skill(tmp_path / "early", avatar_ordered=False,
                   phrases=GAP_PHRASES)
    for mark in ("первая сцена", "последняя сцена"):
        правило = _абзац(skill, skill.index(mark))
        assert "`avatarNeeded: true`" in правило, (
            f"правило про «{mark}» не называет заказ ведущей")


def test_предел_без_лица_назван_меркой_а_не_ощущением(tmp_path):
    """`D32_face_absence` меряет сумму идущих подряд сцен без ведущей. Правило
    говорило «когда сцен без ведущей идёт несколько» — это не мерка, и агенту
    нечем себя проверить.
    """
    skill = _skill(tmp_path, avatar_ordered=False, phrases=GAP_PHRASES)
    правило = _абзац(skill, skill.index("Подряд идущие сцены без ведущей"))
    assert "сложи" in правило.lower(), "не сказано, чем мерить промежуток"
    assert "без ведущей" in правило
    assert "D32_face_absence" in правило


def test_вилка_обычной_сцены_не_спорит_с_полом_сцены_без_ведущей(tmp_path):
    """Ревизия круга 4, место 6: «Обычная сцена живёт 1,5–4 с» стояло рядом с
    «сцена без ведущей живёт не меньше 3 с», и на быстрой речи агент штатно
    отдавал вставке сцену в 2,4 с — законную по первой строке и незаконную по
    второй. Числовой вилки больше нет — пол сцены с ведущей подставлен из
    `MIN_SCENE`, а потолок — из `MAX_STATIC_SPAN`, тем же числом, что и у
    серии, так что второго (более узкого) потолка, с которым можно
    разойтись, в тексте не осталось.
    """
    for kw in ({}, {"avatar_ordered": False, "phrases": FAST_PHRASES}):
        skill = _skill(tmp_path / f"v{len(kw)}", **kw)
        правило = _абзац(skill, skill.index("Сцена с ведущей живёт не короче"))
        assert "с ведущей" in правило, (
            "вилка обычной сцены не сказала, к какой сцене относится")
        assert "без ведущей" in правило, (
            "рядом с вилкой не назван пол сцены без ведущей")


def _граница_в_счёте_агента(duration: float) -> float:
    """Та же граница бюджета, но в мерке агента: сложением длительностей фраз.

    Гейт судит секунды ЗАКАЗА, а агент складывает фразы, и разница — ручки по
    краям кусков. Число считает `avatar_budget_targets`, повторять его формулу
    в тесте нельзя по той же причине, что и в `_цели`.
    """
    from reels_factory.avatar_islands import (
        avatar_budget_targets, avatar_islands_settings,
    )

    return avatar_budget_targets(
        duration, avatar_islands_settings({}))["hard_target_seconds"]


def test_граница_бюджета_названа_и_в_счёте_агента(tmp_path):
    """Хвост между агентами. Сверка велела складывать длительности фраз и
    сравнивать сумму с границей, названной в секундах ЗАКАЗА: заказ длиннее
    показа на ручки, поэтому пункт сверки обещал проход плану, который
    `D29_avatar_budget` заворачивает. Граница называется дважды — секундами
    заказа (её видит гейт) и секундами счёта агента (её проверяет он сам).
    """
    for имя, phrases, duration in МАТЕРИАЛЫ:
        text = _text(tmp_path / f"h{имя}", phrases=phrases, clips=[],
                     duration=duration, avatar_ordered=False)
        мера = _секунды(_граница_в_счёте_агента(duration))
        заказ = _секунды(_цели(duration)[1])
        assert мера != заказ, "тест бессмыслен: обе границы совпали"
        свои = [part for part in _абзацы(_где_ведущей_нет(text), мера)
                if "твоём счёте" in part]
        assert свои, f"{имя}: граница в счёте агента ({мера}) не названа"
        пункт = [line for line in
                 text.split("## Сверка перед сдачей")[1].splitlines()
                 if "длительностей фраз всех сцен" in line]
        assert пункт, f"{имя}: пункта сверки про бюджет нет"
        абзац = _абзац(text, text.index(пункт[0]))
        assert мера in абзац, (
            f"{имя}: сверка судит счёт агента чужой меркой — в ней {заказ}, "
            f"а сложение фраз меряется {мера}")


#: Требование «отдай вставке столько-то» вместе с вилкой сцен и их длиной.
ДЕЙСТВИЕМ = re.compile(
    r"отдай не меньше ([\d,]+) с, а целься в ([\d,]+) с\.\*\* Это от (\d+) до "
    r"(\d+) сцен .*?каждая длиной от ([\d,]+) с до ([\d,]+) с")


def test_вилка_сцен_без_ведущей_набирает_названные_секунды(tmp_path):
    """Блок «То же требование действием» предъявлял требование, невыполнимое по
    построению: пол вилки считался по пределу без лица (10 с), а потолок сцены
    назывался тут же и равен 8 с. На 56-секундном ролике выходило «отдай 25,2 с
    тремя сценами по 8 с» — 24 с потолка против 25,2 с требования. Требование,
    которого этим числом сцен не выполнить, — это сгоревшая пересдача.
    """
    for имя, phrases, duration in МАТЕРИАЛЫ:
        text = _text(tmp_path / f"g{имя}", phrases=phrases, clips=[],
                     duration=duration, avatar_ordered=False)
        найдено = ДЕЙСТВИЕМ.search(text)
        assert найдено, f"{имя}: блока «То же требование действием» нет"

        def _число(part):
            return float(part.replace(",", "."))

        пол, цель, мало, много, коротко, потолок = (
            _число(найдено.group(1)), _число(найдено.group(2)),
            int(найдено.group(3)), int(найдено.group(4)),
            _число(найдено.group(5)), _число(найдено.group(6)))

        assert мало * потолок >= цель - 1e-6, (
            f"{имя}: {мало} сцен по {потолок} с не набирают названной цели "
            f"{цель} с — задание требует невозможного")
        assert мало * потолок >= пол - 1e-6, (
            f"{имя}: {мало} сцен по {потолок} с не набирают даже пола {пол} с")
        assert много * коротко >= пол - 1e-6 and много >= мало, (
            f"{имя}: вилка сцен вывернута — от {мало} до {много}")


def _вердикт_бюджета(scenes, phrases, duration, заказ) -> str:
    """Вердикт D29 по этому плану при заказе ровно в названные секунды.

    `заказ=None` — заказа нет вовсе: ровно то положение, в котором находится
    задание, пока плана монтажа никто не построил. Иначе заказ подаётся готовым
    словарём `order_facts` (hf_render.py): строить его тут не из чего — плана
    монтажа у брифа нет, — а проверяется здесь не арифметика заказа, а то,
    каким числом гейт разговаривает с агентом.
    """
    from reels_factory.avatar_islands import avatar_islands_settings
    from reels_factory.hf_render import _early_plan_gates

    длина = {p["id"]: (float(p["start"]), float(p["end"])) for p in phrases}
    размеченные = []
    for scene in scenes:
        scene = dict(scene)
        first, last = scene["phrases"][0], scene["phrases"][-1]
        scene.setdefault("startSec", длина[first][0])
        scene.setdefault("endSec", длина[last][1])
        размеченные.append(scene)
    order = None if заказ is None else {
        "plan": {"summary": {"avatar_billed_seconds": заказ}},
        "edit_plan": {}, "billed_seconds": заказ, "restored": [], "error": ""}
    return _early_plan_gates(размеченные, duration, phrases,
                             avatar_islands_settings({}),
                             order=order)["D29_avatar_budget"]


def test_граница_в_счёте_агента_достижима_а_без_заказа_бюджет_не_судит(tmp_path):
    """Здесь стояло обещание, которое оказалось ложным, и его цена известна.

    Обещание было такое: план, уложившийся в `hard_target_seconds` (границу,
    переведённую в мерку агента — сложение длительностей фраз) и прошедший
    остальные ранние правила, бюджет обязан взять. Держал его сплошной перебор
    расстановок, 117 740 штук, не нашедший ни одного контрпримера. Но перебор
    судил НАШУ оценку заказа, а не заказ: оценка не знала про
    `_restore_short_faceless` (`avatar_islands.py`), который возвращает ведущую
    куску короче `MIN_FULLSCREEN_S` и добавляет его секунды в счёт. Боевой
    прогон `06eb0a8f` (01.09.2026) стал контрпримером: оценка 29,383 с при
    настоящем заказе 36,213 с и границе 29,773 с — пользователь заплатил $18 и
    ролика не получил.

    Мерка агента осталась, гарантией быть перестала. Пиним то, что от неё
    осталось правдой:

    1. Число сверки достижимо. Перебор находит под ним расстановки, которые
       проходят и все прочие ранние правила разом — роли, пол сцены без
       ведущей, пропажу лица, число вставок. Число, которого не выполнить, —
       это сгоревшая пересдача, и таким оно уже было (круг 5).
    2. Мерка агента и граница заказа — разные числа, и разводят их ручки по
       краям кусков (`avatar_budget_targets`). Полоса между ними реальна: план
       на 38,5 с обычной речи лежит ниже границы заказа 39,2 с и выше меры
       счёта 36,4 с; сплошной перебор нашёл таких 366 из 65 536. Раньше это
       был довод «сверке не хватит границы заказа»; теперь — напоминание, что
       счёт агента заказа не предсказывает.
    3. Без построенного заказа бюджет молчит вердиктом SKIP. Ни PASS, ни FAIL:
       выдуманное число тут уже стоило $18. Настоящий заказ судят там, где он
       есть, — `test_hf_render.py`.
    """
    from reels_factory.hf_render import SKIPPED_VERDICT

    for имя, phrases, duration in МАТЕРИАЛЫ:
        мера = _граница_в_счёте_агента(duration)
        куски = [phrases[i:i + 2] for i in range(0, len(phrases), 2)]
        проверено = 0
        for mask in range(1 << len(куски)):
            флаги = [bool(mask >> bit & 1) for bit in range(len(куски))]
            сумма = sum(float(p["end"]) - float(p["start"])
                        for кусок, флаг in zip(куски, флаги) if флаг
                        for p in кусок)
            if сумма > мера:
                continue
            # Вставку несут и сцены без ведущей (кадр там больше нечем
            # закрыть), и середина ролика с ведущей в верхней половине кадра:
            # моментов под вставку план обязан набрать столько же, сколько
            # требует `D34_inserts`, и одними «слепыми» сценами их не набрать.
            #
            # Сцена с ведущей под вставку режется по окну серии: счёт кредитует
            # только те моменты, что доживут до кадра
            # (`hf_montage.survives_series`), а пара фраз обычной речи даёт
            # 7,0 с при окне до 6,0 с. Слепую сцену резать не надо — она лежит
            # на дыре аватара, и отбор берёт её вне очереди.
            def _сцены(i, к, флаг):
                край = i == 0 or i == len(куски) - 1
                со_вставкой = not флаг or not край
                части = [к]
                if (со_вставкой and флаг
                        and sum(float(p["end"]) - float(p["start"])
                                for p in к) > SERIES_MAX):
                    части = [[p] for p in к]
                out = []
                for номер, часть in enumerate(части):
                    scene = {"id": f"s-{i:02d}-{номер}",
                             "phrases": [часть[0]["id"], часть[-1]["id"]],
                             "avatarNeeded": флаг,
                             "beat": "hook" if i == 0 else "point",
                             "presenter": "full" if флаг else "none",
                             "insert": None}
                    if со_вставкой:
                        scene["insert"] = {
                            "shots": ["hands sorting papers on a desk"],
                            "kind": "video"}
                        if флаг:
                            scene["presenter"] = "stack"
                    out.append(scene)
                return out

            план = [scene for i, (к, флаг) in enumerate(zip(куски, флаги))
                    for scene in _сцены(i, к, флаг)]
            плохо = _гейты(план, phrases, duration)
            if плохо:
                # План валят другие правила — про мерку счёта он ничего не
                # говорит: расстановка «всё вставке» тоже лежит под мерой.
                continue
            # Судить заказ нечем — и вердикт обязан сказать это словом, а не
            # выдать зелёный.
            вердикт = _вердикт_бюджета(план, phrases, duration, None)
            assert вердикт.startswith(SKIPPED_VERDICT), вердикт
            проверено += 1
        assert проверено, f"{имя}: под мерой не нашлось ни одного плана"

    # Полоса между меркой агента и границей заказа реальна, и разводят их
    # ручки. План ниже: обычная речь, вставке отданы фразы 7, 9–10, 12–13.
    phrases, duration = _фразы(16, 3.5), 56.0
    без_ведущей = {7, 9, 10, 12, 13}
    план = [{"id": f"s-{p['id']:02d}", "phrases": [p["id"], p["id"]],
             "avatarNeeded": p["id"] not in без_ведущей,
             "beat": "hook" if p["id"] == 0 else "point",
             "presenter": "none" if p["id"] in без_ведущей else "full"}
            for p in phrases]
    сумма = sum(float(p["end"]) - float(p["start"]) for p in phrases
                if p["id"] not in без_ведущей)
    граница = _цели(duration)[1]
    assert _граница_в_счёте_агента(duration) < сумма <= граница, (
        "мера счёта агента и граница заказа сошлись — ручек между ними больше "
        "нет, и сверке хватило бы одной границы")

    # А когда заказ построен, отказ говорит с агентом ЕГО меркой: то же число,
    # что стоит пунктом сверки в задании, и считает его та же функция.
    отказ = _вердикт_бюджета(план, phrases, duration, граница + 1.0)
    assert отказ.startswith("FAIL"), отказ
    assert _секунды(_граница_в_счёте_агента(duration)) in отказ, (
        "отказ не называет границу в счёте агента — сверка и отказ мерят план "
        "разными числами")
    текст = _text(tmp_path / "мера", phrases=phrases, clips=[],
                  duration=duration, avatar_ordered=False)
    assert _секунды(_граница_в_счёте_агента(duration)) in текст, (
        "в задании этого числа нет — агенту нечем сверяться")


def test_действие_бюджета_названо_и_границей_и_целью(tmp_path):
    """Допуск этого круга сказан и в той половине бюджета, которая повёрнута в
    действие. Прежде «отдай не меньше» стояло у числа ЦЕЛИ, и абзац требовал
    больше, чем абзац выше объявлял годным: план между целью и границей задание
    называло годным и тут же запрещало.
    """
    for имя, phrases, duration in МАТЕРИАЛЫ:
        text = _text(tmp_path / f"g{имя}", phrases=phrases, clips=[],
                     duration=duration, avatar_ordered=False)
        отдай = [part for part in _абзацы(_где_ведущей_нет(text),
                                          "отдай не меньше")]
        assert отдай, f"{имя}: требование не повёрнуто в действие"
        цель, граница = _цели(duration)[0], _граница_в_счёте_агента(duration)
        мало = _секунды(duration - граница)
        много = _секунды(duration - цель)
        assert мало != много, "тест бессмыслен: числа совпали"
        assert any(f"не меньше {мало}" in part for part in отдай), (
            f"{имя}: «не меньше» стоит не у границы ({мало})")
        assert any(много in part for part in отдай), (
            f"{имя}: цель ({много}) в требовании-действии не названа")


def test_пол_сцены_без_ведущей_переведён_во_фразы(tmp_path):
    """Хвост соседа: на быстрой речи сплошной перебор не нашёл ни одного годного
    плана из 65 536 — все расстановки, где сцена без ведущей взяла одну фразу,
    валил `D31_faceless_scenes`. Пол сцены сказан секундами, а мерка агента —
    фразы, и перевод он делал сам. Число знает код.
    """
    section = _где_ведущей_нет(
        _text(tmp_path / "fast", phrases=_фразы(16, 2.42), clips=[],
              duration=38.7, avatar_ordered=False))
    сказано = [part for part in _абзацы(section, "не меньше 2 подряд")]
    assert сказано, "на быстрой речи не сказано, сколько фраз берёт такая сцена"
    assert "D31_faceless_scenes" in сказано[0], (
        "рядом с числом не названа проверка, которая его требует")
    длинные = _где_ведущей_нет(
        _text(tmp_path / "slow", phrases=_фразы(16, 3.5), clips=[],
              duration=56.0, avatar_ordered=False))
    assert "подряд, иначе сцена не наберёт" not in длинные, (
        "на обычной речи одной фразы хватает — оговорка лишняя")


def test_краевой_случай_показан_парой_сильный_слабый(tmp_path):
    """Их приём: «**Strong** (concretization)… **Weak** (article-paraphrase)…»
    (faceless-explainer/references/story-design.md:198-199). Канон Sonnet 5
    разрешает отрицательный пример только парой к положительному, поэтому пара
    одна и стоит на самой частой ошибке — сцене без ведущей короче пола.
    """
    skill = _skill(tmp_path, avatar_ordered=False, phrases=FAST_PHRASES)
    примеры = skill.split("<examples>")[1].split("</examples>")[0]
    пара = [block for block in примеры.split("<example>")
            if "Слабый вариант" in block]
    assert пара, "пары «сильный/слабый» на решение про ведущую нет"
    assert "собери их в одну сцену" in пара[0], (
        "в паре не показано, как делать правильно")
    assert примеры.count("Слабый вариант") == 1, (
        "отрицательных примеров больше одного — канон разрешает их только "
        "парой к положительному")


def test_счёт_пример_не_зовёт_в_сцену_длиннее_предела():
    """Ревизия пятого круга: счёт-пример называл куски по 9,0 и 9,6 с, потому
    что мерил их пределом промежутка без лица (10 с). Сцена такой длины —
    отказ раскладки (`MAX_STATIC_SPAN`, 8 с) ещё ДО первого гейта, то есть
    пример учил плану, который срывается раньше всех проверок.
    """
    from reels_factory.hf_brief import _faceless_candidates
    from reels_factory.hf_rhythm import MAX_STATIC_SPAN

    фразы = [{"id": i, "role": ("hook" if i == 0 else "cta" if i == 15
                                else "context"),
              "start": i * 3.6, "end": (i + 1) * 3.6, "text": f"фраза {i}"}
             for i in range(16)]
    куски = _faceless_candidates(фразы)
    assert куски, "пример не нашёл ни одного куска — проверять нечего"
    for кусок in куски:
        длина = sum(float(p["end"]) - float(p["start"]) for p in кусок)
        assert длина <= MAX_STATIC_SPAN + 1e-6, (
            f"пример зовёт в сцену {длина:.1f} с при пределе {MAX_STATIC_SPAN}")


def test_хвост_образца_не_зовёт_прятать_оплаченную_ведущую(tmp_path):
    """Ревизия пятого круга: правило «то же чередование сцен с ведущей и без
    неё» уехало в обе ветки. Там, где аватар уже куплен, прятать его нечем
    оправдать — доктрина этой ветки обратная, и чередование звало бы выбросить
    оплаченные секунды.
    """
    длинные = [{"id": i, "role": ("hook" if i == 0 else "cta" if i == 15
                                  else "context"),
                "start": i * 2.5, "end": (i + 1) * 2.5, "text": f"фраза {i}"}
               for i in range(16)]
    до_заказа = _text(tmp_path / "рано", phrases=длинные, duration=40.0,
                      avatar_ordered=False)
    после_заказа = _text(tmp_path / "поздно", phrases=длинные, duration=40.0)

    хвост_рано = [s for s in до_заказа.splitlines() if "остальные сцены" in s]
    хвост_потом = [s for s in после_заказа.splitlines()
                   if "остальные сцены" in s]
    assert хвост_рано and "чередование" in хвост_рано[0]
    assert not хвост_потом or "чередование" not in хвост_потом[0]


def test_образец_остаётся_разбираемым_json(tmp_path):
    """Ревизия пятого круга: хвост образца разрезали на две строки, и `}}` из
    f-строки уехало в обычную — образец закрывался двумя скобками и переставал
    читаться как JSON в обеих ветках. Тесты этого не поймали: их помощник
    срезает закрытие сам.
    """
    for kw in ({"phrases": EVEN_PHRASES, "avatar_ordered": False},
               {"phrases": GAP_PHRASES}):
        text = _text(tmp_path / str(len(kw)), **kw)
        sample = text.split("```json")[1].split("```")[0].rstrip()
        assert not sample.endswith("}}"), "образец закрыт двумя скобками"
        assert sample.endswith("}")


# ---------- круг 6: чем закрыть кадр ----------
#
# Прогон hf-live2: 2,7 с фона с титром на 25-й секунде. Сцена s-07 стояла со
# вставкой и `avatarNeeded: true`, вставка не собралась, ведущей на этих
# секундах не оказалось — и закрыть кадр было нечем, потому что правило про
# запас было условным: «заполняй `fallback` у сцены с `avatarNeeded: false`».
# Условие агент выполнил по букве, а кадр остался пуст.

def _запас(text: str) -> str:
    """Раздел свода правил про запас — то, чем закрывают кадр без вставки."""
    заголовок = "## Запас: чем закрыть кадр, если вставки не будет"
    assert заголовок in text, "раздела про запас в своде правил нет"
    return text.split(заголовок)[1].split("\n## ")[0]


def _средства(text: str) -> str:
    """Раздел с закрытым списком средств кадра."""
    заголовок = "## Чем закрывают кадр"
    assert заголовок in text, "закрытого списка средств в своде правил нет"
    return text.split(заголовок)[1].split("\n## ")[0]


def test_средства_кадра_даны_закрытым_списком(tmp_path):
    """Диагноз 4: «чем закрыть кадр» нигде не объявлено закрытым списком, а
    последствие описано вместо действия. Канон Anthropic про выбор из набора —
    перечислять валидные значения; форма таблицы у нас уже работает на решении
    про ведущую (`D33_avatar_decisions` зелёный на обоих прогонах).
    """
    section = _средства(_skill(tmp_path))
    for поле in ("`presenter`", "`insert`", "`schema`", "`elements`", "`icon`"):
        assert поле in section, f"средство {поле} в списке не названо"
    assert "шестого нет" in section, "список не объявлен закрытым"
    # У каждого средства названо, что должно сойтись, чтобы оно встало в кадр:
    # именно этого знания агенту не хватило — он считал вставку и ведущую
    # гарантированными.
    assert "судья" in section and "заказ" in section
    # Позицию каталога агент называет сам, а куда она встанет — считает код:
    # закрытого списка приёмов нет, закрытым остаётся список средств.
    assert "любая позиция" in section and "считает" in section


def test_запас_требуется_у_каждой_сцены_со_вставкой(tmp_path):
    """Главная правка круга. Условие «где ведущей нет» агент проверить не
    может: ведущая в кадре — исход заказа и сборки, а не его пометки. Правило
    вешается на саму вставку и становится счётным.
    """
    skill = _запас(_skill(tmp_path))
    assert "У каждой сцены с `insert`" in skill, (
        "правило запаса осталось условным")
    assert "где ведущей нет" not in skill, (
        "условие, которое агент проверить не может, осталось в правиле")
    for name, kw in (("early", {"avatar_ordered": False,
                                "phrases": GAP_PHRASES}),
                     ("ordered", {"clips": CLIPS, "phrases": GAP_PHRASES})):
        section = _где_ведущей_нет(_text(tmp_path / name, **kw))
        assert "У каждой сцены с `insert`" in section, (
            f"{name}: задание требует запас по старому условию")


def test_два_ответа_на_потерянную_вставку_названы_и_упорядочены(tmp_path):
    """Диагноз 3 и канон: `icon` описан как украшение, а не как дешёвое
    спасение кадра, и в плане прогона его ноль. Порядок — по тому, сколько
    средству нужно найти: схему код рисует из текста агента.
    """
    section = _запас(_skill(tmp_path))
    места = [section.find(f"`{поле}`") for поле in ("fallback", "icon")]
    assert all(место > 0 for место in места), "названы не оба ответа"
    assert места == sorted(места), "ответы идут не по порядку выбора"
    assert "первый, который подходит" in section, (
        "не сказано, как выбирать из двух")


def test_позиция_каталога_не_подана_запасом(tmp_path):
    """Живой ранний шаг B4: агент не назвал ни одного `elements` за прогон.
    В задании они лежали только в разделе «Запас» третьим ответом на
    неприехавшую вставку — и читались крайним случаем, а не приёмом, который
    берут по содержанию сцены.
    """
    skill = _skill(tmp_path)
    assert "elements" not in _запас(skill), (
        "позиция каталога снова подана запасом на потерянную вставку")
    раздел = _позиция_каталога(skill)
    assert "по содержанию этой сцены" in раздел, (
        "не сказано, что позицию берут по содержанию сцены")


def test_правило_позиции_каталога_живёт_в_одном_месте(tmp_path):
    """Повтор живого раннего шага (B4b): агент снова вернул `elements: 0`,
    хотя свод правил после B4-fix учит брать позицию по содержанию сцены.
    Причина — вторая редакция того же правила: `BRIEF.md` (его агент читает
    первым и по нему действует «без интервью») в трёх местах продолжал звать
    `elements` третьим из трёх «запасов» для сцен со вставкой. Агент выбрал
    рамку задания и отказался от каталога словами «по схеме и вставкам всё
    покрыто пятью формами».

    Единственное место правила — свод правил, раздел «Чем занять кадр:
    позиция каталога». Задание печатает числа этого ролика и ссылается на
    свод; своей редакции у него нет.

    Образец ответа, порядок работы и сверка перед сдачей — не редакция
    правила: первый показывает форму ответа, второй называет проход, третья
    называет след, который проход обязан оставить. B4c показал, что правило
    без образца молчит (агент не заговорил про каталог вовсе), B4d — что
    правило внутри чужого шага не выполняется (агент искал по индексу и ничего
    не поставил), dens-A…C — что шаг без пункта сверки не доживает до сдачи
    (агент перечислял пункты сверки по порядку и каталог не называл ни разу из
    шести). Поэтому `elements` живут в четырёх местах и ни в одном не
    переписывают правило: свод правил, образец, шаг «пройди сцены по
    каталогу», пункт сверки.
    """
    for name, kw in (("early", {"avatar_ordered": False,
                                "phrases": GAP_PHRASES}),
                     ("ordered", {"clips": CLIPS, "phrases": GAP_PHRASES})):
        целиком = _text(tmp_path / name, **kw)
        задание = (целиком.split("<example>")[0]
                   + целиком.split("</example>")[-1])
        шаги = задание.split("## Порядок работы")[1].split("\n## ")[0]
        сверка = задание.split("## Сверка перед сдачей")[1]
        # Пункт сверки называет след прохода, а не то, как ищут: таблицы
        # признаков, тегов и вида позиции в нём нет — они в своде правил.
        for чужое in ("grep", "catalog.index.md", "`kind`", "`words`"):
            assert чужое not in сверка, (
                f"{name}: сверка переписывает правило поиска ({чужое})")
        assert "elements" not in задание.replace(шаги, "").replace(сверка, ""), (
            f"{name}: у задания снова своя редакция правила про `elements` — "
            "оно живёт в своде правил, а задание на него ссылается")
        # Кандидаты под фразами — данные и адрес правила, а не его вторая
        # редакция: как ищут и как выбирают, сказано в своде.
        фразы = задание.split("## Фразы озвучки")[1].split(NEWLINE_HEADING)[0]
        for чужое in ("grep", "Теги, по которым", "`kind`"):
            assert чужое not in фразы, (
                f"{name}: список кандидатов переписывает правило поиска "
                f"({чужое})")
        # Ссылка на месте: без неё шаг про кадр отправлял бы агента искать
        # средства наугад.
        assert "Чем занять кадр" in шаги and "catalog.index.md" in шаги, (
            f"{name}: шаг про кадр не отсылает ни к своду правил, ни к индексу")
        # Шаг про каталог называет проход и адрес правила, а не правило.
        шаг = [часть for часть in re.split(r"(?m)^\d+\. ", шаги)
               if "elements" in часть]
        assert шаг, f"{name}: прохода по каталогу в порядке работы нет"
        текст = " ".join(шаг[0].split())
        assert "Чем занять кадр: позиция" in текст, (
            f"{name}: шаг не отсылает к разделу свода, где живёт правило")
        assert "запас" not in текст.lower() and "`insert`" not in текст, (
            f"{name}: позиция каталога снова привязана к запасу или вставке")

    skill = _skill(tmp_path)
    правило = "берёшь ты её по содержанию этой сцены"
    assert skill.count(правило) == 1, (
        "правило про позицию каталога стоит в своде правил не один раз")
    assert правило in _позиция_каталога(skill), (
        "правило стоит не в своём разделе")
    # Слова «запас» рядом с `elements` нет нигде: запас — это ответ на
    # неприехавшую вставку, а позицию каталога берут не поэтому. Меряем
    # абзацами: правило и его условие живут в одном абзаце, а перенос строки
    # внутри него ничего не значит.
    for абзац in _абзацы_про(skill, "elements"):
        assert "запас" not in абзац.lower(), (
            "`elements` снова названы запасом: " + абзац)
        assert "`insert`" not in абзац, (
            "`elements` снова привязаны к сцене со вставкой: " + абзац)


def _абзацы_про(text: str, слово: str) -> list[str]:
    """Абзацы, в которых встречается слово, — без строк таблицы.

    Строка таблицы средств называет поле, а не правило: `insert` и `elements`
    стоят там соседними строками закрытого списка, и это не привязка одного к
    другому.
    """
    абзацы = []
    for абзац in text.split(chr(10) * 2):
        проза = chr(10).join(строка for строка in абзац.splitlines()
                             if not строка.lstrip().startswith("|"))
        if слово in проза:
            абзацы.append(проза)
    return абзацы


def _позиция_каталога(text: str) -> str:
    """Раздел свода правил про позицию каталога."""
    заголовок = "## Чем занять кадр: позиция каталога"
    assert заголовок in text, "раздела про позицию каталога в своде правил нет"
    return text.split(заголовок)[1].split(NEWLINE_HEADING)[0]


#: Начало следующего раздела свода правил — им и кончается разбираемый.
NEWLINE_HEADING = chr(10) + "## "


#: Признаки содержания сцены, каждому из которых задание обязано назвать, где
#: искать позицию в индексе. Список — Васин, из разбора B4: агент выбирал
#: `icon`/`fallback` там, где в каталоге лежала подходящая позиция.
#: «имя говорящего» стоит в списке потому, что его же свод предлагает третьим
#: примером фразы шага 1, а строки под него в таблице не было: свой собственный
#: пример свод отправлял по шагу 4 прочь от каталога.
ПРИЗНАКИ = ("число", "сравнение", "код", "порядок шагов", "место",
            "интерфейс", "бренд", "имя говорящего")


def test_каждому_признаку_содержания_названо_где_искать(tmp_path):
    """Правило их скилла реестра — «content type → category → item». У нас
    категория названа тегами индекса: искать агент будет в `catalog.index.md`,
    а там у каждой позиции лежат ровно `tags` и `description`.
    """
    раздел = _позиция_каталога(_skill(tmp_path))
    строки = [line for line in раздел.splitlines()
              if line.startswith("| ") and "`" in line]
    assert строки, "таблицы «что названо в сцене → теги» в разделе нет"
    for признак in ПРИЗНАКИ:
        assert any(признак in line.split("|")[1] for line in строки), (
            f"признаку «{признак}» не названо, где искать в индексе")


def test_положения_без_свободной_зоны_названы_числами_кода(tmp_path):
    """Отчёт B4: `count-up` на сцене с ведущей `punch` сборка сняла молча —
    задание про это ограничение молчало, а оговорка про то же самое стояла
    только у значка. Список положений подставляется тем же
    `hf_compose.effect_zone`, которым код считает зону, — разойтись им нечем.
    """
    from reels_factory import hf_brief
    from reels_factory.hf_compose import effect_zone

    раздел = _позиция_каталога(_skill(tmp_path))
    нет_зоны = [name for name, _, _ in hf_brief.POSITIONS
                if effect_zone(name) is None]
    есть_зона = [name for name, _, _ in hf_brief.POSITIONS
                 if effect_zone(name) is not None]
    assert нет_зоны and есть_зона, "все положения оказались по одну сторону"
    правило = раздел.split("Зона эта есть не всегда.")[1].split("<example>")[0]
    assert "свободном куске кадра" in правило, (
        "правила про свободную зону в разделе нет")
    for name in нет_зоны:
        assert f"`{name}`" in правило, f"{name} не назван как положение без зоны"
    assert "D36_elements" in правило, "не сказано, чем это кончится для плана"


def test_кадр_держат_те_же_средства_что_считает_код(tmp_path):
    """Свод говорил «кадр держит одно из двух — вставка либо схема», а код
    держит его шестью (`hf_montage.frame_filler`), позицией каталога в том
    числе. Живые ранние шаги на трёх новых донорах (dens-A/B/C): агент закрыл
    вставкой каждую сцену без ведущей и поставил 2 позиции на 25 сцен — при
    правиле «держат двое» позиции нечего было держать.
    """
    section = _средства(_skill(tmp_path))
    assert "Кадр держит одно из двух" not in section, (
        "свод снова обещает, что кадр держат только вставка и схема")
    for средство in ("ведущая", "вставка", "схема", "элемент", "значок",
                     "плашка"):
        assert средство in section, f"кадр держит {средство}, а свод молчит"
    assert "наравне со вставкой" in section, (
        "не сказано, что позиция закрывает кадр сама, а не в придачу")


#: Виды позиций каталога, каждый из которых свод обязан разместить в кадре.
#: Считаются по настоящим карточкам: вид, которого в каталоге нет, объяснять
#: незачем, а вид, который есть, агент выберет и должен знать, куда он встанет.
ВИДЫ_ПОЗИЦИЙ = ("effect", "scene", "overlay")


def test_свод_объясняет_каждый_вид_позиции(tmp_path):
    """Из 168 позиций каталога свод размещал в кадре только `effect` (139),
    а про остальные говорил «этого не касается». Живой ранний шаг dens-C:
    агент нашёл по тегу `map` ровно одну позицию — `v-world-map`, вид
    `scene`, — под ролик, который целиком про карту страны, и не поставил
    ничего; все три позиции, когда-либо выбранные агентом, вида `effect`.
    «Возьми позицию другого вида» неисполнимо, пока другие виды не названы.
    """
    from reels_factory.hf_catalog import catalog_cards

    живые = {card.get("kind") for card in catalog_cards().values()}
    раздел = _позиция_каталога(_skill(tmp_path))
    правило = раздел.split("Зона эта есть не всегда.")[1].split("<example>")[0]
    for вид in ВИДЫ_ПОЗИЦИЙ:
        assert вид in живые, f"вида {вид} в каталоге больше нет"
        assert f"`{вид}`" in правило, f"свод не говорит, куда встаёт {вид}"
    assert None in живые, "позиций без вида в каталоге больше нет"
    assert "вида в карточке нет" in правило, (
        "свод не говорит, куда встаёт позиция без вида")
    # У полнокадровой позиции названо, чем она занимает кадр: под ней не видно
    # ни ведущей, ни вставки, и это решает, какой сцене её давать.
    assert "поверх ведущей" in правило, (
        "не сказано, что полнокадровая позиция закрывает ведущую")


def test_образцы_позиций_в_своде_взяты_из_настоящего_каталога(tmp_path):
    """Свод разбирает два примера — счётчик и дифф кода. Имя, вид и слоты в
    разборе обязаны совпадать с карточкой: пример, зовущий позицию, которой в
    каталоге нет или у которой другой вид, учит плану, который заворачивает
    `D36_elements`.
    """
    from reels_factory.hf_catalog import catalog_cards

    cards = catalog_cards()
    раздел = _позиция_каталога(_skill(tmp_path))
    for имя, вид in (("count-up", "effect"), ("v-code-diff", "scene")):
        card = cards.get(имя)
        assert card, f"позиции {имя} в каталоге нет, а свод её разбирает"
        assert card.get("kind") == вид, f"{имя}: вид карточки уже не {вид}"
        assert f"`{имя}`" in раздел, f"свод не разбирает {имя}"
    # Слова показаны хотя бы раз: поле `words` описано форматом с первого дня,
    # и ни один живой прогон его не заполнил — заполненного примера не было.
    слоты = cards["v-code-diff"].get("text_slots") or []
    assert len(слоты) >= 2, "у v-code-diff больше нет слотов под слова"
    assert '"words"' in раздел, "ни один пример свода не заполняет `words`"


def test_фраза_для_поиска_позиции_это_intent_сцены(tmp_path):
    """Шаг 1 просил сочинить фразу про сцену, а такая фраза у сцены уже есть —
    `intent`. Пока они назывались по-разному, поиск шёл до плана и разом на
    весь ролик: dens-A — 2 поиска на 7 сцен, dens-B — 2 на 12, dens-C — 4 на 6,
    и ни один не назван сценой. Второе имя того же — вторая редакция правила.

    Свой поиск у агента теперь второй, а не первый: по словам реплики ищет
    код и печатает найденное под фразой задания (`_phrase_candidates`).
    Причина — те же прогоны: девять живых ранних шагов подряд агент искал
    только по восьми строкам таблицы тегов и ни разу по русскому слову.
    """
    раздел = _позиция_каталога(_skill(tmp_path))
    шаг = раздел.split("1. ")[1].split(chr(10) + "2. ")[0]
    assert "кандидат" in шаг and "`use_when`" in шаг, (
        "шаг 1 не отправляет к кандидатам, найденным кодом")
    assert "этой сцены" in шаг, (
        "не сказано, что кандидаты у каждой сцены свои, а не разом на ролик")
    свой = раздел.split(chr(10) + "2. ")[1].split(chr(10) + "3. ")[0]
    assert "`intent`" in свой, "фраза своего поиска не названа полем плана"
    for name, kw in (("early", {"avatar_ordered": False,
                                "phrases": GAP_PHRASES}),
                     ("ordered", {"clips": CLIPS, "phrases": GAP_PHRASES})):
        шаги = (_text(tmp_path / name, **kw)
                .split("## Порядок работы")[1].split(NEWLINE_HEADING)[0])
        проход = [часть for часть in re.split(r"(?m)^\d+\. ", шаги)
                  if "elements" in часть]
        assert проход and "`intent`" in проход[0], (
            f"{name}: проход по каталогу не называет `intent` сцены")
        assert "что она должна сделать со зрителем" not in проход[0], (
            f"{name}: у порядка работы снова своя редакция фразы поиска")


def test_теги_из_таблицы_есть_в_настоящем_индексе(tmp_path):
    """Задание печатает те же теги, которыми размечен наш каталог: тег,
    которого в индексе нет, отправляет агента искать пустоту.
    """
    from reels_factory.hf_catalog import catalog_cards

    живые = {tag for card in catalog_cards().values()
             for tag in card.get("tags") or []}
    раздел = _позиция_каталога(_skill(tmp_path))
    названные = {piece.strip(" `") for line in раздел.splitlines()
                 if line.startswith("| ") and line.count("|") == 3
                 for piece in line.split("|")[2].split(",")
                 if piece.strip().startswith("`")}
    assert названные, "в таблице не названо ни одного тега"
    assert названные <= живые, (
        f"тегов нет в каталоге: {sorted(названные - живые)}")


def test_таблица_отправляет_искать_и_по_use_when(tmp_path):
    """Строк в таблице восемь, позиций в каталоге полторы сотни.

    Живые ранние шаги dens-A/B/C: агент искал ровно по таблице и упирался в
    её край. Донор B («пять условий успеха ресторана») перебрал все теги
    одной командой, получил `<persisted-output> Output too large`, вторым
    поиском вытащил один `onboarding-stepper-flow` — и каталог для него на
    этом кончился, при том что признак стоял у семи сцен из двенадцати.

    Ответ — не новая строка таблицы под каждый случай, а второй ключ к тому
    же индексу: `use_when` каждой позиции написан теми же словами, какими
    агент пишет `intent`, поэтому `grep` по слову из реплики находит позицию
    и там, где строки в таблице нет. Правило стоит один раз — под таблицей,
    рядом с тем, что оно дополняет.
    """
    раздел = _позиция_каталога(_skill(tmp_path))
    хвост = раздел.split("| имя говорящего")[1].split("Формат:")[0]
    assert "`use_when`" in хвост, (
        "таблица не говорит, что искать можно и по `use_when`")
    assert "`intent`" in хвост, (
        "не сказано, что ищут словом из `intent` сцены")
    assert "grep" in хвост, "не показано, какой командой"
    # И тот же ключ назван в шапке самого индекса — иначе правило свода
    # ссылалось бы на поле, о котором файл молчит.
    from reels_factory.hf_catalog import catalog_index
    assert "`use_when`" in catalog_index(), "шапка индекса про поле молчит"


def test_значок_назван_запасом_а_не_украшением(tmp_path):
    """Условие «уместен на сцене без ведущей и без вставки» не наступает
    никогда: такую сцену агент намеренно не планирует. Значок — ответ на
    «ни одна форма не подходит» и на сцену короче пола любой формы.
    """
    section = _запас(_skill(tmp_path))
    assert "Уместен на сцене без ведущей и без вставки" not in section
    assert "ни на одну форму" in section, (
        "не сказано, что значок берут, когда форма не подошла")
    assert "пола нет" in section, "не сказано, что у значка нет пола сцены"
    assert "Рядом с полнокадровой ведущей код его не ставит" in section
    # Слово `icon` значит в своде правил две разные вещи — поле сцены и имя
    # значка внутри карточки `items`. Разница названа вслух.
    assert "не тот `icon`" in section


def test_значок_описан_так_же_как_ведёт_себя_код(tmp_path):
    """Задание обещало, что значок стоит независимо от вставки, а код теперь
    снимает его там, где вставка приехала (`hf_compose`, цикл значков):
    значок объявлен запасом — пусть им и будет. Расхождение задания с кодом и
    есть та самая тарелка поверх сковороды."""
    section = _запас(_skill(tmp_path))
    assert "Ждать потери вставки он не" not in section, (
        "задание всё ещё обещает значок поверх приехавшей вставки")
    assert "приехала вставка — значка в кадре нет" in section
    # И в закрытом списке средств у значка теперь названо, что должно сойтись.
    средства = _средства(_skill(tmp_path))
    строка = [line for line in средства.splitlines()
              if line.startswith("| значок ")]
    assert строка and "судья принял" in строка[0], (
        "в таблице средств не сказано, что значок отбирает судья")
    assert "вставка сцены не приехала" in строка[0]


def test_запрос_значка_описан_как_запрос_вставки(tmp_path):
    """Судья значков бракует по признакам, которыми управляет сам запрос:
    «restaurant plate fine dining» — сценоописательная фраза, и каталог отдал
    на неё фотографию накрытого стола. У вставки правила запроса есть (длина,
    положительная форма, примеры), у значка их не было."""
    section = _запас(_skill(tmp_path))
    assert "Запрос значка — один предмет, 1–3 слова" in section
    assert "«stopwatch»" in section, "примеров запроса значка нет"
    assert "restaurant plate fine dining" in section, (
        "отказ, стоивший боевого ролика, в задании не назван")


def test_позиции_каталога_в_задание_не_переписываются(tmp_path):
    """«Данные даёт код, не агент», но данными теперь считается индекс рядом, а
    не список в тексте: позиций в каталоге сотни, и переписать их в свод правил
    значит вернуть шестую часть задания, которую агент читал каждый прогон.
    """
    section = _позиция_каталога(_skill(tmp_path))
    # Ни одного имени позиции в самом своде: там метод поиска, а не полка.
    assert "lt-kicker-name" not in section and "camcorder-hud" not in section
    assert "`catalog.index.md`" in section, "куда смотреть, не сказано"


def test_свод_называет_чем_искать_по_индексу(tmp_path):
    """Читать индекс целиком нечем: живой прогон `artyom-early-b4c` получил
    половину файла молча (`catalog_index` держит причину числами). Поэтому шаг
    поиска называет команду, а не «открой файл», и команда ищет тем самым
    тегом, который стоит в таблице признаков рядом.
    """
    раздел = _позиция_каталога(_skill(tmp_path))
    шаг = [line for line in раздел.splitlines() if "grep" in line]
    assert шаг, "чем искать по индексу, в своде не сказано"
    assert "catalog.index.md" in раздел.split("grep")[1][:120], (
        "поиск назван, но не по индексу каталога"
    )
    assert "Открой `catalog.index.md`" not in раздел, (
        "свод всё ещё зовёт открыть индекс целиком"
    )


def test_без_каталога_задание_всё_равно_пишется(monkeypatch, tmp_path):
    """Каталог может быть недоступен (тесты, чужая машина): индекс тогда не
    собирается, но задание остаётся заданием — прогон роняет не это.
    """
    from reels_factory import hf_brief

    def нет_каталога(rdir):
        raise OSError("каталог не разложен реестром")

    monkeypatch.setattr(hf_brief, "write_catalog_files", нет_каталога)
    text = _text(tmp_path)
    assert "Задание на монтаж рилса" in text
    assert not (tmp_path / "catalog.index.md").exists()


def test_краевые_случаи_запаса_показаны_примерами(tmp_path):
    """Канон Anthropic: примеры на краевые случаи, а не на середину. Оба
    краевых случая — из прогона: сцена, мысль которой не ложится ни на одну
    форму, и сцена со вставкой ПОД ведущей.
    """
    section = _запас(_skill(tmp_path))
    примеры = section.count("<example>")
    assert 2 <= примеры <= 5, f"примеров на краевые случаи {примеры}"
    assert "avatarNeeded: true" in section, (
        "не показан краевой случай: вставка под ведущей тоже требует запаса")


def test_образец_даёт_запас_каждой_сцене_со_вставкой(tmp_path):
    """Образец сильнее правила, стоящего рядом. В прогоне он показывал
    `fallback` ровно у одной сцены — той, где `avatarNeeded: false`, — и агент
    воспроизвёл именно эту структуру.
    """
    for name, kw in (("early", {"avatar_ordered": False,
                                "phrases": EVEN_PHRASES}),
                     ("ordered", {"phrases": GAP_PHRASES})):
        board = _board(_text(tmp_path / name, **kw))
        со_вставкой = [s for s in board["scenes"] if s.get("insert")]
        assert со_вставкой, f"{name}: в образце нет сцен со вставкой"
        for scene in со_вставкой:
            assert (scene.get("fallback") or scene.get("icon")
                    or scene.get("overlay")), (
                f'{name}: {scene["id"]} со вставкой и без запаса')


def test_образец_не_называет_вставку_сцене_которую_снимет_отбор(tmp_path):
    """Раздавать вставки штуками, когда гейт считает их по длине, — учить
    плану, который заворачивают.

    Гейт до заказа кредитует только те моменты, что доживут до кадра:
    `survives_series` (hf_montage.py) режет по вилке `SERIES_MIN`–`SERIES_MAX`.
    На медленной речи пара фраз даёт сцену длиннее вилки, и образец ставил ей
    `insert` не глядя — план, срисованный с него, получал от `D34_inserts`
    «названо 3, но 3 из них отбор снимет по длине».
    """
    from reels_factory.hf_montage import survives_series

    for длина in (3.5, 4.0):
        phrases = _фразы(16, длина)
        board = _board(_text(tmp_path / f"i{длина}", phrases=phrases,
                             clips=[], duration=16 * длина,
                             avatar_ordered=False))
        края = {p["id"]: (float(p["start"]), float(p["end"]))
                for p in phrases}
        for scene in board["scenes"]:
            if not scene.get("insert"):
                continue
            размеченная = dict(scene,
                               startSec=края[scene["phrases"][0]][0],
                               endSec=края[scene["phrases"][-1]][1])
            assert survives_series(размеченная), (
                f'фраза {длина} с: образец назвал вставку сцене '
                f'{scene["id"]}, а отбор снимет её по длине')


def test_образец_показывает_значок_там_где_он_встаёт(tmp_path):
    """Приём, которого нет в образце, агент не применяет: значков в плане
    прогона ноль. Показываем его на законном месте — значок не ставится рядом
    с полнокадровой ведущей (`icon_fits`, hf_layout.py).
    """
    from reels_factory.hf_layout import icon_fits

    # Показывается он со второй сцены со вставкой: первая учит запасной схеме,
    # а два одинаковых запаса подряд учили бы, что ответ всегда один.
    for name, kw in (("early", {"avatar_ordered": False,
                                "phrases": FAST_PHRASES}),
                     ("ordered", {"phrases": GAP_PHRASES})):
        board = _board(_text(tmp_path / name, **kw))
        со_значком = [s for s in board["scenes"] if s.get("icon")]
        assert со_значком, f"{name}: образец не показывает `icon` ни разу"
        for scene in со_значком:
            assert str(scene["icon"].get("query") or "").strip(), (
                "значок образца без запроса")
            assert icon_fits(str(scene.get("presenter") or "none")), (
                f'{scene["id"]}: значок стоит там, где код его снимет')


def test_образец_показывает_позицию_каталога(tmp_path):
    """Приёма, которого нет в образце, агент не применяет.

    Три живых ранних шага подряд вернули план без единого `elements`, и
    последний (`artyom-early-b4c`) — уже с чистым заданием и прочитанным
    сводом: транскрипт `5204d33a` не содержит слова «elements» вовсе, а
    заполнены ровно поля образца. Правило про каталог стояло рядом с образцом,
    который опровергал его молчанием.

    Позиция берётся из настоящего каталога и ставится туда, где код найдёт ей
    свободную зону (`effect_zone`); сцену со схемой она не делит — мысль несут
    обе, и образец учил бы набивать кадр, а не выбирать.
    """
    from reels_factory.hf_brief import SAMPLE_ELEMENT
    from reels_factory.hf_catalog import catalog_cards
    from reels_factory.hf_compose import effect_zone

    карточка = catalog_cards().get(SAMPLE_ELEMENT["name"])
    assert карточка, "позиции образца в каталоге нет — образец учит имени в пустоту"
    assert карточка.get("kind") == "effect"
    assert set(SAMPLE_ELEMENT["variables"]) <= set(карточка.get("variables") or {})
    for name, kw in (("early", {"avatar_ordered": False,
                                "phrases": EVEN_PHRASES}),
                     ("ordered", {"phrases": GAP_PHRASES})):
        board = _board(_text(tmp_path / name, **kw))
        с_позицией = [s for s in board["scenes"] if s.get("elements")]
        assert с_позицией, f"{name}: образец не показывает `elements` ни разу"
        for scene in с_позицией:
            assert scene["elements"] == [SAMPLE_ELEMENT], (
                f'{name}: {scene["id"]} называет не ту позицию')
            assert effect_zone(str(scene.get("presenter") or "none")), (
                f'{name}: {scene["id"]} — позиции там некуда встать')
            assert not scene.get("schema"), (
                f'{name}: {scene["id"]} делит кадр между схемой и позицией')


def test_сверка_требует_запас_на_каждой_сцене_а_не_счётом(tmp_path):
    """Диагноз 8 продолжение: «сцен со вставкой ровно столько же, сколько
    сцен с запасом» — счёт, которого в коде нет, и он пропускает план, где
    вставка одной сцены случайно уравновешена запасом совсем другой. Пункт
    сверки требует запас у КАЖДОЙ сцены с `insert`, а не совпадения двух чисел.
    """
    for name, kw in (("early", {"avatar_ordered": False,
                                "phrases": GAP_PHRASES}),
                     ("ordered", {"clips": CLIPS, "phrases": GAP_PHRASES})):
        сверка = _text(tmp_path / name, **kw).split(
            "## Сверка перед сдачей")[1]
        assert "столько же" not in сверка, (
            f"{name}: сверка всё ещё считает запас несуществующим счётом")
        пункты = [part for part in сверка.splitlines()
                  if "`insert`" in part and "запас" in part]
        assert пункты, f"{name}: в сверке нет пункта про запас"
        assert any("каждой сцены" in part for part in пункты), (
            f"{name}: пункт не требует запас у каждой сцены со вставкой")
        assert "где ведущей нет" not in сверка, (
            f"{name}: сверка меряет ту же условную выборку, что и правило")


def test_сверка_требует_след_прохода_по_каталогу(tmp_path):
    """Проход по каталогу был единственным проходом без пункта сверки.

    Счёт по шести живым ранним шагам (density-report): проход по запасу
    держится пунктом сверки и выполнен на всех сценах со вставкой в пяти
    прогонах из шести; у прохода по каталогу пункта не было, и во всех шести
    итоговая реплика агента перечисляла пункты сверки по порядку и каталог не
    называла — включая dens-A-after, где поисков было пять, а элементов ноль.

    Форма — та же, что у пункта про запас: мерка на каждой сцене, а не число
    по ролику. Своего поля у отказа в плане нет и заводить его незачем:
    `intent` агент пишет каждой сцене, и отказ идёт туда же. Гейта пункт не
    заводит — `D36_elements` по-прежнему судит только имя и вид названной
    позиции.
    """
    for name, kw in (("early", {"avatar_ordered": False,
                                "phrases": GAP_PHRASES}),
                     ("ordered", {"clips": CLIPS, "phrases": GAP_PHRASES})):
        сверка = _text(tmp_path / name, **kw).split("## Сверка перед сдачей")[1]
        пункты = [часть for часть in re.split(r"(?m)^\d+\. ", сверка)
                  if "elements" in часть]
        assert пункты, f"{name}: в сверке нет пункта про позицию каталога"
        пункт = пункты[0]
        assert "каждой сцены" in пункт, (
            f"{name}: пункт мерит ролик, а не каждую сцену")
        assert "`intent`" in пункт, (
            f"{name}: пункт не называет, по чему сцену относят к признаку")
        assert "почему её нет" in пункт, (
            f"{name}: пункт не принимает отказ — только названную позицию")
        assert "пересдач" not in пункт and "D36" not in пункт, (
            f"{name}: пункт сверки расширен до гейта")


def test_слои_кадра_названы_одинаково_в_задании_и_своде(tmp_path):
    """Диагноз 11: первое, что агент читает про устройство кадра, беднее того,
    чем он располагает. В задании было три слоя, в своде четыре, а средств
    пять.
    """
    brief = _text(tmp_path)
    skill = _skill(tmp_path)
    слой = brief.split("**Геометрия кадра и разметка**")[1].split("\n- ")[0]
    for средство in ("схема", "плашка", "значок"):
        assert средство in слой, f"в задании слой «{средство}» не назван"
    assert "**схема, плашка или значок**" in skill, (
        "в своде правил слой оформления не назван")


def test_порядок_работы_называет_проход_по_запасу(tmp_path):
    """Канон: последовательные шаги — нумерованным списком, и шага «назови,
    чем закрыт кадр» в нём не было вовсе, хотя промахивается прогон на нём.
    """
    for name, kw in (("early", {"avatar_ordered": False,
                                "phrases": GAP_PHRASES}),
                     ("ordered", {"clips": CLIPS, "phrases": GAP_PHRASES})):
        шаги = _text(tmp_path / name, **kw).split("## Порядок работы")[1]
        шаги = шаги.split("\n## ")[0]
        assert "запас" in шаги, f"{name}: прохода по запасу в шагах нет"


def _ожидаемый_пол_сцен(duration: float, phrases: list[dict]) -> int:
    """То же самое `low`, что считает `write_brief` — пол `min_scenes`,
    зажатый числом фраз."""
    низ = _min_scenes(duration)
    if phrases:
        низ = max(1, min(низ, len(phrases)))
    return низ


#: Три разные длительности и разное число фраз — задача 02 требует, чтобы
#: подстановка сходилась с кодом не на одном частном случае.
_ЗАДАНИЯ = (
    ("короткий", _фразы(8, 2.0), 16.0),
    ("средний", _фразы(16, 3.5), 56.0),
    ("длинный", _фразы(30, 2.0), 60.0),
)


@pytest.mark.parametrize("name, phrases, duration", _ЗАДАНИЯ)
def test_числа_задания_совпадают_с_числами_кода(tmp_path, name, phrases,
                                                duration):
    """Задача 02: каждое число в задании берётся из той же константы или
    функции, которой судит код, а не переписано рядом литералом. Проверяем
    это подстановкой, а не догадкой — пересчитывая те же функции, что и
    `hf_brief`, и ищем ровно их печатное написание в собранном скилле.
    """
    skill = _skill(tmp_path / name, avatar_ordered=False, phrases=phrases,
                   duration=duration)

    low = _ожидаемый_пол_сцен(duration, phrases)
    ждём_вставок = inserts_wanted(list(range(low)))
    assert f"Назови не меньше {ждём_вставок} моментов" in skill, (
        f"{name}: inserts_wanted({low}) = {ждём_вставок} не назван")

    assert f"{_число(SERIES_MIN)}–{_секунды(SERIES_MAX)}" in skill, (
        f"{name}: вилка серии не сходится с SERIES_MIN/SERIES_MAX")

    assert f"не короче {_секунды(MIN_SCENE)}" in skill, (
        f"{name}: пол обычной сцены не сходится с MIN_SCENE")
    assert f"не длиннее {_секунды(MAX_STATIC_SPAN)}" in skill, (
        f"{name}: потолок сцены не сходится с MAX_STATIC_SPAN")
    assert _секунды(MIN_FULLSCREEN_S) in skill, (
        f"{name}: пол сцены без ведущей не сходится с MIN_FULLSCREEN_S")

    ждём_зазор = face_gap(duration)
    assert f"{_секунды(ждём_зазор)} лица" in skill, (
        f"{name}: зазор между сериями не сходится с face_gap({duration})")

    for count in (MINIMUM["pairs"], LIMITS["pairs"]):
        floor = _секунды(min_seconds("pairs", count))
        assert floor in skill, (
            f"{name}: пол `pairs` на {count} строк(и) — {floor} — не назван")


@pytest.mark.parametrize("name, phrases, duration", _ЗАДАНИЯ)
def test_в_задании_нет_старых_литералов_вилки(tmp_path, name, phrases,
                                              duration):
    """Задача 02: «1,5–4 с», «от пяти до восьми» и голое «восьми» — цифры,
    которые код не мерил ничем, и они разошлись бы с любой правкой констант.
    """
    skill = _skill(tmp_path / name, avatar_ordered=False, phrases=phrases,
                   duration=duration)
    for литерал in ("1,5–4", "1,5-4", "от пяти до восьми", "восьми"):
        assert литерал not in skill, f"{name}: старый литерал «{литерал}» вернулся"


def test_раздел_про_правки_кода_после_сдачи_называет_механизмы(tmp_path):
    """Задача 02, пункт 10: тринадцать мест, где код переписывает план после
    сдачи, задание почти не называло. Раздел обязан быть и обязан называть хотя
    бы механизм возврата короткого куска без ведущей — самый дорогой из
    ненаписанных: он добавляет оплаченные секунды поверх решения агента.
    """
    skill = _skill(tmp_path, avatar_ordered=False, phrases=GAP_PHRASES)
    assert "## Что код делает с планом после сдачи" in skill
    раздел = skill.split("## Что код делает с планом после сдачи")[1]
    assert "_restore_short_faceless" in раздел, (
        "механизм возврата короткого куска без ведущей не назван")
    assert _секунды(MIN_FULLSCREEN_S) in раздел, (
        "порог возврата не подставлен из MIN_FULLSCREEN_S")
    for имя in ("settle_schemas", "absorb_scene", "dedupe_neighbours",
                "_fill_frame_holes"):
        assert имя in раздел, f"механизм {имя} не назван в разделе"


#: Реплика донора C, на которой трижды подряд промахивался живой ранний шаг:
#: `v-world-map` находился грепом по тегу `map` и не ставился ни разу, а по
#: русскому слову агент не искал вовсе.
РЕПЛИКА_ПРО_ОБЛАСТИ = "По каждой области. По каждому городу. По каждой школе."


def _фразы_с_репликой(индекс: int) -> list[dict]:
    phrases = [dict(item) for item in _фразы(8)]
    phrases[индекс]["text"] = РЕПЛИКА_ПРО_ОБЛАСТИ
    return phrases


def test_под_фразой_задания_стоят_кандидаты_каталога(tmp_path):
    """Поиск по каталогу делает код и печатает найденное под самой фразой.

    Причина измерена девятью живыми ранними шагами подряд: агент искал только
    по восьми строкам таблицы тегов свода и ни разу по русскому слову реплики,
    хотя `use_when` написан её словами; дословно совпадающую карточку он
    находил дважды и не ставил. Поиск — работа механическая, и она уходит коду,
    как ушли секунды и геометрия (`plan-vs-code-division`).

    Кандидат назван тем, чем по нему решают: имя, вид, `use_when` и слоты с
    переменными. `description` и теги остаются в индексе — они про анимацию.
    """
    from reels_factory.hf_catalog import catalog_cards

    phrases = _фразы_с_репликой(3)
    задание = _text(tmp_path, phrases=phrases, clips=[], duration=16.0,
                    avatar_ordered=False)
    блок = задание.split("## Фразы озвучки")[1].split(NEWLINE_HEADING)[0]
    assert "кандидаты, а не\nрешение" in блок, (
        "не сказано, что это кандидаты, а решение за агентом")
    строки = блок.splitlines()
    начало = next(номер for номер, строка in enumerate(строки)
                  if строка.startswith("- `3`"))
    под = []
    for строка in строки[начало + 1:]:
        if not строка.startswith("  - "):
            break
        под.append(строка)
    assert под, "под фразой не нашлось ни одного кандидата"
    карта = [строка for строка in под if "`v-world-map`" in строка]
    assert карта, f"карта под репликой про области не названа: {под}"
    card = catalog_cards()["v-world-map"]
    assert "(scene)" in карта[0], "у кандидата не назван вид"
    assert card["use_when"] in карта[0], (
        "у кандидата не сказано, что им показывают")
    for slot in card["text_slots"]:
        assert slot in карта[0], f"слот {slot} кандидата не назван"
