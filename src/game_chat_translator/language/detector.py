from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from game_chat_translator.language.base import LanguageProviderError, StatisticalLanguageProvider
from game_chat_translator.language.glossary import GlossaryResolver
from game_chat_translator.models import LanguageAnalysis, LanguageSpan

_TOKEN = re.compile(r"[\w'\u2019.-]+", re.UNICODE)
_TURKISH_MARKERS = frozenset("çğıöşüÇĞİÖŞÜ")
_TURKISH_WORDS = frozenset(
    {
        "abi",
        "ama",
        "ben",
        "bir",
        "bu",
        "gel",
        "güzel",
        "iyi",
        "kanka",
        "mahmut",
        "merhaba",
        "naber",
        "nas\u0131l",
        "sen",
        "tamam",
        "var",
        "yok",
    }
)
_ENGLISH_WORDS = frozenset(
    {
        "are",
        "at",
        "buy",
        "come",
        "do",
        "for",
        "good",
        "hello",
        "hey",
        "how",
        "i",
        "is",
        "need",
        "sell",
        "selling",
        "the",
        "trade",
        "want",
        "what",
        "where",
        "you",
    }
)
_TRANSLITERATED_RUSSIAN = frozenset(
    {"da", "net", "privet", "spasibo", "poka", "brat", "kuda", "kak", "normalno"}
)


@dataclass(frozen=True, slots=True)
class _TokenGuess:
    start: int
    end: int
    language: str
    confidence: float


@dataclass(frozen=True, slots=True)
class _ProtectedRange:
    start: int
    end: int
    source: str


class LocalLanguageDetector:
    def __init__(
        self,
        glossary: GlossaryResolver | None = None,
        statistical_provider: StatisticalLanguageProvider | None = None,
    ) -> None:
        self._glossary = glossary
        self._statistical_provider = statistical_provider

    def analyze(
        self, text: str, *, additional_protected_terms: tuple[str, ...] = ()
    ) -> LanguageAnalysis:
        protected = [
            _ProtectedRange(term.start, term.end, term.source)
            for term in (self._glossary.find(text) if self._glossary is not None else ())
        ]
        for term in sorted(additional_protected_terms, key=len, reverse=True):
            if not term:
                continue
            for match in re.finditer(re.escape(term), text, flags=re.IGNORECASE):
                if (match.start() and text[match.start() - 1].isalnum()) or (
                    match.end() < len(text) and text[match.end()].isalnum()
                ):
                    continue
                if any(
                    match.start() < existing.end and match.end() > existing.start
                    for existing in protected
                ):
                    continue
                protected.append(
                    _ProtectedRange(match.start(), match.end(), text[match.start() : match.end()])
                )
        protected.sort(key=lambda item: item.start)
        guesses: list[_TokenGuess] = []
        for match in _TOKEN.finditer(text):
            if any(match.start() < term.end and match.end() > term.start for term in protected):
                guesses.append(_TokenGuess(match.start(), match.end(), "protected", 1.0))
                continue
            guesses.append(self._guess(match.group(), match.start(), match.end()))
        spans = _merge_guesses(guesses)
        scored = [guess for guess in guesses if guess.language not in {"unknown", "protected"}]
        if not scored:
            primary = "unknown"
            confidence = 0.0
        else:
            weights: dict[str, float] = {}
            for guess in scored:
                weights[guess.language] = weights.get(guess.language, 0.0) + (
                    (guess.end - guess.start) * guess.confidence
                )
            ordered = sorted(weights.items(), key=lambda item: item[1], reverse=True)
            primary = ordered[0][0]
            total = sum(weights.values())
            confidence = ordered[0][1] / total if total else 0.0
            if len(ordered) > 1 and ordered[1][1] / total >= 0.25:
                primary = "mixed"
                confidence = min(ordered[0][1] / total + ordered[1][1] / total, 0.99)
        if self._statistical_provider is not None and (primary == "unknown" or confidence < 0.65):
            statistical_text = _without_protected_terms(text, protected)
            try:
                statistical_language, statistical_confidence = (
                    self._statistical_provider.predict(statistical_text)
                    if statistical_text
                    else ("unknown", 0.0)
                )
            except LanguageProviderError:
                statistical_language, statistical_confidence = "unknown", 0.0
            if statistical_language in {"ru", "en", "tr"} and statistical_confidence >= 0.55:
                primary = statistical_language
                confidence = statistical_confidence
                statistical_spans = tuple(
                    LanguageSpan(
                        start=start,
                        end=end,
                        language=primary,
                        confidence=confidence,
                    )
                    for start, end in _unprotected_ranges(text, protected)
                )
                if statistical_spans:
                    spans = tuple(
                        sorted(
                            (*spans, *statistical_spans),
                            key=lambda span: (span.start, span.end),
                        )
                    )
        return LanguageAnalysis(
            primary_language=primary,
            spans=spans,
            confidence=confidence,
            protected_terms=tuple(term.source for term in protected),
        )

    @staticmethod
    def _guess(token: str, start: int, end: int) -> _TokenGuess:
        letters = [character for character in token if character.isalpha()]
        if not letters:
            return _TokenGuess(start, end, "unknown", 0.0)
        names = [unicodedata.name(character, "") for character in letters]
        if any("CYRILLIC" in name for name in names):
            if all("CYRILLIC" in name for name in names):
                return _TokenGuess(start, end, "ru", 0.99)
            return _TokenGuess(start, end, "mixed", 0.7)
        folded = token.casefold().strip(".'-\u2019")
        if any(character in _TURKISH_MARKERS for character in token):
            return _TokenGuess(start, end, "tr", 0.98)
        if folded in _TURKISH_WORDS:
            return _TokenGuess(start, end, "tr", 0.9)
        if folded in _TRANSLITERATED_RUSSIAN:
            return _TokenGuess(start, end, "ru-Latn", 0.78)
        if folded in _ENGLISH_WORDS:
            return _TokenGuess(start, end, "en", 0.9)
        if all("LATIN" in name for name in names):
            return _TokenGuess(start, end, "unknown", 0.35)
        return _TokenGuess(start, end, "unknown", 0.0)


