"""Гейты раскадровки: их `check` её не читает вовсе, значит проверяем мы."""
import pytest

from reels_factory.hf_gates import check_media, check_storyboard, min_cards

DURATION = 41.5
# три клипа с ведущей, хвост 34.62–41.5 без неё — как в реальном материале
CLIPS = [{"file": "clips/clip-00.mp4", "start": 0.0, "duration": 11.72},
         {"file": "clips/clip-01.mp4", "start": 12.22, "duration": 10.92},
         {"file": "clips/clip-02.mp4", "start": 23.14, "duration": 11.48}]


def _card(index: int, **over):
    card = {"id": f"card-{index:02d}", "intent": "зачем эта карточка",
            "startSec": 0.0, "endSec": 3.0, "accentIndex": 0,
            "zone": "video-overlay",
            "contentHints": {"kicker": "К", "title": "Т", "detail": "Д"}}
    card.update(over)
    return card


def _board(cards, **over):
    board = {
        "schemaVersion": 3,
        "composition": {"fps": 30, "width": 1080, "height": 1920,
                        "durationSeconds": DURATION, "layout": "portrait",
                        "themeId": "noir", "seed": 42},
        "videoTrack": {"sourcePath": "clips/clip-00.mp4", "startSec": 0,
                       "endSec": DURATION,
                       "bounds": {"x": 0, "y": 0, "width": 1080, "height": 1920}},
        "subtitles": {"enabled": True},
        "cards": cards,
    }
    board.update(over)
    return board


def _plausible_cards():
    """Шесть карточек с зазорами: и ритм, и покрытие пропуска без ведущей.

    Зазор между соседними обязателен — карточки впритык детектор сцен видит
    одной склейкой, и планка смен картинки не берётся.
    """
    return [
        _card(1, startSec=1.0, endSec=5.0),
        _card(2, startSec=6.0, endSec=11.7),
        _card(3, zone="fullscreen", startSec=11.733, endSec=19.0),
        _card(4, startSec=20.0, endSec=26.0),
        _card(5, startSec=27.0, endSec=33.5),
        _card(6, zone="fullscreen", startSec=34.5, endSec=41.5),
    ]


def _check(cards, **over):
    return check_storyboard(_board(cards, **over), clips=CLIPS, duration=DURATION)


def test_чистая_раскадровка_проходит():
    assert set(_check(_plausible_cards()).values()) == {"PASS"}


# ---------- схема ----------

def test_наши_прежние_поля_больше_не_принимаются():
    """contentRect и videoRect противоречат videoTrack.bounds их схемы."""
    cards = _plausible_cards()
    cards[0]["contentRect"] = {"left": 0, "top": 0, "width": 10, "height": 10}
    assert _check(cards)["D11_schema"].startswith("FAIL")


def test_чужая_версия_схемы_валится():
    assert _check(_plausible_cards(), schemaVersion=2)["D11_schema"].startswith("FAIL")


def test_карточка_без_смысла_валится():
    cards = _plausible_cards()
    cards[0].pop("intent")
    assert _check(cards)["D11_schema"].startswith("FAIL")


def test_геометрия_ведущей_обязана_быть_задана():
    board = _board(_plausible_cards())
    board["videoTrack"].pop("bounds")
    gates = check_storyboard(board, clips=CLIPS, duration=DURATION)
    assert gates["D11_schema"].startswith("FAIL")


# ---------- плотность ----------

def test_пустая_раскадровка_валится():
    """Прошлый гейт перебирал карточки циклом — пустой список проходил всё."""
    assert _check([])["D13_density"].startswith("FAIL")


def test_группы_субтитров_ловит_зазор_а_не_плотность():
    """34 карточки по 1,1 с — пересказ субтитров, а не монтаж.

    Раньше их заворачивал потолок плотности. Потолка больше нет: его считала
    формула `talking-head-recut`, а `/general-video` числа карточек не называет
    вовсе. Ловит теперь D21 — между такими карточками негде взять зазор 0,8 с.
    """
    cards = [_card(i, startSec=round(i * 1.2, 3), endSec=round(i * 1.2 + 1.1, 3))
             for i in range(34)]
    gates = _check(cards)
    assert gates["D13_density"] == "PASS"
    assert gates["D21_card_gaps"].startswith("FAIL")


@pytest.mark.parametrize("duration,expected", [
    (41.5, 6),     # 41,5 / 8 — иначе останется кусок длиннее восьми секунд
    (12.0, 2),
    (121.2, 16),
])
def test_пол_карточек_от_нашей_планки(duration, expected):
    """Пол выведен из D19 (не больше восьми секунд без смены картинки),
    а не из их формулы плотности."""
    assert min_cards(duration) == expected


