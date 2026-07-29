"""Гейты раскадровки: движок этого не знает, значит проверяем мы."""
from reels_factory.hf_gates import check_storyboard

FACE = {"cx": 540, "cy": 520, "h": 260}


def _card(**over):
    card = {"id": "card-01", "startSec": 0.0, "endSec": 3.0, "zone": "video-overlay",
            "contentRect": {"left": 60, "top": 1400, "width": 960, "height": 400}}
    card.update(over)
    return card


def test_чистая_раскадровка_проходит():
    gates = check_storyboard({"cards": [_card()]}, FACE)
    assert all(value == "PASS" for key, value in gates.items() if key != "D13_rhythm")


def test_карточка_на_лице_валится():
    gates = check_storyboard(
        {"cards": [_card(contentRect={"left": 300, "top": 300, "width": 500, "height": 300})]},
        FACE)
    assert gates["D8_face"].startswith("FAIL")


def test_полноэкранная_карточка_на_лицо_не_проверяется():
    """Там ведущей в кадре нет — аватар на этот кусок не заказан."""
    gates = check_storyboard(
        {"cards": [_card(zone="fullscreen",
                         contentRect={"left": 0, "top": 0, "width": 1080, "height": 1920})]},
        FACE)
    assert gates["D8_face"] == "PASS"


def test_нижняя_треть_разрешена():
    gates = check_storyboard({"cards": [_card(zone="lower-third")]}, FACE)
    assert all(value == "PASS" for key, value in gates.items() if key != "D13_rhythm")


def test_время_вне_сетки_кадров_валится():
    gates = check_storyboard({"cards": [_card(startSec=1.017)]}, FACE)
    assert gates["D9_frame_grid"].startswith("FAIL")


def test_несуществующая_зона_валится():
    gates = check_storyboard({"cards": [_card(zone="куда-то")]}, FACE)
    assert gates["D10_zone"].startswith("FAIL")


def test_карточка_без_прямоугольника_валится():
    card = _card()
    card.pop("contentRect")
    gates = check_storyboard({"cards": [card]}, FACE)
    assert gates["D11_shape"].startswith("FAIL")


def test_интервал_без_ведущей_обязан_быть_закрыт():
    window = {"id": "w1", "final_timing": {"start": 0.0, "end": 3.0}}
    открыт = check_storyboard({"cards": [_card()]}, FACE, [window])
    assert открыт["D12_faceless_cover"].startswith("FAIL")

    закрыт = check_storyboard(
        {"cards": [_card(zone="fullscreen", startSec=0.0, endSec=3.0)]}, FACE, [window])
    assert закрыт["D12_faceless_cover"] == "PASS"

    цепочкой = check_storyboard({"cards": [
        _card(id="c1", zone="fullscreen", startSec=0.0, endSec=1.5),
        _card(id="c2", zone="fullscreen", startSec=1.533, endSec=3.0),
    ]}, FACE, [window])
    assert цепочкой["D12_faceless_cover"] == "PASS"


def test_пустая_раскадровка_проходит():
    gates = check_storyboard({"cards": []}, FACE)
    assert all(value == "PASS" for key, value in gates.items() if key != "D13_rhythm")


def test_ритм_проходит_когда_разрывы_не_дольше_трёх_секунд():
    board = {"cards": [
        _card(id="c1", startSec=6.0, endSec=9.0),
        _card(id="c2", startSec=12.0, endSec=15.0),
    ]}
    gates = check_storyboard(board, FACE, duration=18.0)
    assert gates["D13_rhythm"] == "PASS"


def test_ритм_валится_на_длинном_разрыве():
    board = {"cards": [_card(startSec=8.0, endSec=11.0)]}
    gates = check_storyboard(board, FACE, duration=14.0)
    assert gates["D13_rhythm"].startswith("FAIL")


def test_ритм_не_проверяет_первые_четыре_секунды():
    board = {"cards": [_card(startSec=7.0, endSec=10.0)]}
    gates = check_storyboard(board, FACE, duration=13.0)
    assert gates["D13_rhythm"] == "PASS"


def test_ритм_без_длительности_пропускается():
    gates = check_storyboard({"cards": []}, FACE)
    assert gates["D13_rhythm"].startswith("SKIP")


def test_пузырь_pip_проходит_гейты():
    """Аватар малым окном в углу (аналог пузыря) — законная раскладка."""
    card = _card(
        zone="video-overlay",
        contentRect={"left": 60, "top": 400, "width": 960, "height": 900},
        videoRect={"left": 690, "top": 28, "width": 360, "height": 203},
    )
    gates = check_storyboard({"cards": [card]}, FACE, duration=3.0)
    assert gates["D8_face"] == "PASS"
