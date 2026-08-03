import pytest

from reels_factory.feedback import FeedbackStore


@pytest.fixture
def база(tmp_path):
    return FeedbackStore(tmp_path / "feedback.sqlite3")


def test_пожелание_сохраняется_с_автором(база):
    id_ = база.add(7, topic="montage", text="Хочу перебивки", username="vasya")

    записи = база.list()
    assert len(записи) == 1
    row = записи[0]
    assert row["id"] == id_
    assert row["chat_id"] == 7
    assert row["username"] == "vasya"
    assert row["topic"] == "montage" and row["text"] == "Хочу перебивки"
    assert row["created_at"] > 0


def test_без_username_пишется_null(база):
    база.add(7, topic="montage", text="Хочу титры")
    assert база.list()[0]["username"] is None


def test_пустое_пожелание_не_пишем(база):
    with pytest.raises(ValueError):
        база.add(7, topic="montage", text="   ")
    assert база.count() == 0


def test_список_фильтруется_по_теме_и_новые_сверху(база):
    база.add(7, topic="montage", text="первое")
    база.add(8, topic="montage", text="второе")
    база.add(9, topic="музыка", text="третье")

    тема = база.list(topic="montage")
    assert [r["text"] for r in тема] == ["второе", "первое"]
    assert база.count(topic="montage") == 2
    assert база.count() == 3


def test_база_переживает_переоткрытие(tmp_path):
    path = tmp_path / "feedback.sqlite3"
    FeedbackStore(path).add(7, topic="montage", text="Хочу перебивки")

    assert FeedbackStore(path).count() == 1


def test_один_чат_может_писать_много_раз(база):
    база.add(7, topic="montage", text="раз")
    база.add(7, topic="montage", text="два")
    assert база.count() == 2
