"""Монтажная арифметика: серии, планы камеры, ступени масштаба, вспышки."""
import pytest

from reels_factory.hf_montage import (
    MIN_STEP, PLAN_MAX, PLAN_MIN, PUSH_TO,
    check_shots, cut_into_plans, dedupe_neighbours, flash_moments,
    on_screen_seconds, pick_series, shots_for, show_ordered_avatar,
    split_series, zoom_ladder,
)

CLIPS = [{"file": "a.mp4", "start": 0.0, "duration": 30.0}]


def _scene(index, start, end, presenter="pip-br", look="стол"):
    scene = {"id": f"s-{index:02d}", "startSec": start, "endSec": end,
             "presenter": presenter}
    scene["insert"] = ({"shots": [look, f"{look} крупно"], "kind": "video"}
                       if look else None)
    return scene


def _words(pairs):
    return [{"start": start, "end": end, "text": text}
            for start, end, text in pairs]


# ---------- контракт плана ----------

def test_один_план_в_серии_роняет_план():
    scene = {"id": "s-01", "startSec": 0, "endSec": 3.0,
             "insert": {"shots": ["стол"]}}
    with pytest.raises(RuntimeError, match="серией из 2 планов"):
        check_shots([scene])


def test_короткая_дыра_несёт_один_план():
    """Полсекунды на два плана — это мигание, а не монтаж."""
    assert shots_for(_scene(1, 0.0, 0.5)) == 1
    assert shots_for(_scene(1, 0.0, 3.0)) == 2


# ---------- шов внутри серии ----------

def test_шов_серии_садится_на_сильнейшую_паузу():
    scene = _scene(1, 0.0, 5.0)
    words = _words([(0.1, 0.6, "раз"), (0.7, 1.2, "два."),
                    (2.4, 2.9, "три"), (3.0, 3.6, "четыре")])
    shots = split_series(scene, words)
    # пауза после «два.» длиннее и с точкой — шов между 1.2 и 2.4
    assert len(shots) == 2
    assert 1.2 < shots[0][1] < 2.4


def test_шов_не_режет_план_короче_минимального():
    scene = _scene(1, 0.0, 3.0)
    words = _words([(0.1, 0.3, "раз."), (0.4, 2.9, "длинное")])
    shots = split_series(scene, words)
    assert shots[0][1] - shots[0][0] >= 1.2
    assert shots[1][1] - shots[1][0] >= 1.2


# ---------- отбор серий ----------

def test_серии_держат_лицо_между_собой():
    """Две серии подряд без лица между ними — это не монтаж, а мельтешение."""
    scenes = [_scene(0, 0.0, 3.0, "full", None),
              _scene(1, 3.0, 6.0),
              _scene(2, 6.0, 7.5, "full", None),
              _scene(3, 7.5, 10.5),
              _scene(4, 10.5, 30.0, "full", None)]
    kept, report = pick_series(scenes, CLIPS, 30.0)
    # между s-01 и s-03 лица всего 1,5 с — вместе они стоять не могут
    assert len([name for name in kept if name in ("s-01", "s-03")]) == 1
    assert report["dropped"]


def test_отбор_серий_не_снимает_оплаченного_аватара():
    """Прежний отбор уводил самые длинные сцены с бироллом в `none`, чтобы
    аватар не был виден дольше 60 % ролика. Клипы куплены до плана, экономии в
    этом нет ни секунды — есть только оплаченная ведущая, выброшенная из
    кадра."""
    scenes = [_scene(0, 0.0, 3.0, "full", None)]
    start = 3.0
    for index in range(1, 8):                      # семь кандидатов подряд
        scenes.append(_scene(index * 2 - 1, start, start + 3.0))
        scenes.append(_scene(index * 2, start + 3.0, start + 6.0,
                             "full", None))
        start += 6.0
    duration = scenes[-1]["endSec"]
    kept, report = pick_series(scenes, [{"file": "a.mp4", "start": 0.0,
                                         "duration": duration}], duration)
    assert kept
    assert all(str(scene.get("presenter")) != "none" for scene in scenes)
    assert report["avatar_share"] == 1.0
    assert "stripped" not in report


def test_оплаченная_ведущая_возвращается_в_кадр():
    """`none` остаётся только за дырой между островами: там ведущей нет
    физически. На заказанной секунде она встаёт уголком поверх вставки, а без
    вставки — во весь кадр."""
    scenes = [_scene(0, 0.0, 3.0, "none", "рука"),      # заказана, есть вставка
              _scene(1, 3.0, 6.0, "none", None),        # заказана, вставки нет
              _scene(2, 6.0, 9.0, "none", "стол")]      # дыра
    clips = [{"file": "a.mp4", "start": 0.0, "duration": 6.0}]
    lifted = show_ordered_avatar(scenes, clips, 9.0)
    assert lifted == ["s-00", "s-01"]
    assert scenes[0]["presenter"] == "pip-tr"
    assert scenes[1]["presenter"] == "full"
    assert scenes[2]["presenter"] == "none"


