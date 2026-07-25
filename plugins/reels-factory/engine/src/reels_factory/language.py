"""MVP-языки пользовательского потока: язык выбирается для каждого ролика.

Детектор не переключает язык ролика. Он нужен только как дешёвый локальный
предохранитель: не отправить явно казахский готовый текст в русский ролик и
наоборот. Неоднозначный текст всегда разрешается в пользу выбранного языка.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


SUPPORTED_LANGUAGES = {
    "ru": {"label": "Русский", "emoji": "🇷🇺"},
    "kk": {"label": "Қазақша", "emoji": "🇰🇿"},
}

_KAZAKH_LETTERS = frozenset("әғқңөұүһіӘҒҚҢӨҰҮҺІ")
_TOKEN_RE = re.compile(r"[а-яёәғқңөұүһі]+", re.IGNORECASE)

_RU_WORDS = frozenset({
    "а", "без", "был", "быть", "в", "вам", "вас", "вы", "для", "его",
    "если", "ещё", "и", "из", "или", "как", "когда", "мы", "на", "не",
    "но", "он", "она", "они", "по", "почему", "при", "с", "так", "что",
    "это", "этот", "я",
})
_KK_WORDS = frozenset({
    "ал", "арқылы", "бар", "біз", "бұл", "бір", "ғана", "дейін", "деп",
    "деген", "емес", "және", "жоқ", "кейін", "керек", "мен", "менің",
    "неге", "осы", "сіз", "сондықтан", "туралы", "үшін", "қалай",
})


@dataclass(frozen=True)
class LanguageDecision:
    code: str | None
    confidence: float
    reason: str


def normalize_profile_language(code: str | None) -> str:
    """Вернуть поддерживаемый MVP-код или понятную ошибку."""
    value = str(code or "").strip().lower()
    if value not in SUPPORTED_LANGUAGES:
        raise ValueError(
            f"поддерживаются только языки {tuple(SUPPORTED_LANGUAGES)}, "
            f"получено: {code!r}"
        )
    return value


def language_label(code: str) -> str:
    code = normalize_profile_language(code)
    item = SUPPORTED_LANGUAGES[code]
    return f"{item['emoji']} {item['label']}"


def detect_script_language(text: str) -> LanguageDecision:
    """Консервативно отличить русский от казахского кириллического текста.

    Уверенное решение отдаётся только при сильных сигналах. Для коротких,
    смешанных и казахских текстов в латинице возвращается ``code=None``:
    такой текст не должен блокировать выбранный язык ролика.
    """
    value = str(text or "")
    tokens = [token.lower() for token in _TOKEN_RE.findall(value)]
    letters = sum(len(token) for token in tokens)
    if letters < 12:
        return LanguageDecision(None, 0.0, "too_short")

    kazakh_letters = sum(char in _KAZAKH_LETTERS for char in value)
    kk_words = sum(token in _KK_WORDS for token in tokens)
    ru_words = sum(token in _RU_WORDS for token in tokens)

    if kazakh_letters >= 2:
        return LanguageDecision("kk", 0.99, "kazakh_letters")
    if kazakh_letters == 1 and kk_words >= 1:
        return LanguageDecision("kk", 0.95, "kazakh_letter_and_lexicon")
    if kk_words >= 3 and kk_words >= ru_words + 2:
        return LanguageDecision("kk", 0.90, "kazakh_lexicon")
    if kazakh_letters == 0 and ru_words >= 3 and ru_words >= kk_words + 2:
        return LanguageDecision("ru", 0.90, "russian_lexicon")
    return LanguageDecision(None, 0.0, "ambiguous")


def confident_mismatch(text: str, selected_language: str) -> LanguageDecision | None:
    """Вернуть уверенное несовпадение либо ``None``."""
    selected_language = normalize_profile_language(selected_language)
    decision = detect_script_language(text)
    if (
        decision.code
        and decision.code != selected_language
        and decision.confidence >= 0.85
    ):
        return decision
    return None
