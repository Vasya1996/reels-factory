"""Субтитры — их компонентом caption-highlight, а не нашей вёрсткой."""
import json
from pathlib import Path

from reels_factory.hf_sdk import sdk_session
from reels_factory.hf_captions import (
    COMPONENT_REL, caption_snippet, caption_word_range, write_caption_data,
)

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
    var data = window.__HF_CAPTION__;
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


def _segments(tmp_path, words):
    """Данные титра по списку слов — как их прочтёт компонент."""
    write_caption_data(_public(tmp_path), words=words, duration=10.0)
    return json.loads(
        (tmp_path / "caption-data.json").read_text(encoding="utf-8"))["segments"]


def test_знаки_препинания_не_доезжают_до_кадра(tmp_path):
    """Титр рисует по одному слову: запятая или точка висит отдельным хвостом
    на плашке активного слова, и в кадре это читается как мусор."""
    words = [{"start": 0.0, "end": 0.4, "text": "Сколько"},
             {"start": 0.4, "end": 0.9, "text": "вопросов,"},
             {"start": 0.9, "end": 1.3, "text": "«столько»"},
             {"start": 1.3, "end": 1.7, "text": "Кому?"},
             {"start": 1.7, "end": 2.1, "text": "всё."}]
    said = [w["text"] for s in _segments(tmp_path, words) for w in s["words"]]
    assert said == ["Сколько", "вопросов", "столько", "Кому", "всё"]


def test_дефис_и_апостроф_внутри_слова_остаются(tmp_path):
    """Снимаем только с краёв: в середине те же знаки держат само слово."""
    words = [{"start": 0.0, "end": 0.4, "text": "по-русски,"},
             {"start": 0.4, "end": 0.9, "text": "«д'Артаньян»"},
             {"start": 0.9, "end": 1.3, "text": "кто-нибудь?"}]
    said = [w["text"] for s in _segments(tmp_path, words) for w in s["words"]]
    assert said == ["по-русски", "д'Артаньян", "кто-нибудь"]


def test_числа_и_проценты_не_ломаются(tmp_path):
    """Процента в списке снимаемых знаков нет, а запятая дробного стоит внутри
    слова — «38%» и «2,5» должны остаться числами."""
    words = [{"start": 0.0, "end": 0.4, "text": "38%,"},
             {"start": 0.4, "end": 0.9, "text": "2,5"},
             {"start": 0.9, "end": 1.3, "text": "(1500)"}]
    said = [w["text"] for s in _segments(tmp_path, words) for w in s["words"]]
    assert said == ["38%", "2,5", "1500"]


def test_слово_из_одной_пунктуации_выброшено_а_времена_на_месте(tmp_path):
    """Тире отдельным словом рисовать нечего, но соседям времена не двигаем —
    они звучат тогда же, и подсветка остаётся на своих местах. Деление на
    сегменты считается по прежним временам: убери мы тире до деления, пауза
    0,5 + 0,5 склеилась бы в 1,1 и разорвала бы сегмент надвое."""
    words = [{"start": 0.0, "end": 1.0, "text": "Раз"},
             {"start": 1.5, "end": 1.6, "text": "—"},
             {"start": 2.1, "end": 2.6, "text": "два"}]
    segments = _segments(tmp_path, words)
    assert len(segments) == 1
    assert segments[0]["text"] == "Раз два"
    assert [(w["text"], w["start"], w["end"]) for w in segments[0]["words"]] == [
        ("Раз", 0.0, 1.0), ("два", 2.1, 2.6)]


def test_счёт_слова_по_имени_берёт_ровно_одно(tmp_path):
    """`word` сужает интервал до ОДНОГО слова — не диапазона, которым отвечал
    бы код без имени: пример paste-мишени `caption` (`hf_compose`), где два
    слова сцены иначе легли бы под один класс разом."""
    words = [{"start": 3.0, "end": 3.4, "text": "точка"},
             {"start": 3.5, "end": 3.9, "text": "роста"}]
    assert caption_word_range(words, 0.0, 10.0) == (0, 2)
    assert caption_word_range(words, 0.0, 10.0, word="роста") == (1, 2)
    assert caption_word_range(words, 0.0, 10.0, word="точка") == (0, 1)