def test_аватар_в_уголке_это_аватар_в_кадре():
    """Прежний счёт относил `pip-*` к бироллу: 66 % по бумаге при аватаре,
    которого зритель не терял из виду ни на секунду."""
    scenes = [_scene(0, 0.0, 3.0, "pip-br"),
              _scene(1, 3.0, 6.0, "stack"),
              _scene(2, 6.0, 9.0, "none"),
              _scene(3, 9.0, 12.0, "punch", None)]
    assert on_screen_seconds(scenes) == 9.0


def test_дыра_без_аватара_несёт_серию_вне_очереди():
    """Там ведущей нет физически: без вставки будет чёрный кадр."""
    scenes = [_scene(0, 0.0, 10.0, "full", None),
              _scene(1, 10.0, 12.0, "none", "рука"),
              _scene(2, 12.0, 30.0, "full", None)]
    clips = [{"file": "a.mp4", "start": 0.0, "duration": 10.0}]
    kept, _ = pick_series(scenes, clips, 30.0)
    assert kept == ["s-01"]


def test_одинаковые_куски_разводятся_сменой_кадра():
    """Дешёвое средство: у второй сцены меняется вид кадра, обе остаются на
    месте. Ролику это и на пользу — у ведущей прибавляется положений (D14)."""
    scenes = [_scene(4, 0.0, 1.5, "full", None),
              _scene(5, 1.5, 5.0, "full", None),
              _scene(6, 5.0, 8.0, "none", "стол")]
    clips = [{"file": "a.mp4", "start": 0.0, "duration": 8.0}]
    fixed = dedupe_neighbours(scenes, clips=clips, duration=8.0)
    assert fixed == ["s-05 → punch"]
    assert len(scenes) == 3
    assert scenes[0]["presenter"] != scenes[1]["presenter"]


def test_цепочка_одинаковых_кусков_чередуется():
    """Живой прогон без стока: вставок нет ни у кого, и подряд стоят четыре
    одинаковых куска. Если исключать оба соседних положения, свободных не
    останется ни у одной сцены и цепочка так и стоит одним планом."""
    scenes = [_scene(index, index * 2.0, index * 2.0 + 2.0, "full", None)
              for index in range(1, 5)]
    for scene in scenes:
        scene["phrases"] = [0, 0]
    clips = [{"file": "a.mp4", "start": 0.0, "duration": 10.0}]
    dedupe_neighbours(scenes, clips=clips, duration=10.0)
    assert len(scenes) == 4                       # склейка не понадобилась
    assert [scene["presenter"] for scene in scenes] == [
        "full", "punch", "full", "punch"]


def test_неразводимые_куски_склеиваются_в_один():
    """Обе сцены на дыре без аватара: положение там обязано быть `none`, и
    менять его нечем. Тогда пара становится одним куском — это и предлагала
    сама проверка."""
    scenes = [_scene(1, 0.0, 2.0, "full", None),
              _scene(2, 2.0, 4.0, "none", None),
              _scene(3, 4.0, 6.0, "none", None)]
    for scene in scenes:
        scene["phrases"] = [0, 0]
    # Кадр обеим закрывает значок: иначе они пусты, и разбирает их раньше
    # `settle_empty_frames` — про склейку одинаковых кусков тест был бы не о том.
    for scene in scenes[1:]:
        scene["icon"] = {"query": "bookmark icon"}
    clips = [{"file": "a.mp4", "start": 0.0, "duration": 2.0}]
    dedupe_neighbours(scenes, clips=clips, duration=6.0)
    assert [scene["id"] for scene in scenes] == ["s-01", "s-02"]
    assert scenes[1]["endSec"] == 6.0


def test_первая_сцена_не_склеивается():
    """Ролик обязан открываться лицом — начало не трогаем даже ради D21."""
    scenes = [_scene(1, 0.0, 2.0, "full", None),
              _scene(2, 2.0, 4.0, "full", None)]
    clips = [{"file": "a.mp4", "start": 0.0, "duration": 4.0}]
    dedupe_neighbours(scenes, clips=clips, duration=4.0)
    assert len(scenes) == 2


