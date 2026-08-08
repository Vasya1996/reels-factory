"""Спека оформления frame.md: frontmatter нормативен, дефолты держат сборку."""
from reels_factory.hf_frame import CAPTION_TONES, DEFAULTS, read_frame


def _write(tmp_path, text):
    (tmp_path / "frame.md").write_text(text, encoding="utf-8")
    return tmp_path


def test_без_спеки_собирается_прежний_вид(tmp_path):
    theme = read_frame(tmp_path)
    assert theme["colors"] == DEFAULTS["colors"]
    assert theme["captionTone"] in CAPTION_TONES


def test_спека_читается_из_frontmatter(tmp_path):
    theme = read_frame(_write(tmp_path, (
        "---\n"
        "version: 1\n"
        "name: тёплый кирпич\n"
        "colors:\n"
        '  bg: "#140d0a"\n'
        '  ink: "#fff7f0"\n'
        '  accent: "#FF5A36"\n'
        "captionTone: corporate\n"
        "---\n\nПроза о намерении.\n")))
    assert theme["colors"] == {"bg": "#140d0a", "ink": "#fff7f0",
                               "accent": "#ff5a36"}
    assert theme["captionTone"] == "corporate"
    assert theme["name"] == "тёплый кирпич"


def test_мусор_в_полях_не_роняет_сборку(tmp_path):
    """Спеку пишет агент; битый hex или чужой тон — дефолт, а не авария."""
    theme = read_frame(_write(tmp_path, (
        "---\ncolors:\n  bg: красный\n  accent: \"#12345\"\n"
        "captionTone: эпичный\n---\n")))
    assert theme["colors"]["bg"] == DEFAULTS["colors"]["bg"]
    assert theme["colors"]["accent"] == DEFAULTS["colors"]["accent"]
    assert theme["captionTone"] == DEFAULTS["captionTone"]


def test_битый_yaml_не_роняет_сборку(tmp_path):
    theme = read_frame(_write(tmp_path, "---\ncolors: [неверно\n---\n"))
    assert theme["colors"] == DEFAULTS["colors"]
