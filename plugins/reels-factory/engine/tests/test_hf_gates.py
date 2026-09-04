"""Гейты раскадровки: их `check` её не читает вовсе, значит проверяем мы."""
import pytest

from pathlib import Path

from reels_factory.hf_gates import (
    check_frame_filled, check_media, check_placeholders, check_storyboard,
    elements_problems, frame_filled_problems, min_scenes,
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
    """Серия из двух планов — единственная форма вставки."""
    return {"shots": [look, f"{look} крупно"], "kind": "photo"}


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


#: Раскадровка по монтажному стандарту: серии по два плана, между сериями
#: лицо ≥2,5 с. Куски без аватара (11.72–12.22 и 34.62–41.5) закрыты сценами
#: `none`: там серия обязательна, иначе чёрный кадр, и ведущей на них нет
#: физически. Всюду, где аватар заказан, он в кадре — биролл держит кадр, а
#: ведущая живёт уголком поверх него. Спрятать её там значит выбросить
#: оплаченные секунды, и это ловит D24.
_LAYOUT = [
    (0.0, 2.0, "full", None),
    (2.0, 4.6, "pip-br", "разложить бумаги"),
    (4.6, 8.2, "full", None),
    (8.2, 11.72, "punch", None),
    (11.72, 12.22, "none", "рука на столе"),
    (12.22, 15.8, "full", None),
    (15.8, 18.4, "pip-tr", "печатает на ноутбуке"),
    (18.4, 22.0, "punch", None),
    (22.0, 25.6, "pip-tl", "перелистывает страницы"),
    (25.6, 29.2, "full", None),
    (29.2, 32.8, "pip-tr", "ставит чашку на стол"),
    (32.8, 34.62, "punch", None),
    (34.62, 37.2, "none", "закрывает блокнот"),
    (37.2, 39.4, "none", "телефон в руке"),
    (39.4, DURATION, "none", "ставит чашку"),
]


def _plausible_scenes():
    """Ролик выстлан целиком, соседние сцены различимы, монтаж по стандарту."""
    scenes = []
    for index, (start, end, presenter, look) in enumerate(_LAYOUT):
        scenes.append(_scene(index, quantize(start), quantize(end),
                             presenter=presenter,
                             insert=_photo(look) if look else None))
    return scenes


def _check(scenes, **over):
    return check_storyboard(_board(scenes, **over), clips=CLIPS,
                            duration=DURATION)


def test_чистая_раскадровка_проходит():
    verdicts = _check(_plausible_scenes())
    assert not [name for name, value in verdicts.items()
                if value.startswith("FAIL")]
    assert verdicts["D24_avatar_paid_shown"] == (
        "PASS: оплаченной ведущей мимо кадра 0.0 с")


# ---------- схема ----------

def test_наши_прежние_поля_больше_не_принимаются():
    """contentRect, videoRect и zone противоречат их схеме и модели слоёв."""
    scenes = _plausible_scenes()
    scenes[0]["zone"] = "fullscreen"
    assert _check(scenes)["D11_schema"].startswith("FAIL")


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


def test_шапку_раскадровки_гейт_больше_не_проверяет():
    """Её пишет наш же `complete_storyboard` перед сборкой, а гейт читает файл
    уже после него: проверять там нечего, кроме собственного кода."""
    board = _board(_plausible_scenes())
    board["videoTrack"].pop("bounds")
    board["schemaVersion"] = 2
    assert check_storyboard(board, clips=CLIPS,
                            duration=DURATION)["D11_schema"] == "PASS"


# ---------- плотность ----------

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


def test_снятые_гейты_не_возвращаются():
    """D9 (сетка кадров) и D13 (плотность) сняты как тавтологии: и то и другое
    гарантирует `lay_out_scenes` до всякой сборки. D23 снят следом — число
    планов роняет `check_shots`, длину серии держит отбор. D10 (зона карточки)
    ушёл вместе с зонами."""
    gates = _check(_plausible_scenes())
    for name in ("D9_frame_grid", "D13_density", "D23_series", "D10_zone"):
        assert name not in gates


# ---------- D12: кусок без ведущей ----------

def test_кусок_без_ведущей_без_вставки_это_фоновая_сцена():
    """С фирменным фоном из frame.md чёрного кадра больше нет: сцена без
    вставки на куске без аватара — законная фоновая сцена."""
    scenes = _plausible_scenes()
    scenes[12]["insert"] = None
    assert _check(scenes)["D12_faceless_cover"] == "PASS"


def test_ведущая_на_куске_где_её_нет_валится():
    """План может назначить ей угол там, где аватар не заказан: окно будет
    пустым, а кадр — чёрным."""
    scenes = _plausible_scenes()
    scenes[12]["presenter"] = "pip-br"
    assert _check(scenes)["D12_faceless_cover"].startswith("FAIL")


# ---------- D25: кадр, который так и остался пустым ----------

def test_сцена_без_ведущей_и_без_вставки_валится():
    """Сцена, потерявшая серию при подборе, показывала голый фон с титром —
    и это проезжало молча. Теперь она обязана нести хоть что-то."""
    scenes = _plausible_scenes()
    scenes[12]["insert"] = None
    assert _check(scenes)["D25_empty_frame"].startswith("FAIL")


@pytest.mark.parametrize("filler", [
    {"icon": {"query": "bookmark icon"}},
    {"overlay": {"block": "lt-soft-pill", "text": {"name": "Итог"}}},
    {"schemaShown": True},
])
def test_чем_можно_закрыть_кадр_без_ведущей(filler):
    scenes = _plausible_scenes()
    scenes[12]["insert"] = None
    scenes[12].update(filler)
    assert _check(scenes)["D25_empty_frame"] == "PASS"


# ---------- D24: оплаченная ведущая попала в кадр ----------

def test_спрятанная_ведущая_на_оплаченном_куске_это_провал():
    """Прогон 462a1c62: 9,2 с из 27,5 заказанных не попали в кадр — сцены
    стояли под `none` там, где клип уже куплен. Прежний гейт считал ровно
    наоборот и такую раскадровку хвалил."""
    from reels_factory.hf_gates import check_montage

    scenes = [_scene(0, 0.0, 11.0, presenter="none", insert=_photo("стол")),
              _scene(1, 11.0, DURATION, presenter="full")]
    verdict = check_montage(_board(scenes), clips=CLIPS, duration=DURATION)
    assert verdict["D24_avatar_paid_shown"].startswith("FAIL")
    assert "s-00" in verdict["D24_avatar_paid_shown"]


def test_ведущая_спрятана_на_дыре_и_это_законно():
    """Хвост 34.62–41.5 без клипа: прятать там нечего, аватар не заказан."""
    from reels_factory.hf_gates import check_montage

    scenes = [_scene(0, 0.0, 34.62, presenter="full"),
              _scene(1, 34.62, DURATION, presenter="none",
                     insert=_photo("руки"))]
    verdict = check_montage(_board(scenes), clips=CLIPS, duration=DURATION)
    assert verdict["D24_avatar_paid_shown"].startswith("PASS")


def test_аватар_в_уголке_считается_аватаром_в_кадре():
    """`pip-*` — это ведущая в кадре: заказанные секунды дошли до зрителя."""
    from reels_factory.hf_gates import check_montage

    scenes = [_scene(0, 0.0, 34.62, presenter="pip-br", insert=_photo("стол")),
              _scene(1, 34.62, DURATION, presenter="none",
                     insert=_photo("руки"))]
    verdict = check_montage(_board(scenes), clips=CLIPS, duration=DURATION)
    assert verdict["D24_avatar_paid_shown"].startswith("PASS")


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


def test_фоновая_сцена_без_ведущей_и_вставки_легальна():
    """Фирменный фон из frame.md закрывает кадр; призыв и передышка — это
    фон плюс крупный титр."""
    result = check_frame_filled({"scenes": [_scene(1, 0.0, 2.0,
                                                  presenter="none")]})
    assert result["D20_frame_filled"] == "PASS"


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


def test_две_разные_схемы_подряд_это_два_плана():
    """Прогоны 27 и 30: две сцены подряд потеряли биролл и обе закрылись
    схемой. Вставки нет ни у той, ни у другой, и гейт считал их одним планом —
    хотя слова в схемах разные, и зритель видит смену."""
    scenes = _plausible_scenes()
    for index, plan in ((13, {"form": "list", "items": ["раз", "два"]}),
                        (14, {"form": "stat", "value": "87%",
                              "label": "дошли"})):
        scenes[index]["insert"] = None
        scenes[index]["presenter"] = "none"
        scenes[index]["needsSchema"] = True
        scenes[index]["fallback"] = plan
    assert _check(scenes)["D21_scene_contrast"] == "PASS"


def test_две_одинаковые_схемы_подряд_остаются_одним_планом():
    scenes = _plausible_scenes()
    for index in (13, 14):
        scenes[index]["insert"] = None
        scenes[index]["presenter"] = "none"
        scenes[index]["needsSchema"] = True
        scenes[index]["fallback"] = {"form": "list", "items": ["раз", "два"]}
    assert _check(scenes)["D21_scene_contrast"].startswith("FAIL")


def test_схема_агента_различима_так_же_как_запасная():
    scenes = _plausible_scenes()
    scenes[13]["insert"] = None
    scenes[13]["presenter"] = "none"
    scenes[13]["schema"] = {"form": "brand", "brands": ["notion"]}
    scenes[14]["insert"] = None
    scenes[14]["presenter"] = "none"
    scenes[14]["schema"] = {"form": "brand", "brands": ["telegram"]}
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


# ---------- форма схемы заполнена так, как её блок умеет показать ----------

def _form(plan):
    from reels_factory.hf_gates import _form_problems
    return _form_problems("s-01", "schema", plan)


def test_величина_без_цифры_названа_ошибкой():
    """Их счётчик печатает `Math.round(значение) + суффикс`
    (`mk-progress-stat.html:168`): «десятки» молча становились нулём в кадре."""
    assert not _form({"form": "metric", "why": "величина", "value": "87%"})
    assert any("не с цифры" in p for p in
               _form({"form": "metric", "why": "x", "value": "десятки"}))


def test_перечисление_из_одной_карточки_названо_ошибкой():
    """В вертикали одна карточка — плашка в пустом кадре: 691x288 при 1080x1920,
    и кегль подписи упирается в потолок их же подгонки."""
    one = {"form": "items", "why": "x",
           "items": [{"label": "кто", "icon": "человек"}]}
    assert any("не сцена" in p for p in _form(one))


def test_значок_только_из_нарисованных():
    plan = {"form": "items", "why": "x",
            "items": [{"label": "кто", "icon": "нетакого"},
                      {"label": "что", "icon": "документ"},
                      {"label": "как", "icon": "поиск"}]}
    assert any("не нарисован" in p for p in _form(plan))


def test_строка_пары_без_значения_названа_ошибкой():
    plan = {"form": "pairs", "why": "x",
            "rows": [{"label": "скрипты", "value": ""}]}
    assert any("без значения" in p for p in _form(plan))


def test_разбор_why_обязателен():
    """Рассуждение до метки — приём из их руководства по классификации: без
    него выбор формы не на чем проверить ни агенту, ни человеку."""
    plan = {"form": "brand", "brands": ["notion"]}
    assert any("`why`" in p for p in _form(plan))


def test_заголовок_страницы_не_считается_заглушкой(tmp_path):
    """У их компонентов в `<head>` всегда стоит `<title>`, а в кадре его нет:
    это имя вкладки. Без этой оговорки гейт ловил «Grid Card Assemble» в каждой
    копии блока."""
    from reels_factory.hf_gates import check_placeholders

    comp = tmp_path / "public" / "compositions"
    comp.mkdir(parents=True)
    page = ('<html><head><title>Grid Card Assemble</title></head><body>'
            '<div class="gca-label">{}</div></body></html>')
    (comp / "grid-card-assemble.html").write_text(page.format(""),
                                                  encoding="utf-8")
    (comp / "grid-card-assemble--s-01.html").write_text(page.format("КТО"),
                                                        encoding="utf-8")
    assert check_placeholders(tmp_path)["D22_placeholders"] == "PASS"


def test_нарисованная_надпись_блока_не_считается_заглушкой(tmp_path):
    """Живой прогон 18.08: сборка легла на «в кадр едет заглушка: REC».
    У камкордерного HUD это не слот, а часть рисунка — заполнять там нечего,
    и убрать нельзя, не сломав сам блок. Настоящие заглушки гейт ловить
    обязан по-прежнему.
    """
    from reels_factory.hf_gates import check_placeholders

    compositions = tmp_path / "public" / "compositions"
    compositions.mkdir(parents=True)
    (compositions / "camcorder-hud.html").write_text(
        "<div><span>REC</span><h1>Заголовок блока</h1></div>", encoding="utf-8")
    (compositions / "camcorder-hud--s-01.html").write_text(
        "<div><span>REC</span><h1>Ролик про аватара</h1></div>",
        encoding="utf-8")

    assert check_placeholders(tmp_path)["D22_placeholders"] == "PASS"

    # А незаполненный слот того же блока — по-прежнему провал.
    (compositions / "camcorder-hud--s-02.html").write_text(
        "<div><span>REC</span><h1>Заголовок блока</h1></div>", encoding="utf-8")
    assert check_placeholders(tmp_path)["D22_placeholders"].startswith("FAIL")


# ---------- D25/D20: просьба о схеме — не доказательство схемы ----------
#
# Прогон hf-live2: сцена s-07 ушла в кадр с `needsSchema: true` и без
# `fallback`, `schema_plan` вернул None, в композицию не встало ничего — и оба
# гейта сказали PASS, потому что читали флаг. Флаг ставит сам код
# (`refill_scene`), то есть гейт проверял намерение кода его же намерением.

def _без_ведущей_и_вставки(**over):
    scenes = _plausible_scenes()
    scenes[12]["insert"] = None
    scenes[12].update(over)
    return scenes


def test_просьба_о_схеме_без_запасной_кадр_не_закрывает():
    scenes = _без_ведущей_и_вставки(needsSchema=True)
    assert _check(scenes)["D25_empty_frame"].startswith("FAIL")


def test_запасная_схема_известной_формы_кадр_закрывает():
    scenes = _без_ведущей_и_вставки(
        needsSchema=True,
        fallback={"form": "steps", "why": "порядок",
                  "nodes": ["сценарий", "тема", "ролик"]})
    assert _check(scenes)["D25_empty_frame"] == "PASS"


def test_запасная_схема_неизвестной_формы_кадр_не_закрывает():
    """Форму, которой нет в `hf_schema.FORMS`, не нарисует ни один блок —
    для кадра она то же самое, что пустое поле."""
    scenes = _без_ведущей_и_вставки(needsSchema=True,
                                    fallback={"form": "облако", "items": ["раз"]})
    assert _check(scenes)["D25_empty_frame"].startswith("FAIL")


def test_уголок_ведущей_при_пустой_просьбе_о_схеме_это_чёрный_кадр():
    """D20 верил тому же флагу: уголок остаётся на пустом фоне."""
    result = check_frame_filled({"scenes": [
        _scene(1, 0.0, 2.0, presenter="pip-br", needsSchema=True)]})
    assert result["D20_frame_filled"].startswith("FAIL")


def test_уголок_ведущей_под_запасной_схемой_законен():
    result = check_frame_filled({"scenes": [
        _scene(1, 0.0, 2.0, presenter="pip-br", needsSchema=True,
               fallback={"form": "steps", "why": "порядок",
                         "nodes": ["раз", "два"]})]})
    assert result["D20_frame_filled"] == "PASS"


# ---------- элементы каталога: сверка до денег ----------

FIXTURE_CATALOG = Path(__file__).resolve().parent / "fixtures" / "catalog"


@pytest.fixture
def каталог(monkeypatch):
    """Гейты судят по фикстурному каталогу, а не по боевому."""
    from reels_factory import hf_catalog, hf_montage

    cards, skipped = hf_catalog.catalog_cards, hf_catalog.skipped_blocks
    monkeypatch.setattr(hf_catalog, "catalog_cards",
                        lambda *a, **k: cards(FIXTURE_CATALOG))
    monkeypatch.setattr(hf_catalog, "skipped_blocks",
                        lambda *a, **k: skipped(FIXTURE_CATALOG))
    monkeypatch.setattr(hf_montage, "_element_kinds",
                        lambda: {name: card.get("kind")
                                 for name, card in cards(FIXTURE_CATALOG).items()})
    return FIXTURE_CATALOG


def _элементы(*elements, presenter="pip-br"):
    """Сцена с элементами. Ведущая уголком: при полном кадре свободной зоны
    под `effect` нет вовсе, и такой план ловится отдельным правилом ниже."""
    scene = _scene(1, 0.0, 4.0, presenter=presenter)
    scene["elements"] = list(elements)
    return [scene]


def test_неизвестное_имя_позиции_ловится_до_заказа(каталог):
    """Их `add` неизвестное имя не ставит вовсе, а ставит он блоки уже после
    оплаченного заказа ведущей: тот же вопрос задаётся плану заранее."""
    problems = elements_problems(_элементы({"name": "нет-такого"}))
    assert len(problems) == 1
    assert "catalog.index.md" in problems[0]


def test_позиция_с_причиной_отказа_планом_не_называется(каталог):
    problems = elements_problems(_элементы({"name": "demo-skip"}))
    assert len(problems) == 1 and "--strict" in problems[0]


def test_чужая_переменная_и_чужой_тип_ловятся_по_карточке(каталог):
    чужая = elements_problems(_элементы(
        {"name": "count-up", "variables": {"finish": 250}}))
    assert len(чужая) == 1 and "finish" in чужая[0]
    тип = elements_problems(_элементы(
        {"name": "count-up", "variables": {"end": "двести"}}))
    assert len(тип) == 1 and "number" in тип[0]
    # Булево не число и число не булево: в Python `True` — это `int`, и без
    # оговорки `glow: 1` прошло бы за флаг.
    флаг = elements_problems(_элементы(
        {"name": "count-up", "variables": {"glow": 1}}))
    assert len(флаг) == 1 and "boolean" in флаг[0]
    assert elements_problems(_элементы(
        {"name": "count-up", "variables": {"end": 250, "glow": True,
                                           "suffix": " ₽"}})) == []


def test_лишние_слова_ловятся_по_числу_слотов(каталог):
    problems = elements_problems(_элементы(
        {"name": "demo-scene", "words": ["Первая", "Вторая"]}))
    assert len(problems) == 1 and "слотов у позиции 1" in problems[0]
    assert elements_problems(_элементы(
        {"name": "demo-scene", "words": ["Первая"]})) == []


def test_эффект_без_свободной_зоны_ловится_до_заказа(каталог):
    """Отчёт B4: `count-up` был назван на сцене с ведущей `punch`, гейты дали
    PASS, а сборка сняла элемент молча — уже после оплаченного заказа. Причина
    у кода была та же (`hf_compose.effect_zone`), и теперь она называется
    плану до денег.
    """
    for position in ("full", "punch", "stack"):
        problems = elements_problems(_элементы({"name": "count-up"},
                                               presenter=position))
        assert len(problems) == 1, position
        assert "свободную зону" in problems[0] and position in problems[0]
    # Уголок и отсутствие ведущей зону оставляют — план законен.
    for position in ("pip-tr", "pip-br", "none"):
        assert elements_problems(_элементы({"name": "count-up"},
                                           presenter=position)) == [], position
    # Правило про зону — только у вида `effect`: сцена занимает кадр целиком,
    # стык живёт на срезе, и зона им не нужна.
    for name in ("demo-scene", "demo-stitch"):
        assert elements_problems(_элементы({"name": name},
                                           presenter="full")) == [], name


def test_сверку_элементов_делает_и_d11(каталог):
    """Один код на два места: до заказа его зовёт `D36_elements`, после сборки —
    D11. Разойтись им нечем."""
    board = _board(_элементы({"name": "нет-такого"}))
    verdict = check_storyboard(board, clips=CLIPS, duration=DURATION)
    assert verdict["D11_schema"].startswith("FAIL")
    assert "catalog.index.md" in verdict["D11_schema"]


def test_элемент_кадра_считают_одинаково_d20_и_d25(каталог):
    """Расхождение D20 и D25 на плашке было дефектом: элемент вида `scene` или
    `effect` закрывает кадр для обоих гейтов сразу."""
    from reels_factory.hf_gates import _empty_frame_problems

    сцена = _scene(1, 0.0, 4.0, presenter="pip-tr")
    сцена["elements"] = [{"name": "demo-scene"}]
    assert frame_filled_problems([сцена]) == []
    пустая = dict(сцена, presenter="none")
    assert _empty_frame_problems([пустая]) == []

    # Стык кадра не держит: он живёт секунду на срезе.
    стык = _scene(2, 0.0, 4.0, presenter="pip-tr")
    стык["elements"] = [{"name": "demo-stitch"}]
    assert frame_filled_problems([стык])
    assert _empty_frame_problems([dict(стык, presenter="none")])


def test_снятый_сборкой_элемент_доходит_до_карточки_причиной():
    """Пересборка `artyom-rebuild-4b`: из трёх позиций в кадр встали две, а
    `D36_elements` остался зелёным. Пост-рендерная сверка читала раскадровку,
    откуда сборка снятую позицию уже вычистила, — судить было нечего.

    Теперь сравниваются план агента и собранный кадр, а причину даёт сама
    сборка (`hf_compose.DROPPED_ELEMENTS`). Вердикт WARN, не FAIL: ведущая
    куплена, ролик доезжает, изъян остаётся в карточке словом.
    """
    from reels_factory.hf_compose import DROPPED_ELEMENTS
    from reels_factory.hf_gates import elements_delivered

    план = _board(_элементы({"name": "count-up"}))
    кадр = _board(_элементы())
    кадр[DROPPED_ELEMENTS] = [{"scene": "s-01", "name": "count-up",
                               "why": "ведущая 'full' не оставила зоны"}]
    вердикт = elements_delivered(план, кадр)["D36_elements"]
    assert вердикт.startswith("WARN"), вердикт
    assert "s-01" in вердикт and "count-up" in вердикт
    assert "не оставила зоны" in вердикт, "причина потерялась по дороге"


def test_дошедший_до_кадра_элемент_гейт_не_тревожит():
    from reels_factory.hf_gates import elements_delivered

    план = _board(_элементы({"name": "count-up"}))
    assert elements_delivered(план, _board(_элементы(
        {"name": "count-up"})))["D36_elements"] == "PASS"


def test_уехавшая_вместе_со_сценой_позиция_тоже_изъян():
    """Сцену могло не остаться вовсе — её секунды сводит с соседкой
    `absorb_scene` или `dedupe_neighbours`. Позиция уезжает вместе с ней, и
    причины сборка при этом не пишет: снимала не она."""
    from reels_factory.hf_gates import elements_delivered

    план = _board(_элементы({"name": "count-up"}))
    вердикт = elements_delivered(план, _board([]))["D36_elements"]
    assert вердикт.startswith("WARN") and "сведены с соседней" in вердикт


def test_сборка_записывает_причину_снятия_в_раскадровку():
    """След пишет тот, кто снимает: причина известна только сборке, а гейт и
    карточка читают раскадровку."""
    from reels_factory.hf_compose import DROPPED_ELEMENTS, settle_fillers

    board = _board(_элементы({"name": "такой-позиции-нет"}))
    assert settle_fillers(board, {}) == ["s-01"]
    assert board["scenes"][0]["elements"] == []
    записи = board[DROPPED_ELEMENTS]
    assert len(записи) == 1
    assert записи[0]["scene"] == "s-01"
    assert записи[0]["name"] == "такой-позиции-нет"
    assert "catalog.index.md" in записи[0]["why"]


def test_рисованный_текст_гейт_берёт_из_карточки(monkeypatch, tmp_path):
    """Белый список D22 переехал в карточку: каждая новая позиция иначе
    требовала бы правки кода гейта."""
    from reels_factory import hf_catalog
    from reels_factory.hf_gates import check_placeholders

    decor = hf_catalog.decor_texts
    monkeypatch.setattr(hf_catalog, "decor_texts",
                        lambda *a, **k: decor(FIXTURE_CATALOG))
    compositions = tmp_path / "public" / "compositions"
    compositions.mkdir(parents=True)
    page = "<div><span>Заголовок</span><h1>{}</h1></div>"
    (compositions / "demo-stitch.html").write_text(page.format("Демо"),
                                                   encoding="utf-8")
    (compositions / "demo-stitch--s-01.html").write_text(
        page.format("Ролик про аватара"), encoding="utf-8")
    assert check_placeholders(tmp_path)["D22_placeholders"] == "PASS"