def test_слишком_длинная_сцена_серию_не_несёт():
    scenes = [_scene(0, 0.0, 3.0, "full", None),
              _scene(1, 3.0, 12.0),
              _scene(2, 12.0, 30.0, "full", None)]
    kept, report = pick_series(scenes, CLIPS, 30.0)
    assert kept == []
    assert any("не серия" in text for text in report["dropped"])


# ---------- планы камеры ----------

def test_планы_режутся_по_сильнейшей_паузе():
    words = _words([(0.0, 0.5, "раз"), (0.6, 1.1, "два"),
                    (1.2, 1.7, "три."), (2.6, 3.1, "четыре"),
                    (3.2, 3.7, "пять"), (3.8, 4.3, "шесть")])
    plans = cut_into_plans(words, 0.0, 5.0)
    assert len(plans) >= 2
    for plan in plans:
        assert plan["end"] > plan["start"]
    # граница после «три.» — там и пауза, и точка; план начинается со слова
    assert any(1.7 < plan["start"] <= 2.6 for plan in plans[1:])


def test_план_не_короче_и_не_длиннее_вилки():
    words = _words([(index * 0.4, index * 0.4 + 0.3, f"с{index}")
                    for index in range(30)])
    plans = cut_into_plans(words, 0.0, 12.0)
    for plan in plans[:-1]:
        size = plan["end"] - plan["start"]
        assert PLAN_MIN - 0.5 <= size <= PLAN_MAX + 0.01


# ---------- ступени масштаба ----------

def test_соседние_ступени_отличаются_не_меньше_чем_на_восемь():
    plans = [{"start": index * 2.0, "end": index * 2.0 + 2.0}
             for index in range(9)]
    ladder = zoom_ladder(plans)
    for left, right in zip(ladder, ladder[1:]):
        assert abs(right["scale_from"] - left["scale_to"]) >= MIN_STEP - 1e-9


def test_наезд_не_чаще_каждого_третьего_плана():
    plans = [{"start": index * 2.0, "end": index * 2.0 + 2.0}
             for index in range(9)]
    ladder = zoom_ladder(plans)
    pushes = [index for index, plan in enumerate(ladder)
              if plan["kind"] == "push"]
    assert pushes == [0, 3, 6]
    assert ladder[0]["scale_to"] == PUSH_TO


def test_в_окне_уголке_наезда_нет():
    """18 % прироста на окне в 312 px — три пикселя, их никто не увидит."""
    plans = [{"start": 0.0, "end": 2.0}, {"start": 2.0, "end": 4.0}]
    ladder = zoom_ladder(plans, big=[False, False])
    assert all(plan["kind"] == "static" for plan in ladder)


# ---------- вспышки ----------

def test_вспышек_не_больше_двух():
    plans = zoom_ladder([{"start": index * 2.0, "end": index * 2.0 + 2.0}
                         for index in range(12)])
    assert len(flash_moments(plans, climax=5.0, duration=24.0)) <= 2


def test_вспышка_только_на_возврате_после_крупного():
    plans = [{"start": 0.0, "end": 2.0, "kind": "static",
              "scale_from": 1.08, "scale_to": 1.08},
             {"start": 2.0, "end": 4.0, "kind": "static",
              "scale_from": 1.0, "scale_to": 1.0}]
    assert flash_moments(plans, duration=10.0) == []
    plans[0]["scale_from"] = plans[0]["scale_to"] = 1.18
    assert flash_moments(plans, duration=10.0) == [2.0]


def test_кульминация_агента_идёт_первой():
    plans = zoom_ladder([{"start": index * 2.0, "end": index * 2.0 + 2.0}
                         for index in range(12)])
    assert 7.0 in flash_moments(plans, climax=7.0, duration=24.0)


def test_снятая_серия_возвращает_ведущую_в_кадр():
    """Ведущая в уголке без вставки — чёрный прямоугольник на остальном
    кадре, и это ловит их же аудит переполнения (наш D20)."""
    from reels_factory.hf_montage import drop_series

    scenes = [_scene(0, 0.0, 3.0, "full", None),
              _scene(1, 3.0, 6.0, "pip-br"),
              _scene(2, 6.0, 9.0, "stack"),
              _scene(3, 9.0, 12.0, "none")]
    clips = [{"file": "a.mp4", "start": 0.0, "duration": 12.0}]
    dropped = drop_series(scenes, kept=["s-03"], clips=clips, duration=12.0)
    assert dropped == ["s-01", "s-02"]
    assert scenes[1]["presenter"] == "punch"     # у соседа слева `full`
    assert scenes[2]["presenter"] == "full"      # у соседа слева уже `punch`
    assert scenes[3]["presenter"] == "none"      # оставленная серия не тронута
    assert scenes[3]["insert"] is not None