def test_счёт_слова_по_имени_без_учёта_регистра_и_краевой_пунктуации(tmp_path):
    """Слово плана и слово титра совпадают буквами, не оформлением: агент
    пишет как в реплике, титр — как решит регистр TTS/ASR, и точка на конце
    фразы не должна разводить одно и то же слово на два разных."""
    words = [{"start": 3.0, "end": 3.4, "text": "Бесплатно."}]
    assert caption_word_range(words, 0.0, 10.0, word="бесплатно") == (0, 1)
    assert caption_word_range(words, 0.0, 10.0, word="Бесплатно") == (0, 1)


def test_счёт_слова_по_имени_которого_нет_пуст(tmp_path):
    """Слова нет среди звучащих в интервал — тот же отказ, что и при полном
    отсутствии титра: пустой интервал `(0, 0)`, а не первое попавшееся."""
    words = [{"start": 3.0, "end": 3.4, "text": "точка"}]
    assert caption_word_range(words, 0.0, 10.0, word="деньги") == (0, 0)
    # Слово есть в расшифровке, но не в этом интервале секунд — тот же отказ.
    assert caption_word_range(words, 5.0, 10.0, word="точка") == (0, 0)


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


def test_бренд_с_цветом_подсветки_доезжает_в_данные(tmp_path):
    """`highlightInk` — наше третье поле контракта, не их (`primaryColor`/
    `accentColor`): `write_caption_data` кладёт бренд как есть, а решение,
    каким его считать, остаётся у вызывающего (`hf_compose.build_composition`
    через `hf_frame.highlight_ink`)."""
    write_caption_data(_public(tmp_path), words=WORDS, duration=10.0,
                       brand={"primaryColor": "#f5f7fb",
                              "accentColor": "#5ee0c0",
                              "highlightInk": "#0b0f1a"})
    data = json.loads((tmp_path / "caption-data.json").read_text(encoding="utf-8"))
    assert data["brand"] == {"primaryColor": "#f5f7fb", "accentColor": "#5ee0c0",
                             "highlightInk": "#0b0f1a"}


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


def test_шрифт_прогружается_перед_подгонкой_кегля():
    """rb0908-university 32.2с, «АВТОМАТИЗИРОВАТЬ» обрезано с двух сторон:
    наши шрифты несут `unicode-range`-подмножества, догружаемые лениво по
    первому использованию (`hf_fonts.py`), а на боте компонента ещё нет ни
    одного элемента с текстом — `document.fonts.ready` сам по себе резолвится,
    не дождавшись кириллического начертания Unbounded 800, и подгонка кегля
    меряет запасным шрифтом. `hfBoot` обязан явно запросить гарнитуру
    подписи под текст титра ДО `fonts.ready`."""
    from reels_factory.hf_captions import VETTED

    vetted_text = VETTED.read_text(encoding="utf-8")
    boot_start = vetted_text.index("function hfBoot")
    boot_text = vetted_text[boot_start:]
    load_idx = boot_text.index("document.fonts.load(")
    ready_idx = boot_text.index("document.fonts.ready")
    call = boot_text[load_idx:load_idx + 200]
    assert '"800 ' in call
    assert "Montserrat" in call
    assert load_idx < ready_idx


def test_гарнитура_прогрузки_подменена_тем_же_способом(tmp_path):
    """Подмена имени в `hf_captions.py:286` — слепой `replace` над ЛЮБЫМ
    вхождением `Montserrat` в теле скрипта; строка, добавленная этой правкой,
    должна пройти ту же подмену, что и `fitFontSize`/CSS, иначе движок
    прогрел бы не ту гарнитуру, которую потом мерит и рисует. Проверяем на
    реальной `VETTED`-копии (мок `COMPONENT` наверху файла не несёт `hfBoot`)."""
    from reels_factory.hf_captions import VETTED

    public = tmp_path
    target = public / COMPONENT_REL
    target.parent.mkdir(parents=True)
    target.write_text(VETTED.read_text(encoding="utf-8"), encoding="utf-8")
    write_caption_data(public, words=WORDS, duration=10.0)
    _snippet(public)
    engine = (public / "captions.js").read_text(encoding="utf-8")
    assert 'fonts.load("800 60px Unbounded"' in engine
    assert "Montserrat" not in engine


def test_корень_подогнан_под_наш_кадр(tmp_path):
    public = _public(tmp_path)
    write_caption_data(public, words=WORDS, duration=10.0)
    snippet = _snippet(public)
    assert 'data-width="1080"' in snippet and 'data-height="1920"' in snippet
    assert 'data-duration="10.0000"' in snippet
    assert 'data-track-index="8"' in snippet


