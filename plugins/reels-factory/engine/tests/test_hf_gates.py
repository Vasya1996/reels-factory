"""Гейты раскадровки: их `check` её не читает вовсе, значит проверяем мы."""
import pytest

from reels_factory.hf_gates import (
    check_frame_filled, check_media, check_placeholders, check_storyboard,
    min_scenes,
)
from reels_factory.hf_layout import quantize

DURATION = 41.5
# три клипа с ведущей, хвост 34.62–41.5 без неё — как в реальном материале
CLIPS = [{"file": "clips/clip-00.mp4", "start": 0.0, "duration": 11.72},
         {"file": "clips/clip-01.mp4", "start": 12.22, "duration": 10.92},
         {"file": "clips/clip-02.mp4", "start": 23.14, "duration": 11.48}]


def _scene(index: int, start: float, end: float, **over):
    scene = {"id": f"s-{index:02d}", "intent": "зачем эта сцена",
             "startSec": start, "endSec": end, "presenter": "full",
             "insert": None}
    scene.update(over)
    return scene


def _photo(look: str) -> dict:
    return {"look": look, "kind": "photo"}


def _board(scenes, **over):
    board = {
        "schemaVersion": 3,
        "composition": {"fps": 30, "width": 1080, "height": 1920,
                        "durationSeconds": DURATION, "layout": "portrait",
                        "themeId": "noir", "seed": 42},
        "videoTrack": {"sourcePath": "clips/clip-00.mp4", "startSec": 0,
                       "endSec": DURATION,
                       "bounds": {"x": 0, "y": 0, "width": 1080, "height": 1920}},
        "subtitles": {"enabled": True},
        "scenes": scenes,
    }
    board.update(over)
    return board


def _plausible_scenes():
    """Двадцать две сцены встык: ролик выстлан целиком, соседние различимы.

    Куски без ведущей — 11.72–12.22 и 34.62–41.5 — закрыты сценами, где ведущей
    нет вовсе и стоит полноэкранная вставка.
    """
    edges = [quantize(value) for value in
             (0.0, 2.0, 4.0, 6.0, 8.0, 10.0, 11.72, 12.22, 14.0, 16.0, 18.0,
              20.0, 22.0, 23.14, 25.0, 27.0, 29.0, 31.0, 33.0, 34.62, 37.0,
              39.0, DURATION)]
    faceless = {6, 19, 20, 21}          # индексы сцен внутри пропусков
    scenes = []
    for index, (start, end) in enumerate(zip(edges, edges[1:])):
        if index in faceless:
            scenes.append(_scene(index, start, end, presenter="none",
                                 insert=_photo(f"вставка {index}")))
        elif index % 2:
            scenes.append(_scene(index, start, end, presenter="pip-br",
                                 insert=_photo(f"вставка {index}")))
        else:
            scenes.append(_scene(index, start, end))
    return scenes


def _check(scenes, **over):
    return check_storyboard(_board(scenes, **over), clips=CLIPS,
                            duration=DURATION)


def test_чистая_раскадровка_проходит():
    assert set(_check(_plausible_scenes()).values()) == {"PASS"}


# ---------- схема ----------

def test_наши_прежние_поля_больше_не_принимаются():
    """contentRect, videoRect и zone противоречат их схеме и модели слоёв."""
    scenes = _plausible_scenes()
    scenes[0]["zone"] = "fullscreen"
    assert _check(scenes)["D11_schema"].startswith("FAIL")


def test_чужая_версия_схемы_валится():
    assert _check(_plausible_scenes(), schemaVersion=2)["D11_schema"].startswith("FAIL")


def test_сцена_без_смысла_валится():
    scenes = _plausible_scenes()
    scenes[0].pop("intent")
    assert _check(scenes)["D11_schema"].startswith("FAIL")


def test_выдуманное_положение_ведущей_валится():
    """Позиции нет в списке — падаем внятно, а не додумываем."""
    scenes = _plausible_scenes()
    scenes[0]["presenter"] = "где-то сбоку"
    assert _check(scenes)["D11_schema"].startswith("FAIL")


def test_вставка_без_описания_валится():
    scenes = _plausible_scenes()
    scenes[1]["insert"] = {"kind": "photo"}
    assert _check(scenes)["D11_schema"].startswith("FAIL")


