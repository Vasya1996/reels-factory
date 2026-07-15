"""Словарь исправлений терминов для субтитров на этапе распознавания.

Whisper коверкает узкие термины/имена. Замены применяются по границам слов,
регистронезависимо. По умолчанию словарь ПУСТ (движок generic): доменные
термины и бренд задаёт пользователь через product.brand_captions конфига — они
чинятся уже после распознавания (compose.apply_caption_fixes). Этот модуль —
опциональный крючок: заполни REPLACEMENTS, если хочешь чинить термин ещё в ASR.
"""
import re

# Левое — как Whisper мог распознать (нижний регистр); правое — как должно быть.
REPLACEMENTS: dict[str, str] = {}


def fix_text(text: str) -> str:
    """Применить словарь замен к строке по границам слов."""
    if not REPLACEMENTS:
        return text

    def repl(m):
        w = m.group(0)
        return REPLACEMENTS.get(w.lower(), w)

    return re.sub(r"[A-Za-zА-Яа-яЁё\-]+", repl, text)