def test_снятая_серия_на_дыре_не_оставляет_пустого_кадра():
    """Сцена без ведущей теряла серию и показывала голый фон с титром: ветка
    `none` просто пропускалась. Прогон 28 поймал это гейтом D25. `none` здесь
    законен: аватар на этот кусок не заказывали.

    Закрывалось это `needsSchema` вслепую, и прогон hf-live2 показал цену: без
    `fallback` флаг ставился всё равно, схема не собиралась, а гейты читали
    флаг и говорили PASS. Теперь пустую сцену разбирает `settle_empty_frames`
    в том же порядке шагов, что и сборка (hf_render.py): снять серию — свести
    последствия."""
    from reels_factory.hf_montage import dedupe_neighbours, drop_series

    # Клип кончается на 2,0 с: дальше дыра, и обе сцены на ней. Секунды
    # опустевшей уходят соседке по ту же сторону границы — ведущую на дыру не
    # растягивают.
    scenes = [_scene(0, 0.0, 2.0, "full", None),
              _scene(1, 2.0, 4.0, "none"),
              _scene(2, 4.0, 6.0, "none")]
    for index, scene in enumerate(scenes):
        scene["phrases"] = [index, index]
    clips = [{"file": "a.mp4", "start": 0.0, "duration": 2.0}]
    drop_series(scenes, kept=["s-01"], clips=clips, duration=6.0)
    assert scenes[2]["presenter"] == "none"
    assert not scenes[2].get("needsSchema")

    dedupe_neighbours(scenes, clips=clips, duration=6.0)
    assert [scene["id"] for scene in scenes] == ["s-00", "s-01"]
    assert scenes[1]["endSec"] == 6.0
    assert scenes[0]["endSec"] == 2.0, "ведущую растянули на дыру"


def test_снятая_серия_на_оплаченном_куске_держит_ведущую():
    """Тот же случай, но аватар на этих секундах куплен: прятать его — значит
    выбросить деньги. Кадр закрывает запасная схема, ведущая остаётся."""
    from reels_factory.hf_montage import drop_series

    scenes = [_scene(0, 0.0, 3.0, "full", None),
              _scene(1, 3.0, 6.0, "none")]
    scenes[1]["fallback"] = {"form": "steps", "why": "порядок",
                             "nodes": ["кто", "что"]}
    clips = [{"file": "a.mp4", "start": 0.0, "duration": 6.0}]
    drop_series(scenes, kept=[], clips=clips, duration=6.0)
    assert scenes[1]["presenter"] in ("pip-br", "pip-bl")
    assert scenes[1]["needsSchema"] is True


def test_нижний_уголок_переживает_потерю_биролла():
    """Единственная раскладка агента, которая остаётся: схема стоит в верхней
    трети, нижний уголок с ней не пересекается. Заодно у ролика сохраняется
    третье окно ведущей, которого требует приёмка (D14)."""
    from reels_factory.hf_montage import drop_series

    scenes = [_scene(0, 0.0, 3.0, "full", None),
              _scene(1, 3.0, 6.0, "pip-br")]
    scenes[1]["fallback"] = {"form": "steps", "why": "порядок",
                             "nodes": ["кто", "что"]}
    clips = [{"file": "a.mp4", "start": 0.0, "duration": 6.0}]
    drop_series(scenes, kept=[], clips=clips, duration=6.0)
    assert scenes[1]["presenter"] == "pip-br"
    assert scenes[1]["needsSchema"] is True


def test_без_запасной_схемы_уголок_уходит_под_полный_кадр():
    from reels_factory.hf_montage import drop_series

    scenes = [_scene(0, 0.0, 3.0, "full", None),
              _scene(1, 3.0, 6.0, "pip-br")]
    clips = [{"file": "a.mp4", "start": 0.0, "duration": 6.0}]
    drop_series(scenes, kept=[], clips=clips, duration=6.0)
    assert scenes[1]["presenter"] == "punch"
    assert not scenes[1].get("needsSchema")


@pytest.fixture
def каталог(monkeypatch):
    """Виды позиций берём из фикстурного каталога: `count-up` — `effect`."""
    from pathlib import Path

    from reels_factory import hf_catalog, hf_montage

    корень = Path(__file__).resolve().parent / "fixtures" / "catalog"
    cards = hf_catalog.catalog_cards
    monkeypatch.setattr(hf_montage, "_element_kinds",
                        lambda: {name: card.get("kind")
                                 for name, card in cards(корень).items()})


