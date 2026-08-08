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

def _public(tmp_path):
    target = tmp_path / COMPONENT_REL
    target.parent.mkdir(parents=True)
    target.write_text(COMPONENT, encoding="utf-8")
    return tmp_path


def test_титр_идёт_весь_ролик(tmp_path):
    """Гасить его было нужно, пока сцена была непрозрачным блоком со своим
    текстом. В слоёном кадре своего текста нет ни у вставки, ни у ведущей."""
    write_caption_data(_public(tmp_path), words=WORDS, duration=10.0)
    data = json.loads((tmp_path / "caption-data.json").read_text(encoding="utf-8"))
    said = [w["text"] for s in data["segments"] for w in s["words"]]
    assert said == ["Все", "продажи", "скрыто", "снова"]


def _snippet(public):
    """Сниппет через мост к их SDK: кусок компонента вынимает их разборщик."""
    with sdk_session() as sdk:
        return caption_snippet(sdk, public, track_index=8, duration=10.0)


def test_данные_в_их_контракте(tmp_path):
    write_caption_data(_public(tmp_path), words=WORDS, duration=10.0)
    data = json.loads((tmp_path / "caption-data.json").read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert data["resolution"] == {"width": 1080, "height": 1920}
    # пауза длиннее полусекунды разрывает сегмент
    assert len(data["segments"]) == 3


def test_сниппет_без_внешних_ссылок(tmp_path):
    public = _public(tmp_path)
    write_caption_data(public, words=WORDS, duration=10.0)
    snippet = _snippet(public)
    assert "fonts.googleapis.com" not in snippet
    assert "cdn.jsdelivr.net" not in snippet


def test_гарнитура_подменена_в_обоих_местах(tmp_path):
    """Компонент и рисует, и меряет ширину одним именем — менять надо оба."""
    public = _public(tmp_path)
    write_caption_data(public, words=WORDS, duration=10.0)
    snippet = _snippet(public)
    engine = (public / "captions.js").read_text(encoding="utf-8")
    assert "Montserrat" not in snippet and "Montserrat" not in engine
    # рисует стиль, меряет ширину движок — гарнитура подменена в обоих
    assert "Unbounded" in snippet and "Unbounded" in engine


def test_корень_подогнан_под_наш_кадр(tmp_path):
    public = _public(tmp_path)
    write_caption_data(public, words=WORDS, duration=10.0)
    snippet = _snippet(public)
    assert 'data-width="1080"' in snippet and 'data-height="1920"' in snippet
    assert 'data-duration="10.0000"' in snippet
    assert 'data-track-index="8"' in snippet


def test_движок_титра_уезжает_отдельным_файлом(tmp_path):
    """Их линтер считает строки index.html и за 300 даёт предупреждение
    `composition_file_too_large`; под `--strict` оно роняет сборку. В прогоне
    13 из 684 строк 608 были этим скриптом и его данными."""
    public = _public(tmp_path)
    write_caption_data(public, words=WORDS, duration=10.0)
    snippet = _snippet(public)
    assert "window.__HF_CAPTION__ = {" in (
        public / "captions.js").read_text(encoding="utf-8")
    assert '<script src="captions.js">' in snippet
