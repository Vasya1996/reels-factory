"""Композицию собирает код: слои кадра, ведущая, вставки, субтитры, звук."""
import json
import re
import shutil
from pathlib import Path

import pytest

from reels_factory import hf_compose
from reels_factory.hf_compose import (
    build_composition, collect_intents, complete_storyboard, icon_intents,
    presenter_timeline, settle_inserts,
)
from reels_factory.hf_layout import VIDEO_RECTS
from reels_factory.hf_sdk import sdk_session

CLIPS = [{"file": "clips/clip-00.mp4", "start": 0.0, "duration": 6.0}]
WORDS = [{"start": 0.2, "end": 0.6, "text": "Все"},
         {"start": 0.6, "end": 1.1, "text": "продажи"},
         {"start": 4.0, "end": 4.4, "text": "точка"}]


def _board(scenes):
    return {"schemaVersion": 3,
            "composition": {"fps": 30, "width": 1080, "height": 1920,
                            "durationSeconds": 6.0, "layout": "portrait"},
            "videoTrack": {"sourcePath": "clips/clip-00.mp4", "startSec": 0,
                           "endSec": 6.0,
                           "bounds": {"x": 0, "y": 0, "width": 1080, "height": 1920}},
            "subtitles": {"enabled": True},
            "scenes": scenes}


@pytest.fixture
def run(tmp_path, monkeypatch):
    (tmp_path / "public").mkdir(parents=True)
    # Блок вспышки ставит `hyperframes add` перед сборкой; здесь его заменяет
    # заглушка — иначе любая сборка, где вспышка встала, падала бы на его
    # отсутствии, а не на том, что проверяет тест.
    blocks = tmp_path / "public" / "compositions"
    blocks.mkdir(parents=True, exist_ok=True)
    (blocks / "editorial-flash-overlay.html").write_text(
        '<div data-composition-id="editorial-flash-overlay" data-duration="4">'
        "</div><script>window.__timelines = {};</script>", encoding="utf-8")
    monkeypatch.setattr(hf_compose, "write_caption_data",
                        lambda public, **kw: public / "caption-data.json")
    monkeypatch.setattr(hf_compose, "caption_snippet",
                        lambda sdk, public, **kw: '<div id="highlight"></div>')
    return tmp_path


def _shots(first, second, kind="photo"):
    """Серия из двух планов — единственная форма вставки."""
    return {"shots": [first, second], "kind": kind}


def _found(scene_id, *files):
    return {f"{scene_id}::shot{shot}": {"file": file}
            for shot, file in enumerate(files)}


SCENES = [
    {"id": "s-01", "intent": "хук", "startSec": 0, "endSec": 3.033,
     "presenter": "full", "insert": None},
    {"id": "s-02", "intent": "разбор", "startSec": 3.033, "endSec": 6.0,
     "presenter": "pip-br",
     "insert": _shots("переговоры в офисе", "рука листает бумаги")},
]

FOUND = _found("s-02", ".media/images/a.jpg", ".media/images/b.jpg")


def _build(tmp_path, scenes=None, resolved=None, face=None):
    board = _board(json.loads(json.dumps(scenes or SCENES)))
    with sdk_session() as sdk:
        build_composition(tmp_path, sdk, storyboard=board, clips=CLIPS,
                          duration=6.0, words=WORDS,
                          resolved=FOUND if resolved is None else resolved,
                          face=face)
    return (tmp_path / "public" / "index.html").read_text(encoding="utf-8"), board


# ---------- слои кадра ----------

def test_биролл_встаёт_серией_из_двух_планов(run):
    """Одиночной вставки не бывает: биролл входит в кадр серией."""
    html, _ = _build(run)
    assert 'id="ins-s-02-0" class="ins clip"' in html
    assert 'id="ins-s-02-1" class="ins clip"' in html
    assert 'src=".media/images/a.jpg"' in html
    assert 'src=".media/images/b.jpg"' in html
    # обёртка несёт время, медиа внутри — только картинку: клип обязан быть
    # прямым потомком корня композиции
    assert 'data-start="3.0333"' in html


def test_вставка_под_ведущей_в_углу_занимает_весь_кадр(run):
    html, _ = _build(run)
    layer = html[html.index('id="ins-s-02-0"'):]
    assert "left:0px;top:0px;width:1080px;height:1920px" in layer[:300]


def test_вставка_дополняет_ведущую_в_половине_кадра(run):
    scenes = json.loads(json.dumps(SCENES))
    scenes[1]["presenter"] = "stack"
    html, _ = _build(run, scenes=scenes)
    layer = html[html.index('id="ins-s-02-0"'):]
    assert "top:844px" in layer[:300]


def test_ведущей_в_нижней_половине_кадра_больше_нет():
    """`split` сажал её лицо ровно в полосу титра — D8 валился всегда."""
    from reels_factory.hf_layout import PRESENTER_POSITIONS, insert_rect

    assert "split" not in PRESENTER_POSITIONS
    assert insert_rect("split") is None


def test_вставка_при_ведущей_во_весь_кадр_роняет_сборку(run):
    """Поставить её некуда — она закрыла бы собой ведущую."""
    scenes = json.loads(json.dumps(SCENES))
    scenes[1]["presenter"] = "full"
    with pytest.raises(RuntimeError, match="вставке места нет"):
        _build(run, scenes=scenes)


def test_ведущая_лежит_выше_вставки_в_разметке(run):
    """Порядок отрисовки держит z-index, но и порядок в DOM повторяет его."""
    html, _ = _build(run)
    assert html.index('id="ins-s-02-0"') < html.index('id="video-wrap"')


def test_планы_разложены_по_дорожкам_по_три(run):
    """Четвёртый на одной дорожке — предупреждение `timeline_track_too_dense`,
    а под `--strict` предупреждение роняет сборку."""
    scenes, resolved = [], {}
    for index in range(4):
        start = round(index * 2.6, 3)
        scenes.append({"id": f"s-{index:02d}", "intent": "и",
                       "startSec": start, "endSec": round(start + 2.6, 3),
                       "presenter": "pip-br",
                       "insert": _shots(f"план {index} а", f"план {index} б")})
        resolved.update(_found(f"s-{index:02d}", f"{index}a.jpg", f"{index}b.jpg"))
    html, _ = _build(run, scenes=scenes, resolved=resolved)
    tracks = [html[m:m + 30] for m in range(len(html))
              if html.startswith('data-track-index="', m)]
    used = {t.split('"')[1] for t in tracks}
    assert {"3", "4", "5"} <= used


def test_шов_внутри_серии_а_на_краях_жёсткая_склейка(run):
    """Правило Юли: вход в серию и выход из неё — hard cut, движение живёт
    только на шве между двумя планами."""
    html, _ = _build(run)
    # первый план приходит без анимации
    assert 'tl.fromTo("#ins-s-02-0' not in html
    # шов: первый уезжает, второй приезжает их cut-the-curve
    assert 'tl.to("#ins-s-02-0 .ins-media", { x: -230' in html
    assert ('tl.fromTo("#ins-s-02-1 .ins-media", { x: 230, autoAlpha: 0.35 }'
            in html)
    assert '"power4.out"' in html
    # последний план серии не продлевается: выход жёсткой склейкой
    assert 'tl.to("#ins-s-02-1 .ins-media", { x:' not in html


def test_смена_главы_едет_вертикально(run):
    scenes = json.loads(json.dumps(SCENES))
    scenes[1]["beat"] = "turn"
    html, _ = _build(run, scenes=scenes)
    assert 'tl.fromTo("#ins-s-02-1 .ins-media", { y: -230' in html


def test_уходящий_план_живёт_дольше_на_время_шва(run):
    """«Outgoing scene content must be fully visible when the transition
    starts» — уходящий план живёт дольше своего куска на время шва."""
    html, _ = _build(run)
    # сцена 3.033–6.0, шов посередине, первый план продлён на 0.3
    first = html[html.index('id="ins-s-02-0"'):]
    assert 'data-start="3.0333"' in first[:400]
    # соседние планы на разных дорожках — пересечение на шве легально
    assert 'data-track-index="3"' in html and 'data-track-index="4"' in html


def test_кульминация_ставит_вспышку_из_их_каталога(run, monkeypatch):
    """Их накладка сабкомпозицией: копия под сцену, канвас 1920x1080 вписан
    обёрткой с transform, пик вспышки приходит на стык."""
    scenes = json.loads(json.dumps(SCENES))
    scenes[1]["beat"] = "climax"
    html, _ = _build(run, scenes=scenes)
    unique = "editorial-flash-overlay--fx0"
    assert f'data-composition-src="compositions/{unique}.html"' in html
    # стык на 3.033, пик на 58% из 4 с: старт 3.033 - 2.32 = 0.713
    assert 'data-start="0.7130"' in html
    assert (run / "public" / "compositions" / f"{unique}.html").exists()


