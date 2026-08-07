"""Композицию собирает код: блоки каталога, ведущая, субтитры, звук."""
import json

import pytest

from reels_factory import hf_compose
from reels_factory.hf_compose import build_composition, collect_intents
from reels_factory.hf_sdk import sdk_session

BLOCK = """<!doctype html>
<html><head><style>.g99-x{color:red}</style></head>
<body>
  <div id="g99-root" data-composition-id="g99-demo" data-start="0"
       data-width="1080" data-height="1920" data-duration="2">
    <div id="g99-clip" class="clip" data-start="0" data-duration="2">
      <div class="g99-line"><span class="g99-w g99-wa">СТРОКА</span></div>
      <div id="g99-art-slot" class="g99-slot" data-slot="image"
           data-slot-role="art"><span class="g99-sl">slot</span></div>
      <div id="g99-presenter-slot" class="g99-slot" data-slot="video"
           data-slot-role="presenter"><span class="g99-sl">slot</span></div>
    </div>
  </div>
  <script>window.__timelines["g99-demo"] = tl;</script>
</body></html>"""

CLIPS = [{"file": "clips/clip-00.mp4", "start": 0.0, "duration": 6.0}]
WORDS = [{"start": 0.2, "end": 0.6, "text": "Все"},
         {"start": 0.6, "end": 1.1, "text": "продажи"},
         {"start": 4.0, "end": 4.4, "text": "точка"}]


def _board(cards):
    return {"schemaVersion": 3,
            "composition": {"fps": 30, "width": 1080, "height": 1920,
                            "durationSeconds": 6.0, "layout": "portrait"},
            "videoTrack": {"sourcePath": "clips/clip-00.mp4", "startSec": 0,
                           "endSec": 6.0,
                           "bounds": {"x": 0, "y": 0, "width": 1080, "height": 1920}},
            "subtitles": {"enabled": True},
            "cards": cards}


@pytest.fixture
def run(tmp_path, monkeypatch):
    public = tmp_path / "public"
    (public / "compositions").mkdir(parents=True)
    (public / "compositions" / "g99-demo.html").write_text(BLOCK, encoding="utf-8")
    monkeypatch.setattr(hf_compose, "write_caption_data",
                        lambda public, **kw: public / "caption-data.json")
    monkeypatch.setattr(hf_compose, "caption_snippet",
                        lambda sdk, public, **kw: '<div id="highlight"></div>')
    return tmp_path


CARDS = [
    {"id": "card-01", "intent": "хук", "startSec": 0, "endSec": 3.02,
     "accentIndex": 0, "zone": "fullscreen", "contentHints": {"title": "Т"},
     "render": {"kind": "block", "block": "g99-demo",
                "text": {"line": "ВСЕ ПРОДАЖИ"}}},
    {"id": "card-02", "intent": "разбор", "startSec": 4.0, "endSec": 6.0,
     "accentIndex": 1, "zone": "fullscreen", "contentHints": {"title": "Т"},
     "render": {"kind": "block", "block": "g99-demo",
                "text": {"line": "ВТОРАЯ СЦЕНА"},
                "media": {"art": "переговоры в офисе"}}},
]


def _build(tmp_path, cards=None, resolved=None):
    board = _board(json.loads(json.dumps(cards or CARDS)))
    with sdk_session() as sdk:
        build_composition(tmp_path, sdk, storyboard=board, clips=CLIPS,
                          duration=6.0, words=WORDS,
                          resolved=resolved if resolved is not None else {
                              "card-02::art": {"file": ".media/image/a.jpg"}})
    return (tmp_path / "public" / "index.html").read_text(encoding="utf-8"), board


def test_блок_подключается_сабкомпозицией_своей_копией(run):
    html, _ = _build(run)
    assert 'data-composition-src="compositions/g99-demo--card-01.html"' in html
    assert 'data-composition-id="g99-demo--card-01"' in html
    copy = (run / "public" / "compositions" / "g99-demo--card-01.html").read_text(
        encoding="utf-8")
    # ключ таймлайна переименован вместе с id, иначе две карточки одного блока
    # затёрли бы друг друга
    assert '__timelines["g99-demo--card-01"]' in copy
    assert "ВСЕ" in copy and "ПРОДАЖИ" in copy