def test_корень_титра_помечен_разрешением_полосы(tmp_path):
    """Полосу титра мы сами объявляем запретной их гейтом `--caption-zone` с
    `severity=error` (`hf_render.py`), а слова титра стоят ровно в ней: отступ
    620 px от низа при полосе от 998,4. Без пометки требование невыполнимо по
    построению, и сборка держалась на том, что гейт снимает один кадр
    `t = duration`, где последняя группа уже погашена. `closest()` находит
    атрибут на корне для каждого слова
    (layout-audit.browser.js:108-110,1403)."""
    public = _public(tmp_path)
    write_caption_data(public, words=WORDS, duration=10.0)
    snippet = _snippet(public)
    assert 'data-layout-allow-caption-zone="true"' in snippet


def test_демо_вместо_движка_роняет_сборку(tmp_path):
    """11.08.2026 их `add` привёз версию компонента, где движок заменён
    демонстрацией: свои `WORDS` в коде, `window.__HF_CAPTION__` не читается.
    В кадр поехал их демо-текст («DRAG AND DROP») вместо реплик диктора, и
    прошло это молча — поймали только по гейту «текст на лице». Реестр они
    отдают из ветки `main`, так что версия меняется под нами без спроса."""
    import pytest

    public = _public(tmp_path)
    demo = (public / COMPONENT_REL).read_text(encoding="utf-8").replace(
        "var data = window.__HF_CAPTION__;", "var WORDS = [{text: 'DRAG'}];")
    (public / COMPONENT_REL).write_text(demo, encoding="utf-8")
    write_caption_data(public, words=WORDS, duration=10.0)
    with pytest.raises(RuntimeError, match="демо-текст"):
        _snippet(public)


def test_проверенная_копия_компонента_лежит_рядом():
    """Запасной путь `install`: если их версия перестала читать наши данные,
    несёт нашу правку кегля/переноса слова или подгонки цвета под контраст,
    берётся эта копия — иначе титр молча покажет чужой текст, обрезанное
    слово или буквы ниже порога контраста."""
    from reels_factory.hf_captions import (
        CONTRAST_MARKER, DATA_HOOK, FIT_MARKER, VETTED,
    )

    assert VETTED.exists(), f"нет проверенной копии компонента: {VETTED}"
    vetted_text = VETTED.read_text(encoding="utf-8")
    assert DATA_HOOK in vetted_text
    assert FIT_MARKER in vetted_text
    assert CONTRAST_MARKER in vetted_text
    assert "white-space: nowrap;" in vetted_text  # дефис внутри .hl-word не переносит строку


def test_привезённая_версия_без_нашей_подгонки_заменяется_проверенной(
        tmp_path, monkeypatch):
    """`install()` не должен молча взять чужой файл без нашей правки кегля и
    переноса слова: их `add` может привезти версию, где `FIT_MARKER` ещё нет
    (обычный случай — правка живёт только в `VETTED`, см. шапку модуля).
    Симулируем `npx hyperframes add`, чтобы не ходить в сеть: настоящий
    `subprocess.run` заменён на функцию, кладущую в `target` файл, который
    читает данные (`DATA_HOOK` есть), но нашей подгонки не несёт."""
    import subprocess

    from reels_factory import hf_captions

    def fake_run(cmd, **kwargs):
        target = Path(kwargs["cwd"]) / hf_captions.COMPONENT_REL
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            f"<html><body>{hf_captions.DATA_HOOK}</body></html>",
            encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(hf_captions.subprocess, "run", fake_run)
    result = hf_captions.install(tmp_path)
    assert hf_captions.FIT_MARKER in result.read_text(encoding="utf-8")
    assert result.read_bytes() == hf_captions.VETTED.read_bytes()


def test_привезённая_версия_с_подгонкой_кегля_но_без_контраста_тоже_заменяется(
        tmp_path, monkeypatch):
    """Метки независимы: версия может нести старую правку кегля/переноса
    (`FIT_MARKER`) и всё ещё не знать про подгонку цвета под контраст
    (`CONTRAST_MARKER`, добавлена позже) — тогда `install()` обязан заменить
    файл на `VETTED`, а не остановиться на первой найденной метке."""
    import subprocess

    from reels_factory import hf_captions

    def fake_run(cmd, **kwargs):
        target = Path(kwargs["cwd"]) / hf_captions.COMPONENT_REL
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            f"<html><body>{hf_captions.DATA_HOOK} {hf_captions.FIT_MARKER}"
            "</body></html>", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(hf_captions.subprocess, "run", fake_run)
    result = hf_captions.install(tmp_path)
    assert hf_captions.CONTRAST_MARKER in result.read_text(encoding="utf-8")
    assert result.read_bytes() == hf_captions.VETTED.read_bytes()