def test_снятая_серия_не_отнимает_зону_у_элемента(каталог):
    """Пересборка `artyom-rebuild-4b`: `count-up` стоял на сцене `pip-br`,
    ранняя сверка признала зону (`effect_zone("pip-br")` — не `None`), а
    дальше отбор серий по бюджету снял со сцены вставку. Код считал кадр
    пустым и поднимал ведущую во весь кадр — после чего сборка снимала
    элемент, для которого зоны уже не осталось, и в ролик он не попал.

    Элемент кадр закрывает (`filling_element`, тот же счёт у D20 и D25),
    значит досыпать в такую сцену нечего: положение агента остаётся, запасная
    схема не включается — она встала бы прямо на элемент.
    """
    from reels_factory.hf_compose import effect_zone
    from reels_factory.hf_montage import drop_series

    scenes = [_scene(0, 0.0, 3.0, "full", None),
              _scene(1, 3.0, 6.0, "pip-br")]
    scenes[1]["elements"] = [{"name": "count-up",
                              "variables": {"end": 12, "suffix": " раз в год"}}]
    scenes[1]["fallback"] = {"form": "steps", "why": "порядок",
                             "nodes": ["кто", "что"]}
    clips = [{"file": "a.mp4", "start": 0.0, "duration": 6.0}]
    drop_series(scenes, kept=[], clips=clips, duration=6.0)
    assert scenes[1]["presenter"] == "pip-br", "положение агента переписано"
    assert effect_zone(scenes[1]["presenter"]) is not None, (
        "зоны под элемент в кадре не осталось")
    assert scenes[1]["elements"], "элемент выброшен из плана"
    assert not scenes[1].get("needsSchema"), (
        "запасная схема встала бы поверх элемента: обе занимают кадр выше "
        "полосы титра")


def test_без_элемента_снятая_серия_поднимает_ведущую_как_прежде(каталог):
    """Та же сцена без элемента: кадр после снятой вставки правда пуст, и
    закрывать его нечем, кроме ведущей."""
    from reels_factory.hf_montage import drop_series

    scenes = [_scene(0, 0.0, 3.0, "full", None),
              _scene(1, 3.0, 6.0, "pip-br")]
    clips = [{"file": "a.mp4", "start": 0.0, "duration": 6.0}]
    drop_series(scenes, kept=[], clips=clips, duration=6.0)
    assert scenes[1]["presenter"] == "punch"


def test_разводя_соседей_код_оставляет_элементу_зону(каталог):
    """Второе место, где переписывается положение: `dedupe_neighbours`. Оно
    спрашивает те же `positions_for`, и уголки там остаются — иначе развод
    пары стоил бы элемента."""
    from reels_factory.hf_compose import effect_zone
    from reels_factory.hf_montage import dedupe_neighbours

    scenes = [_scene(0, 0.0, 3.0, "pip-br", None),
              _scene(1, 3.0, 6.0, "pip-br", None)]
    for scene in scenes:
        scene["elements"] = [{"name": "count-up"}]
    clips = [{"file": "a.mp4", "start": 0.0, "duration": 6.0}]
    dedupe_neighbours(scenes, clips=clips, duration=6.0)
    assert len(scenes) == 2, "пару склеили вместо развода положением"
    assert scenes[0]["presenter"] != scenes[1]["presenter"]
    for scene in scenes:
        assert effect_zone(scene["presenter"]) is not None, scene["id"]


def test_зазор_взят_у_неё_но_считается_долей():
    """Планка её — «между сериями лицо ≥2,5 с», и снята она с эталонов длиной
    41,5 с. Секундой её держать нельзя: на 30-секундном ролике те же 2,5 с
    съедают вдвое большую долю и выбрасывают половину бироллов."""
    from reels_factory.hf_montage import face_gap

    assert round(face_gap(41.5), 2) == 2.5      # на эталоне — ровно её число
    assert face_gap(30.0) < 2.5                 # короткий ролик дышит чаще
    assert face_gap(120.0) == 3.5               # длинный не превращается в клип
    assert face_gap(0.0) == 1.5                 # вырожденный случай не роняет


def test_зазор_округлён_до_десятой():
    """Задание печатает зазор через `hf_montage_skill.number` — одна десятая
    секунды, а отбор серий (`spaced` в `pick_series`) судит `face_gap(duration)`
    тем же значением. Раньше функция возвращала 2,4096..., текст печатал
    «2,4 с», и число в тексте не было числом, которым судят план."""
    from reels_factory.hf_montage import face_gap

    # 2,5 / 41,5 * 40 = 2,409638... — без округления не совпало бы с печатью.
    value = face_gap(40.0)
    assert value == round(value, 1)
    assert value == 2.4