def test_плашка_не_заезжает_на_следующую(run):
    """Две плашки стоят на одном месте кадра: наложение их же аудит зовёт
    `content_overlap` (прогон 24, сцены 19,63 и 23,13 при родных 4,8 с)."""
    (run / "public" / "compositions" / "lt-kicker-name.html").write_text(
        '<div data-composition-id="lt-kicker-name" data-duration="2.5"'
        ' data-width="1920" data-height="1080"></div>', encoding="utf-8")
    scenes = json.loads(json.dumps(SCENES))
    scenes[0]["endSec"] = scenes[1]["startSec"] = 2.0
    scenes[0]["overlay"] = {"block": "lt-kicker-name", "text": {}}
    scenes[1]["overlay"] = {"block": "lt-kicker-name", "text": {}}
    html, _ = _build(run, scenes=scenes)
    # первая идёт 0–2.0 (до второй), а не свои 2.5
    first = html[html.index('id="ovl-s-01"'):]
    assert 'data-duration="2.0000"' in first[:400]
    assert 'id="ovl-s-02"' in html


def test_ранняя_кульминация_обходится_без_вспышки(run):
    """Пику вспышки нужно 2,32 с разбега — раньше него вспышку не поставить."""
    scenes = json.loads(json.dumps(SCENES))
    scenes[0]["beat"] = "climax"
    html, _ = _build(run, scenes=scenes)
    assert "editorial-flash-overlay" not in html


def test_список_вспышек_в_camera_json_это_разметка_а_не_замысел(run):
    """Файл — отчёт о сделанном, а не замысел, значит в нём стоит
    ровно то, что встало в кадр."""
    scenes = json.loads(json.dumps(SCENES))
    scenes[1]["beat"] = "climax"
    html, _ = _build(run, scenes=scenes)
    camera = json.loads((run / "camera.json").read_text(encoding="utf-8"))
    assert re.findall(r'id="fx-(\d+)"', html) == ["0"]
    assert camera["flash"] == [3.033]


def test_невлезшая_вспышка_выпадает_из_списка_и_называет_причину(run, capsys):
    """Стык раньше 2,32 с: вспышку не поставить, и обещать её гейту нельзя —
    он пойдёт мерить яркость там, где ничего не стоит (прогон 3ecf2289)."""
    scenes = json.loads(json.dumps(SCENES))
    scenes[0]["beat"] = "climax"          # стык на 0,0 с
    html, _ = _build(run, scenes=scenes)
    camera = json.loads((run / "camera.json").read_text(encoding="utf-8"))
    assert 'id="fx-' not in html
    assert camera["flash"] == []
    assert ("вспышка на 0.00 с снята — разгон блока 2.32 с не влезает "
            "в начало ролика") in capsys.readouterr().out


# ---------- ведущая ----------

def test_положение_ведущей_называет_план(run):
    html, _ = _build(run)
    assert "left: 738, top: 1337" in html          # pip-br
    # переезд стыком: твин по left/top их линтер заворачивает ошибкой
    # gsap_non_transform_motion
    assert 'tl.to("#video-wrap"' not in html


def test_где_ведущей_нет_окно_гасится():
    scenes = [{"id": "s-01", "startSec": 0, "endSec": 2.0, "presenter": "full"},
              {"id": "s-02", "startSec": 2.0, "endSec": 6.0, "presenter": "none"}]
    clips = [{"file": "clips/clip-00.mp4", "start": 0.0, "duration": 2.0}]
    assert presenter_timeline(scenes, clips, 6.0) == [(0.0, "full"), (2.0, "none")]


def test_план_не_вернёт_ведущую_туда_где_её_не_заказали():
    """Названное положение честно применялось к пустому окну — проба считала
    положения, которых зритель не видел."""
    scenes = [{"id": "s-01", "startSec": 0, "endSec": 2.0, "presenter": "full"},
              {"id": "s-02", "startSec": 2.0, "endSec": 6.0, "presenter": "pip-br"}]
    clips = [{"file": "clips/clip-00.mp4", "start": 0.0, "duration": 2.0}]
    assert presenter_timeline(scenes, clips, 6.0) == [(0.0, "full"), (2.0, "none")]


def test_сцены_на_стыке_островов_ведущую_не_теряют():
    """Соседние острова идут встык, и сцена на их границе остаётся с ведущей."""
    clips = [{"file": "a.mp4", "start": 0.0, "duration": 3.0},
             {"file": "b.mp4", "start": 3.0, "duration": 3.0}]
    scenes = [{"id": "s-01", "startSec": 0, "endSec": 4.0, "presenter": "full"},
              {"id": "s-02", "startSec": 4.0, "endSec": 6.0, "presenter": "punch"}]
    moments = presenter_timeline(scenes, clips, 6.0)
    assert [name for _, name in moments] == ["full", "punch"]


FACE = {"cx": 526, "cy": 707, "h": 269}      # замер прогона 24


def test_кадрирование_клипа_считается_по_замеру_лица(run):
    """От центра невысокое окно (`stack` — 1080x844) режет исходник по
    538..1382 и срезает макушку: по этому замеру она на 438."""
    from reels_factory.hf_compose import CROP_HEADROOM, crop_position

    html, _ = _build(run, face=FACE)
    assert "object-position: 50% 30.7%" in html
    assert "__FIT__" not in html
    # доля взята по самой тесной раскладке, и в её полосе макушка с запасом
    share = float(crop_position(FACE).split()[1].rstrip("%")) / 100
    band_top = share * (1920 - 844)                  # stack: масштаб 1:1
    assert band_top <= FACE["cy"] - FACE["h"] * (1 + CROP_HEADROOM) + 0.5
    # точка наезда — своя, кадрирование её не трогает
    assert "transform-origin: 48.7% 36.8%" in html


def test_наезд_в_невысоком_окне_не_выносит_видео_за_кадр():
    """Их `--frame-check` меряет `getBoundingClientRect` тега `<video>` против
    корня композиции и ни `overflow:hidden` обёртки, ни
    `data-layout-allow-overflow` не знает — штатной пометки у правила нет
    вовсе (layout-audit.browser.js:1411-1415, checkPipeline.ts:310-330).
    Окно, кроющее ≥95 % канваса по обеим сторонам, проверка пропускает сама
    (`candidateIsSized`, checkPipeline.ts:222-228) — это `full` и `punch`.
    `stack` (1080x844) не кроет: при лице на 37,4 % ширины наезд 1,18 выносит
    правый край на 121,7 px, а их порог — 120."""
    import math

    from reels_factory.hf_compose import camera_plans, frame_safe_scale

    face = {"cx": 404, "cy": 776, "h": 260}
    assert frame_safe_scale("full", face) == math.inf
    assert frame_safe_scale("punch", face) == math.inf
    assert frame_safe_scale("stack", face) == 1.177
    # лицо посередине — резать нечего, наезд идёт полным
    assert frame_safe_scale("stack", None) > 1.18

    words = [{"start": 0.0, "end": 1.0, "text": "раз"},
             {"start": 1.0, "end": 3.0, "text": "два"}]
    plans = camera_plans([(0.0, "stack")], words, 3.0, face=face)
    assert [plan["kind"] for plan in plans] == ["push"]
    assert plans[0]["scale_to"] == 1.177


def test_без_замера_лица_клип_режется_от_центра(run):
    """Ненайденное лицо — не лицо: гадать, где макушка, не по чему."""
    html, _ = _build(run)
    assert "object-position: 50% 50%" in html


def test_клипы_лежат_слоем_а_не_в_потоке(run):
    """Без position:absolute второй клип уходит за нижний край обёртки —
    ведущая пропадает после первого куска, остаток ролика идёт по чёрному."""
    html, _ = _build(run)
    layer = html[html.index("#video-wrap video"):]
    assert "position: absolute" in layer[:120] and "inset: 0" in layer[:120]


def _clip_tags(html):
    """Числа с тегов ведущей: сравнивать надо времена, а не строки."""
    return [(float(re.search(r'data-start="([\d.]+)"', tag).group(1)),
             float(re.search(r'data-duration="([\d.]+)"', tag).group(1)))
            for tag in re.findall(r'<video class="clip" id="clip-\d\d"[^>]*>',
                                  html)]


def _build_clips(tmp_path, clips):
    board = _board(json.loads(json.dumps(SCENES)))
    with sdk_session() as sdk:
        build_composition(tmp_path, sdk, storyboard=board, clips=clips,
                          duration=6.0, words=WORDS, resolved=FOUND, face=None)
    return (tmp_path / "public" / "index.html").read_text(encoding="utf-8")


def test_клипы_ведущей_сходятся_встык_на_неудобных_кадрах(run):
    """Кадры 2 и 4 сетки 1/30: 0.0666 + 0.0667. Старая формула квантовала уже
    посчитанную разность и растягивала первый клип до 0.067 — конец уезжал на
    0.134 и наезжал на соседа, а их линт роняет `check --strict`."""
    html = _build_clips(run, [
        {"file": "clips/clip-00.mp4", "start": 0.067, "duration": 0.066},
        {"file": "clips/clip-01.mp4", "start": 0.133, "duration": 5.867}])
    (start, length), (next_start, _) = _clip_tags(html)
    assert length == 0.0667
    assert start + length == pytest.approx(next_start, abs=1e-9)