def test_уже_лежащая_в_staging_версия_без_подгонки_тоже_заменяется(
        tmp_path, monkeypatch):
    """07.09.2026, `rb0909-ai-employee`: папку задания скопировали с
    августовского прогона вместе с `.hf-captions/`, и ранний возврат
    (`if target.exists(): return target`) отдавал компонент без обеих правок
    как есть — ни один маркер не проверялся, потому что проверка стояла
    только для только что привезённого `npx add` файла. Здесь `target`
    существует ДО вызова `install()`, `subprocess.run` заменён на функцию,
    которая проваливает тест при вызове — `npx` не должен запускаться вовсе,
    раз `target` уже на месте, — и всё равно должна вернуться `VETTED`."""
    import subprocess

    from reels_factory import hf_captions

    def fail_run(cmd, **kwargs):
        raise AssertionError("npx add не должен запускаться: target уже есть")

    target = tmp_path / ".hf-captions" / hf_captions.COMPONENT_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"<html><body>{hf_captions.DATA_HOOK}</body></html>",
                      encoding="utf-8")

    monkeypatch.setattr(hf_captions.subprocess, "run", fail_run)
    result = hf_captions.install(tmp_path)
    assert result == target
    assert hf_captions.FIT_MARKER in result.read_text(encoding="utf-8")
    assert result.read_bytes() == hf_captions.VETTED.read_bytes()


def test_три_метки_есть_но_байты_не_vetted_всё_равно_заменяются(
        tmp_path, monkeypatch):
    """08.09.2026, прод, задание `rb0908-university`: `.hf-captions/` несла
    компонент от 31.08 — до PR #105 с прогревом кириллического начертания
    перед подгонкой кегля. Все три метки (`DATA_HOOK`/`FIT_MARKER`/
    `CONTRAST_MARKER`) уже были внутри этого старого файла, старый
    маркерный `_vet` принимал его как свой ранним возвратом, и
    «ИССЛЕДОВАТЕЛЯМИ» обрезало по краям кадра. Критерий теперь — совпадение
    байтов с `VETTED`, а не список меток: файл с тремя метками, но чужим
    телом, обязан замениться."""
    import subprocess

    from reels_factory import hf_captions

    def fail_run(cmd, **kwargs):
        raise AssertionError("npx add не должен запускаться: target уже есть")

    stale_with_all_markers = (
        "<html><body>"
        f"{hf_captions.DATA_HOOK} {hf_captions.FIT_MARKER} "
        f"{hf_captions.CONTRAST_MARKER}"
        "</body></html>"
    )
    assert stale_with_all_markers != hf_captions.VETTED.read_text(encoding="utf-8")

    target = tmp_path / ".hf-captions" / hf_captions.COMPONENT_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(stale_with_all_markers, encoding="utf-8")

    monkeypatch.setattr(hf_captions.subprocess, "run", fail_run)
    result = hf_captions.install(tmp_path)
    assert result == target
    assert result.read_bytes() == hf_captions.VETTED.read_bytes()


def test_уже_лежащая_в_staging_версия_идентичная_vetted_не_перезаписывается(
        tmp_path, monkeypatch):
    """Совпадающие с `VETTED` байты не должны трогать файл: не только
    содержимое остаётся тем же, но и `_vet` не должен переписывать файл,
    когда сверять уже нечего — иначе каждый прогон бил бы по диску и по
    mtime staging-копии без всякой причины."""
    import shutil
    import subprocess
    import time

    from reels_factory import hf_captions

    def fail_run(cmd, **kwargs):
        raise AssertionError("npx add не должен запускаться: target уже есть")

    target = tmp_path / ".hf-captions" / hf_captions.COMPONENT_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(hf_captions.VETTED, target)
    before_mtime = target.stat().st_mtime_ns
    time.sleep(0.01)

    monkeypatch.setattr(hf_captions.subprocess, "run", fail_run)
    result = hf_captions.install(tmp_path)
    assert result == target
    assert target.stat().st_mtime_ns == before_mtime
    assert result.read_bytes() == hf_captions.VETTED.read_bytes()


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
