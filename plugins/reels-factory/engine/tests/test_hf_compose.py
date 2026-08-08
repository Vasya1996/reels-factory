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
    monkeypatch.setattr(hf_compose, "write_caption_data",
                        lambda public, **kw: public / "caption-data.json")
    monkeypatch.setattr(hf_compose, "caption_snippet",
                        lambda sdk, public, **kw: '<div id="highlight"></div>')
    return tmp_path


SCENES = [
    {"id": "s-01", "intent": "хук", "startSec": 0, "endSec": 3.033,
     "presenter": "full", "insert": None},
    {"id": "s-02", "intent": "разбор", "startSec": 3.033, "endSec": 6.0,
     "presenter": "pip-br",
     "insert": {"look": "переговоры в офисе", "kind": "photo"}},
]

FOUND = {"s-02": {"file": ".media/images/a.jpg"}}


def _build(tmp_path, scenes=None, resolved=None):
    board = _board(json.loads(json.dumps(scenes or SCENES)))
    with sdk_session() as sdk:
        build_composition(tmp_path, sdk, storyboard=board, clips=CLIPS,
                          duration=6.0, words=WORDS,
                          resolved=FOUND if resolved is None else resolved)
    return (tmp_path / "public" / "index.html").read_text(encoding="utf-8"), board


# ---------- слои кадра ----------

def test_вставка_встаёт_обычным_клипом(run):
    html, _ = _build(run)
    assert 'id="ins-s-02" class="ins clip"' in html
    assert 'src=".media/images/a.jpg"' in html
    # обёртка несёт время, медиа внутри — только картинку: клип обязан быть
    # прямым потомком корня композиции
    assert 'data-start="3.0330"' in html


def test_вставка_под_ведущей_в_углу_занимает_весь_кадр(run):
    html, _ = _build(run)
    layer = html[html.index('id="ins-s-02"'):]
    assert "left:0px;top:0px;width:1080px;height:1920px" in layer[:300]


def test_вставка_дополняет_ведущую_в_половине_кадра(run):
    scenes = json.loads(json.dumps(SCENES))
    scenes[1]["presenter"] = "stack"
    html, _ = _build(run, scenes=scenes)
    layer = html[html.index('id="ins-s-02"'):]
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
    assert html.index('id="ins-s-02"') < html.index('id="video-wrap"')


def test_вставки_разложены_по_дорожкам_по_три(run):
    """Четвёртая на одной дорожке — предупреждение `timeline_track_too_dense`,
    а под `--strict` предупреждение роняет сборку."""
    scenes = []
    for index in range(7):
        start = round(index * 0.8, 3)
        scenes.append({"id": f"s-{index:02d}", "intent": "и",
                       "startSec": start, "endSec": round(start + 0.8, 3),
                       "presenter": "pip-br",
                       "insert": {"look": f"вставка {index}", "kind": "photo"}})
    html, _ = _build(run, scenes=scenes,
                     resolved={f"s-{i:02d}": {"file": ".media/images/a.jpg"}
                               for i in range(7)})
    tracks = [html[m:m + 30] for m in range(len(html))
              if html.startswith('data-track-index="', m)]
    used = {t.split('"')[1] for t in tracks}
    assert {"3", "4", "5"} <= used


def test_вставка_медленно_наезжает(run):
    """Неподвижной картинки в эталонных рилсах не бывает ни секунды."""
    html, _ = _build(run)
    assert 'tl.set("#ins-s-02 .ins-media", { scale: 1 }' in html
    assert 'tl.to("#ins-s-02 .ins-media"' in html


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

def test_намерения_собираются_из_плана():
    requests = collect_intents(_board(json.loads(json.dumps(SCENES))))
    assert requests == [{"key": "s-02", "type": "image",
                         "intent": "переговоры в офисе"}]


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


def test_вставку_для_куска_без_ведущей_занимают_у_соседа():
    """Одна неподобранная картинка в хвосте роняла всю сборку. Повтор кадра —
    плохо, чёрный экран — провал: занимаем ту, что не стоит рядом."""
    board = _board([
        {"id": "s-01", "intent": "и", "startSec": 0.0, "endSec": 2.0,
         "presenter": "pip-br", "insert": {"look": "стол"}},
        {"id": "s-02", "intent": "и", "startSec": 2.0, "endSec": 4.0,
         "presenter": "pip-tl", "insert": {"look": "окно"}},
        {"id": "s-03", "intent": "и", "startSec": 4.0, "endSec": 6.0,
         "presenter": "none", "insert": {"look": "не найдётся"}}])
    short = [{"file": "clips/clip-00.mp4", "start": 0.0, "duration": 4.0}]
    resolved = {"s-01": {"file": "a.jpg"}, "s-02": {"file": "b.jpg"}}
    settle_inserts(board, resolved, short, 6.0)
    # у соседней s-02 стоит b.jpg, значит занимаем другую
    assert resolved["s-03"]["file"] == "a.jpg"
    assert board["scenes"][2]["insert"] is not None


def test_одна_картинка_на_две_сцены_не_ставится():
    """`media-use` отвечает на близкие намерения одним файлом. Повтор кадра —
    брак монтажа, и их линтер зовёт его `duplicate_media_discovery_risk`."""
    board = _board([
        {"id": "s-01", "intent": "и", "startSec": 0.0, "endSec": 3.0,
         "presenter": "pip-br", "insert": {"look": "стол"}},
        {"id": "s-02", "intent": "и", "startSec": 3.0, "endSec": 6.0,
         "presenter": "pip-tl", "insert": {"look": "тот же стол другими словами"}}])
    lost = settle_inserts(board, {"s-01": {"file": "a.jpg"},
                                  "s-02": {"file": "a.jpg"}}, CLIPS, 6.0)
    assert lost == ["s-02"]
    assert board["scenes"][1]["insert"] is None


def test_занять_не_у_кого_роняет_сборку():
    board = _board([{"id": "s-01", "intent": "и", "startSec": 0.0,
                     "endSec": 6.0, "presenter": "none",
                     "insert": {"look": "нечто"}}])
    short = [{"file": "clips/clip-00.mp4", "start": 0.0, "duration": 2.0}]
    with pytest.raises(RuntimeError, match="занять\nкартинку не у кого|не у кого"):
        settle_inserts(board, {}, short, 6.0)


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