def _merge_guesses(guesses: list[_TokenGuess]) -> tuple[LanguageSpan, ...]:
    spans: list[LanguageSpan] = []
    for guess in guesses:
        if guess.language == "unknown":
            continue
        if spans and spans[-1].language == guess.language:
            prior = spans.pop()
            spans.append(
                LanguageSpan(
                    start=prior.start,
                    end=guess.end,
                    language=guess.language,
                    confidence=min(prior.confidence, guess.confidence),
                )
            )
        else:
            spans.append(
                LanguageSpan(
                    start=guess.start,
                    end=guess.end,
                    language=guess.language,
                    confidence=guess.confidence,
                )
            )
    return tuple(spans)


def _without_protected_terms(text: str, protected: list[_ProtectedRange]) -> str:
    characters = list(text)
    for term in protected:
        characters[term.start : term.end] = " " * (term.end - term.start)
    return " ".join("".join(characters).split())


def _unprotected_ranges(text: str, protected: list[_ProtectedRange]) -> tuple[tuple[int, int], ...]:
    ranges: list[tuple[int, int]] = []
    cursor = 0
    for term in protected:
        if cursor < term.start:
            _append_visible_range(ranges, text, cursor, term.start)
        cursor = max(cursor, term.end)
    if cursor < len(text):
        _append_visible_range(ranges, text, cursor, len(text))
    return tuple(ranges)


def _append_visible_range(ranges: list[tuple[int, int]], text: str, start: int, end: int) -> None:
    while start < end and not text[start].isalnum():
        start += 1
    while end > start and not text[end - 1].isalnum():
        end -= 1
    if start < end:
        ranges.append((start, end))