def test_время_в_разметке_не_перебирает_границу_кадра(run):
    """Суть правки: напечатанное время НЕ больше границы своего кадра.

    Рантайм показывает элемент при `currentTime >= start` без допуска, а сикает
    ровно в `frameIndex/fps`. Перебор вверх хотя бы на 1e-6 — и элемент выходит
    кадром позже задуманного; то же и с концом, `start + duration`. Неудобные
    кадры вроде 2/30 = 0.0666667 старое трёхзначное «0.067» перебирало.

    Кадр здесь полный: накладка со скримом, схема, серия вставок, значок и
    клипы ведущей на стыке неудобных кадров.
    """
    _with_schema_block(run)
    (run / "public" / "compositions" / "lt-kicker-name.html").write_text(
        '<div data-composition-id="lt-kicker-name" data-duration="2.5"'
        ' data-width="1920" data-height="1080"></div>', encoding="utf-8")
    scenes = [
        {"id": "s-01", "intent": "хук", "startSec": 0, "endSec": 0.533,
         "presenter": "full", "insert": None},
        {"id": "s-02", "intent": "разбор", "startSec": 0.533, "endSec": 3.567,
         "presenter": "pip-br",
         "insert": _shots("переговоры в офисе", "рука листает бумаги"),
         # накладка без своей подложки — под неё встаёт ещё и скрим
         "overlay": {"block": "lt-kicker-name", "text": {}}},
        {"id": "s-03", "intent": "довод", "startSec": 3.567, "endSec": 4.033,
         "presenter": "none", "insert": None,
         "icon": {"query": "bookmark save icon"}},
        {"id": "s-04", "intent": "итог", "startSec": 4.033, "endSec": 6.0,
         "presenter": "none", "insert": None,
         "schema": {"form": "pairs", "why": "у пунктов свои значения",
                    "rows": [{"label": "раз", "value": "первое"},
                             {"label": "два", "value": "второе"}]}},
    ]
    resolved = dict(_found("s-02", ".media/images/a.jpg", ".media/images/b.jpg"))
    resolved["s-03::icon"] = {"file": ".media/images/icon_001.png"}
    board = _board(json.loads(json.dumps(scenes)))
    with sdk_session() as sdk:
        build_composition(run, sdk, storyboard=board, clips=[
            {"file": "clips/clip-00.mp4", "start": 0.067, "duration": 0.066},
            {"file": "clips/clip-01.mp4", "start": 0.133, "duration": 5.867}],
            duration=6.0, words=WORDS, resolved=resolved, face=None)
    html = (run / "public" / "index.html").read_text(encoding="utf-8")

    # Звук из счёта вон: он микшируется в секундах через `atrim`/`adelay`,
    # сетки кадров у него нет. Вспышка тоже: на кадр стыка у неё привязан пик,
    # а не старт, поэтому она идёт мимо `markup_time` (см. `build_composition`).
    visual = re.sub(r"<audio[^>]*>|<div id=\"fx-\d+\"[^>]*>", "", html)
    times = [(float(start), float(length)) for start, length in re.findall(
        r'data-start="([\d.]+)" data-duration="([\d.]+)"', visual)]
    # накладка, скрим под ней, два плана серии, схема и два клипа ведущей
    assert len(times) == 7, f"кадр вышел не тем: {times}"
    for start, length in times:
        # Оба числа напечатаны с четырьмя знаками, поэтому их точная сумма —
        # тоже четырёхзначная: `round` снимает мусор двоичного сложения.
        for value in (start, round(start + length, 4)):
            assert value <= round(value * 30) / 30, (
                f"{value} стоит за границей своего кадра — "
                f"элемент выйдет кадром позже (start={start}, dur={length})")


def test_наезд_клипов_ведущей_роняет_сборку(run):
    """Ловим наезд у себя: их отчёт назвал бы номер правила, а не клип."""
    with pytest.raises(RuntimeError, match="наезжают друг на друга"):
        _build_clips(run, [
            {"file": "clips/clip-00.mp4", "start": 0.0, "duration": 3.1},
            {"file": "clips/clip-01.mp4", "start": 3.0, "duration": 3.0}])


# ---------- титр и общая рамка ----------

def test_титр_идёт_весь_ролик(run):
    """Гасить его было нужно, пока сцена была блоком со своим текстом."""
    html, _ = _build(run)
    assert "#highlight" not in html.split('id="highlight"')[1]


def test_ролик_знает_свою_длительность_и_звук(run):
    html, _ = _build(run)
    assert 'data-duration="6.0000"' in html
    assert '<audio id="voice" src="voice.wav"' in html
    assert 'data-root="true"' in html


def test_раскадровка_переписывается_округлённой(run):
    _build(run)
    board = json.loads((run / "storyboard.json").read_text(encoding="utf-8"))
    assert board["scenes"][0]["endSec"] == 3.033


# ---------- намерения и подбор ----------

def test_намерения_собираются_по_планам_серии():
    requests = collect_intents(_board(json.loads(json.dumps(SCENES))))
    assert [r["key"] for r in requests] == ["s-02::shot0", "s-02::shot1"]
    assert requests[0]["type"] == "image"
    assert requests[0]["intent"] == "переговоры в офисе"
    assert requests[1]["intent"] == "рука листает бумаги"
    # длину просим на план, а не на всю сцену: файл короче плана замрёт
    assert requests[0]["seconds"] == round(2.967 / 2, 3)
    # под pip-* вставка занимает весь кадр — по этому прямоугольнику отсев
    # меряет растяжение; вставка при ведущей в кадре не обязательна
    assert requests[0]["rect"]["width"] == 1080
    assert requests[0]["required"] is False


def test_вставка_без_ведущей_помечена_обязательной():
    scenes = json.loads(json.dumps(SCENES))
    scenes[1]["presenter"] = "none"
    assert collect_intents(_board(scenes))[0]["required"] is True


def test_вид_вставки_переводится_в_тип_подбора():
    scenes = json.loads(json.dumps(SCENES))
    scenes[1]["insert"]["kind"] = "logo"
    assert collect_intents(_board(scenes))[0]["type"] == "logo"


def test_ненайденная_вставка_отдаёт_кадр_ведущей():
    """Каталог отвечает не на каждое намерение, а сессия агента стоит минут
    пятнадцать. Оставить сцену как есть нельзя: под ведущей в углу вместо
    вставки был бы чёрный прямоугольник."""
    board = _board(json.loads(json.dumps(SCENES)))
    lost = settle_inserts(board, {}, CLIPS, 6.0)
    assert lost == ["s-02"]
    # соседняя сцена уже стоит `full`, значит этой достаётся `punch`
    assert board["scenes"][1]["presenter"] == "punch"
    assert board["scenes"][1]["insert"] is None


def test_прозрачная_вставка_за_вставку_не_считается(monkeypatch, tmp_path):
    """Прогон 14: шесть файлов из четырнадцати пришли rgba, и сквозь них был
    виден чёрный фон сцены — весь финал ролика вышел чёрным экраном."""
    monkeypatch.setattr(hf_compose, "insert_problem",
                        lambda path: "файл прозрачный")
    board = _board(json.loads(json.dumps(SCENES)))
    lost = settle_inserts(board, FOUND, CLIPS, 6.0, public=tmp_path)
    assert lost == ["s-02"]
    assert board["scenes"][1]["insert"] is None


def test_замена_вставки_не_повторяет_соседа(monkeypatch, tmp_path):
    """Иначе две сцены подряд станут одним планом и D21 завернёт сборку."""
    monkeypatch.setattr(hf_compose, "insert_problem", lambda path: "мелкий")
    board = _board(json.loads(json.dumps(SCENES)))
    settle_inserts(board, FOUND, CLIPS, 6.0, public=tmp_path)
    assert board["scenes"][0]["presenter"] == "full"
    assert board["scenes"][1]["presenter"] == "punch"


def test_кусок_без_ведущей_без_вставки_идёт_под_схему():
    """Прежде такая сцена занимала вставку у соседней — в кадр вставала
    картинка не про эту реплику, в обход сверки по содержимому. Теперь сцена
    помечается под запасную схему, и подбор идёт по её же полю `fallback`."""
    board = _board([
        {"id": "s-01", "intent": "и", "startSec": 0.0, "endSec": 2.0,
         "presenter": "pip-br", "insert": _shots("стол", "стол крупно")},
        {"id": "s-02", "intent": "и", "startSec": 2.0, "endSec": 4.0,
         "presenter": "pip-tl", "insert": _shots("окно", "окно крупно")},
        {"id": "s-03", "intent": "и", "startSec": 4.0, "endSec": 6.0,
         "presenter": "none", "insert": _shots("не найдётся", "тоже нет"),
         "fallback": {"form": "steps", "why": "порядок",
                      "nodes": ["кто", "что"]}}])
    short = [{"file": "clips/clip-00.mp4", "start": 0.0, "duration": 4.0}]
    resolved = {**_found("s-01", "a.jpg", "b.jpg"),
                **_found("s-02", "c.jpg", "d.jpg")}
    settle_inserts(board, resolved, short, 6.0)
    third = board["scenes"][2]
    assert third["insert"] is None
    assert third["needsSchema"] is True
    assert third["presenter"] == "none"
    # чужие файлы в кадр не переехали
    assert "s-03::shot0" not in resolved


def test_знаки_брендов_ищутся_для_схемы():
    """Из четырёх форм схемы искать нужно только знаки бренда: цифру, список
    и связь агент называет словами."""
    from reels_factory.hf_compose import schema_intents
    scenes = [{"id": "s-03", "schema": {"form": "brand",
                                        "brands": ["notion", "telegram"]}},
              {"id": "s-04", "schema": {"form": "list", "items": ["раз"]}}]
    requests = schema_intents(scenes)
    assert [r["key"] for r in requests] == ["s-03::brand0", "s-03::brand1"]
    assert requests[0]["type"] == "logo" and requests[0]["entity"] == "notion"