def test_соседние_бироллы_склеиваются_в_одну_серию():
    """Агент ставит моменты подряд там, где подряд идёт мысль, а отбор разводил
    такие пары силой — вторая теряла биролл. Пара становится одной серией."""
    from reels_factory.hf_montage import merge_adjacent_series, shot_queries

    scenes = [_scene(0, 0.0, 2.0, "full", None),
              _scene(1, 2.0, 4.4, "none"),
              _scene(2, 4.4, 6.8, "none"),
              _scene(3, 6.8, 9.0, "full", None)]
    scenes[1]["insert"] = {"shots": ["hands typing", "hands typing closeup"],
                           "kind": "video"}
    scenes[2]["insert"] = {"shots": ["phone in hand", "phone closeup"],
                           "kind": "video"}
    scenes[1]["phrases"], scenes[2]["phrases"] = [1, 1], [2, 2]

    merged = merge_adjacent_series(scenes)

    assert merged == ["s-02"]
    assert len(scenes) == 3
    assert scenes[1]["endSec"] == 6.8
    assert scenes[1]["phrases"] == [1, 2]
    assert shot_queries(scenes[1]) == ["hands typing", "phone in hand"]


def test_слишком_длинная_пара_не_склеивается():
    """Больше SERIES_MAX — это два стоячих плана, а не монтаж."""
    from reels_factory.hf_montage import merge_adjacent_series

    scenes = [_scene(0, 0.0, 4.0, "none"), _scene(1, 4.0, 8.0, "none")]
    scenes[0]["insert"] = {"shots": ["a", "a2"], "kind": "video"}
    scenes[1]["insert"] = {"shots": ["b", "b2"], "kind": "video"}

    assert merge_adjacent_series(scenes) == []
    assert len(scenes) == 2


def test_потолок_аватара_шестьдесят_процентов():
    """Требование заказчика 10.08.2026: секунда аватара — главные деньги
    ролика. Потолок остался прежним, но меряет теперь заказ, а не показ:
    клипы покупаются до плана, и спрятанная ведущая ничего не сберегает."""
    from reels_factory.hf_montage import AVATAR_ON_SCREEN_MAX

    assert AVATAR_ON_SCREEN_MAX == 0.60


def test_короткая_схема_отдаёт_сцену_соседке():
    """Пересборка 462a1c62: `steps` из двух узлов встал на сцену 2,1 с при поле
    2,8 с. Схема снималась уже в кадре, и сцена без ведущей оставалась с одним
    фоном — обрыв рассказа, который ловит D25 после сборки."""
    from reels_factory.hf_montage import settle_schemas

    scenes = [{"id": "s-01", "startSec": 0.0, "endSec": 3.0,
               "presenter": "full", "phrases": [0, 1], "insert": None},
              {"id": "s-02", "startSec": 3.0, "endSec": 5.1,
               "presenter": "none", "phrases": [2, 2], "insert": None,
               "schema": {"form": "steps", "why": "порядок",
                          "nodes": ["кто", "что"]}}]
    settled = settle_schemas(scenes)

    assert settled == ["s-02 → соседке"]
    assert [scene["id"] for scene in scenes] == ["s-01"]
    assert scenes[0]["endSec"] == 5.1
    assert scenes[0]["phrases"] == [0, 2]


def test_схема_снимается_когда_соседки_нет():
    """Слить не с кем — тогда схему снимаем, а кадр закрывает ведущая."""
    from reels_factory.hf_montage import settle_schemas

    scenes = [{"id": "s-01", "startSec": 0.0, "endSec": 2.0,
               "presenter": "pip-br", "phrases": [0, 0], "insert": None,
               "schema": {"form": "items", "why": "набор",
                          "items": [{"label": "а", "icon": "поиск"}] * 3}}]
    settle_schemas(scenes)

    assert "schema" not in scenes[0]
    assert scenes[0]["presenter"] in ("full", "punch")


def test_запасной_схеме_меряют_секунды_как_своей():
    """Пол формы `steps` на три узла — 4,0 с (hf_schema.py:68). Пока проход
    смотрел одно поле `schema`, запасная схема из `fallback` доезжала
    неизмеренной до `build_composition` и снималась уже там — после всех
    чинящих проходов. Сцена на дыре без аватара оставалась с фоном и титром, и
    D25 валил сборку за то, чего агент не делал: `fallback` у него заполнен."""
    from reels_factory.hf_montage import settle_schemas

    scenes = [{"id": "s-01", "startSec": 0.0, "endSec": 3.0,
               "presenter": "full", "phrases": [0, 1], "insert": None},
              {"id": "s-02", "startSec": 3.0, "endSec": 5.1,
               "presenter": "none", "phrases": [2, 2], "insert": None,
               "needsSchema": True,
               "fallback": _запасная("раз", "два", "три")}]

    assert settle_schemas(scenes) == ["s-02 → соседке"]
    assert [scene["id"] for scene in scenes] == ["s-01"]


