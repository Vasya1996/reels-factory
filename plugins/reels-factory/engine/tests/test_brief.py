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