def test_запасная_схема_ищется_только_когда_биролл_не_встал():
    """Схема, выбранная агентом, работает всегда; запасная — только там, где
    сток не ответил, и платить за неё в обычном прогоне незачем."""
    from reels_factory.hf_compose import schema_intents
    dormant = [{"id": "s-02", "fallback": {"form": "brand",
                                           "brands": ["notion"]}}]
    assert schema_intents(dormant) == []
    awake = [{**dormant[0], "needsSchema": True}]
    assert [r["key"] for r in schema_intents(awake)] == ["s-02::brand0"]


def test_половина_серии_не_ставится_вовсе():
    """Один план из двух — это одиночная вставка, а её в монтаже не бывает."""
    board = _board(json.loads(json.dumps(SCENES)))
    lost = settle_inserts(board, _found("s-02", "a.jpg"), CLIPS, 6.0)
    assert lost == ["s-02"]
    assert board["scenes"][1]["insert"] is None


def test_один_файл_на_два_плана_не_ставится():
    """`media-use` отвечает на близкие намерения одним файлом. Повтор кадра —
    брак монтажа, и их линтер зовёт его `duplicate_media_discovery_risk`."""
    board = _board(json.loads(json.dumps(SCENES)))
    lost = settle_inserts(board, _found("s-02", "a.jpg", "a.jpg"), CLIPS, 6.0)
    assert lost == ["s-02"]
    assert board["scenes"][1]["insert"] is None


def test_сцена_без_вставки_и_без_схемы_доживает_до_гейта():
    """Сборку такая сцена больше не роняет на месте: её судит D25, и агент
    получает причину вместе с остальными находками, а не по одной.

    Просьба о схеме тут больше не выставляется: `fallback` у сцены нет, рисовать
    схему не из чего, и флаг означал бы закрытый кадр там, где кадр пуст
    (прогон hf-live2). Сцена уходит в `lost` и в находку D25, а секунды её
    отдаёт соседке `settle_empty_frames` — здесь соседки нет."""
    from reels_factory.hf_montage import frame_filler

    board = _board([{"id": "s-01", "intent": "и", "startSec": 0.0,
                     "endSec": 6.0, "presenter": "none",
                     "insert": _shots("нечто", "и ещё нечто")}])
    short = [{"file": "clips/clip-00.mp4", "start": 0.0, "duration": 2.0}]
    lost = settle_inserts(board, {}, short, 6.0)
    assert lost == ["s-01"]
    assert not board["scenes"][0].get("needsSchema")
    assert frame_filler(board["scenes"][0]) == ""
    assert board["scenes"][0]["insert"] is None


# ---------- шапка раскадровки ----------

def test_шапка_раскадровки_заполняется_кодом():
    """Агент отдаёт только сцены: в шапке решений нет, а разойтись есть где."""
    board = complete_storyboard({"scenes": []}, clips=CLIPS, duration=41.508)
    assert board["schemaVersion"] == 3
    assert board["composition"]["durationSeconds"] == 41.5
    assert board["videoTrack"]["bounds"] == {"x": 0, "y": 0, "width": 1080,
                                             "height": 1920}
    assert board["subtitles"] == {"enabled": True}


def test_свой_videoTrack_агента_не_переживает_сборку():
    """Sonnet отдал videoTrack списком по клипу — гейт схемы искал bounds."""
    board = complete_storyboard({"scenes": [], "videoTrack": [{"sourcePath": "x"}]},
                                clips=CLIPS, duration=6.0)
    assert isinstance(board["videoTrack"], dict)


# ---------- накладки агента и иконки ----------

_LT = ('<!doctype html><html><head><style>.lt{color:red}</style></head><body>'
       '<div id="root" data-composition-id="lt-clean-bar" data-start="0"'
       ' data-width="1920" data-height="1080" data-duration="4.8">'
       '<div class="clip lt" data-start="0" data-duration="4.8">'
       '<span class="lt-name">Jordan Avery</span>'
       '<span class="lt-role">Host</span></div></div>'
       '<script>window.__timelines = window.__timelines || {};'
       'var tl = {};</script></body></html>')


def _with_lt(run):
    compositions = run / "public" / "compositions"
    compositions.mkdir(parents=True, exist_ok=True)
    (compositions / "lt-clean-bar.html").write_text(_LT, encoding="utf-8")
    return run


def test_накладка_агента_встаёт_сабкомпозицией_с_текстом(run):
    """Их блок из каталога: копия под сцену, слоты заполняет код их SDK,
    широкий канвас вписан по ширине кадра над полосой титра."""
    _with_lt(run)
    scenes = json.loads(json.dumps(SCENES))
    # сцене нужен запас под родные 4.8 с блока (порог 0.7 доли)
    scenes[0]["endSec"] = 2.0
    scenes[1]["startSec"] = 2.0
    scenes[1]["overlay"] = {"block": "lt-clean-bar",
                            "text": {"name": "Мария", "role": "продажи"}}
    html, _ = _build(run, scenes=scenes)
    unique = "lt-clean-bar--s-02"
    assert f'data-composition-src="compositions/{unique}.html"' in html
    assert 'data-track-index="40"' in html
    copy = (run / "public" / "compositions" / f"{unique}.html").read_text(
        encoding="utf-8")
    assert ">Мария<" in copy and "Jordan Avery" not in copy


def test_накладка_не_из_каталога_снимается_а_не_роняет_прогон(run, monkeypatch):
    """Паспорта накладок лежат в OVERLAYS.md, и агент открывает файл сам. Не
    открыл — назовёт имя по памяти, реестр такого блока не отдаст, и сборка
    упала бы целиком. Накладка того не стоит: снимаем, как запрещённые."""
    _with_lt(run)
    monkeypatch.setattr(hf_compose, "_known_overlays",
                        lambda: frozenset({"lt-clean-bar"}))
    scenes = json.loads(json.dumps(SCENES))
    scenes[0]["endSec"] = 2.0
    scenes[1]["startSec"] = 2.0
    scenes[1]["overlay"] = {"block": "lower-third-fancy", "text": {"name": "М"}}
    html, _ = _build(run, scenes=scenes)
    assert "lower-third-fancy" not in html


def test_фактура_кроет_кадр_целиком(run, monkeypatch):
    """Протечка света, рамка видоискателя и оформление стоп-кадра приезжают тем
    же канвасом 1920x1080, что и плашки, но обязаны заливать кадр. Прежде их
    считали плашкой: масштаб по ширине давал ленту 1080x608 поперёк середины."""
    _with_lt(run)
    monkeypatch.setattr(hf_compose, "_texture_blocks",
                        lambda: frozenset({"lt-clean-bar"}))
    scenes = json.loads(json.dumps(SCENES))
    scenes[0]["endSec"] = 2.0
    scenes[1]["startSec"] = 2.0
    scenes[1]["overlay"] = {"block": "lt-clean-bar", "text": {}}
    html, _ = _build(run, scenes=scenes)
    layer = html[html.index('<div class="ovl"'):]
    # масштаб по высоте кадра (1920/1080), лишнее по ширине срезано поровну
    assert "top:0" in layer[:80] and "scale(1.7778)" in layer[:400]
    assert "left:-1167px" in layer[:80]


def test_плашка_остаётся_над_полосой_титра(run):
    """Всё, что не помечено фактурой, вписывается по ширине и кончается выше
    слов титра — иначе их аудит зовёт content_overlap."""
    _with_lt(run)
    scenes = json.loads(json.dumps(SCENES))
    scenes[0]["endSec"] = 2.0
    scenes[1]["startSec"] = 2.0
    scenes[1]["overlay"] = {"block": "lt-clean-bar", "text": {"name": "М"}}
    html, _ = _build(run, scenes=scenes)
    layer = html[html.index('<div class="ovl"'):]
    assert "left:0;top:372px" in layer[:80] and "scale(0.5625)" in layer[:400]


def _scrim_scenes(count: int, span: float = 4.0):
    """Ролик из `count` сцен, у каждой накладка без подложки и вставка."""
    scenes, resolved = [], {}
    for index in range(count):
        start = round(index * span, 3)
        name = f"s-{index:02d}"
        scenes.append({"id": name, "intent": "и", "startSec": start,
                       "endSec": round(start + span, 3), "presenter": "pip-br",
                       "insert": _shots("переговоры", "бумаги"),
                       "overlay": {"block": "lt-clean-bar",
                                   "text": {"name": "М"}}})
        resolved.update(_found(name, ".media/images/a.jpg",
                               ".media/images/b.jpg"))
    return scenes, resolved


def _build_scrims(run, monkeypatch, count):
    _with_lt(run)
    monkeypatch.setattr(hf_compose, "_block_backing",
                        lambda: {"lt-clean-bar": "none"})
    scenes, resolved = _scrim_scenes(count)
    duration = round(count * 4.0, 3)
    board = _board(json.loads(json.dumps(scenes)))
    board["composition"]["durationSeconds"] = duration
    board["videoTrack"]["endSec"] = duration
    with sdk_session() as sdk:
        build_composition(run, sdk, storyboard=board, clips=CLIPS,
                          duration=duration, words=WORDS, resolved=resolved)
    return (run / "public" / "index.html").read_text(encoding="utf-8")