def test_снятая_запасная_схема_называет_причину(capsys):
    """Отдать секунды некому — схему снимаем, и в логе стоит, чего не хватило:
    та же строка, что печатала сборка."""
    from reels_factory.hf_montage import settle_schemas

    scenes = [{"id": "s-01", "startSec": 0.0, "endSec": 2.0,
               "presenter": "none", "phrases": [0, 0], "insert": None,
               "needsSchema": True,
               "fallback": _запасная("раз", "два", "три")}]
    settle_schemas(scenes)

    assert "needsSchema" not in scenes[0]
    сказано = capsys.readouterr().out
    assert "steps" in сказано and "4.0" in сказано


def test_план_с_четырьмя_вставками_возвращается_на_доработку():
    """Пересборка 462a1c62: план назвал четыре момента вместо пяти, до кадра
    дошли две вставки, и ролик встал одним планом на 8,1 с при пределе 8.
    Проверка стоит до подбора и до рендера — цена ошибки одна попытка плана, а
    не полный прогон."""
    from reels_factory.hf_montage import check_inserts

    scenes = [_scene(index, index * 3.0, index * 3.0 + 3.0,
                     "pip-tr" if index < 4 else "full",
                     "рука" if index < 4 else None)
              for index in range(10)]
    with pytest.raises(RuntimeError, match="вставок в плане 4"):
        check_inserts(scenes)

    scenes[4]["insert"] = {"shots": ["стол", "стол крупно"], "kind": "video"}
    check_inserts(scenes)


def test_дозаказный_счёт_вставок_смотрит_длину_сцены():
    """Отбор серий режет кандидатов по длине (окно 2,4–6,0 с), а дозаказный
    счёт считал их штуками. План из сцен по 7,0 с проходил проверку целиком,
    терял в `pick_series` все четыре вставки и всплывал гейтом D15 — уже после
    того, как клипы у HeyGen куплены."""
    from reels_factory.hf_montage import check_inserts, pick_series

    scenes = [_scene(index, index * 7.0, index * 7.0 + 7.0,
                     "stack" if index < 4 else "full",
                     "рука" if index < 4 else None)
              for index in range(8)]
    clips = [{"file": "a.mp4", "start": 0.0, "duration": 56.0}]

    kept, _ = pick_series(scenes, clips, 56.0)
    assert kept == [], "сцену длиннее серии отбор не берёт"

    with pytest.raises(RuntimeError, match="отбор снимет по длине"):
        check_inserts(scenes)

    # Та же длина, но аватара на этих секундах не заказывали: отбор берёт такую
    # сцену вне очереди — иначе кадр там чёрный, — и счёт обязан её кредитовать.
    for scene in scenes[:4]:
        scene["avatarNeeded"] = False
    check_inserts(scenes)


def test_секунды_дыры_не_растягивают_соседку_с_ведущей():
    """Соседка с живой ведущей, доросшая до куска, где аватара нет физически,
    законного положения не имеет вовсе: с ведущей её валит D12, без ведущей —
    D25. Поэтому секунды пустой сцены на дыре она не принимает, и сцена
    остаётся гейтам."""
    from reels_factory.hf_layout import avatar_gaps
    from reels_factory.hf_montage import settle_empty_frames

    scenes = [_scene(0, 0.0, 3.0, "full", None),
              {"id": "s-01", "startSec": 3.0, "endSec": 5.0,
               "presenter": "none", "insert": None, "phrases": [1, 1]}]
    scenes[0]["phrases"] = [0, 0]
    clips = [{"file": "a.mp4", "start": 0.0, "duration": 3.0}]

    settled = settle_empty_frames(scenes, avatar_gaps(clips, 5.0))

    assert settled == []
    assert [scene["id"] for scene in scenes] == ["s-00", "s-01"]
    assert scenes[0]["endSec"] == 3.0, "ведущую растянули через границу острова"


def test_на_коротком_ролике_пяти_вставок_не_требуют():
    """Пол считается от числа сцен: четырёх сцен со вставкой в трёх сценах не
    бывает, и требовать их — требовать невозможного."""
    from reels_factory.hf_montage import check_inserts

    check_inserts([_scene(0, 0.0, 3.0, "pip-tr", "рука"),
                   _scene(1, 3.0, 6.0, "pip-tl", "стол"),
                   _scene(2, 6.0, 9.0, "full", None)])


# ---------- чем закрыт кадр после того, как код снял вставку ----------

