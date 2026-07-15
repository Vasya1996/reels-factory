from reels_factory.glossary import fix_text, REPLACEMENTS


def test_пустой_словарь_не_трогает_текст():
    assert fix_text("обычная фраза без терминов") == "обычная фраза без терминов"


def test_заполненный_словарь_чинит_по_границам_слов():
    REPLACEMENTS["пабг"] = "PUBG"
    try:
        assert fix_text("играю в пабг") == "играю в PUBG"
    finally:
        REPLACEMENTS.pop("пабг", None)