def test_скрим_под_накладкой_несёт_клип(run, monkeypatch):
    """Элемент со временем, но без токена `clip` — ошибка их линтера
    `timed_element_missing_clip_class` (composition.ts:544-580, severity
    error), а ошибка обрывает `check` ещё до браузерной части. И это же
    видимость: без `.clip` рантайм держит тёмный градиент весь ролик."""
    html = _build_scrims(run, monkeypatch, 1)
    scrim = html[html.index('id="scrim-s-00"') - 60:][:200]
    assert 'class="ovl-scrim clip"' in scrim
    assert "data-start=" in scrim and "data-duration=" in scrim


def test_скримы_раскладываются_по_дорожкам(run, monkeypatch):
    """Скрим — обычный `div` с `data-start`, а не маунт, и их счётчик
    плотности его считает: больше трёх на дорожке — `timeline_track_too_dense`
    (composition.ts:17,409), под `--strict` это падение."""
    html = _build_scrims(run, monkeypatch, 5)
    tracks = [html[html.index(f'id="scrim-s-{index:02d}"'):][:200]
              .split('data-track-index="')[1].split('"')[0]
              for index in range(5)]
    assert len(tracks) == 5, "скримы встали не под каждую накладку"
    counts = {track: tracks.count(track) for track in set(tracks)}
    assert max(counts.values()) <= 3, f"дорожка перегружена: {counts}"
    # Полоса скримов ни с чем не делится: ниже схема, выше накладки.
    assert all(hf_compose.TRACK_SCHEMA < int(track) < hf_compose.TRACK_OVERLAY
               for track in tracks)


def test_таймлайн_открывается_настоящим_твином(run):
    """Их правило `gsap_timeline_set_initial_hide` (warning, под `--strict`
    падение) смотрит только на `tl.set(..., 0)`, стоящие ДО первого твина в
    порядке исходника: `firstTweenIndex` и `windows.slice(0, firstTweenIndex)`
    (packages/lint/src/rules/gsap.ts:2377-2380). Наши гасящие `set` — фон
    схемы и окно ведущей — идут после дыхания глоу, поэтому в выборку не
    попадают. Тест держит именно этот порядок."""
    _with_schema_block(run)
    scenes = json.loads(json.dumps(SCENES))
    scenes[1]["presenter"] = "none"
    scenes[1]["insert"] = None
    scenes[1]["schema"] = {"form": "pairs", "why": "у пунктов свои значения",
                           "rows": [{"label": "раз", "value": "первое"},
                                    {"label": "два", "value": "второе"}]}
    html, _ = _build(run, scenes=scenes, resolved={})
    script = html[html.index("tl.to(\"#bg-glow\""):]
    assert script.startswith('tl.to("#bg-glow", { scale: 1.12, duration: 6')
    hides = [html.index(line) for line in re.findall(r"tl\.set\([^\n]*", html)
             if ('display: "none" }, 0)' in line
                 or "autoAlpha: 0 }, 0)" in line)]
    assert hides, "в кадре не осталось ни одного гасящего set — тест пуст"
    assert min(hides) > html.index('tl.to("#bg-glow"')


def test_накладке_у_края_ролика_не_хватает_времени(run):
    """Родная длительность 4.8 с не влезает в хвост — накладка снимается.

    Прежде это роняло сборку целиком, и роняло закономерно: задание само
    предлагало ставить плашку «на призыве в финале», где места нет никогда.
    Ролик без плашки живёт, попытка сборки стоит дороже."""
    _with_lt(run)
    scenes = json.loads(json.dumps(SCENES))
    scenes[1]["startSec"] = 4.0
    scenes[0]["endSec"] = 4.0
    scenes[1]["overlay"] = {"block": "lt-clean-bar", "text": {"name": "М"}}
    html, _ = _build(run, scenes=scenes)
    assert "lt-clean-bar--s-02" not in html


def test_накладка_с_чужим_слотом_снимается(run):
    """Имя слота названо не из паспорта: заполнение падает, но цена ошибки
    должна равняться цене плашки, а не цене всей попытки."""
    _with_lt(run)
    scenes = json.loads(json.dumps(SCENES))
    scenes[0]["endSec"] = 2.0
    scenes[1]["startSec"] = 2.0
    scenes[1]["overlay"] = {"block": "lt-clean-bar",
                            "text": {"такого-слота-нет": "М"}}
    html, _ = _build(run, scenes=scenes)
    assert "lt-clean-bar--s-02" not in html


def test_значок_на_подложке_со_свечением(run):
    """Значок оформлен их приёмами: подложка, свечение за ней, вход
    spring-pop. Клипом он не ставится — своей композиции у значка нет,
    видимостью правит наш таймлайн (их PiP-рецепт «wrapper без data»)."""
    scenes = json.loads(json.dumps(SCENES))
    scenes[1]["presenter"] = "none"
    scenes[1]["insert"] = None
    scenes[1]["icon"] = {"query": "bookmark save icon"}
    resolved = {"s-02::icon": {"file": ".media/images/icon_001.png"}}
    html, _ = _build(run, scenes=scenes, resolved=resolved)
    assert 'id="icon-s-02" class="icon-spot">' in html
    assert "icon-spot clip" not in html
    icon_div = html[html.index('id="icon-s-02"'):html.index("</div>",
                               html.index('id="icon-s-02"'))]
    assert "data-start" not in icon_div and "data-track-index" not in icon_div
    assert 'id="icon-s-02-glow" class="icon-glow"' in html
    assert 'id="icon-s-02-plate" class="icon-plate"' in html
    assert 'src=".media/images/icon_001.png"' in html
    assert 'tl.set("#icon-s-02", { autoAlpha: 0 }, 0);' in html
    # вход плашки — spring-pop без отскока, свечение расцветает под неё
    assert ('tl.fromTo("#icon-s-02-plate", { scale: 0, opacity: 0 }' in html
            and 'ease: "power3.out"' in html)
    assert 'tl.fromTo("#icon-s-02-glow", { opacity: 0, scale: 0.82 }' in html
    # перекраска силуэта фильтром ушла вместе с костылём
    assert "brightness(0) invert(1)" not in html


def test_свечение_значка_дышит_конечной_фазой_а_не_петлёй(run):
    """Их правило: дыхание свечения — конечный твин по прокси-фазе, не yoyo
    (rules/ambient-glow-bloom.md:16)."""
    scenes = json.loads(json.dumps(SCENES))
    scenes[1]["presenter"] = "none"
    scenes[1]["insert"] = None
    scenes[1]["icon"] = {"query": "bookmark save icon"}
    html, _ = _build(run, scenes=scenes,
                     resolved={"s-02::icon": {"file": ".media/i.png"}})
    breathe = html[html.index("const phase_s_02"):]
    assert "yoyo" not in breathe.split("})();")[0]
    assert 'ease: "none"' in breathe
    assert "Math.sin(phase_s_02.p)" in breathe


def test_значок_снимается_если_ведущая_заняла_его_место(run):
    """Раскладка меняется уже после подбора: сцена без вставки уходит под
    полнокадровую ведущую, и значок оказался бы у неё на лице."""
    scenes = json.loads(json.dumps(SCENES))
    scenes[1]["presenter"] = "full"
    scenes[1]["insert"] = None
    scenes[1]["icon"] = {"query": "bookmark save icon"}
    html, board = _build(run, scenes=scenes,
                         resolved={"s-02::icon": {"file": ".media/i.png"}})
    assert 'id="icon-s-02"' not in html
    assert "icon" not in board["scenes"][1]


def test_значок_уступает_приехавшей_вставке(run):
    """Значок объявлен запасом и ведёт себя как запас. Прежде он стоял
    безусловно, и круглая плашка с тарелкой легла поверх руки со сковородой —
    два раза про одно и то же в одном кадре."""
    scenes = json.loads(json.dumps(SCENES))
    scenes[1]["icon"] = {"query": "handshake deal icon"}
    resolved = dict(FOUND, **{"s-02::icon": {"file": ".media/i.png"}})
    html, board = _build(run, scenes=scenes, resolved=resolved)
    assert 'id="ins-s-02-0"' in html
    assert 'id="icon-s-02"' not in html
    assert "icon" not in board["scenes"][1]


def test_потерянная_вставка_возвращает_значок_в_кадр(run):
    """Ровно тот случай, ради которого запас и называется: серия не собралась,
    и кадр закрывает значок."""
    scenes = json.loads(json.dumps(SCENES))
    scenes[1]["presenter"] = "pip-br"
    scenes[1]["icon"] = {"query": "handshake deal icon"}
    # серия неполная: один план из двух — вся серия снимается
    resolved = {"s-02::shot0": {"file": ".media/images/a.jpg"},
                "s-02::icon": {"file": ".media/i.png"}}
    html, board = _build(run, scenes=scenes, resolved=resolved)
    assert 'id="ins-s-02-0"' not in html
    assert 'id="icon-s-02" class="icon-spot">' in html
    assert board["scenes"][1]["icon"] == {"query": "handshake deal icon"}


def test_снятый_значок_не_делает_кадр_пустым():
    """Гейты D20/D25 считают кадр закрытым по `frame_filler`, и сцена, у
    которой значок уступил вставке, называется вставкой, а не пустотой."""
    from reels_factory.hf_montage import frame_filler

    scene = {"id": "s-02", "presenter": "none",
             "insert": {"shots": ["раз", "два"], "kind": "video"}}
    assert frame_filler(scene) == "вставка"