def test_длительность_блока_становится_длительностью_карточки(run):
    _build(run)
    copy = (run / "public" / "compositions" / "g99-demo--card-01.html").read_text(
        encoding="utf-8")
    assert 'data-duration="3.033"' in copy
    assert 'data-duration="2"' not in copy


def test_ведущая_уходит_в_слот_блока_а_общее_окно_прячется(run):
    html, _ = _build(run)
    copy = (run / "public" / "compositions" / "g99-demo--card-01.html").read_text(
        encoding="utf-8")
    assert "g99-presenter" in copy and "clips/clip-00.mp4" in copy
    assert 'tl.set("#video-wrap", { autoAlpha: 0 }, 0);' in html


def test_слишком_короткая_карточка_роняет_сборку(run):
    """Блок собирается своим таймлайном: обрежешь — покажешь полусцену."""
    cards = json.loads(json.dumps(CARDS))
    cards[0]["endSec"] = 0.5          # блок родной длительности 2 с
    with pytest.raises(RuntimeError, match="не успеет собраться"):
        _build(run, cards=cards)


def test_титр_гаснет_под_карточкой(run):
    """Компонент держит группу слов до следующей — она доживала до сцены."""
    html, _ = _build(run)
    assert 'tl.set("#highlight", { autoAlpha: 0 }, 0.0);' in html
    assert 'tl.set("#highlight", { autoAlpha: 1 }, 3.033);' in html


def test_карточка_без_блока_роняет_сборку(run):
    """Карточка собирается только блоком: своей вёрстки у агента больше нет."""
    cards = json.loads(json.dumps(CARDS))
    cards[1]["render"] = {"kind": "block"}
    with pytest.raises(RuntimeError, match="не назван блок каталога"):
        _build(run, cards=cards)


def test_разделитель_рубрики_срезается_кодом(run):
    """Одна такая точка в тексте агента стоила прошлому прогону сессии."""
    cards = json.loads(json.dumps(CARDS))
    cards[0]["render"]["text"] = {"line": "ПРОДАЖИ · БАЗА"}
    _build(run, cards=cards)
    copy = (run / "public" / "compositions" / "g99-demo--card-01.html").read_text(
        encoding="utf-8")
    assert "·" not in copy
    assert "ПРОДАЖИ" in copy and "БАЗА" in copy


def test_вставка_подставляется_кодом(run):
    _build(run)
    copy = (run / "public" / "compositions" / "g99-demo--card-02.html").read_text(
        encoding="utf-8")
    assert 'src=".media/image/a.jpg"' in copy


def test_неподобранная_вставка_не_роняет_сборку(run):
    """Каталог отвечает не на каждое намерение, а сессия агента стоит минут
    пятнадцать: слот уезжает пустым, а «вставок нет совсем» ловит гейт D16."""
    _build(run, resolved={})
    copy = (run / "public" / "compositions" / "g99-demo--card-02.html").read_text(
        encoding="utf-8")
    assert "g99-art-slot" not in copy


def test_намерения_собираются_из_плана(run):
    board = _board(json.loads(json.dumps(CARDS)))
    with sdk_session() as sdk:
        requests = collect_intents(sdk, run / "public", board)
    by_key = {r["key"]: r["intent"] for r in requests}
    assert by_key["card-02::art"] == "переговоры в офисе"
    # у первой карточки намерения нет — код берёт слова самой карточки, иначе
    # слот уехал бы пустым и гейт D16 завернул бы сборку
    assert by_key["card-01::art"] == "Т хук"


def test_раскадровка_переписывается_округлённой(run):
    _build(run)
    board = json.loads((run / "storyboard.json").read_text(encoding="utf-8"))
    assert board["cards"][0]["endSec"] == 3.033


def test_ролик_знает_свою_длительность_и_звук(run):
    html, _ = _build(run)
    assert 'data-duration="6.0000"' in html
    assert '<audio id="voice" src="voice.wav"' in html
    assert 'data-root="true"' in html


def test_в_паузе_между_карточками_ведущая_возвращается(run):
    """Иначе после сцены с ведущей внутри блока кадр остаётся чёрным."""
    html, _ = _build(run)
    assert "autoAlpha: 1 }, 3.033);" in html
    # переезд стыком: твин по left/top их линтер заворачивает ошибкой
    # gsap_non_transform_motion
    assert 'tl.to("#video-wrap"' not in html


