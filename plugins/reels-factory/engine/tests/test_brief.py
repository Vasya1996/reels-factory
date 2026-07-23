import json

import pytest

from reels_factory.brief import BriefError, load_brief, validate_brief


def _ok_brief():
    return {"captions": {"style": "popword", "keywords": ["скилы"]},
            "brolls": [{"start": 10.0, "end": 13.0, "query": "laptop typing"}]}


def test_валидное_тз_нормализуется():
    b = validate_brief(_ok_brief(), 30.0)
    assert b["brolls"][0]["start"] == 10.0


def test_вставка_на_хуке_запрещена():
    brief = {"brolls": [{"start": 1.0, "end": 4.0, "query": "x"}]}
    with pytest.raises(BriefError, match="хук"):
        validate_brief(brief, 30.0)


def test_вставок_не_больше_трёх():
    brolls = [{"start": 4.0 + i * 5, "end": 6.0 + i * 5, "query": "x"} for i in range(4)]
    with pytest.raises(BriefError, match="слайдшоу"):
        validate_brief({"brolls": brolls}, 40.0)


def test_длительность_в_коридоре():
    brief = {"brolls": [{"start": 5.0, "end": 5.5, "query": "x"}]}
    with pytest.raises(BriefError, match="коридора"):
        validate_brief(brief, 30.0)


def test_пересечения_запрещены():
    brief = {"brolls": [{"start": 5.0, "end": 9.0, "query": "x"},
                        {"start": 8.0, "end": 11.0, "query": "y"}]}
    with pytest.raises(BriefError, match="пересекаются"):
        validate_brief(brief, 30.0)


def test_нужен_query_или_src():
    brief = {"brolls": [{"start": 5.0, "end": 8.0}]}
    with pytest.raises(BriefError, match="query"):
        validate_brief(brief, 30.0)


def test_выход_за_конец_ролика():
    brief = {"brolls": [{"start": 27.0, "end": 32.0, "query": "x"}]}
    with pytest.raises(BriefError, match="за концом"):
        validate_brief(brief, 30.0)


def test_неизвестный_стиль_сабов():
    brief = {"captions": {"style": "comic"}}
    with pytest.raises(BriefError, match="comic"):
        validate_brief(brief, 30.0)


def test_load_brief_читает_json(tmp_path):
    p = tmp_path / "tz.json"
    p.write_text(json.dumps(_ok_brief()), encoding="utf-8")
    assert load_brief(p)["brolls"][0]["query"] == "laptop typing"


def test_load_brief_битый_json_понятная_ошибка(tmp_path):
    p = tmp_path / "tz.json"
    p.write_text("{oops", encoding="utf-8")
    with pytest.raises(BriefError, match="JSON"):
        load_brief(p)


# --- лента приёмов, стикеры, переходы ---

def test_shots_валидная_лента_с_ротацией():
    brief = {"shots": [
        {"start": 0.0, "end": 3.2, "type": "zoom_out"},
        {"start": 3.2, "end": 6.2, "type": "punch"},
        {"start": 6.2, "end": 8.2, "type": "push"},
    ]}
    b = validate_brief(brief, 30.0)
    assert [s["type"] for s in b["shots"]] == ["zoom_out", "punch", "push"]


def test_shots_ротация_нарушена_подряд_одинаковые():
    brief = {"shots": [
        {"start": 0.0, "end": 3.0, "type": "push"},
        {"start": 3.0, "end": 6.0, "type": "push"},
    ]}
    with pytest.raises(BriefError, match="ротация"):
        validate_brief(brief, 30.0)


def test_shots_broll_между_одинаковыми_чинит_ротацию():
    brief = {"shots": [
        {"start": 0.0, "end": 3.0, "type": "push"},
        {"start": 6.0, "end": 9.0, "type": "push"},
    ], "brolls": [{"start": 3.0, "end": 6.0, "query": "x"}]}
    b = validate_brief(brief, 30.0)
    assert len(b["shots"]) == 2


def test_shots_неизвестный_тип():
    brief = {"shots": [{"start": 0.0, "end": 3.0, "type": "spin"}]}
    with pytest.raises(BriefError, match="spin"):
        validate_brief(brief, 30.0)


def test_stickers_валидируются():
    brief = {"stickers": [
        {"start": 11.2, "end": 13.3, "text": "напиши пост", "anim": "typewriter"}]}
    b = validate_brief(brief, 30.0)
    assert b["stickers"][0]["anim"] == "typewriter"


def test_stickers_пустой_текст():
    brief = {"stickers": [{"start": 1.0, "end": 2.0, "text": " "}]}
    with pytest.raises(BriefError, match="text"):
        validate_brief(brief, 30.0)


def test_transitions_вне_ролика():
    with pytest.raises(BriefError, match="вне ролика"):
        validate_brief({"transitions": [29.9]}, 30.0)