def test_геометрия_ведущей_обязана_быть_задана():
    board = _board(_plausible_scenes())
    board["videoTrack"].pop("bounds")
    assert check_storyboard(board, clips=CLIPS,
                            duration=DURATION)["D11_schema"].startswith("FAIL")


# ---------- плотность ----------

def test_пустая_раскадровка_валится():
    """Прошлый гейт перебирал сцены циклом — пустой список проходил всё."""
    assert _check([])["D13_density"].startswith("FAIL")


@pytest.mark.parametrize("duration,expected", [
    (41.5, 6),      # ceil(41,5 / 8): пол только против дыр длиннее D19
    (12.0, 2),
    (121.2, 16),
])
def test_пол_сцен_только_против_дыр(duration, expected):
    """Пол выведен из D19 (кусок не длиннее восьми секунд), и только из него.
    Прежний вывод из D18 давал 21 сцену на 41,5 с — метроном; смену картинки
    дают ещё переход, смена положения ведущей и наезд, поэтому планку D18
    числом сцен не назначаем."""
    assert min_scenes(duration) == expected


def test_пяти_сцен_на_сорок_секунд_мало():
    """При пяти сценах на 41,5 с найдётся кусок длиннее восьми секунд."""
    step = DURATION / 5
    scenes = [_scene(i, round(i * step, 3), round((i + 1) * step, 3))
              for i in range(5)]
    assert _check(scenes)["D13_density"].startswith("FAIL")


def test_потолка_плотности_нет():
    edges = [round(i * DURATION / 40, 3) for i in range(41)]
    scenes = [_scene(i, start, end, presenter="pip-br" if i % 2 else "full",
                     insert=_photo(f"в{i}") if i % 2 else None)
              for i, (start, end) in enumerate(zip(edges, edges[1:]))]
    assert _check(scenes)["D13_density"] == "PASS"


# ---------- сетка ----------

def test_время_вне_сетки_кадров_валится():
    scenes = _plausible_scenes()
    scenes[0]["endSec"] = 2.017
    scenes[1]["startSec"] = 2.017
    assert _check(scenes)["D9_frame_grid"].startswith("FAIL")


def test_гейта_зоны_больше_нет():
    assert "D10_zone" not in _check(_plausible_scenes())


# ---------- D12: кусок без ведущей ----------

def test_кусок_без_ведущей_обязан_нести_вставку():
    scenes = _plausible_scenes()
    scenes[19]["insert"] = None
    assert _check(scenes)["D12_faceless_cover"].startswith("FAIL")


def test_ведущая_на_куске_где_её_нет_валится():
    """План может назначить ей угол там, где аватар не заказан: окно будет
    пустым, а кадр — чёрным."""
    scenes = _plausible_scenes()
    scenes[19]["presenter"] = "pip-br"
    assert _check(scenes)["D12_faceless_cover"].startswith("FAIL")


# ---------- D20: пустого кадра не бывает ----------

def test_ведущая_в_углу_без_вставки_это_чёрный_кадр():
    result = check_frame_filled({"scenes": [_scene(1, 0.0, 2.0,
                                                  presenter="pip-bl")]})
    assert result["D20_frame_filled"].startswith("FAIL")


def test_ведущая_во_весь_кадр_закрывает_его_сама():
    result = check_frame_filled({"scenes": [_scene(1, 0.0, 2.0)]})
    assert result["D20_frame_filled"] == "PASS"


def test_ведущая_в_углу_поверх_вставки_норма():
    result = check_frame_filled({"scenes": [
        _scene(1, 0.0, 2.0, presenter="pip-bl", insert=_photo("стол"))]})
    assert result["D20_frame_filled"] == "PASS"


def test_половина_кадра_без_вставки_это_чёрный_кадр():
    result = check_frame_filled({"scenes": [_scene(1, 0.0, 2.0,
                                                  presenter="stack")]})
    assert result["D20_frame_filled"].startswith("FAIL")


def test_без_ведущей_и_без_вставки_кадр_пуст():
    result = check_frame_filled({"scenes": [_scene(1, 0.0, 2.0,
                                                  presenter="none")]})
    assert result["D20_frame_filled"].startswith("FAIL")