def _запасная(*nodes):
    """Запасная схема в её нынешней форме — той, которую собирает hf_schema."""
    return {"form": "steps", "why": "порядок шагов", "nodes": list(nodes)}


def test_запасная_схема_агента_идёт_в_дело():
    """Поле `fallback` было парой {бренд, значок} и стало схемой с `form`, а
    `refill_scene` до сих пор искал ключи `logo`/`icon` — то есть не находил
    ничего никогда. В прогоне hf-live2 так молча выброшены обе запасные схемы,
    которые агент написал (s-04 `pairs`, s-06 `steps`)."""
    from reels_factory.hf_montage import drop_series

    scenes = [_scene(0, 0.0, 3.0, "full", None),
              _scene(1, 3.0, 6.0, "pip-br")]
    scenes[1]["fallback"] = _запасная("кто", "что")
    clips = [{"file": "a.mp4", "start": 0.0, "duration": 6.0}]
    drop_series(scenes, kept=[], clips=clips, duration=6.0)
    assert scenes[1]["presenter"] == "pip-br"
    assert scenes[1]["needsSchema"] is True


def test_просьба_о_схеме_без_запасной_не_выставляется():
    """Ветка дыры ставила `needsSchema` любой безлицой сцене, не глядя, есть ли
    чем эту схему нарисовать: `schema_plan` возвращал None, в кадр не вставало
    ничего, а гейты читали флаг и говорили PASS."""
    from reels_factory.hf_montage import refill_scene

    scenes = [_scene(0, 0.0, 3.0, "full", None),
              _scene(1, 3.0, 6.0, "none", None)]
    refill_scene(scenes, 1, [(3.0, 6.0)])
    assert scenes[1]["presenter"] == "none"
    assert not scenes[1].get("needsSchema")


def test_чем_закрыт_кадр_называется_одним_словом():
    from reels_factory.hf_montage import frame_filler

    пусто = {"id": "s-07", "presenter": "none", "insert": None}
    assert frame_filler(пусто) == ""
    assert frame_filler({**пусто, "presenter": "pip-br"}) == "ведущая"
    assert frame_filler({**пусто, "insert": {"shots": ["a", "b"]}}) == "вставка"
    assert frame_filler({**пусто, "needsSchema": True,
                         "fallback": _запасная("раз", "два")}) == "схема"
    assert frame_filler({**пусто, "needsSchema": True,
                         "fallback": {"logo": "notion"}}) == ""
    assert frame_filler({**пусто, "icon": {"query": "bookmark"}}) == "значок"
    assert frame_filler({**пусто, "overlay": {"block": "lt-kicker-name"}}) == "плашка"


def test_сцена_без_чем_закрыть_кадр_отдаётся_соседке():
    """Дефект прогона hf-live2 целиком: сцена на дыре аватара потеряла серию
    (её планы пришли побайтными дублями), закрыть кадр было нечем — и зритель
    получил 2,7 с фона с титром. Секунды уходят соседке, чей кадр занят — и
    соседка эта по ту же сторону границы острова: клип кончается на 3,0 с, и
    принять секунды дыры может только та, что сама на дыре."""
    from reels_factory.hf_montage import dedupe_neighbours

    scenes = [_scene(0, 0.0, 3.0, "full", None),
              {"id": "s-01", "startSec": 3.0, "endSec": 5.7, "presenter": "none",
               "insert": None, "phrases": [1, 1]},
              _scene(2, 5.7, 8.0, "none")]
    scenes[0]["phrases"], scenes[2]["phrases"] = [0, 0], [2, 2]
    clips = [{"file": "a.mp4", "start": 0.0, "duration": 3.0}]

    dedupe_neighbours(scenes, clips=clips, duration=8.0)

    assert [scene["id"] for scene in scenes] == ["s-00", "s-02"]
    assert scenes[0]["endSec"] == 3.0, "ведущую растянули на дыру"
    assert scenes[1]["startSec"] == 3.0
    assert scenes[1]["phrases"] == [1, 2]


def test_соседки_нет_и_пустая_сцена_остаётся_гейтам():
    """Отдать некому — сцена живёт дальше пустой, и это не молчаливый выпуск:
    её ловят D25 по раскадровке и D26 по собранной композиции."""
    from reels_factory.hf_montage import dedupe_neighbours, frame_filler

    scenes = [{"id": "s-00", "startSec": 0.0, "endSec": 9.0, "presenter": "none",
               "insert": None, "phrases": [0, 3]}]
    dedupe_neighbours(scenes, clips=[], duration=9.0)
    assert len(scenes) == 1
    assert frame_filler(scenes[0]) == ""