def test_в_паузе_без_клипа_ведущей_нет():
    from reels_factory.hf_compose import presenter_timeline

    cards = [{"id": "c1", "startSec": 0, "endSec": 2.0},
             {"id": "c2", "startSec": 5.0, "endSec": 6.0}]
    clips = [{"file": "clips/clip-00.mp4", "start": 0.0, "duration": 2.0}]
    moments = presenter_timeline(cards, clips, 6.0)
    # в паузе 2.0–5.0 клипа нет: показывать нечего, окно остаётся спрятанным
    assert moments == [(0.0, "none")]


CLIPS_REAL = [{"file": "clips/clip-00.mp4", "start": 0.0, "duration": 11.733},
              {"file": "clips/clip-01.mp4", "start": 12.233, "duration": 10.9},
              {"file": "clips/clip-02.mp4", "start": 23.133, "duration": 11.5}]


def test_окно_ведущей_берёт_клип_с_наибольшим_перекрытием():
    """Прогон 10 упал на рендере: карточка начиналась в 23,1 с, клип ведущей
    кончался в 23,133, и выбор по первому кадру давал окно в один кадр —
    «captured 0 of expected 1 frames … aborting render»."""
    from reels_factory.hf_compose import _presenter_media

    piece = _presenter_media(CLIPS_REAL, {"startSec": 23.1, "endSec": 26.4})
    assert piece["file"] == "clips/clip-02.mp4"
    # клип начинается позже карточки — окно появляется со сдвигом, а не тянется
    assert piece["start"] == 0.033
    assert piece["duration"] == 3.267
    assert piece["media_start"] == 0.0


def test_окно_ведущей_не_выходит_за_конец_файла():
    from reels_factory.hf_compose import _presenter_media

    piece = _presenter_media(CLIPS_REAL, {"startSec": 21.0, "endSec": 26.0})
    clip = next(c for c in CLIPS_REAL if c["file"] == piece["file"])
    assert piece["media_start"] + piece["duration"] <= clip["duration"] + 1e-6


def test_огрызок_клипа_в_окно_ведущей_не_ставится():
    """Меньше двух кадров их рендер заворачивает целиком."""
    from reels_factory.hf_compose import _presenter_media

    assert _presenter_media(CLIPS_REAL, {"startSec": 11.7, "endSec": 12.2}) is None


def test_шапка_раскадровки_заполняется_кодом():
    """Агент отдаёт только карточки: в шапке решений нет, а разойтись есть где."""
    from reels_factory.hf_compose import complete_storyboard

    board = complete_storyboard({"cards": []}, clips=CLIPS, duration=41.508)
    assert board["schemaVersion"] == 3
    assert board["composition"]["durationSeconds"] == 41.5
    assert board["videoTrack"]["bounds"] == {"x": 0, "y": 0, "width": 1080,
                                             "height": 1920}
    assert board["subtitles"] == {"enabled": True}


def test_зона_карточки_выводится_кодом():
    """Карточка — всегда блок, а блок непрозрачен во весь кадр."""
    from reels_factory.hf_compose import complete_storyboard

    board = complete_storyboard({"cards": [{"id": "c1", "render": {"block": "g"}}]},
                                clips=CLIPS, duration=6.0)
    assert board["cards"][0]["zone"] == "fullscreen"
    assert board["cards"][0]["render"]["kind"] == "block"


def test_свой_videoTrack_агента_не_переживает_сборку():
    """Sonnet отдал videoTrack списком по клипу — гейт схемы искал bounds."""
    from reels_factory.hf_compose import complete_storyboard

    board = complete_storyboard({"cards": [], "videoTrack": [{"sourcePath": "x"}]},
                                clips=CLIPS, duration=6.0)
    assert isinstance(board["videoTrack"], dict)


def test_клипы_лежат_слоем_а_не_в_потоке(run):
    """Без position:absolute второй клип уходит за нижний край обёртки —
    ведущая пропадает после первого куска, остаток ролика идёт по чёрному."""
    html, _ = _build(run)
    layer = html[html.index("#video-wrap video"):]
    assert "position: absolute" in layer[:120] and "inset: 0" in layer[:120]