def test_потолка_плотности_больше_нет():
    """Прогоны 8 и 9 оба упёрлись ровно в расчётный потолок 10."""
    cards = [_card(i, startSec=round(i * 2.0, 3), endSec=round(i * 2.0 + 1.0, 3))
             for i in range(20)]
    assert _check(cards)["D13_density"] == "PASS"


# ---------- сетка, чёрный кадр ----------

def test_время_вне_сетки_кадров_валится():
    cards = _plausible_cards()
    cards[0]["startSec"] = 1.017
    assert _check(cards)["D9_frame_grid"].startswith("FAIL")


def test_гейта_зоны_больше_нет():
    """D10 снят: список зон был из `talking-head-recut`, а проверял он значение,
    которое до гейтов проставляет наш же `complete_storyboard`."""
    cards = _plausible_cards()
    cards[0]["zone"] = "куда-то"
    assert "D10_zone" not in _check(cards)


def test_интервал_без_ведущей_обязан_быть_закрыт():
    cards = _plausible_cards()
    cards[-1]["zone"] = "video-overlay"  # прозрачная зона чёрный кадр не прячет
    assert _check(cards)["D12_faceless_cover"].startswith("FAIL")


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
    """Ровно то, чем кончился прошлый прогон: ведущая, субтитры и текст."""
    project = _project(tmp_path, "<div>ПРОДАЖИ</div>", ledger=False, image=False)
    assert check_media(project)["D16_media_use"].startswith("FAIL")


def test_ссылка_на_несуществующий_файл_не_считается(tmp_path):
    project = _project(tmp_path, '<img src="media/нет-такого.jpg">', image=False)
    assert check_media(project)["D16_media_use"].startswith("FAIL")


def test_внешняя_ссылка_вставкой_не_считается(tmp_path):
    project = _project(tmp_path, '<img src="https://example.com/a.jpg">', image=False)
    assert check_media(project)["D16_media_use"].startswith("FAIL")


def test_пропуск_закрывается_цепочкой_карточек():
    cards = _plausible_cards()
    cards[-1] = _card(6, zone="fullscreen", startSec=34.5, endSec=38.0)
    cards.append(_card(7, zone="fullscreen", startSec=38.033, endSec=41.5))
    assert _check(cards)["D12_faceless_cover"] == "PASS"


# ---------- D20: пустого кадра не бывает ----------
#
# Уменьшенное окно ведущей закрывает седьмую часть кадра. Прозрачная карточка
# над ним оставляет остальное чёрным — так вышло на проверочном прогоне.

def _filled_card(**over):
    card = {"id": "c1", "intent": "и", "accentIndex": 0, "startSec": 0.0,
            "endSec": 3.0, "zone": "video-overlay", "contentHints": {},
            "render": {"kind": "fragment"}}
    card.update(over)
    return {"cards": [card]}


def test_ведущая_в_углу_под_прозрачной_карточкой_это_чёрный_кадр():
    from reels_factory.hf_gates import check_frame_filled

    result = check_frame_filled(_filled_card(presenter="pip-bl"))
    assert result["D20_frame_filled"].startswith("FAIL")


def test_ведущая_во_весь_кадр_под_прозрачной_карточкой_норма():
    from reels_factory.hf_gates import check_frame_filled

    assert check_frame_filled(_filled_card(presenter="full"))["D20_frame_filled"] == "PASS"


def test_ведущая_в_углу_под_полноэкранной_карточкой_норма():
    from reels_factory.hf_gates import check_frame_filled

    result = check_frame_filled(_filled_card(presenter="pip-bl", zone="fullscreen"))
    assert result["D20_frame_filled"] == "PASS"


def test_ведущая_сверху_и_карточка_снизу_закрывают_кадр():
    from reels_factory.hf_gates import check_frame_filled

    # stack: видео 0–844, side-panel: карточка 1152–1920 — между ними дыра
    result = check_frame_filled(_filled_card(presenter="stack", zone="side-panel"))
    assert result["D20_frame_filled"].startswith("FAIL")


def test_блок_каталога_закрывает_кадр_сам():
    from reels_factory.hf_gates import check_frame_filled

    result = check_frame_filled(_filled_card(presenter="none",
                                      render={"kind": "block", "block": "g07"}))
    assert result["D20_frame_filled"] == "PASS"
