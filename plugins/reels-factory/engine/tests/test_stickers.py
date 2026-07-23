from reels_factory.stickers import build_stickers_ass


def test_pop_стикер_одно_событие(tmp_path):
    p = tmp_path / "st.ass"
    build_stickers_ass([{"start": 1.0, "end": 3.0, "text": "БЕСПЛАТНО"}], p)
    content = p.read_text(encoding="utf-8")
    assert content.count("Dialogue:") == 1
    assert "БЕСПЛАТНО" in content
    assert "\\t(0,70,\\fscx106" in content  # пружинка


def test_typewriter_печатается_по_букве(tmp_path):
    p = tmp_path / "st.ass"
    build_stickers_ass([{"start": 1.0, "end": 3.0, "text": "пост",
                         "anim": "typewriter"}], p)
    content = p.read_text(encoding="utf-8")
    assert content.count("Dialogue:") == 4     # по событию на букву
    assert "п|" in content                     # курсор во время печати
    assert content.rstrip().endswith("пост")   # финал без курсора до конца окна


def test_неизвестная_анимация(tmp_path):
    try:
        build_stickers_ass([{"start": 1, "end": 2, "text": "x", "anim": "fly"}],
                           tmp_path / "x.ass")
        assert False
    except ValueError as e:
        assert "fly" in str(e)