# ---------- D21: соседние сцены различимы ----------

def test_две_одинаковые_сцены_подряд_это_один_план():
    """Зазора между сценами больше нет, и смену даёт сама граница — но только
    если по её сторонам разная картинка."""
    scenes = _plausible_scenes()
    scenes[1]["presenter"] = "full"
    scenes[1]["insert"] = None
    assert _check(scenes)["D21_scene_contrast"].startswith("FAIL")


def test_разная_вставка_при_том_же_положении_различима():
    scenes = _plausible_scenes()
    scenes[0]["presenter"] = "pip-br"
    scenes[0]["insert"] = _photo("совсем другая картинка")
    assert _check(scenes)["D21_scene_contrast"] == "PASS"


# ---------- вставки ----------

def _project(tmp_path, html: str, *, ledger: bool = True, image: bool = True):
    public = tmp_path / "public"
    (public / "media").mkdir(parents=True)
    if image:
        (public / "media" / "hands.jpg").write_bytes(b"\xff\xd8\xff")
    if ledger:
        (tmp_path / ".media").mkdir()
        (tmp_path / ".media" / "manifest.jsonl").write_text(
            '{"type":"image"}\n', encoding="utf-8")
    (public / "index.html").write_text(html, encoding="utf-8")
    return tmp_path


def test_подобранная_картинка_принимается(tmp_path):
    project = _project(tmp_path, '<img src="media/hands.jpg">')
    assert check_media(project)["D16_media_use"] == "PASS"


def test_картинка_из_css_тоже_считается(tmp_path):
    project = _project(tmp_path, '<div style="background:url(media/hands.jpg)">')
    assert check_media(project)["D16_media_use"] == "PASS"


def test_ролик_без_единой_вставки_валится(tmp_path):
    """Ровно то, чем кончился прогон 03.08: ведущая, субтитры и текст."""
    project = _project(tmp_path, "<div>ПРОДАЖИ</div>", ledger=False, image=False)
    assert check_media(project)["D16_media_use"].startswith("FAIL")


def test_ссылка_на_несуществующий_файл_не_считается(tmp_path):
    project = _project(tmp_path, '<img src="media/нет-такого.jpg">', image=False)
    assert check_media(project)["D16_media_use"].startswith("FAIL")


def test_внешняя_ссылка_вставкой_не_считается(tmp_path):
    project = _project(tmp_path, '<img src="https://example.com/a.jpg">', image=False)
    assert check_media(project)["D16_media_use"].startswith("FAIL")


# ---------- заглушки блоков ----------

def _block_pair(tmp_path, copy_html):
    compositions = tmp_path / "public" / "compositions"
    compositions.mkdir(parents=True)
    (compositions / "lt-clean-bar.html").write_text(
        '<div><span class="lt-name">Jordan Avery</span>'
        '<span class="lt-role">Host</span><span class="n">01</span></div>'
        "<style>.x{color:red}</style><script>var t = 1;</script>",
        encoding="utf-8")
    (compositions / "lt-clean-bar--s-02.html").write_text(
        copy_html, encoding="utf-8")
    return tmp_path


def test_заглушка_в_копии_блока_валится(tmp_path):
    """Их линтер незаполненных плейсхолдеров не ловит вовсе — среди его кодов
    нет ни одного про заглушки. Заглушка — текст, дословно совпадающий с
    исходником блока."""
    run = _block_pair(
        tmp_path,
        '<div><span class="lt-name">Jordan Avery</span>'
        '<span class="lt-role">Ведущая</span><span class="n">01</span></div>')
    verdict = check_placeholders(run)["D22_placeholders"]
    assert verdict.startswith("FAIL") and "Jordan Avery" in verdict


def test_заполненная_копия_блока_проходит(tmp_path):
    """Цифры и значки — оформление сцены, совпадение по ним не заглушка."""
    run = _block_pair(
        tmp_path,
        '<div><span class="lt-name">Вася Андронов</span>'
        '<span class="lt-role">Ведущая</span><span class="n">01</span></div>')
    assert check_placeholders(run)["D22_placeholders"] == "PASS"


def test_прогон_без_блоков_проходит_гейт_заглушек(tmp_path):
    assert check_placeholders(tmp_path)["D22_placeholders"] == "PASS"