def _with_schema_block(run, form="pairs"):
    """Блок схемы в проекте: его ставит `hyperframes add` перед сборкой."""
    from reels_factory.hf_schema import FORMS
    compositions = run / "public" / "compositions"
    compositions.mkdir(parents=True, exist_ok=True)
    block = FORMS[form]
    (compositions / f"{block}.html").write_text(
        f'<!doctype html><html><head><style>#mk-sl-root{{width:1920px;'
        f'height:1080px}}</style></head><body>'
        f'<div id="mk-sl-root" data-composition-id="{block}"'
        f' data-duration="8" data-width="1920" data-height="1080"></div>'
        f'<script>(function(){{ var CONFIG = {{ rows: [] }};'
        f' var DUR = 8;'
        # Их список центрирует колонку по высоте канваса — по этой строке
        # перенос сажает её в безопасную высоту, выше полосы титра.
        f' col.style.top = Math.round((1080 - colH) / 2) + "px";'
        f' }})();</script>'
        f'<script>window.__timelines = window.__timelines || {{}};</script>'
        f"</body></html>", encoding="utf-8")
    return run


def test_схема_закрывает_кадр_их_блоком(run):
    """Прежде тут стоял одинокий значок на белом кружке — в кадре он читался
    эмблемой. Теперь форму собирает их же блок, вписанный в вертикаль."""
    _with_schema_block(run)
    scenes = json.loads(json.dumps(SCENES))
    scenes[1]["presenter"] = "none"
    scenes[1]["insert"] = None
    scenes[1]["schema"] = {"form": "pairs", "why": "у пунктов свои значения",
                           "rows": [{"label": "раз", "value": "первое"},
                                    {"label": "два", "value": "второе"}]}
    html, board = _build(run, scenes=scenes, resolved={})
    assert 'id="schema-s-02" class="clip"' in html
    assert 'data-composition-src="compositions/mk-specs-list--s-02.html"' in html
    assert board["scenes"][1]["schemaShown"] is True
    copy = (run / "public" / "compositions" / "mk-specs-list--s-02.html")
    text = copy.read_text(encoding="utf-8")
    assert "Object.assign(CONFIG," in text and "1080px" in text


def test_перечисление_получает_содержимое_штатным_каналом(run):
    """Их упругий компонент читает `getVariables()`, поэтому содержимое идёт
    атрибутом на хост, а не довеском к литералу: канваса и `CONFIG` у него
    нет вовсе (`grid-card-assemble.html:207-210`)."""
    compositions = run / "public" / "compositions"
    compositions.mkdir(parents=True, exist_ok=True)
    (compositions / "grid-card-assemble.html").write_text(
        '<!doctype html><html data-composition-duration="4.5"><head><style>'
        '#root{width:100cqw}</style></head><body>'
        '<div id="root" data-composition-id="grid-card-assemble"'
        ' data-duration="4.5" data-width="1080" data-height="1920">'
        '<div class="gca-stage" data-slot="items" role="list"></div></div>'
        "<script>var textW = 1, maxChars = 1;"
        " var labelCqw = textW / (maxChars * 0.75);</script>"
        "<script>window.__timelines = window.__timelines || {};</script>"
        "</body></html>", encoding="utf-8")
    scenes = json.loads(json.dumps(SCENES))
    scenes[1]["presenter"] = "none"
    scenes[1]["insert"] = None
    scenes[1]["schema"] = {
        "form": "items", "why": "перечисление",
        "items": [{"label": "кто", "icon": "человек"},
                  {"label": "что", "icon": "документ"},
                  {"label": "как", "icon": "поиск"}]}
    html, board = _build(run, scenes=scenes, resolved={})
    assert "data-variable-values=" in html
    assert "КТО,ЧТО,КАК" in html
    copy = (compositions / "grid-card-assemble--s-02.html").read_text(
        encoding="utf-8")
    # Слот заполнен нашими карточками, и подписи в нём совпадают с переменной
    # знак в знак: кегль считается по переменной, и разошедшиеся строки режутся.
    assert copy.count('class="gca-card"') == 3
    assert "Object.assign(CONFIG," not in copy
    assert "1920px" not in copy


def test_схема_стоит_на_живом_фоне_а_не_на_ровном_цвете(run):
    """Под схемной сценой нет ни ведущей, ни вставки, а корни блоков схемы
    прозрачны: в кадре оставался ровный цвет из frame.md. Фон ставит код их
    компонентом `aurora-drift`, вмерженным сниппетом."""
    _with_schema_block(run)
    scenes = json.loads(json.dumps(SCENES))
    scenes[1]["presenter"] = "none"
    scenes[1]["insert"] = None
    scenes[1]["schema"] = {"form": "pairs", "why": "у пунктов свои значения",
                           "rows": [{"label": "раз", "value": "первое"},
                                    {"label": "два", "value": "второе"}]}
    html, _ = _build(run, scenes=scenes, resolved={})
    assert 'id="bg-aurora-s-02" class="aurora"' in html
    assert html.count('class="ad-blob ') == 3
    # фон живёт ровно свою сцену и дрейфует один оборот синуса
    assert 'tl.set("#bg-aurora-s-02", { display: "block" }, 3.0333);' in html
    assert 'tl.set("#bg-aurora-s-02", { display: "none" }, 6.0);' in html
    assert "6.2832" in html and "cqw" in html


def test_фон_схемы_снимается_display_а_не_прозрачностью(run):
    """Каждый фон — пять полей с `filter: blur` и радиальными градиентами, а у
    них про такие записано: «Presence alone matters: opacity:0 and
    visibility:hidden overlays still contribute to the capture-layer
    regression… The only escape hatch is `display: none`»
    (packages/lint/src/rules/composition.ts:1186-1191). Порог их
    предупреждения — 25 элементов, наблюдённый дефект — чёрный кадр на первой
    половине рендера; пять схемных сцен дают ровно 25."""
    _with_schema_block(run)
    scenes = json.loads(json.dumps(SCENES))
    scenes[1]["presenter"] = "none"
    scenes[1]["insert"] = None
    scenes[1]["schema"] = {"form": "pairs", "why": "у пунктов свои значения",
                           "rows": [{"label": "раз", "value": "первое"},
                                    {"label": "два", "value": "второе"}]}
    html, _ = _build(run, scenes=scenes, resolved={})
    фон = [line for line in html.splitlines() if "#bg-aurora-s-02" in line
           and "tl.set(" in line]
    assert len(фон) == 3, "фон включают и гасят три `set`"
    assert not [line for line in фон if "autoAlpha" in line]
    assert 'tl.set("#bg-aurora-s-02", { display: "none" }, 0);' in html


def test_выезд_полей_фона_помечен_разрешённым(run):
    """Выезд заложен в геометрию полей (`-18cqw`, `-28cqw`, `-34cqh`), а
    `.aurora` его срезает — их аудит раскладки зовёт это `container_overflow` и
    сам называет выход: «mark intentional overflow with
    data-layout-allow-overflow». Атрибут стоит на обёртке: отказ они ищут через
    `closest()` (packages/cli/src/commands/layout-audit.browser.js:104-106),
    одним атрибутом накрыты все три поля."""
    _with_schema_block(run)
    scenes = json.loads(json.dumps(SCENES))
    scenes[1]["presenter"] = "none"
    scenes[1]["insert"] = None
    scenes[1]["schema"] = {"form": "pairs", "why": "у пунктов свои значения",
                           "rows": [{"label": "раз", "value": "первое"},
                                    {"label": "два", "value": "второе"}]}
    html, _ = _build(run, scenes=scenes, resolved={})
    обёртка = next(line for line in html.splitlines()
                   if 'id="bg-aurora-s-02"' in line)
    assert 'data-layout-allow-overflow="true"' in обёртка
    # поля лежат внутри обёртки, то есть `closest()` их находит
    assert обёртка.count('class="ad-blob ') == 3


def test_фона_нет_там_где_схема_не_встала(run):
    """Фон — оформление схемы, а не самостоятельный слой: снятая схема уносит
    его с собой, иначе сцена осталась бы с одним крашеным кадром."""
    _with_schema_block(run, form="brand")
    scenes = json.loads(json.dumps(SCENES))
    scenes[1]["presenter"] = "none"
    scenes[1]["insert"] = None
    scenes[1]["schema"] = {"form": "brand", "brands": ["notion"]}
    html, _ = _build(run, scenes=scenes, resolved={})
    assert "bg-aurora" not in html


def test_фон_схемы_лежит_между_декором_и_вставкой(run):
    """Слой 8: выше фоновых глоу ролика (5) и ниже вставки (10). А имя его —
    вне списка `hf_probe.FRAME_CONTENT_PREFIXES`, иначе фон объявлял бы
    занятым пустой кадр."""
    from reels_factory.hf_probe import FRAME_CONTENT_PREFIXES

    template = (hf_compose.TEMPLATE).read_text(encoding="utf-8")
    layer = template[template.index(".aurora {"):]
    assert "z-index: 8;" in layer[:400]
    assert not "bg-aurora-s-02".startswith(FRAME_CONTENT_PREFIXES)


