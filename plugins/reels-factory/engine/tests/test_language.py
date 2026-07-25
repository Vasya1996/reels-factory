import pytest

from reels_factory.language import (
    confident_mismatch,
    detect_script_language,
    language_label,
    normalize_profile_language,
)


def test_казахский_определяется_по_алфавиту_и_лексике():
    decision = detect_script_language(
        "Бұл қазақша сценарий. Бүгін адамдар үшін пайдалы бір нәрсе айтамыз."
    )
    assert decision.code == "kk"
    assert decision.confidence >= 0.95


def test_русский_определяется_консервативно():
    decision = detect_script_language(
        "Это русский сценарий, и мы используем его для нового ролика, "
        "потому что он хорошо объясняет тему."
    )
    assert decision.code == "ru"
    assert decision.confidence >= 0.85


def test_короткий_и_смешанный_текст_не_переключает_язык():
    assert detect_script_language("Новый ролик").code is None
    assert detect_script_language("Бренд туралы новый ролик").code is None


def test_mismatch_только_для_уверенного_другого_языка():
    russian = (
        "Это готовый русский текст, и мы хотим использовать его для ролика, "
        "но профиль настроен на другой язык."
    )
    assert confident_mismatch(russian, "kk").code == "ru"
    assert confident_mismatch(russian, "ru") is None
    assert confident_mismatch("Короткий текст", "kk") is None


def test_поддерживаются_только_ru_и_kk():
    assert normalize_profile_language(" KK ") == "kk"
    assert language_label("ru") == "🇷🇺 Русский"
    with pytest.raises(ValueError, match="только языки"):
        normalize_profile_language("en")
