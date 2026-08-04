"""Субтитры — их компонентом caption-highlight, а не нашей вёрсткой."""
import json

from reels_factory.hf_sdk import sdk_session
from reels_factory.hf_captions import COMPONENT_REL, caption_snippet, write_caption_data

COMPONENT = """<!doctype html>
<html><head>
<link href="https://fonts.googleapis.com/css2?family=Montserrat" rel="stylesheet" />
<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
<style>
  .hl-word { font-family: "Montserrat", sans-serif; font-weight: 800; }
</style>
</head>
<body>
<div id="highlight" data-composition-id="caption-highlight" data-timeline-locked
     data-start="0" data-duration="8" data-fps="30" data-width="1920" data-height="1080">
  <div class="hl-overlay"></div>
  <div id="hl-container"></div>
</div>
<script>
  (function () {
    var fitCtx = null;
    fitCtx.font = "800 " + 80 + "px Montserrat";
  })();
</script>
</body></html>"""

WORDS = [{"start": 0.1, "end": 0.5, "text": "Все"},
         {"start": 0.5, "end": 1.0, "text": "продажи"},
         {"start": 4.2, "end": 4.6, "text": "скрыто"},
         {"start": 8.0, "end": 8.4, "text": "снова"}]

CARDS = [{"id": "c1", "zone": "fullscreen", "startSec": 4.0, "endSec": 5.0}]


def _public(tmp_path):
    target = tmp_path / COMPONENT_REL
    target.parent.mkdir(parents=True)
    target.write_text(COMPONENT, encoding="utf-8")
    return tmp_path


def test_слова_под_полноэкранной_карточкой_в_титр_не_идут(tmp_path):
    write_caption_data(_public(tmp_path), words=WORDS, cards=CARDS, duration=10.0)
    data = json.loads((tmp_path / "caption-data.json").read_text(encoding="utf-8"))
    said = [w["text"] for s in data["segments"] for w in s["words"]]
    assert said == ["Все", "продажи", "снова"]


def _snippet(public):
    """Сниппет через мост к их SDK: кусок компонента вынимает их разборщик."""
    with sdk_session() as sdk:
        return caption_snippet(sdk, public, track_index=8, duration=10.0)


def test_данные_в_их_контракте(tmp_path):
    write_caption_data(_public(tmp_path), words=WORDS, cards=[], duration=10.0)
    data = json.loads((tmp_path / "caption-data.json").read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert data["resolution"] == {"width": 1080, "height": 1920}
    # пауза длиннее полусекунды разрывает сегмент
    assert len(data["segments"]) == 3


def test_сниппет_без_внешних_ссылок(tmp_path):
    public = _public(tmp_path)
    write_caption_data(public, words=WORDS, cards=[], duration=10.0)
    snippet = _snippet(public)
    assert "fonts.googleapis.com" not in snippet
    assert "cdn.jsdelivr.net" not in snippet


def test_гарнитура_подменена_в_обоих_местах(tmp_path):
    """Компонент и рисует, и меряет ширину одним именем — менять надо оба."""
    public = _public(tmp_path)
    write_caption_data(public, words=WORDS, cards=[], duration=10.0)
    snippet = _snippet(public)
    assert "Montserrat" not in snippet
    assert snippet.count("Unbounded") == 2


def test_корень_подогнан_под_наш_кадр(tmp_path):
    public = _public(tmp_path)
    write_caption_data(public, words=WORDS, cards=[], duration=10.0)
    snippet = _snippet(public)
    assert 'data-width="1080"' in snippet and 'data-height="1920"' in snippet
    assert 'data-duration="10.0000"' in snippet
    assert 'data-track-index="8"' in snippet


def test_данные_приходят_сразу_а_не_запросом(tmp_path):
    """Компонент умеет и `fetch`, и глобал; в рендере честнее глобал."""
    public = _public(tmp_path)
    write_caption_data(public, words=WORDS, cards=[], duration=10.0)
    snippet = _snippet(public)
    assert "window.__HF_CAPTION__ = {" in snippet