def test_фон_схемы_красится_нашей_палитрой_а_не_их_холодной_базой(run):
    """Их база зашита в скрипте компонента (`deep: { base: "#050711" }`), и
    углы кадра уходили в почти чёрный вместо тёплого bg из frame.md."""
    _with_schema_block(run)
    scenes = json.loads(json.dumps(SCENES))
    scenes[1]["presenter"] = "none"
    scenes[1]["insert"] = None
    scenes[1]["schema"] = {"form": "pairs", "why": "у пунктов свои значения",
                           "rows": [{"label": "раз", "value": "первое"},
                                    {"label": "два", "value": "второе"}]}
    theme = {"colors": {"bg": "#1a1210", "ink": "#ffffff",
                        "accent": "#ff5a36"}}
    board = _board(json.loads(json.dumps(scenes)))
    with sdk_session() as sdk:
        build_composition(run, sdk, storyboard=board, clips=CLIPS,
                          duration=6.0, words=WORDS, resolved={}, theme=theme)
    html = (run / "public" / "index.html").read_text(encoding="utf-8")
    rule = html[html.index(".aurora {"):html.index(".aurora .ad-base,")]
    assert "--ad-base: #1a1210" in rule
    assert "--ad-color: #ff5a36" in rule
    # виньетка гасит углы своим же цветом кадра, а не их чёрным
    vignette = html[html.rindex(".aurora .ad-vignette {"):]
    assert "rgb(0 0 0" not in vignette[:300]
    assert "var(--ad-base) 100%" in vignette[:300]


def test_все_схемы_ролика_лежат_на_одной_дорожке(run):
    """Ротации у схем нет и не нужно: их счётчик плотности пропускает маунты
    первой же строкой цикла — `if (isCompositionRootOrMount(tag.raw))
    continue;` (packages/lint/src/rules/composition.ts:394 на пине v0.7.84,
    признак — `data-composition-id` или `data-composition-src`). Схема выезжает
    именно маунтом, то есть `timeline_track_too_dense` её не видит; по времени
    схемы не пересекаются никогда, каждая занимает свою сцену целиком."""
    _with_schema_block(run)
    scenes = []
    for index in range(5):
        start = round(index * 4.0, 3)
        scenes.append({"id": f"s-{index:02d}", "intent": "и",
                       "startSec": start, "endSec": round(start + 4.0, 3),
                       "presenter": "none", "insert": None,
                       "schema": {"form": "pairs", "why": "свои значения",
                                  "rows": [{"label": "раз", "value": "первое"},
                                           {"label": "два", "value": "второе"}]}})
    board = _board(json.loads(json.dumps(scenes)))
    board["composition"]["durationSeconds"] = 20.0
    board["videoTrack"]["endSec"] = 20.0
    with sdk_session() as sdk:
        build_composition(run, sdk, storyboard=board, clips=CLIPS,
                          duration=20.0, words=WORDS, resolved={})
    html = (run / "public" / "index.html").read_text(encoding="utf-8")
    assert html.count('id="schema-s-') == 5
    tracks, маунты = [], 0
    for scene in scenes:
        tag = html[html.index(f'id="schema-{scene["id"]}"'):][:400]
        tracks.append(tag.split('data-track-index="')[1].split('"')[0])
        маунты += "data-composition-src=" in tag
    assert маунты == 5, "схема перестала быть маунтом — счёт плотности её увидит"
    assert set(tracks) == {str(hf_compose.TRACK_SCHEMA)}
    # дорожка схем ни с чем не делится
    занятые = {str(hf_compose.TRACK_VIDEO), str(hf_compose.TRACK_INSERT),
               str(hf_compose.TRACK_SCRIM), str(hf_compose.TRACK_OVERLAY),
               str(hf_compose.TRACK_OVERLAY + 1), str(hf_compose.TRACK_CAPTION),
               str(hf_compose.TRACK_FX), str(hf_compose.TRACK_SFX),
               str(hf_compose.TRACK_AUDIO)}
    assert not set(tracks) & занятые


def test_схема_короче_своей_анимации_не_ставится(run):
    """Форме нужно время, чтобы досказать вход: сцена короче — блок покажет
    себя недорисованным, а это хуже, чем не показать вовсе."""
    _with_schema_block(run)
    scenes = json.loads(json.dumps(SCENES))
    scenes[1]["presenter"] = "none"
    scenes[1]["insert"] = None
    scenes[1]["startSec"], scenes[1]["endSec"] = 5.4, 6.0
    scenes[0]["endSec"] = 5.4
    scenes[1]["schema"] = {"form": "pairs", "why": "у пунктов свои значения",
                           "rows": [{"label": "раз", "value": "первое"},
                                    {"label": "два", "value": "второе"}]}
    html, board = _build(run, scenes=scenes, resolved={})
    assert 'id="schema-s-02"' not in html
    assert "schemaShown" not in board["scenes"][1]


def test_схема_бренда_без_знака_не_рисуется(run):
    _with_schema_block(run, form="brand")
    scenes = json.loads(json.dumps(SCENES))
    scenes[1]["presenter"] = "none"
    scenes[1]["insert"] = None
    scenes[1]["schema"] = {"form": "brand", "brands": ["notion"]}
    html, board = _build(run, scenes=scenes, resolved={})
    assert 'id="schema-s-02"' not in html
    assert "schemaShown" not in board["scenes"][1]


def test_запрос_иконки_попадает_в_намерения():
    scenes = json.loads(json.dumps(SCENES))
    scenes[1]["presenter"] = "none"
    scenes[1]["insert"] = None
    scenes[1]["icon"] = {"query": "fire flame icon"}
    icons = icon_intents(scenes)
    assert icons and icons[0]["key"] == "s-02::icon"
    assert icons[0]["intent"] == "fire flame icon"
    assert icons[0]["type"] == "icon"


def test_значок_на_полнокадровой_ведущей_даже_не_ищется():
    """Место значка — верхняя треть по центру, и при ведущей во весь кадр это
    её лицо. Запрос туда не уходит вовсе: подбор стоит времени."""
    scenes = json.loads(json.dumps(SCENES))
    scenes[0]["presenter"] = "full"
    scenes[0]["icon"] = {"query": "fire flame icon"}
    assert not icon_intents(scenes)


def test_значок_сцены_со_вставкой_не_подбирается_вовсе():
    """Значок — запас: приехала вставка, и в кадр он не встанет. Пока запросы
    шли вместе со вставками, за такой значок платили поиском по каталогу,
    скачиванием превью и долей платной сессии судьи — и он же занимал `id`
    каталога, отбирая его у сцены, которой закрыть кадр больше нечем."""
    scenes = json.loads(json.dumps(SCENES))
    scenes[1]["presenter"] = "pip-br"
    scenes[1]["icon"] = {"query": "fire flame icon"}
    assert scenes[1]["insert"], "сцена без вставки — тест ничего не проверяет"
    assert not icon_intents(scenes)
    # А потеряла вставку (`settle_inserts` обнулил) — значок нужен.
    scenes[1]["insert"] = None
    assert [r["key"] for r in icon_intents(scenes)] == ["s-02::icon"]


def test_значки_не_идут_первым_заходом():
    """Первый заход — только вставки: чем закрыт кадр, к этому моменту ещё не
    известно."""
    scenes = json.loads(json.dumps(SCENES))
    scenes[1]["presenter"] = "none"
    scenes[1]["insert"] = None
    scenes[1]["icon"] = {"query": "fire flame icon"}
    assert not [r for r in collect_intents(_board(scenes))
                if r["type"] == "icon"]


def test_накладка_агента_попадает_в_установку_блоков():
    from reels_factory.hf_compose import needed_blocks
    scenes = json.loads(json.dumps(SCENES))
    scenes[1]["overlay"] = {"block": "lt-soft-pill", "text": {}}
    # блок вспышки ставится всегда: где она вспыхнет, решает арифметика планов
    # камеры уже во время сборки, а ставить блок тогда поздно
    assert needed_blocks(_board(scenes)) == ["editorial-flash-overlay",
                                             "lt-soft-pill"]


# ---------- что не встанет в кадр, снимается до разбора пустых сцен ----------

def _пара(filler: dict) -> dict:
    """Соседка с ведущей и сцена без аватара, кадр которой держит только
    `filler` — значок или плашка."""
    return _board([
        {"id": "s-01", "intent": "хук", "startSec": 0.0, "endSec": 3.0,
         "presenter": "full", "insert": None},
        {"id": "s-02", "intent": "мысль", "startSec": 3.0, "endSec": 6.0,
         "presenter": "none", "insert": None, **filler},
    ])


def test_значок_без_файла_снимается_до_разбора_пустых_сцен(monkeypatch):
    """Значок — законный способ закрыть кадр, и сцена без аватара может стоять
    на нём одном. Но подбор мог не ответить, а снимался значок уже в
    `build_composition` — после `settle_empty_frames`, и починить сцену коду
    было нечем: кадр оставался пустым, D25 и D26 роняли сборку."""
    from reels_factory.hf_compose import settle_fillers
    from reels_factory.hf_montage import dedupe_neighbours, frame_filler

    board = _пара({"icon": {"query": "закладка"}})
    assert settle_fillers(board, {}) == ["s-02"]
    assert "icon" not in board["scenes"][1]
    assert frame_filler(board["scenes"][1]) == ""
    dedupe_neighbours(board["scenes"], clips=CLIPS, duration=6.0)
    assert [s["id"] for s in board["scenes"]] == ["s-01"]
    assert board["scenes"][0]["endSec"] == 6.0


