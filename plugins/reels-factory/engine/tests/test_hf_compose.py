"""Композицию собирает код: слои кадра, ведущая, вставки, субтитры, звук."""
import json

import pytest

from reels_factory import hf_compose
from reels_factory.hf_compose import (
    build_composition, collect_intents, complete_storyboard,
    presenter_timeline, settle_inserts,
)
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
    assert 'data-start="3.0330"' in html


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
    assert 'data-start="3.0330"' in first[:400]
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
         "fallback": {"logo": "notion", "icon": "checklist icon"}}])
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
    получает причину вместе с остальными находками, а не по одной."""
    board = _board([{"id": "s-01", "intent": "и", "startSec": 0.0,
                     "endSec": 6.0, "presenter": "none",
                     "insert": _shots("нечто", "и ещё нечто")}])
    short = [{"file": "clips/clip-00.mp4", "start": 0.0, "duration": 2.0}]
    settle_inserts(board, {}, short, 6.0)
    assert board["scenes"][0]["needsSchema"] is True
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


def test_накладке_у_края_ролика_не_хватает_времени(run):
    """Родная длительность 4.8 с не влезает в хвост — внятная ошибка."""
    _with_lt(run)
    scenes = json.loads(json.dumps(SCENES))
    scenes[1]["startSec"] = 4.0
    scenes[0]["endSec"] = 4.0
    scenes[1]["overlay"] = {"block": "lt-clean-bar",
                            "text": {"name": "М", "role": "п"}}
    with pytest.raises(RuntimeError, match="накладке"):
        _build(run, scenes=scenes)


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


def _with_schema_block(run, form="list"):
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
        f' var DUR = 8; }})();</script>'
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
    scenes[1]["schema"] = {"form": "list", "items": ["раз", "два"]}
    html, board = _build(run, scenes=scenes, resolved={})
    assert 'id="schema-s-02" class="clip"' in html
    assert 'data-composition-src="compositions/mk-specs-list--s-02.html"' in html
    assert board["scenes"][1]["schemaShown"] is True
    copy = (run / "public" / "compositions" / "mk-specs-list--s-02.html")
    text = copy.read_text(encoding="utf-8")
    assert "Object.assign(CONFIG," in text and "1080px" in text


def test_схема_короче_своей_анимации_не_ставится(run):
    """Форме нужно время, чтобы досказать вход: сцена короче — блок покажет
    себя недорисованным, а это хуже, чем не показать вовсе."""
    _with_schema_block(run)
    scenes = json.loads(json.dumps(SCENES))
    scenes[1]["presenter"] = "none"
    scenes[1]["insert"] = None
    scenes[1]["startSec"], scenes[1]["endSec"] = 5.4, 6.0
    scenes[0]["endSec"] = 5.4
    scenes[1]["schema"] = {"form": "list", "items": ["раз", "два"]}
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
    scenes[1]["icon"] = {"query": "fire flame icon"}
    requests = collect_intents(_board(scenes))
    icons = [r for r in requests if r["type"] == "icon"]
    assert icons and icons[0]["key"] == "s-02::icon"
    assert icons[0]["intent"] == "fire flame icon"


def test_значок_на_полнокадровой_ведущей_даже_не_ищется():
    """Место значка — верхняя треть по центру, и при ведущей во весь кадр это
    её лицо. Запрос туда не уходит вовсе: подбор стоит времени."""
    scenes = json.loads(json.dumps(SCENES))
    scenes[0]["presenter"] = "full"
    scenes[0]["icon"] = {"query": "fire flame icon"}
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