def test_найденный_значок_остаётся_на_месте():
    """Подбор ответил — снимать нечего, и сцена живёт своей жизнью."""
    from reels_factory.hf_compose import settle_fillers
    from reels_factory.hf_montage import frame_filler

    board = _пара({"icon": {"query": "закладка"}})
    found = {"s-02::icon": {"file": ".media/icons/a.png"}}
    assert settle_fillers(board, found) == []
    assert frame_filler(board["scenes"][1]) == "значок"


def test_накладка_не_из_каталога_снимается_до_разбора_пустых_сцен(monkeypatch):
    """Имя блока по памяти — та же дыра, что и ненайденный значок: плашку
    снимала сборка, а пустую сцену разбирать было уже поздно."""
    from reels_factory.hf_compose import settle_fillers
    from reels_factory.hf_montage import frame_filler

    monkeypatch.setattr(hf_compose, "_known_overlays",
                        lambda: frozenset({"lt-clean-bar"}))
    board = _пара({"overlay": {"block": "lower-third-fancy", "text": {}}})
    assert settle_fillers(board, {}) == ["s-02"]
    assert frame_filler(board["scenes"][1]) == ""


def test_известная_накладка_кадр_держит(monkeypatch):
    from reels_factory.hf_compose import settle_fillers
    from reels_factory.hf_montage import frame_filler

    monkeypatch.setattr(hf_compose, "_known_overlays",
                        lambda: frozenset({"lt-clean-bar"}))
    board = _пара({"overlay": {"block": "lt-clean-bar", "text": {}}})
    assert settle_fillers(board, {}) == []
    assert frame_filler(board["scenes"][1]) == "плашка"


def test_причина_негодности_накладки_считается_одним_местом(monkeypatch):
    """`settle_fillers` и сама сборка обязаны судить блок одинаково: разойдись
    они — сборка снимет плашку, которую проход посчитал стоящей, и сцена снова
    останется с пустым кадром."""
    monkeypatch.setattr(hf_compose, "_skipped_blocks",
                        lambda: {"lt-broken": "их блок ломает рендер"})
    monkeypatch.setattr(hf_compose, "_known_overlays",
                        lambda: frozenset({"lt-clean-bar", "lt-broken"}))
    assert hf_compose.overlay_problem("lt-clean-bar") is None
    assert "ломает" in (hf_compose.overlay_problem("lt-broken") or "")
    assert "OVERLAYS.md" in (hf_compose.overlay_problem("lt-нет") or "")


# ---------- элементы каталога ----------

FIXTURE_CATALOG = Path(__file__).resolve().parent / "fixtures" / "catalog"


@pytest.fixture
def каталог(run, monkeypatch):
    """Фикстурный каталог вместо боевого: три вида позиции и одна без вида.

    Блоки кладём в `public/compositions` руками — в прогоне их туда ставит
    `hyperframes add` до сборки.
    """
    from reels_factory.hf_catalog import catalog_cards

    cards = catalog_cards(FIXTURE_CATALOG)
    monkeypatch.setattr(hf_compose, "_catalog_cards", lambda: cards)
    monkeypatch.setattr(hf_compose, "_skipped_blocks",
                        lambda: {"demo-skip": "их же проверка валит блок"})
    monkeypatch.setattr(hf_compose, "_texture_blocks", frozenset)
    blocks = FIXTURE_CATALOG / "registry" / "blocks"
    for name in cards:
        shutil.copyfile(blocks / name / f"{name}.html",
                        run / "public" / "compositions" / f"{name}.html")
    return run


def _с_элементами(*elements, presenter="pip-tr"):
    scenes = json.loads(json.dumps(SCENES))
    scenes[1]["presenter"] = presenter
    scenes[1]["insert"] = None
    scenes[1]["elements"] = list(elements)
    return scenes


def test_элемент_сцены_встаёт_во_весь_кадр_со_словами_агента(каталог):
    """Вид `scene` едет тем же путём, что схема: канвас под вертикаль, палитра
    и шрифт правилом CSS, слова — существующим слоем слотов."""
    html, _ = _build(каталог, scenes=_с_элементами(
        {"name": "demo-scene", "words": ["Наш заголовок"]}), resolved={})
    mount = html[html.index('id="el-s-02-0"'):]
    assert 'data-composition-src="compositions/demo-scene--s-02.html"' in mount
    assert "width:1080px;height:1920px" in mount[:400]
    copy = (каталог / "public" / "compositions"
            / "demo-scene--s-02.html").read_text(encoding="utf-8")
    assert "Наш заголовок" in copy and "Заголовок</div>" not in copy
    # Канвас переехал в вертикаль, а гарнитуру блок получил правилом ниже.
    assert 'data-width="1080" data-height="1920"' in copy
    assert "#demo-scene-root { font-family: 'Manrope'" in copy


def test_эффект_встаёт_в_свободную_зону_кадра(каталог):
    """Зону считает код: ниже окна ведущей и выше полосы титра. Агент её не
    называет вовсе."""
    html, _ = _build(каталог, scenes=_с_элементами(
        {"name": "count-up", "variables": {"end": 250, "suffix": " ₽"}}),
        resolved={})
    box = html[html.index('<div class="ovl" style="left:0px;top:583px'):]
    assert "height:397px" in box[:200], box[:200]
    assert 'data-variable-values=' in box[:600] and '"end": 250' in box[:600]
    # Зона не заезжает ни на окно ведущей, ни на полосу титра.
    assert 583 >= VIDEO_RECTS["pip-tr"]["top"] + VIDEO_RECTS["pip-tr"]["height"]
    assert 583 + 397 <= hf_compose.CAPTION_BAND_TOP


def test_эффекту_без_свободной_зоны_места_нет(каталог, capsys):
    """Ведущая во весь кадр не оставляет зоны — элемент снимается, а сборка
    идёт дальше: цена ошибки равна цене элемента, а не прогона."""
    html, board = _build(каталог, scenes=_с_элементами(
        {"name": "count-up"}, presenter="full"), resolved={})
    assert "el-s-02-0" not in html
    assert "свободной зоны" in capsys.readouterr().out
    assert board["scenes"][1]["elements"] == []


def test_стык_встаёт_за_срез_сцены_и_живёт_свою_длительность(каталог):
    """Их же правило размещения накладки-перехода: «place this block spanning
    the host's cut point (e.g. start 0.9s before the cut)»."""
    html, _ = _build(каталог, scenes=_с_элементами({"name": "demo-stitch"}),
                     resolved={})
    mount = html[html.index('id="el-s-02-0"'):]
    assert 'data-start="2.1333"' in mount[:400], mount[:400]
    assert 'data-duration="2.2000"' in mount[:400]
    # Поверх всего, слоем вспышки: переход кроет кадр целиком.
    assert '<div class="fx" style="left:' in html[:html.index('id="el-s-02-0"')]


def test_позиция_без_вида_встаёт_плашкой_над_полосой_титра(каталог):
    """Обратная совместимость: карточка без `reels.kind` — сегодняшняя плашка,
    и геометрия у неё та же."""
    html, _ = _build(каталог, scenes=_с_элементами(
        {"name": "demo-plain", "words": ["Имя"]}), resolved={})
    before = html[:html.index('id="el-s-02-0"')]
    assert 'class="ovl" style="left:0;top:' in before
    assert "top:0px" not in before.rsplit('class="ovl"', 1)[1]


def test_старый_план_с_полем_overlay_собирается_как_прежде(каталог, monkeypatch):
    """План прошлого прогона называет блок в `overlay` — он обязан собраться:
    поле из задания убрано, а из кода нет."""
    monkeypatch.setattr(hf_compose, "_known_overlays",
                        lambda: frozenset({"demo-plain"}))
    scenes = json.loads(json.dumps(SCENES))
    scenes[1]["insert"] = None
    scenes[1]["overlay"] = {"block": "demo-plain", "text": {"line": "Имя"}}
    html, _ = _build(каталог, scenes=scenes, resolved={})
    assert 'id="ovl-s-02"' in html


def test_имена_элементов_попадают_в_установку_блоков():
    """Ставит блоки их `hyperframes add`, и список ему даёт `needed_blocks`."""
    from reels_factory.hf_compose import needed_blocks

    scenes = json.loads(json.dumps(SCENES))
    scenes[0]["elements"] = [{"name": "demo-scene"}, {"name": "count-up"}]
    scenes[1]["elements"] = [{"name": "demo-scene"}]
    assert needed_blocks(_board(scenes)) == ["editorial-flash-overlay",
                                             "demo-scene", "count-up"]


def test_упругая_позиция_получает_коробку_в_копии_и_кадр_в_стенсиле(каталог):
    """Их полка размеров не объявляет нарочно — позиция заполняет коробку
    хоста. Их же линтер зовёт это `root_missing_dimensions` (severity error), и
    под `--strict` файл роняет сборку: он судит каждый файл сам по себе.
    Коробку считает код, поэтому её и объявляем — копии зону, стенсилю кадр.
    """
    _build(каталог, scenes=_с_элементами({"name": "count-up"}), resolved={})
    compositions = каталог / "public" / "compositions"
    copy = (compositions / "count-up--s-02.html").read_text(encoding="utf-8")
    assert 'data-width="1080" data-height="397"' in copy
    stencil = (compositions / "count-up.html").read_text(encoding="utf-8")
    assert 'data-width="1080" data-height="1920"' in stencil
